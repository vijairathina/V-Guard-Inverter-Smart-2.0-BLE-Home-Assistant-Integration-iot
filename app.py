from flask import Flask, render_template, jsonify, request
from bluetooth_manager import BluetoothManager
import threading
import logging
import time
import config

app = Flask(__name__)
app.config['SECRET_KEY'] = 'vguard-smart-2.0-secret'

# Initialize Bluetooth Manager
bt_manager = BluetoothManager()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Store connected device info
connected_device = {
    'name': None,
    'address': None,
    'status': 'disconnected',
    'signal_strength': 0,
    'battery': 0,
    'voltage': 0.0,
    'temperature': 0.0,
    'current': 0.0,
    'power': 0.0,
    'uptime': 0,
    'connect_time': None,
    'device_info': {},
    'monitoring_enabled': False
}


# Initialize Home Assistant Publisher
try:
    from home_assistant import HassPublisher
    hass_publisher = HassPublisher()
except Exception as e:
    logger.warning(f"Home Assistant publisher init error: {e}")
    hass_publisher = None



auto_connect_target = None
auto_connect_enabled = False

def start_auto_connect(target_device: str = 'VG_SMART_BT_WF_2'):
    """Start background auto-connect thread targeting device name or address with auto-retry."""
    global auto_connect_target, auto_connect_enabled
    if auto_connect_enabled:
        return
    auto_connect_target = target_device or getattr(config, 'AUTO_CONNECT_DEVICE', 'VG_SMART_BT_WF_2')
    auto_connect_enabled = True

    def _auto_connect_loop():
        retry_interval = getattr(config, 'AUTO_CONNECT_RETRY_INTERVAL', 30)
        logger.info(f"Starting BLE Auto-Connect background thread for target '{auto_connect_target}' (Disconnected retry interval: {retry_interval}s)...")
        time.sleep(2.0)
        while auto_connect_enabled:
            wait_seconds = retry_interval
            try:
                if not bt_manager.is_connected():
                    logger.info(f"[Auto-Connect] Target '{auto_connect_target}' disconnected. Scanning nearby BLE devices (next retry in {retry_interval}s if failed)...")
                    found_devices = bt_manager.scan_devices(duration=5)
                    matched_dev = None

                    target_upper = auto_connect_target.upper()
                    for dev in found_devices:
                        dev_name = (dev.get('name') or '').upper()
                        dev_addr = (dev.get('address') or '').upper()
                        if target_upper in dev_name or target_upper == dev_addr or (target_upper == 'VG_SMART_BT_WF_2' and ('VG_SMART_BT_WF' in dev_name or '48:F6:EE:F4:D1:76' in dev_addr)):
                            matched_dev = dev
                            break

                    if not matched_dev and (target_upper == 'VG_SMART_BT_WF_2' or ':' in target_upper):
                        fallback_addr = '48:F6:EE:F4:D1:76' if target_upper == 'VG_SMART_BT_WF_2' else auto_connect_target
                        matched_dev = {'address': fallback_addr, 'name': auto_connect_target}
                        logger.info(f"[Auto-Connect] Target address fallback: trying direct connect to '{fallback_addr}' for '{auto_connect_target}'...")

                    if matched_dev:
                        addr = matched_dev['address']
                        name = matched_dev['name']
                        logger.info(f"[Auto-Connect] Found match/target '{name}' ({addr})! Connecting...")
                        success, message = bt_manager.connect(addr, device_name=name)
                        if success:
                            connected_device['address'] = addr
                            connected_device['name'] = name
                            connected_device['status'] = 'connected'
                            connected_device['connect_time'] = time.time()
                            connected_device['monitoring_enabled'] = True
                            logger.info(f"[Auto-Connect] Successfully connected to {name} ({addr})!")
                            wait_seconds = 5  # When connected, check connection state every 5s
                        else:
                            logger.warning(f"[Auto-Connect] Connection attempt failed: {message}. Waiting {retry_interval}s before next scan...")
                            wait_seconds = retry_interval
                    else:
                        logger.info(f"[Auto-Connect] Device '{auto_connect_target}' not detected in scan. Waiting {retry_interval}s before next scan...")
                        wait_seconds = retry_interval
                else:
                    wait_seconds = 5  # Check state every 5s while connected
            except Exception as e:
                logger.error(f"[Auto-Connect] Unexpected error in auto-connect loop: {e}")
                wait_seconds = retry_interval

            for _ in range(wait_seconds):
                if not auto_connect_enabled:
                    break
                time.sleep(1.0)

    ac_thread = threading.Thread(target=_auto_connect_loop, daemon=True, name="AutoConnectWorker")
    ac_thread.start()


