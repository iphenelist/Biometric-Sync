frappe.pages["biometric-sync-dashboard"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "Biometric Sync Dashboard",
        single_column: true
    });

    page.add_menu_item(__("Sync Settings"), () => {
        frappe.set_route("Form", "Biometric Sync Settings");
    });

    page.add_menu_item(__("Add Device"), () => {
        frappe.set_route("Form", "Biometric Device", "new-biometric-device");
    });

    page.add_inner_button(__("Sync All Devices"), () => {
        frappe.confirm(
            __("Sync all active devices now?"),
            () => {
                frappe.show_alert({ message: __("Syncing all devices..."), indicator: "blue" });
                frappe.call({
                    method: "biometric_sync.biometric_sync.page.biometric_sync_dashboard.biometric_sync_dashboard.sync_all_devices",
                    callback(r) {
                        if (r.message) {
                            const pushed = r.message.reduce((s, d) => s + (d.records_pushed || 0), 0);
                            frappe.show_alert({
                                message: __("{0} record(s) pushed across {1} device(s).", [pushed, r.message.length]),
                                indicator: "green"
                            });
                            load_dashboard();
                        }
                    }
                });
            }
        );
    }, __("Actions"));

    $(wrapper).find(".layout-main-section").html(`
        <div id="bs-dashboard" style="padding: 20px;">
            <div id="bs-stats" class="row" style="margin-bottom: 24px;"></div>
            <div id="bs-devices" style="margin-bottom: 32px;"></div>
            <div id="bs-logs"></div>
        </div>
    `);

    function load_dashboard() {
        frappe.call({
            method: "biometric_sync.biometric_sync.page.biometric_sync_dashboard.biometric_sync_dashboard.get_dashboard_data",
            callback(r) {
                if (!r.message) return;
                const { devices, recent_logs, stats } = r.message;
                render_stats(stats);
                render_devices(devices);
                render_logs(recent_logs);
            }
        });
    }

    function render_stats(stats) {
        const colors = ["blue", "green", "orange", "red"];
        const items = [
            { label: "Total Devices", value: stats.total_devices, color: colors[0] },
            { label: "Active Devices", value: stats.active_devices, color: colors[1] },
            { label: "Syncs Today", value: stats.total_logs_today, color: colors[2] },
            { label: "Failed Today", value: stats.failed_today, color: colors[3] },
        ];
        $("#bs-stats").html(items.map(s => `
            <div class="col-sm-3">
                <div class="card" style="padding: 16px; border-left: 4px solid var(--${s.color}-500, #888); margin-bottom: 12px;">
                    <div style="font-size: 28px; font-weight: 600;">${s.value}</div>
                    <div style="color: var(--text-muted); font-size: 13px;">${s.label}</div>
                </div>
            </div>
        `).join(""));
    }

    function render_devices(devices) {
        if (!devices.length) {
            $("#bs-devices").html(`<p class="text-muted">${__("No devices found. Add a device to get started.")}</p>`);
            return;
        }

        const rows = devices.map(d => {
            const status_badge = d.last_sync_status
                ? `<span class="indicator-pill ${d.last_sync_status === 'Success' ? 'green' : d.last_sync_status === 'Failed' ? 'red' : 'gray'}">${d.last_sync_status}</span>`
                : `<span class="indicator-pill gray">${__("Never")}</span>`;
            const active_badge = d.is_active
                ? `<span class="indicator-pill green">${__("Active")}</span>`
                : `<span class="indicator-pill gray">${__("Disabled")}</span>`;

            return `
                <tr>
                    <td><a href="/app/biometric-device/${d.name}">${d.device_id}</a></td>
                    <td>${d.ip_address}</td>
                    <td>${d.device_id}</td>
                    <td>${active_badge}</td>
                    <td>${status_badge}</td>
                    <td>${d.last_synced_on ? frappe.datetime.str_to_user(d.last_synced_on) : "—"}</td>
                    <td>${d.last_records_pushed || 0}</td>
                </tr>
            `;
        }).join("");

        $("#bs-devices").html(`
            <h6 style="margin-bottom: 12px;">${__("Devices")}</h6>
            <table class="table table-bordered table-hover">
                <thead>
                    <tr>
                        <th>${__("Device ID")}</th>
                        <th>${__("IP Address")}</th>
                        <th>${__("Device ID")}</th>
                        <th>${__("Status")}</th>
                        <th>${__("Last Sync")}</th>
                        <th>${__("Last Sync Time")}</th>
                        <th>${__("Records Pushed")}</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `);
    }

    function render_logs(logs) {
        if (!logs.length) {
            $("#bs-logs").html(`<p class="text-muted">${__("No sync logs yet.")}</p>`);
            return;
        }

        const rows = logs.map(l => {
            const badge = `<span class="indicator-pill ${l.status === 'Success' ? 'green' : l.status === 'Failed' ? 'red' : 'gray'}">${l.status}</span>`;
            return `
                <tr>
                    <td><a href="/app/biometric-sync-log/${l.name}">${l.name}</a></td>
                    <td>${l.device || "—"}</td>
                    <td>${frappe.datetime.str_to_user(l.sync_start)}</td>
                    <td>${badge}</td>
                    <td>${l.records_fetched}</td>
                    <td>${l.records_pushed}</td>
                    <td>${l.records_skipped}</td>
                </tr>
            `;
        }).join("");

        $("#bs-logs").html(`
            <h6 style="margin-bottom: 12px;">${__("Recent Sync Logs")}</h6>
            <table class="table table-bordered table-hover">
                <thead>
                    <tr>
                        <th>${__("Log ID")}</th>
                        <th>${__("Device")}</th>
                        <th>${__("Sync Start")}</th>
                        <th>${__("Status")}</th>
                        <th>${__("Fetched")}</th>
                        <th>${__("Pushed")}</th>
                        <th>${__("Skipped")}</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `);
    }

    load_dashboard();

    // Auto-refresh every 2 minutes
    setInterval(load_dashboard, 120000);
};
