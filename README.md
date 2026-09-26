# V-Guard Smart Inverter Control Panel & Home Assistant Bridge

A real-time Web Control Center, reverse-engineered BLE GATT telemetry engine, and Home Assistant REST API sync bridge for **V-Guard Smart Inverter** devices (`VG_SMART_BT_WF_2` / `SYNERGY` / `VGINV` series).

---

## ✨ Features

- **⚡ Real-Time BLE Telemetry**: Grid AC Voltage/Frequency, Output Voltage/Current/Power, Battery Terminal Voltage & Charge %, Operating Temperature, and Calculated Remaining Backup Runtime.
- **🔌 Smart Settings Control**:
  - Inverter Output ON/OFF
  - Forced Mains Power Cut / Restore Grid
  - High Load Appliance Mode Toggle
  - Deep Discharge Extra Backup Mode Toggle
  - Turbo Fast Battery Charging Toggle
  - Eco & Bypass Operating Modes
- **🏠 Home Assistant Live Sync**: Automatically creates & streams sensors (`binary_sensor.vguard_inverter_ble_connected`, `sensor.vguard_inverter_mains_status`, `sensor.vguard_inverter_battery_voltage`, `sensor.vguard_inverter_load_watts`, etc.) directly via REST API.
- **📊 Dynamic Outage Analytics**: Live incident metrics, today's power cut counters, outage durations, and visual bar charts.
- **🔄 Smart Auto-Connect Worker**: Continuous Bluetooth auto-connect worker with 30-second backoff logic during disconnections.

---

## 🚀 Quick Start

```powershell
# 1. Activate Virtual Environment
.\venv\Scripts\activate

# 2. Run Flask Web Application in Auto-Connect Mode
python app.py --auto-connect VG_SMART_BT_WF_2
```

Navigate to `http://127.0.0.1:5000` in your web browser.

---

## 📖 Full Run & Publishing Guide

For complete deployment options (Windows Service, Systemd Linux service, Docker, Home Assistant Token setup, GitHub publishing, and 8-byte BLE GATT protocol specs), see:

👉 **[RUN_AND_PUBLISH.md](file:///d:/PY/VGuard/RUN_AND_PUBLISH.md)**

---

## 💻 Tech Stack & Architecture

- **Backend**: Python 3.9+, Flask, Bleak (Async BLE)
- **Frontend**: Vanilla HTML5/CSS3 with Glassmorphism aesthetic and live REST telemetry polling
- **Home Assistant**: Automated REST State Engine
- **Bluetooth Protocol**: Reverse-engineered binary GATT 8-byte frames derived from V-Guard APK decompilation
