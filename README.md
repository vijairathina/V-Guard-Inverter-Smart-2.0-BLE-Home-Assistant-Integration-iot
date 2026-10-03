# V-Guard Smart Inverter - BLE & Home Assistant Integration - IOT

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-REST%20API-41BDF5.svg?logo=home-assistant)](https://www.home-assistant.io/)
[![Bluetooth LE](https://img.shields.io/badge/Bluetooth-BLE%20GATT-0082FC.svg?logo=bluetooth)](https://www.bluetooth.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An open-source, reverse-engineered Bluetooth Low Energy (BLE) control panel, telemetry bridge, and Home Assistant integration for **V-Guard Smart Inverters** (`VG_SMART_BT_WF_2`, Synergy, and compatible series).

Control your inverter, monitor real-time battery and grid status, and automate power management directly within Home Assistant—no cloud or proprietary app required.

---

## 📑 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Supported Hardware](#-supported-hardware)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
  - [1. Web Control Panel](#1-web-control-panel)
  - [2. Command Line Interface (CLI)](#2-command-line-interface-cli)
- [Home Assistant Integration](#-home-assistant-integration)
  - [Setup Instructions](#setup-instructions)
  - [Exposed Entities](#exposed-entities)
- [Background Service Deployment](#-background-service-deployment)
  - [Linux / Raspberry Pi (Systemd)](#linux--raspberry-pi-systemd)
  - [Windows Service (NSSM)](#windows-service-nssm)
- [Reverse-Engineered BLE Protocol](#-reverse-engineered-ble-protocol)
  - [GATT Services & Characteristics](#gatt-services--characteristics)
  - [8-Byte Binary Frame Structure](#8-byte-binary-frame-structure)
  - [Verified Hardware Commands](#verified-hardware-commands)
- [Troubleshooting](#-troubleshooting)
- [Disclaimer & License](#-disclaimer--license)

---

## ✨ Features

- **⚡ Real-Time BLE Telemetry**:
  - Grid AC Input Voltage & Frequency
  - Inverter Output Voltage, Current, and Active Load (Watts)
  - Battery Terminal Voltage & State of Charge (SOC %)
  - Internal Operating Temperature
  - Remaining Backup Runtime calculation
- **🎛️ Full Hardware Control**:
  - Inverter Output ON / OFF
  - Forced Mains Power Cut (Simulate grid failure / run on battery) & Restore Grid
  - High Load Appliance Mode (Wide AC voltage window)
  - Deep Discharge Extra Backup Mode
  - Turbo Fast Battery Charging
- **🏠 Home Assistant Integration**:
  - Streams state updates directly to Home Assistant via REST API
  - Automatically provisions sensors and binary sensors
  - Supports bidirectional control from Home Assistant
- **🔄 Fault-Tolerant Auto-Connect**:
  - Autonomous BLE background reconnection engine with backoff protection
- **💻 Modern Web Dashboard**:
  - Responsive, dark glassmorphism user interface
  - Outage tracking, power cut counter, and real-time graphs

---

## 🏗️ Architecture

```
┌─────────────────────────┐          BLE GATT          ┌───────────────────────────────┐
│   V-Guard Smart         │  (8-byte binary frames)   │   V-Guard Python Engine       │
│   Inverter Device       │ ◄──────────────────────► │   • bleak (Async BLE client)  │
│   (VG_SMART_BT_WF_2)    │                           │   • State & Telemetry parser  │
└─────────────────────────┘                           └──────────────┬────────────────┘
                                                                     │
                                             ┌───────────────────────┴───────────────────────┐
                                             ▼                                               ▼
                              ┌─────────────────────────────┐                 ┌─────────────────────────────┐
                              │     Flask Web Dashboard     │                 │   Home Assistant REST API   │
                              │    (http://localhost:5000)  │                 │    Live Entity Streaming    │
                              └─────────────────────────────┘                 └─────────────────────────────┘
```

---

## 🔌 Supported Hardware

| Hardware | Compatibility | Notes |
|:---|:---:|:---|
| **V-Guard Smart Inverter** (`VG_SMART_BT_WF_2`) | Verified | Full telemetry + command controls |
| **V-Guard Synergy Series** | Compatible | Standard 8-byte GATT payload models |
| **V-Guard Smart 2.0 Smart Plugs** | Partial | Uses ASCII UART-over-BLE mode |

---

## 📋 Prerequisites

- **Python**: Version 3.9 or higher
- **Bluetooth Adapter**: BLE 4.0 or newer adapter on your host system (built-in or USB dongle)
- **Supported Operating Systems**:
  - Linux (Ubuntu, Debian, Raspberry Pi OS with BlueZ)
  - Windows 10 / 11

---

## 📦 Installation

```bash
# 1. Clone the repository
git clone https://github.com/vijairathina/V-Guard-Smart-2.0-BLE-Home-Assistant-Integration.git
cd V-Guard-Smart-2.0-BLE-Home-Assistant-Integration

# 2. Create and activate a Python virtual environment
# On Linux / macOS:
python3 -m venv venv
source venv/bin/activate

# On Windows (PowerShell):
python -m venv venv
.\venv\Scripts\activate

# 3. Install required packages
pip install -r requirements.txt
```

---

## 🚀 Quick Start

### 1. Web Control Panel

#### Auto-Connect Mode (Recommended)
Automatically searches for and locks onto your inverter:
```bash
python app.py --auto-connect VG_SMART_BT_WF_2
```

#### Manual Mode
Launch the server and scan/connect manually from the web UI:
```bash
python app.py
```

Then open your browser and go to:
👉 **`http://localhost:5000`**

#### Custom Host / Port
```bash
python app.py --host 0.0.0.0 --port 8080 --auto-connect VG_SMART_BT_WF_2
```

---

### 2. Command Line Interface (CLI)

You can also inspect devices or trigger commands directly from the terminal:

```bash
# Scan for nearby V-Guard BLE devices
python cli.py scan

# Query live telemetry from an inverter
python cli.py status --device "VG_SMART_BT_WF_2"

# Send a direct hardware command (e.g. toggle output, force power cut)
python cli.py command inverter_on
python cli.py command force_cut_on
python cli.py command turbo_charging_on
```

---

## 🏠 Home Assistant Integration

This bridge automatically provisions and updates sensors in Home Assistant using the Home Assistant REST API.

### Setup Instructions

1. **Generate a Long-Lived Access Token in Home Assistant**:
   - In Home Assistant, open your User Profile (bottom left).
   - Scroll to **Long-Lived Access Tokens** and click **Create Token**.
   - Name it `V-Guard Inverter` and copy the generated token.

2. **Configure Connection**:
   - Copy the sample config:
     ```bash
     cp ha_config.json.example ha_config.json
     ```
   - Edit `ha_config.json`:
     ```json
     {
       "ha_url": "http://192.168.1.100:8123",
       "ha_token": "PASTE_YOUR_LONG_LIVED_ACCESS_TOKEN_HERE",
       "push_interval": 10
     }
     ```
   *(Note: You can also update these credentials at any time via the Web Dashboard Settings tab!)*

3. **Start the Application**:
   Once started, the bridge will immediately push live states into Home Assistant.

### Exposed Entities

| Entity ID | Type | Description | Unit |
|:---|:---:|:---|:---:|
| `binary_sensor.vguard_inverter_ble_connected` | Binary Sensor | Bluetooth connection status | On/Off |
| `sensor.vguard_inverter_connection_status` | Sensor | Human-readable connection state | — |
| `sensor.vguard_inverter_mains_status` | Sensor | Grid power state (`MAINS AVAILABLE` / `POWER CUT`) | — |
| `sensor.vguard_inverter_battery_voltage` | Sensor | Scaled battery terminal voltage | `V` |
| `sensor.vguard_inverter_battery_pct` | Sensor | Calculated battery state of charge | `%` |
| `sensor.vguard_inverter_grid_voltage` | Sensor | Grid input AC voltage | `V` |
| `sensor.vguard_inverter_load_watts` | Sensor | Active load consumed by appliances | `W` |
| `sensor.vguard_inverter_backup_time` | Sensor | Estimated remaining backup runtime | `min` |

---

## ⚙️ Background Service Deployment

### Linux / Raspberry Pi (Systemd)

To run the gateway 24/7 as a background daemon on a Raspberry Pi or Linux server:

1. Create a service file:
   ```bash
   sudo nano /etc/systemd/system/vguard.service
   ```

2. Paste the following configuration (adjust paths and user as necessary):
   ```ini
   [Unit]
   Description=V-Guard Smart Inverter BLE Control & HA Bridge
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

3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable vguard.service
   sudo systemctl start vguard.service
   ```

---

### Windows Service (NSSM)

To run automatically in the background on Windows without an open terminal window:

1. Download [NSSM (Non-Sucking Service Manager)](https://nssm.cc/).
2. In an Administrator PowerShell terminal:
   ```powershell
   nssm install VGuardInverter "C:\path\to\VGuard\venv\Scripts\python.exe" "app.py --auto-connect VG_SMART_BT_WF_2"
   nssm set VGuardInverter AppDirectory "C:\path\to\VGuard"
   nssm set VGuardInverter Start SERVICE_AUTO_START
   nssm start VGuardInverter
   ```

---

## ⚡ Reverse-Engineered BLE Protocol

### GATT Services & Characteristics

The V-Guard Smart Inverter exposes the following BLE GATT structure:

- **Service UUID**: `0003cdd0-0000-1000-8000-00805f9b0131`
- **RX Characteristic (Write)**: `0003cdd1-0000-1000-8000-00805f9b0131`
- **TX Characteristic (Notify)**: `0003cdd2-0000-1000-8000-00805f9b0131`

### 8-Byte Binary Frame Structure

Hardware control commands require strict 8-byte frames:

| Byte Index | Field | Description | Example |
|:---:|:---|:---|:---:|
| `0` | Header | Fixed command header | `0xFF` |
| `1` | Value Low | Parameter value lower byte | `0x01` |
| `2` | Value High | Parameter value upper byte | `0x00` |
| `3` | Register | Function / Register opcode | `0x16` (Output) |
| `4` | Delimiter | Frame delimiter | `0x0C` |
| `5` | Reserved | Padding byte | `0x00` |
| `6` | Trailer 1 | Fixed frame tail | `0xFF` |
| `7` | Trailer 2 | Fixed frame tail | `0xFF` |

### Verified Hardware Commands

| Command Name | GATT Hex Frame | Action |
|:---|:---|:---|
| `inverter_on` | `FF 01 00 16 0C 00 FF FF` | Turn Inverter Output ON |
| `inverter_off` | `FF 00 00 16 0C 00 FF FF` | Turn Inverter Output OFF |
| `force_cut_on` | `FF 00 00 2E 0C 00 FF FF` | Force Mains Cut (Switch to Battery Backup) |
| `force_cut_off` | `FF 01 00 2E 0C 00 FF FF` | Restore Grid Mains Supply |
| `appliance_mode_on` | `FF 4C 04 3E 0C 00 FF FF` | Enable High Appliance Voltage Window |
| `appliance_mode_off`| `FF 64 00 3E 0C 00 FF FF` | Enable Standard Voltage Window |
| `extra_backup_on` | `FF E8 03 6E 0C 00 FF FF` | Deep Discharge Extra Backup ON |
| `extra_backup_off` | `FF 00 00 6E 0C 00 FF FF` | Deep Discharge Extra Backup OFF |
| `turbo_charging_on` | `FF 01 00 6C 0C 00 FF FF` | Turbo Fast Battery Charging ON |
| `turbo_charging_off`| `FF 00 00 6C 0C 00 FF FF` | Standard Battery Charging Mode |

---

## 🛠️ Troubleshooting

- **Inverter Not Found During Scan**:
  - Ensure the inverter is within Bluetooth range (< 5–10 meters).
  - Verify that the inverter is not already paired/connected to the official Android/iOS app (BLE allows only one active connection at a time).
- **Linux BLE Permissions**:
  - If running without root, ensure your user is in the `bluetooth` group:
    ```bash
    sudo userver -a -G bluetooth $USER
    ```
- **Port In Use (Address already in use: 5000)**:
  - Run on a different port using `--port <PORT>`:
    ```bash
    python app.py --port 5050
    ```

---

## 📄 Disclaimer & License

- **Disclaimer**: This is an independent open-source project created via clean-room protocol analysis for local automation and interoperability. It is not affiliated with, endorsed by, or associated with V-Guard Industries Ltd.
- **License**: Released under the [MIT License](LICENSE).
