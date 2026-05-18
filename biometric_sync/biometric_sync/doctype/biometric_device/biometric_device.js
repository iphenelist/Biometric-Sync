frappe.ui.form.on("Biometric Device", {
    refresh(frm) {
        _toggle_protocol_fields(frm);

        if (!frm.is_new()) {
            // Test Connection — only meaningful for direct ZK devices
            if (frm.doc.protocol !== "BioTime") {
                frm.add_custom_button(__("Test Connection"), function () {
                    frappe.show_alert({ message: __("Testing connection..."), indicator: "blue" });
                    frm.call("test_connection").then(r => {
                        if (r.message && r.message.success) {
                            const info = r.message.info;
                            frappe.msgprint({
                                title: __("Connection Successful"),
                                indicator: "green",
                                message: `
                                    <table class="table table-bordered" style="margin-top:8px;">
                                        <tr><td><b>${__("Device Name")}</b></td><td>${info.device_name || "—"}</td></tr>
                                        <tr><td><b>${__("Firmware")}</b></td><td>${info.firmware || "—"}</td></tr>
                                        <tr><td><b>${__("Serial Number")}</b></td><td>${info.serial_number || "—"}</td></tr>
                                        <tr><td><b>${__("Platform")}</b></td><td>${info.platform || "—"}</td></tr>
                                        <tr><td><b>${__("Enrolled Users")}</b></td><td>${info.users !== null ? info.users : "—"}</td></tr>
                                    </table>
                                `
                            });
                        } else {
                            frappe.msgprint({
                                title: __("Connection Failed"),
                                indicator: "red",
                                message: r.message && r.message.error || __("Could not reach device.")
                            });
                        }
                    });
                }, __("Actions"));
            }

            frm.add_custom_button(__("Sync Now"), function () {
                frappe.show_alert({ message: __("Sync started..."), indicator: "blue" });
                frm.call("sync_now").then(r => {
                    if (r.message && r.message.success) {
                        frappe.show_alert({
                            message: __("Sync complete. {0} record(s) pushed.", [r.message.records_pushed]),
                            indicator: "green"
                        });
                        frm.reload_doc();
                    } else {
                        frappe.show_alert({
                            message: __("Sync failed: ") + (r.message && r.message.error || "Unknown error"),
                            indicator: "red"
                        });
                        frm.reload_doc();
                    }
                });
            }, __("Actions"));

            // Color-code the last sync status badge
            if (frm.doc.last_sync_status === "Success") {
                frm.get_field("last_sync_status").$wrapper.find(".control-value").css("color", "green");
            } else if (frm.doc.last_sync_status === "Failed") {
                frm.get_field("last_sync_status").$wrapper.find(".control-value").css("color", "red");
            }
        }
    },

    protocol(frm) {
        _toggle_protocol_fields(frm);
    }
});

function _toggle_protocol_fields(frm) {
    const is_biotime = frm.doc.protocol === "BioTime";

    // ip_address and clear_from_device_on_fetch are only relevant for direct ZK devices
    frm.toggle_display("ip_address", !is_biotime);
    frm.toggle_display("clear_from_device_on_fetch", !is_biotime);
    frm.toggle_reqd("ip_address", !is_biotime);
}
