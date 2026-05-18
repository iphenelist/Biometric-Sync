import frappe
from frappe.model.document import Document


class BiometricSyncLog(Document):
    pass


def create_log(device_name, status, records_fetched=0, records_pushed=0,
               records_skipped=0, error_message=None, raw_log=None, sync_start=None):
    """Helper to create a Biometric Sync Log entry."""
    log = frappe.get_doc({
        "doctype": "Biometric Sync Log",
        "device": device_name,
        "sync_start": sync_start or frappe.utils.now_datetime(),
        "sync_end": frappe.utils.now_datetime(),
        "status": status,
        "records_fetched": records_fetched,
        "records_pushed": records_pushed,
        "records_skipped": records_skipped,
        "error_message": error_message,
        "raw_log": raw_log,
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return log
