"""
biometric_sync.scheduled_tasks.sync_attendance
-----------------------------------------------
ZKTeco Direct sync engine.
Handles only devices with protocol != "BioTime".
BioTime devices are handled entirely in biotime_sync.py.
"""

import time

import requests
import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime, time_diff_in_seconds
import traceback

from biometric_sync.biometric_sync.doctype.biometric_sync_log.biometric_sync_log import create_log


# ── Entry point (scheduler) ───────────────────────────────────────────────────

def run_sync():
    """Called by hooks.py scheduler every minute."""
    try:
        settings = frappe.get_single("Biometric Sync Settings")
    except Exception:
        return

    if not settings.is_enabled:
        return

    if not _should_run(settings):
        return

    devices = frappe.get_all(
        "Biometric Device",
        filters={"is_active": 1, "protocol": ["!=", "BioTime"]},
        fields=["name"]
    )

    for d in devices:
        device = frappe.get_doc("Biometric Device", d.name)
        try:
            sync_single_device(device, settings)
        except Exception:
            frappe.log_error(
                title=f"Biometric Sync Failed: {device.device_name}",
                message=traceback.format_exc()
            )


def _should_run(settings):
    """Check if enough time has passed since last run (based on pull_frequency)."""
    cache_key = "biometric_sync_last_run"
    last_run = frappe.cache().get_value(cache_key)
    frequency_seconds = (settings.pull_frequency or 60) * 60

    if last_run:
        elapsed = time_diff_in_seconds(now_datetime(), get_datetime(last_run))
        if elapsed < frequency_seconds:
            return False

    frappe.cache().set_value(cache_key, str(now_datetime()))
    return True


# ── Single device sync ────────────────────────────────────────────────────────

def sync_single_device(device, settings):
    """
    Pull attendance logs from one ZKTeco device and push to ERPNext via API.
    If use_data_staging is enabled, records go to Biometric Data Staging.
    Otherwise they go directly to Employee Checkin.
    """
    sync_start = now_datetime()
    raw_lines = []
    max_retries = int(settings.max_retry_attempts or 3)

    try:
        params = settings.get_connection_params()
        logs = _pull_from_device_with_retry(device, params, max_retries)

        if not logs:
            device.update_sync_status("No Data", 0)
            create_log(device_name=device.name, status="No Data", sync_start=sync_start)
            return {"success": True, "records_pushed": 0}

        for log_entry in logs:
            raw_lines.append(str(log_entry))

        pushed = 0
        skipped = 0

        if params.get("use_data_staging"):
            records = []
            for log_entry in logs:
                log_type = _resolve_log_type(log_entry, device.punch_direction)
                records.append({
                    "attendance_device_id": str(log_entry.user_id),
                    "timestamp": log_entry.timestamp.isoformat(),
                    "punch_type": log_type,
                    "device_id": device.device_id,
                    "status": "Pending"
                })
            pushed, skipped = _push_bulk_to_staging_api(records, params)
        else:
            for log_entry in logs:
                result = _push_checkin_via_api(log_entry, device, params)
                if result == "pushed":
                    pushed += 1
                elif result == "skipped":
                    skipped += 1

        device.update_sync_status("Success", pushed)
        _update_shift_type_sync(device)
        create_log(
            device_name=device.name,
            status="Success",
            records_fetched=len(logs),
            records_pushed=pushed,
            records_skipped=skipped,
            raw_log="\n".join(raw_lines),
            sync_start=sync_start
        )
        return {"success": True, "records_pushed": pushed}

    except Exception as e:
        err = traceback.format_exc()
        device.update_sync_status("Failed", 0)
        create_log(
            device_name=device.name,
            status="Failed",
            error_message=err,
            raw_log="\n".join(raw_lines),
            sync_start=sync_start
        )
        frappe.log_error(title=f"Biometric Sync Error: {device.device_name}", message=err)
        return {"success": False, "records_pushed": 0, "error": str(e)}


# ── Pull from device ──────────────────────────────────────────────────────────

def _pull_from_device_with_retry(device, params, max_retries):
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return _pull_from_device(device, params)
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                frappe.logger().warning(
                    f"Biometric Sync: {device.device_name} attempt {attempt}/{max_retries} failed "
                    f"({e}). Retrying in 5s..."
                )
                time.sleep(5)
    raise last_exc