def _sync_ha_now(force: bool = False):
    """Sync state to Home Assistant immediately."""
    try:
        if hass_publisher and hass_publisher.is_configured():
            telemetry = bt_manager.get_telemetry() or {}
            is_conn = bt_manager.is_connected()
            telemetry['ble_connected'] = is_conn
            telemetry['connection_status'] = "Connected" if is_conn else "Disconnected"
            telemetry['connected_device'] = bt_manager.device_name if (is_conn and bt_manager.device_name) else ("VG_SMART_BT_WF_2" if auto_connect_enabled else "Disconnected")
            hass_publisher.publish_telemetry(telemetry, force=force)
    except Exception as e:
        logger.error(f"HA sync error: {e}")

def _ha_background_loop():
    """Background worker checking state changes every 2 seconds and maintaining heartbeat."""
    while True:
        _sync_ha_now(force=False)
        time.sleep(2.0)

def _execute_ha_command(cmd_name: str):
    """Execute inverter command triggered by Home Assistant and immediately sync state."""
    logger.info(f"[HA-Listener] Executing command from Home Assistant: '{cmd_name}'")
    try:
        res = bt_manager.send_inverter_command(cmd_name)
        # Immediate state sync back to Home Assistant
        _sync_ha_now(force=True)
        return res
    except Exception as e: x
        logger.error(f"[HA-Listener] Command '{cmd_name}' execution error: {e}")
        return {'success': False, 'error': str(e)}

# Start Home Assistant real-time WebSocket command listener
if hass_publisher and hass_publisher.is_configured():
    try:
        hass_publisher.start_command_listener(_execute_ha_command)
    except Exception as e:
        logger.warning(f"Failed to start HA command listener: {e}")

# Register real-time callback so BLE telemetry arrival triggers HA sync immediately
try:
    bt_manager.register_response_callback(lambda raw: _sync_ha_now(force=False))
except Exception:
    pass

# Start background HA worker thread
ha_thread = threading.Thread(target=_ha_background_loop, daemon=True, name="HASyncWorker")
ha_thread.start()


@app.route('/')
def index():
    """Home page"""
    return render_template('index.html')


