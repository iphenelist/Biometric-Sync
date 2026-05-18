import frappe
from frappe.model.document import Document
import re


class BiometricDevice(Document):

    def validate(self):
        self._validate_ip()
        self._validate_device_id()

    def _validate_ip(self):
        ip_pattern = r"^(\d{1,3}\.){3}\d{1,3}$"
        if not re.match(ip_pattern, self.ip_address or ""):
            frappe.throw(f"Invalid IP address: {self.ip_address}")
        parts = self.ip_address.split(".")
        if any(int(p) > 255 for p in parts):
            frappe.throw(f"Invalid IP address: {self.ip_address}")

    def _validate_device_id(self):
        if not str(self.device_id).strip().isdigit():
            frappe.throw("Device ID must be a numeric value.")

    def update_sync_status(self, status, records_pushed=0):
        """Called after each sync attempt to update status fields."""
        self.db_set("last_synced_on", frappe.utils.now_datetime())
        self.db_set("last_sync_status", status)
        self.db_set("last_records_pushed", records_pushed)
        frappe.db.commit()

    @frappe.whitelist()
    def sync_now(self):
        """Manual sync trigger — called from the form button."""
        from biometric_sync.scheduled_tasks.sync_attendance import sync_single_device
        try:
            settings = frappe.get_single("Biometric Sync Settings")
        except frappe.DoesNotExistError:
            frappe.throw("Biometric Sync Settings have not been configured yet. Please set them up before syncing.")
        result = sync_single_device(self, settings)
        return result

    @frappe.whitelist()
    def test_connection(self):
        """
        Ping the device and return its info without pulling any logs.
        Called from the Test Connection button on the form.
        """
        try:
            from zk import ZK
        except ImportError:
            frappe.throw("pyzk library not installed. Run: ./env/bin/pip install pyzk")

        try:
            settings = frappe.get_single("Biometric Sync Settings")
        except frappe.DoesNotExistError:
            frappe.throw("Biometric Sync Settings have not been configured yet.")

        zk = ZK(
            self.ip_address,
            port=int(settings.port or 4370),
            timeout=int(settings.timeout or 10),
            password=0,
            force_udp=False,
            ommit_ping=False
        )

        conn = None
        try:
            conn = zk.connect()
            info = {
                "firmware": conn.get_firmware_version(),
                "serial_number": conn.get_serialnumber(),
                "device_name": conn.get_device_name(),
                "platform": conn.get_platform(),
                "users": conn.get_users_count() if hasattr(conn, "get_users_count") else None,
            }
            return {"success": True, "info": info}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn:
                conn.disconnect()
