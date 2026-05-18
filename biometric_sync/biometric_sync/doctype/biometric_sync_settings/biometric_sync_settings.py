import frappe
from frappe.model.document import Document


class BiometricSyncSettings(Document):

    def validate(self):
        if self.pull_frequency and self.pull_frequency < 1:
            frappe.throw("Pull Frequency must be at least 1 minute.")
        if self.port and (self.port < 1 or self.port > 65535):
            frappe.throw("Port must be between 1 and 65535.")
        if self.erpnext_url:
            self.erpnext_url = self.erpnext_url.rstrip("/")
        if self.biotime_url:
            self.biotime_url = self.biotime_url.rstrip("/")
        if self.enable_biotime:
            if not self.biotime_url:
                frappe.throw("BioTime URL is required when BioTime Sync is enabled.")
            if not self.biotime_username:
                frappe.throw("BioTime Username is required when BioTime Sync is enabled.")
            if not self.biotime_password:
                frappe.throw("BioTime Password is required when BioTime Sync is enabled.")

    def get_connection_params(self):
        """Return dict of connection params for the sync task."""
        return {
            "erpnext_url": self.erpnext_url,
            "api_key": self.api_key,
            "api_secret": self.get_password("api_secret"),
            "erpnext_version": self.erpnext_version,
            "protocol": self.protocol,
            "port": self.port,
            "timeout": self.timeout or 10,
            "pull_frequency": self.pull_frequency,
            "import_start_date": str(self.import_start_date) if self.import_start_date else None,
            "logs_directory": self.logs_directory,
            "use_data_staging": self.use_data_staging,
            "enable_biotime": self.enable_biotime,
            "biotime_url": self.biotime_url,
            "biotime_username": self.biotime_username,
            "biotime_password": self.get_password("biotime_password") if self.biotime_password else None,
            "biotime_page_size": self.biotime_page_size or 100,
            "biotime_verify_ssl": self.biotime_verify_ssl,
        }
