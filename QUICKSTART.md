# Quick Start Guide - V-Guard Smart 2.0 Flask Control Panel

## 30-Second Quick Start

1. **Install dependencies**:
   ```bash
   cd d:\PY\VGuard
   pip install -r requirements.txt
   ```

2. **Run the application**:
   ```bash
   python app.py
   ```

3. **Open browser**:
   - Navigate to: `http://localhost:5000`

4. **Start using**:
   - Click "Scan for Devices"
   - Select your V-Guard device
   - Click "Connect"
   - Use the control panel

## File Structure

- **app.py** - Main Flask application with API routes
- **bluetooth_manager.py** - Bluetooth communication and device handling
- **config.py** - Configuration settings
- **templates/index.html** - Web interface
- **static/style.css** - Web interface styling
- **requirements.txt** - Python dependencies
- **README.md** - Full documentation

## Key Features

✅ **Device Discovery** - Find V-Guard devices via Bluetooth
✅ **Device Connection** - Connect/disconnect from devices
✅ **Device Control** - Power, modes, sensitivity, commands
✅ **Device Monitoring** - Battery, signal, status tracking
✅ **Web Interface** - Modern, responsive dashboard
✅ **REST API** - Full API for integration

## API Quick Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/scan-devices` | GET | Find nearby devices |
| `/api/connect` | POST | Connect to device |
| `/api/disconnect` | POST | Disconnect device |
| `/api/device-info` | GET | Get device details |
| `/api/send-command` | POST | Send command to device |
| `/api/status` | GET | Get connection status |

## Common Commands

```bash
# Power on device
POST /api/send-command
{"command": "power", "params": {"state": "on"}}

# Set sensitivity
POST /api/send-command
{"command": "sensitivity", "params": {"level": 7}}

# Change mode
POST /api/send-command
{"command": "mode", "params": {"mode": "manual"}}
```

## Testing Without Hardware

The application includes **mock Bluetooth support**. If PyBluez is not available or no device is found:

1. Run the app normally
2. Use mock devices in the device list
3. All commands will return mock responses
4. Perfect for UI/API testing

To test API endpoints directly:

```bash
# Using curl
curl http://localhost:5000/api/scan-devices

# Or using Python
import requests
response = requests.get('http://localhost:5000/api/status')
print(response.json())
```

## Configuration

Edit `config.py` to customize:

- **Port**: `FLASK_PORT = 5000`
- **Bluetooth timeout**: `BLUETOOTH_CONNECT_TIMEOUT = 10`
- **Device names**: Update `MOCK_DEVICES`
- **Command codes**: Update `COMMAND_CODES`

## Troubleshooting

### PyBluez not installing?
```bash
pip install pybluez --only-binary :all:
```

### Port already in use?
```bash
# Change port in config.py or run on different port:
python -c "from app import app; app.run(port=5001)"
```

### Device not connecting?
1. Ensure device is powered on
2. Check Bluetooth is enabled
3. Try scanning again
4. Check device logs: check `vguard_app.log`

## Next Steps

1. **Customize the UI** - Edit `templates/index.html`
2. **Add more commands** - Update `bluetooth_manager.py`
3. **Deploy** - Use Gunicorn for production
4. **Integrate** - Use REST API from other applications

## Example: Python Integration

```python
import requests

BASE_URL = 'http://localhost:5000/api'

# Scan devices
devices = requests.get(f'{BASE_URL}/scan-devices').json()

# Connect to first device
if devices['devices']:
    device = devices['devices'][0]
    connection = requests.post(f'{BASE_URL}/connect', json={
        'address': device['address'],
        'name': device['name']
    }).json()
    
    # Get device info
    info = requests.get(f'{BASE_URL}/device-info').json()
    print(f"Battery: {info['info']['battery']}%")
    
    # Send command
    result = requests.post(f'{BASE_URL}/send-command', json={
        'command': 'power',
        'params': {'state': 'on'}
    }).json()
    
    # Disconnect
    requests.post(f'{BASE_URL}/disconnect')
```

## Production Deployment

For production use:

```bash
# Install Gunicorn
pip install gunicorn

# Run with Gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app

# In config.py, set FLASK_DEBUG = False
```

## Additional Resources

- Full documentation: See [README.md](README.md)
- Bluetooth protocol details: Check `bluetooth_manager.py` comments
- Configuration options: See `config.py`
- Frontend code: Edit `templates/index.html` and `static/style.css`

---

**Ready to go!** Run `python app.py` and visit `http://localhost:5000`