def _pull_from_device(device, params):
    try:
        from zk import ZK
    except ImportError:
        frappe.throw(_("pyzk library not installed. Run: pip install pyzk"))

    zk = ZK(
        device.ip_address,
        port=params["port"],
        timeout=params["timeout"],
        password=0,
        force_udp=False,
        ommit_ping=False
    )

    conn = None
    logs = []

    try:
        conn = zk.connect()
        conn.disable_device()

        all_logs = conn.get_attendance()

        import_start = params.get("import_start_date")
        for log in all_logs:
            if import_start:
                log_date = str(log.timestamp.date()) if hasattr(log.timestamp, "date") else str(log.timestamp)[:10]
                if log_date < import_start:
                    continue
            logs.append(log)

        if device.clear_from_device_on_fetch:
            conn.clear_attendance()

        conn.enable_device()

    finally:
        if conn:
            conn.disconnect()

    return logs


# ── Push to ERPNext — staging path ────────────────────────────────────────────

_STAGING_BATCH_SIZE = 50
_STAGING_MAX_RETRIES = 3
_STAGING_TIMEOUT = 60


def _push_bulk_to_staging_api(records, params):
    url = f"{params['erpnext_url']}/api/method/biometric_client.biometric_client.api.upload_bulk_biometric_data"
    headers = {
        "Authorization": f"token {params['api_key']}:{params['api_secret']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    total_pushed = 0
    total_skipped = 0

    for batch_start in range(0, len(records), _STAGING_BATCH_SIZE):
        batch = records[batch_start: batch_start + _STAGING_BATCH_SIZE]
        pushed, skipped = _post_staging_batch_with_retry(batch, url, headers)
        total_pushed += pushed
        total_skipped += skipped

    return total_pushed, total_skipped


def _post_staging_batch_with_retry(batch, url, headers):
    last_exc = None
    for attempt in range(1, _STAGING_MAX_RETRIES + 1):
        try:
            response = requests.post(url, headers=headers, json=batch, timeout=_STAGING_TIMEOUT)
            # Frappe wraps whitelisted method responses under a "message" key
            data = response.json().get("message", {})

            if response.status_code == 200 and data.get("success"):
                details = data.get("details", {})
                pushed = len(details.get("success", []))
                skipped = len(details.get("duplicates", [])) + len(details.get("failed", []))
                return pushed, skipped

            error_msg = data.get("message") or str(response.status_code)
            raise Exception(f"Staging API returned {response.status_code}: {error_msg}")

        except requests.exceptions.Timeout as e:
            last_exc = e
            if attempt < _STAGING_MAX_RETRIES:
                frappe.logger().warning(
                    f"Biometric Staging API: batch of {len(batch)} timed out "
                    f"(attempt {attempt}/{_STAGING_MAX_RETRIES}). Retrying in 5s..."
                )
                time.sleep(5)
        except Exception as e:
            last_exc = e
            if attempt < _STAGING_MAX_RETRIES:
                frappe.logger().warning(
                    f"Biometric Staging API: attempt {attempt}/{_STAGING_MAX_RETRIES} failed "
                    f"({e}). Retrying in 5s..."
                )
                time.sleep(5)

    frappe.log_error(title="Biometric Staging API Error", message=str(last_exc))
    raise last_exc


# ── Push to ERPNext — normal path ─────────────────────────────────────────────

def _push_checkin_via_api(log_entry, device, params):
    employee = _get_employee(log_entry.user_id)
    if not employee:
        return "skipped"

    log_type = _resolve_log_type(log_entry, device.punch_direction)
    url = f"{params['erpnext_url']}/api/resource/Employee Checkin"
    headers = {
        "Authorization": f"token {params['api_key']}:{params['api_secret']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "employee": employee,
        "time": str(log_entry.timestamp),
        "log_type": log_type,
        "device_id": device.device_id,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code in (200, 201):
            return "pushed"
        error_body = response.text or ""
        if "DuplicateEntryError" in error_body or "already exists" in error_body.lower():
            return "skipped"
        frappe.log_error(
            title=f"Employee Checkin API Error [{device.device_id}]",
            message=f"Status {response.status_code}: {error_body[:500]}"
        )
        return "skipped"
    except Exception as e:
        frappe.log_error(
            title=f"Employee Checkin API Exception [{device.device_id}]",
            message=str(e)
        )
        return "skipped"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_employee(device_user_id):
    return frappe.db.get_value(
        "Employee",
        {"attendance_device_id": str(device_user_id), "status": "Active"},
        "name"
    )


def _resolve_log_type(log_entry, punch_direction):
    if punch_direction == "IN":
        return "IN"
    elif punch_direction == "OUT":
        return "OUT"
    else:
        punch = getattr(log_entry, "punch", None)
        if punch == 1:
            return "OUT"
        return "IN"


def _update_shift_type_sync(device):
    if not device.shift_type:
        return
    frappe.db.set_value(
        "Shift Type",
        device.shift_type,
        "last_sync_of_checkin",
        now_datetime(),
        update_modified=False
    )
    frappe.db.commit()
