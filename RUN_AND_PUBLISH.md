# V-Guard Smart Inverter - Run & Publish Guide

An end-to-end control center, reverse-engineered BLE GATT telemetry engine, and Home Assistant integration for **V-Guard Smart Inverters** (`VG_SMART_BT_WF` series).

---

## 🚀 Quick Run Guide

### 1. Prerequisites & Setup

Ensure Python 3.9+ is installed.

```powershell
# Clone or open project directory
cd d:\PY\VGuard

# Create & activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt
```

#### `requirements.txt`
```text
bleak>=0.20.0
flask>=2.2.0
requests>=2.28.0
```

---

### 2. Running the Web App

#### Standard Mode (Manual UI Connect)
```powershell
python app.py
```
Open your browser at `http://127.0.0.1:5000` to access the Web Control Panel.

#### Auto-Connect Mode (Recommended for Dedicated Gateway)
Automatically scans for and connects to your specific V-Guard BLE inverter upon startup:
```powershell
python app.py --auto-connect VG_SMART_BT_WF_2
```

#### Custom Host & Port
```powershell
python app.py --host 0.0.0.0 --port 8080 --auto-connect VG_SMART_BT_WF_2
```

---

## 📡 Home Assistant Integration Setup

The application automatically streams live telemetry, binary sensors, and metrics directly to Home Assistant using the REST API.

### 1. Obtain Long-Lived Access Token in Home Assistant
1. Go to your **Home Assistant Profile** -> **Long-Lived Access Tokens**.
2. Click **Create Token**, name it `V-Guard Inverter`, and copy the token string.

### 2. Configure Home Assistant Connection in `config.py` or `ha_config.json`
Update `ha_config.json` or [config.py](file:///d:/PY/VGuard/config.py):
```json
{
  "enabled": true,
  "url": "http://192.168.1.100:8123",
  "token": "YOUR_LONG_LIVED_ACCESS_TOKEN_HERE"
}
```

### 3. Automatically Created Entities in Home Assistant
When `app.py` runs, it continuously publishes these entities:
- `binary_sensor.vguard_inverter_ble_connected` — Live Bluetooth connectivity status
- `sensor.vguard_inverter_connection_status` — Detailed BLE status string
- `sensor.vguard_inverter_connected_device` — Bluetooth device name (`VG_SMART_BT_WF_2`)
- `sensor.vguard_inverter_mains_status` — Grid mains status (`MAINS AVAILABLE` or `POWER CUT DETECTED`)
- `sensor.vguard_inverter_battery_voltage` — Scaled battery terminal voltage (V)
- `sensor.vguard_inverter_battery_pct` — Battery state of charge (%)
- `sensor.vguard_inverter_grid_voltage` — Grid AC input voltage (V)
- `sensor.vguard_inverter_load_watts` — Active load power (W)
- `sensor.vguard_inverter_backup_time` — Remaining battery backup runtime (Minutes)

---

## ⚙️ Publishing & Deployment Options

### Option A: Deploy as a Background Windows Service (NSSM)

To run the gateway continuously on Windows boot without needing an active shell window:

1. Download **NSSM** (Non-Sucking Service Manager) from `nssm.cc`.
2. Open PowerShell as Administrator and execute:
   ```powershell
   nssm install VGuardInverter "d:\PY\VGuard\venv\Scripts\python.exe" "d:\PY\VGuard\app.py --auto-connect VG_SMART_BT_WF_2"
   nssm set VGuardInverter AppDirectory "d:\PY\VGuard"
   nssm set VGuardInverter Start SERVICE_AUTO_START
   nssm start VGuardInverter
   ```
3. Check service status:
   ```powershell
   Get-Service VGuardInverter
   ```

---

### Option B: Deploy on Linux / Raspberry Pi (Systemd)

If running on a Linux box or Raspberry Pi with BlueZ Bluetooth stack:

1. Create a systemd service file `/etc/systemd/system/vguard.service`:
   ```ini
   [Unit]
   Description=V-Guard Smart Inverter BLE Control Panel & HA Bridge
   After=bluetooth.target network.target

   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi/VGuard
   ExecStart=/home/pi/VGuard/venv/bin/python app.py --auto-connect VG_SMART_BT_WF_2
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

2. Enable and start service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable vguard.service
   sudo systemctl start vguard.service
   ```

---

### Option C: Publish to GitHub Repository

To publish this project to GitHub or Gitlab:

1. **Create `.gitignore`**:
   ```gitignore
   venv/
   __pycache__/
   *.pyc
   *.log
   ha_config.json
   .qodo/
   search_results.*
   ```

2. **Initialize & Push Git Repo**:
   ```powershell
   git init
   git add app.py bluetooth_manager.py inverter_protocol.py home_assistant.py config.py requirements.txt templates/ static/ README.md RUN_AND_PUBLISH.md
   git commit -m "Initial release: V-Guard Smart Inverter BLE Control Panel & HA Integration"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/vguard-smart-inverter.git
   git push -u origin main
   ```

---

## ⚡ BLE Protocol & GATT Command Reference

V-Guard Inverters use strict **8-byte binary GATT payloads** over Bluetooth Low Energy.

### Primary UUIDs
- **Service UUID**: `0003cdd0-0000-1000-8000-00805f9b0131`
- **RX (Write) Characteristic**: `0003cdd1-0000-1000-8000-00805f9b0131`
- **TX (Notify) Characteristic**: `0003cdd2-0000-1000-8000-00805f9b0131`

### Binary GATT Write Frame Structure
| Byte 0 | Byte 1 | Byte 2 | Byte 3 | Byte 4 | Byte 5 | Byte 6 | Byte 7 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `0xFF` | `Val Low` | `Val High` | `Reg Cmd` | `0x0C` | `0x00` | `0xFF` | `0xFF` |

### Verified Hardware Command Table
| Command | GATT Frame (Hex) | Description |
|:---|:---|:---|
| `inverter_on` | `FF 01 00 16 0C 00 FF FF` | Turn Inverter Output ON |
| `inverter_off` | `FF 00 00 16 0C 00 FF FF` | Turn Inverter Output OFF |
| `force_cut_on` | `FF 00 00 2E 0C 00 FF FF` | Mains Forced Power Cut (Simulate Grid Cut) |
| `force_cut_off` | `FF 01 00 2E 0C 00 FF FF` | Restore Grid Mains Input |
| `appliance_mode_on` | `FF 4C 04 3E 0C 00 FF FF` | High Appliance Voltage Range Mode |
| `appliance_mode_off` | `FF 64 00 3E 0C 00 FF FF` | Standard Voltage Range Mode |
| `extra_backup_on` | `FF E8 03 6E 0C 00 FF FF` | Deep Discharge Extra Backup |
| `extra_backup_off` | `FF 00 00 6E 0C 00 FF FF` | Standard Discharge Depth |
| `turbo_charging_on` | `FF 01 00 6C 0C 00 FF FF` | Fast Battery Charging ON |
| `turbo_charging_off` | `FF 00 00 6C 0C 00 FF FF` | Standard Battery Charging |

---

## 🛠️ Troubleshooting

- **BLE Scan Timeout**: Ensure Bluetooth is enabled on the host computer and the inverter is within 5 meters.
- **Auto-Connect Retry Backoff**: When disconnected, the system scans every 30 seconds to prevent aggressive radio polling.
- **Port Conflict**: Use `--port <PORT_NUM>` if port 5000 is occupied by another application.