@app.route('/api/scan-devices', methods=['GET'])
def scan_devices():
    """Scan for nearby Bluetooth devices"""
    try:
        logger.info("Starting Bluetooth device scan...")
        devices = bt_manager.scan_devices(duration=5)
        
        # Filter for V-Guard devices
        vguard_devices = [
            d for d in devices 
            if 'vguard' in d.get('name', '').lower() 
            or 'v-guard' in d.get('name', '').lower()
            or d.get('name', '').lower().startswith('vg_')
            or 'vg_smart' in d.get('name', '').lower()
        ]
        
        logger.info(f"Found {len(vguard_devices)} V-Guard devices")
        return jsonify({
            'success': True,
            'devices': vguard_devices,
            'total_found': len(devices),
            'vguard_devices': len(vguard_devices)
        })
    except Exception as e:
        logger.error(f"Scan error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/connect', methods=['POST'])
def connect_device():
    """Connect to a Bluetooth device"""
    try:
        data = request.json
        address = data.get('address')
        name = data.get('name')
        
        if not address:
            return jsonify({'success': False, 'error': 'Device address required'}), 400
        
        logger.info(f"Attempting to connect to {name} ({address})...")
        
        success, message = bt_manager.connect(address, device_name=name)
        
        if success:
            connected_device['address'] = address
            connected_device['name'] = name
            connected_device['status'] = 'connected'
            connected_device['connect_time'] = time.time()
            connected_device['monitoring_enabled'] = True
            logger.info(f"Successfully connected to {name}")
        
        return jsonify({
            'success': success,
            'message': message,
            'device': connected_device if success else None
        })
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/disconnect', methods=['POST'])
def disconnect_device():
    """Disconnect from Bluetooth/BLE device.
    Optional JSON body: { "stop_auto_connect": true } to also pause the auto-connect worker.
    """
    global auto_connect_enabled
    try:
        data = request.get_json(silent=True) or {}
        stop_ac = data.get('stop_auto_connect', False)

        logger.info(f"Disconnecting from device (stop_auto_connect={stop_ac})...")
        connected_device['monitoring_enabled'] = False

        if stop_ac:
            auto_connect_enabled = False
            logger.info("Auto-connect worker paused by user request.")

        success, message = bt_manager.disconnect()

        if success:
            connected_device['status'] = 'disconnected'
            connected_device['address'] = None
            connected_device['name'] = None
            connected_device['signal_strength'] = 0
            connected_device['battery'] = 0
            connected_device['voltage'] = 0.0
            connected_device['temperature'] = 0.0
            connected_device['current'] = 0.0
            connected_device['power'] = 0.0
            connected_device['uptime'] = 0
            connected_device['connect_time'] = None
            connected_device['device_info'] = {}
            logger.info("Device disconnected successfully")

        return jsonify({
            'success': success,
            'message': message,
            'auto_connect_paused': stop_ac
        })
    except Exception as e:
        logger.error(f"Disconnect error: {str(e)}")
        connected_device['status'] = 'disconnected'
        connected_device['connect_time'] = None
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auto-connect/stop', methods=['POST'])
def stop_auto_connect_route():
    """Pause the BLE auto-connect worker without disconnecting the current session."""
    global auto_connect_enabled
    auto_connect_enabled = False
    logger.info("Auto-connect worker stopped by API request.")
    return jsonify({'success': True, 'message': 'Auto-connect paused. Device will not reconnect automatically.'})


@app.route('/api/auto-connect/start', methods=['POST'])
def start_auto_connect_route():
    """Resume the BLE auto-connect worker."""
    data = request.get_json(silent=True) or {}
    target = data.get('target', auto_connect_target or getattr(config, 'AUTO_CONNECT_DEVICE', 'VG_SMART_BT_WF_2'))
    start_auto_connect(target)
    logger.info(f"Auto-connect worker (re)started for target '{target}' by API request.")
    return jsonify({'success': True, 'message': f'Auto-connect resumed for {target}', 'target': target})


@app.route('/api/auto-connect/status', methods=['GET'])
def auto_connect_status_route():
    """Return current auto-connect worker state."""
    return jsonify({
        'auto_connect_enabled': auto_connect_enabled,
        'auto_connect_target': auto_connect_target,
        'ble_connected': bt_manager.is_connected(),
        'connected_device': bt_manager.device_name if bt_manager.is_connected() else None
    })


@app.route('/api/device-info', methods=['GET'])
def get_device_info():
    """Get connected device information"""
    try:
        if connected_device['status'] != 'connected':
            return jsonify({
                'success': False,
                'error': 'No device connected'
            }), 400
        
        logger.info("Requesting device information...")
        info = bt_manager.get_device_info()
        
        connected_device['device_info'] = info
        connected_device['battery'] = info.get('battery', 0)
        connected_device['signal_strength'] = info.get('signal_strength', 0)
        connected_device['voltage'] = info.get('voltage', 0.0)
        connected_device['temperature'] = info.get('temperature', 0.0)
        connected_device['current'] = info.get('current', 0.0)
        connected_device['power'] = info.get('power', 0.0)
        
        return jsonify({
            'success': True,
            'info': info,
            'device': connected_device
        })
    except Exception as e:
        logger.error(f"Get info error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/send-command', methods=['POST'])
def send_command():
    """Send command to connected device"""
    try:
        data = request.json
        command = data.get('command')
        params = data.get('params', {})
        
        if not command:
            return jsonify({'success': False, 'error': 'Command required'}), 400
        
        if connected_device['status'] != 'connected':
            return jsonify({'success': False, 'error': 'No device connected'}), 400
        
        logger.info(f"Sending command: {command} with params: {params}")
        inv_cmds = getattr(bt_manager, '_inverter_write_commands', {}) or {}
        if command in bt_manager.get_telemetry() or command in inv_cmds or any(k in command for k in ['force_cut', 'appliance_mode', 'extra_backup', 'turbo_charging', 'holiday_mode', 'eco_mode', 'bypass', 'ac_charge', 'inverter_']):
            response = bt_manager.send_inverter_command(command)
        else:
            response = bt_manager.send_command(command, params)
        
        return jsonify({
            'success': True,
            'command': command,
            'response': response
        })
    except Exception as e:
        logger.error(f"Command error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ----------------------------------------------------------------------
# Typed Inverter Endpoints
# ----------------------------------------------------------------------

@app.route('/api/inverter/telemetry', methods=['GET'])
def get_inverter_telemetry():
    """Get complete inverter telemetry dict."""
    telemetry = bt_manager.get_telemetry()
    return jsonify({
        'success': True,
        'connected': bt_manager.is_connected(),
        'telemetry': telemetry
    })


@app.route('/api/inverter/command', methods=['POST'])
def handle_inverter_command():
    """Execute typed inverter write command."""
    try:
        data = request.get_json(silent=True) or {}
        cmd = data.get('command')
        val = data.get('value')
        if not cmd:
            return jsonify({'success': False, 'error': 'Missing command parameter'}), 400

        resp = bt_manager.send_inverter_command(cmd, val)
        return jsonify(resp)
    except Exception as e:
        logger.error(f"Inverter command route error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


CONFIG_JSON_PATH = 'ha_config.json'

def load_ha_config():
    """Load settings from ha_config.json or fall back to config.py defaults."""
    import os, json
    cfg = {
        'ha_url': getattr(config, 'HA_URL', ''),
        'ha_token': getattr(config, 'HA_TOKEN', ''),
        'push_interval': getattr(config, 'HA_PUSH_INTERVAL', 10),
    }
    if os.path.exists(CONFIG_JSON_PATH):
        try:
            with open(CONFIG_JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    cfg.update(data)
        except Exception as e:
            logger.error(f"Error reading ha_config.json: {e}")
    return cfg

def save_ha_config(data: dict):
    """Save settings to ha_config.json on disk."""
    import json
    try:
        with open(CONFIG_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        logger.info("Saved HA config to ha_config.json")
    except Exception as e:
        logger.error(f"Error writing ha_config.json: {e}")


@app.route('/api/inverter/ha-config', methods=['GET', 'POST'])
def ha_config():
    """Get or update Home Assistant integration settings."""
    current_cfg = load_ha_config()
    if request.method == 'GET':
        return jsonify({
            'success': True,
            'ha_url': current_cfg.get('ha_url', ''),
            'ha_token': current_cfg.get('ha_token', ''),
            'push_interval': current_cfg.get('push_interval', 10),
            'configured': hass_publisher.is_configured() if hass_publisher else False,
            'last_status': hass_publisher.last_status if hass_publisher else 'Disabled'
        })

    data = request.json or {}
    url = data.get('ha_url', current_cfg.get('ha_url', ''))
    token = data.get('ha_token', current_cfg.get('ha_token', ''))
    interval = data.get('push_interval', current_cfg.get('push_interval', 10))

    if url is not None:
        url = str(url).strip()
    if token is not None:
        token = str(token).strip()
    if interval is not None and str(interval).isdigit():
        interval = int(interval)

    new_cfg = {
        'ha_url': url,
        'ha_token': token,
        'push_interval': interval
    }

    # Save to ha_config.json
    save_ha_config(new_cfg)

    # Update runtime publisher
    if hass_publisher:
        hass_publisher.ha_url = url.rstrip('/')
        hass_publisher.ha_token = token
        hass_publisher.push_interval = interval
        hass_publisher.reconnect_ws()
        hass_publisher.start_command_listener(_execute_ha_command)

    test_res = hass_publisher.test_connection() if hass_publisher else {'success': False, 'message': 'Publisher unavailable'}
    return jsonify({
        'success': True,
        'message': f"Configuration saved to ha_config.json! {test_res.get('message', '')}",
        'test_result': test_res
    })




@app.route('/api/inverter/ha-push', methods=['POST'])
def trigger_ha_push():
    """Manually trigger immediate Home Assistant push."""
    if not hass_publisher or not hass_publisher.is_configured():
        return jsonify({'success': False, 'error': 'Home Assistant is not configured'}), 400

    telemetry = bt_manager.get_telemetry()
    ok = hass_publisher.publish_telemetry(telemetry)
    return jsonify({
        'success': ok,
        'status': hass_publisher.last_status
    })


@app.route('/api/ha/command', methods=['POST'])
def ha_command():
    """Receive Home Assistant button trigger / REST action to execute inverter GATT command."""
    try:
        data = request.get_json(silent=True) or {}
        cmd = data.get('command') or data.get('action')
        if not cmd and 'entity_id' in data:
            ent = str(data['entity_id'])
            for suffix, c_name in [
                ('btn_inverter_on', 'inverter_on'),
                ('btn_inverter_off', 'inverter_off'),
                ('btn_force_cut_30m', 'force_cut_30m'),
                ('btn_force_cut_60m', 'force_cut_60m'),
                ('btn_force_cut_120m', 'force_cut_120m'),
                ('btn_force_cut_clear', 'force_cut_clear'),
                ('btn_eco_mode_on', 'eco_mode_on'),
                ('btn_eco_mode_off', 'eco_mode_off'),
                ('btn_turbo_charging_on', 'turbo_charging_on'),
                ('btn_turbo_charging_off', 'turbo_charging_off'),
                ('btn_extra_backup_on', 'extra_backup_on'),
                ('btn_extra_backup_off', 'extra_backup_off'),
                ('btn_holiday_mode_on', 'holiday_mode_on'),
                ('btn_holiday_mode_off', 'holiday_mode_off'),
            ]:
                if suffix in ent:
                    cmd = c_name
                    break

        if not cmd:
            return jsonify({'success': False, 'error': 'Missing command parameter'}), 400

        logger.info(f"[HA-Command] Executing Home Assistant command '{cmd}'...")
        resp = bt_manager.send_inverter_command(cmd)
        return jsonify(resp)
    except Exception as e:
        logger.error(f"HA command error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/status', methods=['GET'])
def get_status():
    """Get current connection status and telemetry"""
    is_connected = bt_manager.is_connected()
    telemetry = bt_manager.get_telemetry()
    connected_device['status'] = 'connected' if is_connected else 'disconnected'
    connected_device['telemetry'] = telemetry
    
    for k, v in telemetry.items():
        if k != 'raw_responses':
            connected_device[k] = v
            
    if is_connected and connected_device.get('connect_time'):
        connected_device['uptime'] = int(time.time() - connected_device['connect_time'])

    return jsonify({
        'connected': is_connected,
        'device': connected_device,
        'telemetry': telemetry
    })



@app.route('/api/available-commands', methods=['GET'])
def get_available_commands():
    """Get list of available commands for V-Guard device"""
    commands = {
        'inverter_on': {'description': 'Turn Inverter Output ON', 'params': []},
        'inverter_off': {'description': 'Turn Inverter Output OFF', 'params': []},
        'eco_mode_on': {'description': 'Turn Eco Mode ON', 'params': []},
        'eco_mode_off': {'description': 'Turn Eco Mode OFF', 'params': []},
        'ac_charge_on': {'description': 'Enable AC Charging', 'params': []},
        'ac_charge_off': {'description': 'Disable AC Charging', 'params': []},
        'bypass_on': {'description': 'Enable Bypass Mode', 'params': []},
        'bypass_off': {'description': 'Disable Bypass Mode', 'params': []},
        'status': {'description': 'Get device status & telemetry', 'params': []},
    }
    return jsonify({'commands': commands})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="V-Guard Smart Inverter Control Panel")
    parser.add_argument('--auto-connect', '--connect', '-c', nargs='?', const='VG_SMART_BT_WF_2', type=str, help="Auto-connect to BLE device on startup (default: VG_SMART_BT_WF_2)")
    parser.add_argument('--device', '-d', type=str, help="Target BLE device name or MAC address")
    parser.add_argument('--port', '-p', type=int, default=5004, help="Flask server port (default: 5000)")
    args = parser.parse_args()

    target_dev = args.device or args.auto_connect or getattr(config, 'AUTO_CONNECT_DEVICE', 'VG_SMART_BT_WF_2')
    if target_dev and getattr(config, 'AUTO_CONNECT_ENABLED', True):
        device_name = target_dev if isinstance(target_dev, str) else 'VG_SMART_BT_WF_2'
        logger.info(f"Auto-connect enabled for device: '{device_name}'")
        start_auto_connect(device_name)

    logger.info("Starting V-Guard Smart 2.0 Flask Application")
    app.run(debug=True, host='0.0.0.0', port=args.port)

