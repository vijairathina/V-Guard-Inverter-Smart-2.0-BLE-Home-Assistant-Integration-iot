# 🍓 Raspberry Pi 4 (RPi4) Deployment Guide — V-Guard Smart Inverter

This guide provides step-by-step instructions to set up, run, and auto-start the **V-Guard Smart Inverter Control Center** on Raspberry Pi 4 (Raspberry Pi OS 64-bit / 32-bit).

---

## 🛠️ Step 1: Install System Prerequisites

Open terminal on your Raspberry Pi 4 and install Bluetooth BlueZ & Python dependencies:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv bluez bluetooth
```

Ensure the Raspberry Pi Bluetooth service is active:
```bash
sudo systemctl enable --now bluetooth
```

---

## 🔓 Step 2: Grant BLE Permissions to Python

To allow Python to perform BLE scans and GATT connections without requiring `sudo`:

```bash
sudo setcap 'cap_net_raw,cap_net_admin+eip' $(readlink -f $(which python3))
```

---

## 📁 Step 3: Clone / Copy Code & Set Up Virtual Environment

Navigate to your workspace directory (e.g. `/home/pi/VGuard`):

```bash
cd /home/pi/VGuard

# Create Python virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 🚀 Step 4: Run Application Manually

Test running the application:

```bash
python3 app.py --auto-connect VG_SMART_BT_WF_2
```

Access the Web Control Center from any device on your local network:
* **Local Web Dashboard**: `http://<YOUR_RPI_IP>:5000` (e.g. `http://192.168.1.100:5000`)

---

## 🔄 Step 5: Configure Systemd Service (Auto-Start at Boot)

To ensure the V-Guard controller runs automatically in the background at boot:

1. Create a systemd service file:
```bash
sudo nano /etc/systemd/system/vguard.service
```

2. Paste the following configuration (update `/home/pi/VGuard` if your path is different):
```ini
[Unit]
Description=V-Guard Smart Inverter Control Center & Home Assistant Bridge
After=network-online.target bluetooth.target
Wants=network-online.target bluetooth.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/VGuard
ExecStart=/home/pi/VGuard/venv/bin/python3 app.py --auto-connect VG_SMART_BT_WF_2
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

3. Save and close (`Ctrl + O`, `Enter`, `Ctrl + X`).

4. Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable vguard.service
sudo systemctl start vguard.service
```

5. Check live status & logs:
```bash
# Check service status
sudo systemctl status vguard.service

# View live real-time logs
sudo journalctl -u vguard.service -f
```

---

## 🏠 Step 6: Home Assistant REST Integration Setup

Once running on Raspberry Pi 4:
1. Open `http://<YOUR_RPI_IP>:5000` in your browser.
2. Click the **🏠 HA** button in the top right.
3. Enter your Home Assistant URL (e.g., `http://192.168.1.50:8123`) and Long-Lived Access Token.
4. Click **Save Config** — all 25+ inverter entities will automatically sync to Home Assistant!
