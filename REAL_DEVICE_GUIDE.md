# Real Bluetooth Device Connection Guide

## ✅ Real Device Support Implemented

The V-Guard Smart 2.0 Flask Control Panel now has **full support for real Bluetooth device connection** using PyBluez and RFCOMM protocol.

## Features

### Real Bluetooth Connection
- ✅ Actual device scanning using Bluetooth discovery
- ✅ RFCOMM socket connection (ports 1-12)
- ✅ Background receive thread for real-time data
- ✅ Send/receive raw data support
- ✅ Connection state monitoring
- ✅ Proper error handling and recovery

### Advanced Features
- ✅ Multi-threaded communication (non-blocking)
- ✅ Response callbacks for real-time updates
- ✅ Thread-safe connection management
- ✅ Automatic port detection
- ✅ Connection health monitoring

## Installation (Real Device Mode)

### Prerequisites
- **Windows 10/11** with Bluetooth hardware
- **Python 3.7+**
- **Visual C++ Build Tools** (for compiling PyBluez)

### Setup Steps

1. **Install C++ Build Tools**:
   ```bash
   # Option A: Install Visual Studio Build Tools (Recommended)
   # Download from: https://visualstudio.microsoft.com/downloads/
   # Select "Desktop development with C++"
   
   # Option B: Install using pip
   pip install windows-cpp-build-tools
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Install dependencies with real device support**:
   ```bash
   pip install -r requirements.txt --only-binary :all:
   ```

   Or manually:
   ```bash
   pip install Flask==2.3.3 Werkzeug==2.3.7
   pip install pybluez --only-binary :all:
   ```

4. **Verify installation**:
   ```bash
   python -c "import bluetooth; print('✓ PyBluez installed')"
   ```

## Using Real Devices

### Method 1: Web Interface (Recommended)

1. **Start Flask server**:
   ```bash
   python app.py
   ```

2. **Open browser**:
   ```
   http://localhost:5000
   ```

3. **Scan for devices**:
   - Click "Scan for Devices" button
   - Wait for scan to complete (5-10 seconds)
   - Select your V-Guard device from the list

4. **Connect**:
   - Click "Connect" next to your device
   - Wait for connection confirmation
   - Use the control panel

### Method 2: Python Script (Testing)

```bash
python test_bluetooth.py
```

This runs an interactive test that:
- Scans for real Bluetooth devices
- Attempts connection to a specified device
- Tests device communication
- Validates command sending

### Method 3: Programmatic Access

```python
from bluetooth_manager import BluetoothManager

# Create manager
bt = BluetoothManager()

# Scan for devices
devices = bt.scan_devices(duration=10)
print(f"Found {len(devices)} devices")

# Connect
success, msg = bt.connect(devices[0]['address'])
if success:
    # Get device info
    info = bt.get_device_info()
    print(f"Battery: {info['battery']}%")
    
    # Send command
    response = bt.send_command('power', {'state': 'on'})
    
    # Disconnect
    bt.disconnect()
```

## How Real Connection Works

### Device Discovery
```python
devices = bt.scan_devices(duration=10)  # Scan for 10 seconds
# Uses native Bluetooth discovery API
# Returns list of discovered devices with MAC addresses
```

### RFCOMM Connection
```python
success, msg = bt.connect('00:1A:7D:DA:71:13')
# Attempts connection on RFCOMM ports 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12
# Returns True on first successful connection
# Starts background receive thread
```

### Communication Protocol
```
Packet Structure:
┌─────────┬─────────┬─────────┬────────────┬──────────┐
│ Header  │ Length  │ Command │ Parameters │ Checksum │
│ (0xAABB)│ (1 byte)│ (1 byte)│ (N bytes)  │ (1 byte) │
└─────────┴─────────┴─────────┴────────────┴──────────┘

Example:
AA BB 02 01 03  = power command with params
│  │  │  │  │
│  │  │  │  └── Checksum
│  │  │  └────── Command param (0x03)
│  │  └───────── Command code (0x01 = power)
│  └──────────── Payload length (2 bytes)
└─────────────── Header
```

### Background Receive Thread
```python
# Automatic background thread receives data
# Stores last response for immediate access
# Calls registered callbacks in real-time

