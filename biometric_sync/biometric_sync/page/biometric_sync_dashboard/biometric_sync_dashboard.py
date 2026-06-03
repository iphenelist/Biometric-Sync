import frappe


@frappe.whitelist()
def get_dashboard_data():
    """Return all data needed to render the sync dashboard."""
    devices = frappe.get_all(
        "Biometric Device",
        fields=[
            "name", "ip_address", "device_id",
            "is_active", "last_synced_on", "last_sync_status", "last_records_pushed"
        ],
        order_by="device_id asc"
    )

    recent_logs = frappe.get_all(
        "Biometric Sync Log",
        fields=[
            "name", "device", "sync_start", "sync_end",
            "status", "records_fetched", "records_pushed", "records_skipped"
        ],
        order_by="sync_start desc",
        limit=50
    )

    stats = {
        "total_devices": len(devices),
        "active_devices": sum(1 for d in devices if d.is_active),
        "total_logs_today": frappe.db.count(
            "Biometric Sync Log",
            {"sync_start": [">=", frappe.utils.today()]}
        ),
        "failed_today": frappe.db.count(
            "Biometric Sync Log",
            {
                "sync_start": [">=", frappe.utils.today()],
                "status": "Failed"
            }
        )
    }

    return {
        "devices": devices,
        "recent_logs": recent_logs,
        "stats": stats
    }


@frappe.whitelist()
def sync_all_devices():
    """Trigger sync for all active devices immediately."""
    from biometric_sync.scheduled_tasks.sync_attendance import sync_single_device
    settings = frappe.get_single("Biometric Sync Settings")

    if not settings.erpnext_url:
        frappe.throw("Biometric Sync Settings not configured.")

    devices = frappe.get_all(
        "Biometric Device",
        filters={"is_active": 1},
        fields=["name"]
    )

    results = []
    for d in devices:
        device = frappe.get_doc("Biometric Device", d.name)
        result = sync_single_device(device, settings)
        results.append({"device": device.name, **result})

    return results
