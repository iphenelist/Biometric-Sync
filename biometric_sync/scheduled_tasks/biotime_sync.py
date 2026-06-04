"""
biometric_sync.scheduled_tasks.biotime_sync
--------------------------------------------
BioTime sync engine. Completely independent from sync_attendance.py.

- Handles only Biometric Devices with protocol = "BioTime"
- Always sends directly to Employee Checkin via API — no data staging
- Runs on its own scheduler entry in hooks.py
"""

import time
import datetime

import requests
import frappe
from frappe.utils import now_datetime, get_datetime, time_diff_in_seconds
import traceback

from biometric_sync.biometric_sync.doctype.biometric_sync_log.biometric_sync_log import create_log


# ── Entry point (scheduler) ───────────────────────────────────────────────────

def run_biotime_sync():
    """Called by hooks.py scheduler every minute."""
    try:
        settings = frappe.get_single("Biometric Sync Settings")
    except Exception:
        return

    if not settings.enable_biotime:
        return

    if not _should_run(settings):
        return

    devices = frappe.get_all(
        "Biometric Device",
        filters={"is_active": 1, "protocol": "BioTime"},
        fields=["name"]
    )

    for d in devices:
        device = frappe.get_doc("Biometric Device", d.name)
        try:
            sync_biotime_device(device, settings)
        except Exception:
            frappe.log_error(
                title=f"BioTime Sync Failed: {device.device_name}",
                message=traceback.format_exc()
            )


def _should_run(settings):
    """Check if enough time has passed since last BioTime run."""
    cache_key = "biotime_sync_last_run"
    last_run = frappe.cache().get_value(cache_key)
    frequency_seconds = (settings.pull_frequency or 60) * 60

    if last_run:
        elapsed = time_diff_in_seconds(now_datetime(), get_datetime(last_run))
        if elapsed < frequency_seconds:
            return False

    frappe.cache().set_value(cache_key, str(now_datetime()))
    return True


# ── Single device sync ────────────────────────────────────────────────────────

def sync_biotime_device(device, settings):
    """
    Fetch attendance logs from BioTime for one device and push directly
    to Employee Checkin via ERPNext REST API. No data staging used.
    """
    sync_start = now_datetime()
    raw_lines = []
    max_retries = int(settings.max_retry_attempts or 3)

    try:
        params = settings.get_connection_params()
        logs = _pull_from_biotime_with_retry(device, params, max_retries)

        if not logs:
            device.update_sync_status("No Data", 0)
            create_log(device_name=device.name, status="No Data", sync_start=sync_start)
            return {"success": True, "records_pushed": 0}

        for log_entry in logs:
            raw_lines.append(str(log_entry))

        pushed = 0
        skipped = 0
        for log_entry in logs:
            result = _push_checkin_via_api(log_entry, device, params)
            if result == "pushed":
                pushed += 1
            else:
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
        frappe.log_error(title=f"BioTime Sync Error: {device.device_name}", message=err)
        return {"success": False, "records_pushed": 0, "error": str(e)}


# ── Pull from BioTime API ─────────────────────────────────────────────────────

class _BiotimeLogEntry:
    """Normalizes a BioTime transaction record to the standard log interface."""

    _OUT_STATES = {"1", "2", "5"}  # Check Out, Break Out, Overtime Out

    def __init__(self, record):
        self.user_id = str(record.get("emp_code", ""))
        punch_time = record.get("punch_time", "")
        try:
            self.timestamp = datetime.datetime.strptime(punch_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            self.timestamp = datetime.datetime.fromisoformat(punch_time)
        state = str(record.get("punch_state", "0"))
        self.punch = 1 if state in self._OUT_STATES else 0

    def __repr__(self):
        return f"BiotimeLog(user_id={self.user_id}, timestamp={self.timestamp}, punch={self.punch})"


def _pull_from_biotime_with_retry(device, params, max_retries):
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return _pull_from_biotime(device, params)
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                frappe.logger().warning(
                    f"BioTime Sync: {device.device_name} attempt {attempt}/{max_retries} failed "
                    f"({e}). Retrying in 5s..."
                )
                time.sleep(5)
    raise last_exc


def _pull_from_biotime(device, params):
    """
    Authenticate with BioTime and fetch attendance transactions for this device.
    Only fetches records since the last successful sync (incremental).
    Handles BioTime's paginated API automatically.
    """
    token = _get_biotime_token(params)
    verify_ssl = bool(params.get("biotime_verify_ssl", True))
    page_size = params.get("biotime_page_size") or 100

    headers = {
        "Authorization": f"JWT {token}",
        "Content-Type": "application/json",
    }

    cache_key = f"biotime_last_sync_{device.name}"
    last_sync = frappe.cache().get_value(cache_key)

    query = {
        "terminal_sn": device.device_id,
        "page_size": page_size,
        "page": 1,
    }
    if last_sync:
        query["start_time"] = last_sync
    elif params.get("import_start_date"):
        query["start_time"] = params["import_start_date"] + " 00:00:00"

    url = f"{params['biotime_url']}/iclock/api/transactions/"
    logs = []
    extra_params = query

    while url:
        response = requests.get(
            url,
            headers=headers,
            params=extra_params,
            verify=verify_ssl,
            timeout=params.get("timeout") or 10
        )
        response.raise_for_status()
        data = response.json()

        for record in data.get("data", []):
            entry = _BiotimeLogEntry(record)
            if entry.user_id:
                logs.append(entry)

        url = data.get("next")
        extra_params = {}  # next URL already contains all query params

    frappe.cache().set_value(cache_key, str(now_datetime()))
    return logs


def _get_biotime_token(params):
    """Authenticate with BioTime and return a JWT token."""
    url = f"{params['biotime_url']}/jwt-api-token-auth/"
    response = requests.post(
        url,
        json={
            "username": params["biotime_username"],
            "password": params["biotime_password"]
        },
        verify=bool(params.get("biotime_verify_ssl", True)),
        timeout=params.get("timeout") or 10
    )
    response.raise_for_status()
    token = response.json().get("token")
    if not token:
        raise Exception("BioTime authentication failed: no token returned")
    return token


# ── Push to ERPNext ───────────────────────────────────────────────────────────

def _push_checkin_via_api(log_entry, device, params):
    """POST a single Employee Checkin to ERPNext REST API."""
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
            title=f"BioTime Checkin API Error [{device.device_id}]",
            message=f"Status {response.status_code}: {error_body[:500]}"
        )
        return "skipped"
    except Exception as e:
        frappe.log_error(
            title=f"BioTime Checkin API Exception [{device.device_id}]",
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
    for row in device.shift_type:
        frappe.db.set_value(
            "Shift Type",
            row.shift_type,
            "last_sync_of_checkin",
            now_datetime(),
            update_modified=False
        )
    frappe.db.commit()
