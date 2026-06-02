# Biometric Sync App

A Frappe/ERPNext custom app that syncs ZKTeco/ESSL biometric attendance device data
directly into ERPNext Employee Checkin records, feeding the Auto Attendance system.

> **Important:** This app must run on a server that has **direct local network access** to your
> biometric devices. It connects to devices over TCP (default port 4370), so the Frappe bench and
> the biometric devices must be on the same LAN or VPN. It will **not** work if the bench is
> hosted on a remote cloud server that cannot reach the devices.

## Features

- Supports **multiple devices** (one `Biometric Device` record per device)
- Global settings (port, protocol, API credentials) in **Biometric Sync Settings** (Single DocType)
- Per-device sync logs in **Biometric Sync Log**
- **Sync Dashboard** page with device status + recent logs
- **Manual sync** button on each device form
- Auto sync via Frappe scheduler (configurable frequency)
- Duplicate check — won't push the same punch twice
- Handles IN / OUT / AUTO punch direction per device

---

## Installation

### Step 1 — Get the app

```bash
cd /path/to/frappe-bench
bench get-app biometric_sync https://github.com/yourorg/biometric_sync
```

### Step 2 — Install Python dependencies

```bash
cd /path/to/frappe-bench
./env/bin/pip install -e apps/biometric_sync
```

This installs the app (including `pyzk`) into the bench's Python virtualenv using `pyproject.toml`.

### Step 3 — Register the app with the bench

```bash
# Add to sites/apps.txt
echo "biometric_sync" >> sites/apps.txt
```

Then add an entry for `biometric_sync` in `sites/apps.json`:

```json
"biometric_sync": {
    "is_repo": true,
    "resolution": {
        "commit_hash": null,
        "branch": "develop"
    },
    "required": [],
    "idx": 12,
    "version": "0.1.0"
}
```

### Step 4 — Install on your site

```bash
bench --site yoursite.localhost install-app biometric_sync
```

### Step 5 — Migrate and restart

```bash
bench --site yoursite.localhost migrate
bench restart
```

---

## Configuration

### Step 1 — Biometric Sync Settings
Go to **Biometric Sync > Biometric Sync Settings**

Fill in:
| Field | Value |
|---|---|
| ERPNext URL | https://erp.yourcompany.com |
| API Key | (from ERPNext User API Access) |
| API Secret | (from ERPNext User API Access) |
| ERPNext Version | 14 or 15 |
| Protocol | ZKTeco |
| Port | 4370 |
| Pull Frequency | 60 (minutes) |
| Enable Auto Sync | ✅ |

### Step 2 — Generate API Key in ERPNext
1. Go to the ERPNext User you want to use
2. Click **API Access** → **Generate Keys**
3. The user needs:
   - **Create** permission on `Employee Checkin`
   - **Write** permission on `Shift Type`

### Step 3 — Add Biometric Devices
Go to **Biometric Sync > Biometric Device > New**

Fill in:
| Field | Value |
|---|---|
| Device Name | Main Gate |
| Device ID | 1 (from physical device) |
| IP Address | 192.168.1.100 |
| Punch Direction | AUTO |
| Is Active | ✅ |

Repeat for each device.

### Step 4 — Map Employees to Device User IDs
On each **Employee** record, set:
- **Attendance Device ID** = the user ID enrolled on the biometric device

---

## How it Works

```
Scheduler (every N minutes)
    │
    ├─ reads Biometric Sync Settings (port, protocol, API creds)
    │
    └─ loops over active Biometric Device records
           │
           ├─ connects via pyzk (ZKTeco SDK)
           ├─ pulls attendance logs from device
           ├─ maps device user_id → Employee (via attendance_device_id)
           ├─ creates Employee Checkin records (skips duplicates)
           └─ writes Biometric Sync Log (Success/Failed/No Data)

ERPNext Auto Attendance (built-in)
    └─ reads Employee Checkin → marks Attendance (Present/Absent/Half Day)
```

---

## Manual Sync

- From a **Biometric Device** form → **Actions > Sync Now**
- From the **Biometric Sync Dashboard** → **Sync All Devices**

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `pyzk not installed` | Run `./env/bin/pip install pyzk` inside the bench directory |
| `Module Biometric Sync not found` | Ensure `biometric_sync` is in both `sites/apps.txt` and `sites/apps.json`, then run `bench --site yoursite migrate` and `bench restart` |
| `App biometric_sync not in apps.txt` | Add the entry to `sites/apps.json` as shown in Step 3 above |
| Device connection timeout | Check IP, port, and network connectivity |
| Employee not found | Set `attendance_device_id` on Employee record |
| Duplicates not skipped | Check `device_id` is unique per device |
| API auth failed | Regenerate API key/secret in ERPNext |

---

## File Structure

```
biometric_sync/
├── biometric_sync/
│   ├── biometric_sync/          ← Frappe module directory (required)
│   │   ├── doctype/
│   │   │   ├── biometric_device/
│   │   │   │   ├── biometric_device.json      ← DocType schema
│   │   │   │   ├── biometric_device.py        ← Controller (validate, sync_now)
│   │   │   │   └── biometric_device.js        ← Form buttons
│   │   │   ├── biometric_sync_log/
│   │   │   │   ├── biometric_sync_log.json    ← DocType schema
│   │   │   │   └── biometric_sync_log.py      ← Controller + create_log helper
│   │   │   └── biometric_sync_settings/
│   │   │       ├── biometric_sync_settings.json ← Single DocType schema
│   │   │       └── biometric_sync_settings.py   ← Controller + get_connection_params
│   │   ├── page/
│   │   │   └── biometric_sync_dashboard/
│   │   │       ├── biometric_sync_dashboard.json ← Page config
│   │   │       ├── biometric_sync_dashboard.py   ← API endpoints
│   │   │       └── biometric_sync_dashboard.js   ← Dashboard UI
│   │   └── workspace/
│   │       └── biometric_sync/
│   │           └── biometric_sync.json        ← Desk workspace/sidebar entry
│   ├── scheduled_tasks/
│   │   └── sync_attendance.py                 ← Core sync engine
│   ├── hooks.py                               ← Scheduler + fixture registration
│   └── modules.txt                            ← Declares "Biometric Sync" module
├── pyproject.toml                             ← Dependencies (pyzk, requests)
└── setup.py
```