def on_data(data):
    print(f"Received: {data.hex()}")

bt.register_response_callback(on_data)
```

## API Methods

### Scanning
```python
# Scan for devices (blocking)
devices = bt.scan_devices(duration=5)
# Returns: [{'address': 'XX:XX:...', 'name': 'Device Name', ...}, ...]
```

### Connection
```python
# Connect to device
success, message = bt.connect('00:1A:7D:DA:71:13', port=None)
# port: optional RFCOMM port (auto-detect if None)

# Check connection status
is_connected = bt.is_connected()

# Disconnect
success, message = bt.disconnect()
```

### Communication
```python
# Send structured command
response = bt.send_command('power', {'state': 'on'}, wait_response=True)

# Send raw data
success = bt.send_raw_data(b'\xAA\xBB\x01...')

# Receive raw data
data = bt.receive_raw_data(timeout=1.0)
```

### Information
```python
# Get device info
info = bt.get_device_info()
# Returns: {'name': ..., 'battery': ..., 'signal_strength': ..., ...}

# Register callback for real-time updates
bt.register_response_callback(callback_function)
```

## Troubleshooting

### Issue: "PyBluez not available"

**Solution**: Install with binary wheels
```bash
pip install pybluez --only-binary :all:
```

### Issue: "Connection failed on port X"

**Solution**: Device may not support RFCOMM on those ports
```python
# Try specific port
success, msg = bt.connect('00:1A:7D:DA:71:13', port=5)
```

### Issue: "Could not connect to address"

**Possible causes**:
- Device is off or out of range
- Device is already connected elsewhere
- Device doesn't support Bluetooth Classic (check if it's BLE-only)
- Windows Bluetooth driver issue

**Solutions**:
1. Power cycle the device
2. Disconnect from other devices
3. Update Windows Bluetooth drivers
4. Check Device Manager for Bluetooth status

### Issue: "Command sent but no response"

**Normal behavior** - Device may not send responses
```python
# Send without waiting for response
response = bt.send_command('power', wait_response=False)
```

### Issue: Port already in use

**Solution**: Change Flask port in config.py
```python
FLASK_PORT = 5001  # Change to different port
```

## Device Communication Protocol

The application implements a custom Bluetooth protocol compatible with V-Guard devices:

### Supported Commands
```
0x01 - Power:      Turn device on/off
0x02 - Mode:       Set device mode
0x03 - Sensitivity: Adjust sensitivity level
0x04 - Alarm:      Control alarm
0x05 - Reset:      Reset device
0x06 - Status:     Get device status
0x07 - Battery:    Get battery level
0x08 - Signal:     Get signal strength
```

### Example Communication Flow
```
CLIENT → DEVICE:  AA BB 02 01 01  (Power ON)
DEVICE → CLIENT:  AA BB 02 01 00  (Acknowledged)

CLIENT → DEVICE:  AA BB 02 03 07  (Sensitivity 7)
DEVICE → CLIENT:  AA BB 02 03 00  (Acknowledged)
```

## Performance Tips

1. **Non-blocking**: Use background thread for real-time updates
2. **Timeouts**: Receive operations timeout after 5 seconds
3. **Threading**: Connection thread-safe using locks
4. **Buffering**: Data buffer stores multiple messages
5. **Callbacks**: Register callbacks for event-driven updates

## Security Notes

- Bluetooth traffic is not encrypted by default
- Use trusted networks only
- V-Guard devices should be paired first (manual pairing via Windows)

## Next Steps

1. **Test connection**: Run `python test_bluetooth.py`
2. **Test web interface**: Open `http://localhost:5000`
3. **Check logs**: Monitor application logs for debug info
4. **Customize protocol**: Update command codes in `bluetooth_manager.py`

## Support

If you encounter issues:

1. Check `vguard_app.log` for detailed error messages
2. Run test script with verbose output
3. Enable DEBUG logging level in config.py
4. Check Windows Device Manager for Bluetooth status

---

**V-Guard Smart 2.0 Flask Control Panel - Real Bluetooth Edition**
