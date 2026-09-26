"""
Home Assistant Integration Module for V-Guard Inverter
Pushes telemetry, binary states, sensors, buttons, and switches to Home Assistant via REST API.
Listens in real time for button presses and switch toggles via Home Assistant's WebSocket API.
"""

import logging
import threading
import time
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple, Callable, List

try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

try:
    import config
except ImportError:
    config = None

logger = logging.getLogger(__name__)


def _http_request(url: str, method: str = 'GET', headers: Optional[Dict[str, str]] = None, payload: Optional[Dict[str, Any]] = None, timeout: float = 5.0) -> Tuple[int, str]:
    """Execute HTTP request using standard library urllib."""
    req = urllib.request.Request(url, method=method)
    headers = headers or {}
    for k, v in headers.items():
        req.add_header(k, v)

    body = None
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        req.add_header('Content-Type', 'application/json')

    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as resp:
            status = resp.status
            res_body = resp.read().decode('utf-8', errors='replace')
            return status, res_body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')
    except Exception as e:
        raise e


class HassPublisher:
    """Publishes V-Guard Inverter state to Home Assistant and receives real-time control events."""

    def __init__(self, ha_url: Optional[str] = None, ha_token: Optional[str] = None, prefix: Optional[str] = None):
        import os
        cfg_url = getattr(config, 'HA_URL', '')
        cfg_token = getattr(config, 'HA_TOKEN', '')
        cfg_interval = getattr(config, 'HA_PUSH_INTERVAL', 10)

        if os.path.exists('ha_config.json'):
            try:
                with open('ha_config.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        cfg_url = data.get('ha_url', cfg_url)
                        cfg_token = data.get('ha_token', cfg_token)
                        cfg_interval = data.get('push_interval', cfg_interval)
            except Exception:
                pass

        self.ha_url = (ha_url or cfg_url).rstrip('/')
        self.ha_token = ha_token or cfg_token
        self.prefix = prefix or getattr(config, 'HA_ENTITY_PREFIX', 'vguard_inverter')
        self.push_interval = cfg_interval
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_push_time = 0
        self._last_heartbeat_time = 0
        self._last_pushed_state: Dict[str, str] = {}
        self._buttons_pushed = False
        self.last_status = "Not configured"

        # WebSocket listener state
        self._command_callback: Optional[Callable[[str], Any]] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_running = False
        self._ws_client = None

    def is_configured(self) -> bool:
        return bool(self.ha_url and self.ha_token)

    def test_connection(self) -> Dict[str, Any]:
        """Verify connection to Home Assistant API."""
        if not self.is_configured():
            return {"success": False, "message": "Home Assistant URL or Token is missing"}

        headers = {
            "Authorization": f"Bearer {self.ha_token}",
        }
        url = f"{self.ha_url}/api/"
        try:
            status, res_body = _http_request(url, method='GET', headers=headers, timeout=5)
            if status == 200:
                try:
                    data = json.loads(res_body)
                    return {"success": True, "message": data.get("message", "API running")}
                except Exception:
                    return {"success": True, "message": "Connected to HA API"}
            return {"success": False, "message": f"HTTP {status}: {res_body}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def start_command_listener(self, callback: Callable[[str], Any]):
        """Start real-time Home Assistant WebSocket listener to execute button presses and switch toggles."""
        self._command_callback = callback
        if not self._ws_running:
            self._ws_running = True
            self._ws_thread = threading.Thread(target=self._ws_listener_loop, daemon=True, name="HACommandListener")
            self._ws_thread.start()
            logger.info("Home Assistant real-time WebSocket command listener thread started.")

    def reconnect_ws(self):
        """Force the WebSocket listener to reconnect (e.g. after config change)."""
        if self._ws_client:
            try:
                self._ws_client.close()
            except Exception:
                pass
            self._ws_client = None

    def _ws_listener_loop(self):
        """Continuously listen for Home Assistant button presses and switch toggles via WebSocket."""
        while self._ws_running:
            if not self.is_configured() or not WEBSOCKET_AVAILABLE:
                time.sleep(3.0)
                continue

            try:
                ws_scheme = 'wss://' if self.ha_url.startswith('https://') else 'ws://'
                raw_host = self.ha_url.split('://', 1)[-1].rstrip('/')
                ws_url = f"{ws_scheme}{raw_host}/api/websocket"
                logger.info(f"[HA-WS] Connecting to Home Assistant WebSocket at {ws_url}...")

                ws = websocket.create_connection(ws_url, timeout=7.0)
                self._ws_client = ws

                # 1. Auth required
                auth_req = json.loads(ws.recv())
                if auth_req.get('type') != 'auth_required':
                    logger.warning(f"[HA-WS] Unexpected initial message: {auth_req}")
                    ws.close()
                    time.sleep(3.0)
                    continue

                # 2. Authenticate
                ws.send(json.dumps({'type': 'auth', 'access_token': self.ha_token}))
                auth_res = json.loads(ws.recv())
                if auth_res.get('type') != 'auth_ok':
                    logger.error(f"[HA-WS] Authentication failed: {auth_res}")
                    ws.close()
                    time.sleep(10.0)
                    continue

                logger.info("[HA-WS] Authenticated successfully with Home Assistant WebSocket!")

                # 3. Subscribe to service calls (button.press, switch.turn_on/turn_off, etc.)
                ws.send(json.dumps({'id': 1, 'type': 'subscribe_events', 'event_type': 'call_service'}))
                sub1 = json.loads(ws.recv())
                logger.info(f"[HA-WS] Subscribed to call_service events: {sub1.get('success')}")

                # 4. Event processing loop (listening for button.press and switch.turn_on/turn_off)
                while self._ws_running:
                    raw_msg = ws.recv()
                    if not raw_msg:
                        break
                    try:
                        msg = json.loads(raw_msg)
                        self._handle_ws_message(msg)
                    except Exception as e:
                        logger.debug(f"[HA-WS] Error handling message: {e}")

            except Exception as e:
                logger.warning(f"[HA-WS] WebSocket connection error: {e}. Reconnecting in 5s...")
                time.sleep(5.0)
            finally:
                if self._ws_client:
                    try:
                        self._ws_client.close()
                    except Exception:
                        pass
                    self._ws_client = None

    def _handle_ws_message(self, msg: Dict[str, Any]):
        """Parse incoming WebSocket events from Home Assistant and dispatch commands."""
        if msg.get('type') != 'event':
            return

        ev = msg.get('event', {})
        ev_type = ev.get('event_type')
        if ev_type != 'call_service':
            return

        ev_data = ev.get('data', {})
        service = str(ev_data.get('service', ''))
        srv_data = ev_data.get('service_data', {})
        ent_val = srv_data.get('entity_id')

        target_entities: List[str] = []
        if isinstance(ent_val, list):
            target_entities = [str(e) for e in ent_val]
        elif isinstance(ent_val, str):
            target_entities = [ent_val]

        for ent in target_entities:
            ent_lower = ent.lower()
            if 'vguard' not in ent_lower and self.prefix not in ent_lower:
                continue

            cmd = None
            # 1. Button entity matching (covers buttons and service calls)
            if 'btn_force_cut_30m' in ent_lower:
                cmd = 'force_cut_30m'
            elif 'btn_force_cut_60m' in ent_lower:
                cmd = 'force_cut_60m'
            elif 'btn_force_cut_120m' in ent_lower:
                cmd = 'force_cut_120m'
            elif 'btn_force_cut_clear' in ent_lower or 'btn_force_cut_off' in ent_lower:
                cmd = 'force_cut_clear'
            elif 'btn_inverter_on' in ent_lower:
                cmd = 'inverter_on'
            elif 'btn_inverter_off' in ent_lower:
                cmd = 'inverter_off'
            elif 'btn_eco_mode_on' in ent_lower:
                cmd = 'eco_mode_on'
            elif 'btn_eco_mode_off' in ent_lower:
                cmd = 'eco_mode_off'
            elif 'btn_turbo_charging_on' in ent_lower:
                cmd = 'turbo_charging_on'
            elif 'btn_turbo_charging_off' in ent_lower:
                cmd = 'turbo_charging_off'
            elif 'btn_extra_backup_on' in ent_lower:
                cmd = 'extra_backup_on'
            elif 'btn_extra_backup_off' in ent_lower:
                cmd = 'extra_backup_off'
            elif 'btn_holiday_mode_on' in ent_lower:
                cmd = 'holiday_mode_on'
            elif 'btn_holiday_mode_off' in ent_lower:
                cmd = 'holiday_mode_off'
            # 2. Switch entity matching (turn_on / turn_off / toggle)
            elif 'force_cut' in ent_lower:
                if service in ('turn_on', 'toggle'):
                    cmd = 'force_cut_30m'
                elif service == 'turn_off':
                    cmd = 'force_cut_clear'
            elif 'power' in ent_lower or 'inverter_output' in ent_lower:
                if service in ('turn_on', 'toggle'):
                    cmd = 'inverter_on'
                elif service == 'turn_off':
                    cmd = 'inverter_off'
            elif 'eco_mode' in ent_lower:
                if service in ('turn_on', 'toggle'):
                    cmd = 'eco_mode_on'
                elif service == 'turn_off':
                    cmd = 'eco_mode_off'
            elif 'turbo_charging' in ent_lower:
                if service in ('turn_on', 'toggle'):
                    cmd = 'turbo_charging_on'
                elif service == 'turn_off':
                    cmd = 'turbo_charging_off'
            elif 'extra_backup' in ent_lower:
                if service in ('turn_on', 'toggle'):
                    cmd = 'extra_backup_on'
                elif service == 'turn_off':
                    cmd = 'extra_backup_off'
            elif 'holiday_mode' in ent_lower:
                if service in ('turn_on', 'toggle'):
                    cmd = 'holiday_mode_on'
                elif service == 'turn_off':
                    cmd = 'holiday_mode_off'

            if cmd:
                logger.info(f"[HA-WS] Dispatched command '{cmd}' from Home Assistant event on '{ent}' (service={service})")
                if self._command_callback:
                    try:
                        self._command_callback(cmd)
                    except Exception as ex:
                        logger.error(f"[HA-WS] Command callback error: {ex}")

    def publish_telemetry(self, telemetry: Dict[str, Any], force: bool = False) -> bool:
        """
        Push inverter telemetry dict to Home Assistant using event/sync method:
        - Only pushes when entity state or availability changes (like ESP door sensor).
        - Periodic heartbeat (every 120s) ensures HA state stays fresh.
        - When disconnected or no data: marks device unavailable, sensors set to -1 or null.
        """
        if not self.is_configured():
            self.last_status = "HA not configured"
            return False

        headers = {
            "Authorization": f"Bearer {self.ha_token}",
        }

        now_t = time.time()
        is_heartbeat = (now_t - self._last_heartbeat_time) > 120.0
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")

        # Determine connection & device availability
        is_connected = bool(telemetry.get('ble_connected'))
        last_ble = telemetry.get('last_ble_timestamp')
        is_stale = (not is_connected) or (last_ble is not None and (now_t - last_ble) > 45.0)
        is_available = is_connected and not is_stale

        telemetry['connected_device'] = telemetry.get('connected_device') or ("VG_SMART_BT_WF_2" if is_connected else "Disconnected")
        telemetry['mains_status'] = "Power Cut" if telemetry.get('utility_fail') else "Mains Available"

        device_info = {
            "identifiers": ["vguard_inverter_ble"],
            "name": "V-Guard Smart Inverter",
            "model": "V-Guard Synergy / Smart Inverter",
            "manufacturer": "V-Guard Industries Ltd."
        }

        mappings = [
            # Device Availability & Connection Status (ESP-style sync)
            ("binary_sensor", "status", "Device Status", None, "mdi:check-network", "connectivity"),
            ("binary_sensor", "available", "Device Available", None, "mdi:access-point-check", "connectivity"),
            ("binary_sensor", "ble_connected", "BLE Connected Status", None, "mdi:bluetooth-connect", "connectivity"),
            ("sensor", "connection_status", "BLE Connection Status", None, "mdi:bluetooth", None),
            ("sensor", "connected_device", "Connected BLE Device Name", None, "mdi:bluetooth-transfer", None),

            # Mains Status & Grid Outage
            ("sensor", "mains_status", "Mains Status", None, "mdi:transmission-tower", None),
            ("binary_sensor", "utility_fail", "Grid Power Cut", None, "mdi:power-off", "power"),

            # Battery Voltage & Electrical Sensors
            ("sensor", "battery_voltage", "Battery Voltage", "V", "mdi:battery-charging-100", "voltage"),
            ("sensor", "battery_current", "Battery Current", "A", "mdi:current-dc", "current"),
            ("sensor", "battery_pct", "Battery Percentage", "%", "mdi:battery-50", "battery"),
            ("sensor", "ac_input_voltage", "AC Input Voltage", "V", "mdi:transmission-tower", "voltage"),
            ("sensor", "ac_output_voltage", "AC Output Voltage", "V", "mdi:power-plug", "voltage"),
            ("sensor", "load_watts", "Load Power", "W", "mdi:lightning-bolt", "power"),
            ("sensor", "load_va", "Load Apparent Power", "VA", "mdi:flash-outline", "apparent_power"),
            ("sensor", "load_pct", "Load Percentage", "%", "mdi:gauge", None),
            ("sensor", "output_current", "Output Current", "A", "mdi:current-ac", "current"),
            ("sensor", "backup_time_mins", "Remaining Backup Time", "min", "mdi:timer-outline", "duration"),
            ("sensor", "remaining_hours", "Remaining Backup Hours", "h", "mdi:clock-outline", "duration"),
            ("sensor", "temperature", "Inverter Temperature", "°C", "mdi:thermometer", "temperature"),
            ("sensor", "power_cut_count", "Power Cut Count Today", "times", "mdi:counter", None),
            ("sensor", "power_cut_duration_mins", "Power Cut Duration Today", "min", "mdi:history", "duration"),

            # Binary sensors & status
            ("binary_sensor", "battery_low", "Battery Low Alarm", None, "mdi:battery-alert", "battery"),
            ("binary_sensor", "inverter_output", "Inverter Output Active", None, "mdi:power-socket-us", "running"),

            # Switches/States
            ("sensor", "eco_mode", "Eco Mode State", None, "mdi:leaf", None),
            ("sensor", "ac_charge", "AC Charging State", None, "mdi:battery-charging", None),
            ("sensor", "bypass_mode", "Bypass Mode State", None, "mdi:bypass", None),
            ("sensor", "alarm_status", "Alarm Register Raw", None, "mdi:alert-circle-outline", None),
        ]

        pushed_count = 0
        total_entities = 0

        for domain, suffix, friendly_name, unit, icon, dev_class in mappings:
            total_entities += 1
            entity_id = f"{domain}.{self.prefix}_{suffix}"
            url = f"{self.ha_url}/api/states/{entity_id}"

            # Availability entities reflect online/offline state directly
            if suffix in ("status", "available"):
                state_str = "on" if is_available else "off"
            elif suffix == "ble_connected":
                state_str = "on" if is_connected else "off"
            elif suffix == "connection_status":
                state_str = "Connected" if is_connected else "Disconnected"
            elif suffix == "connected_device":
                state_str = telemetry.get('connected_device', 'Disconnected') if is_connected else "Disconnected"
            elif not is_available:
                # User requirement: if no data / unavailable, make it null or -1
                if domain == "binary_sensor":
                    state_str = "off"
                else:
                    state_str = "-1"
            else:
                raw_val = telemetry.get(suffix)
                if raw_val is None:
                    state_str = "-1"
                elif domain == "binary_sensor":
                    state_str = "on" if bool(raw_val) else "off"
                elif isinstance(raw_val, float):
                    state_str = str(round(raw_val, 2))
                else:
                    state_str = str(raw_val)

            # Sync check: only send HTTP update if state changed, or forced, or heartbeat
            prev_state = self._last_pushed_state.get(entity_id)
            if not force and not is_heartbeat and prev_state == state_str:
                continue

            attributes = {
                "friendly_name": f"V-Guard Inverter {friendly_name}",
                "available": is_available,
                "last_synced": now_str,
                "device_info": device_info
            }
            if unit:
                attributes["unit_of_measurement"] = unit
            if icon:
                attributes["icon"] = icon
            if dev_class:
                attributes["device_class"] = dev_class

            payload = {
                "state": state_str,
                "attributes": attributes
            }

            try:
                status, _ = _http_request(url, method='POST', headers=headers, payload=payload, timeout=2.5)
                if status in (200, 201):
                    self._last_pushed_state[entity_id] = state_str
                    pushed_count += 1
            except Exception as e:
                logger.debug(f"Failed pushing {entity_id} to HA: {e}")

        # Interactive Switch Entities for Home Assistant
        switch_mappings = [
            ("switch", "power", "Inverter Power", "mdi:power", "on" if bool(telemetry.get('power_state') == 1) else "off"),
            ("switch", "force_cut", "Forced Power Cut (30m)", "mdi:flash-off", "on" if bool(telemetry.get('forced_power_cut')) else "off"),
            ("switch", "eco_mode", "Eco Mode", "mdi:leaf", "on" if bool(telemetry.get('eco_mode') == 1) else "off"),
            ("switch", "turbo_charging", "Turbo Charging", "mdi:battery-charging-wireless", "on" if bool(telemetry.get('turbo_charging') == 1) else "off"),
            ("switch", "extra_backup", "Extra Backup", "mdi:battery-plus", "on" if bool(telemetry.get('extra_backup') == 1) else "off"),
            ("switch", "holiday_mode", "Holiday Mode", "mdi:beach", "on" if bool(telemetry.get('holiday_mode') == 1) else "off"),
        ]

        for domain, suffix, friendly_name, icon, state_val in switch_mappings:
            entity_id = f"{domain}.{self.prefix}_{suffix}"
            url = f"{self.ha_url}/api/states/{entity_id}"
            state_str = state_val if is_available else "off"
            prev_state = self._last_pushed_state.get(entity_id)
            if not force and not is_heartbeat and prev_state == state_str:
                continue

            payload = {
                "state": state_str,
                "attributes": {
                    "friendly_name": f"V-Guard Inverter {friendly_name}",
                    "icon": icon,
                    "available": is_available,
                    "last_synced": now_str,
                    "device_info": device_info
                }
            }
            try:
                status, _ = _http_request(url, method='POST', headers=headers, payload=payload, timeout=2.5)
                if status in (200, 201):
                    self._last_pushed_state[entity_id] = state_str
                    pushed_count += 1
            except Exception as e:
                logger.debug(f"Failed pushing switch {entity_id} to HA: {e}")

        # Control Buttons for Home Assistant (pushed once or on force)
        if not self._buttons_pushed or force:
            button_mappings = [
                ("button", "btn_inverter_on", "Inverter Power ON", "mdi:power-on", "inverter_on"),
                ("button", "btn_inverter_off", "Inverter Power OFF", "mdi:power-off", "inverter_off"),
                ("button", "btn_force_cut_30m", "Force Cut 30 Mins", "mdi:flash-off", "force_cut_30m"),
                ("button", "btn_force_cut_60m", "Force Cut 60 Mins", "mdi:flash-off", "force_cut_60m"),
                ("button", "btn_force_cut_120m", "Force Cut 120 Mins", "mdi:flash-off", "force_cut_120m"),
                ("button", "btn_force_cut_clear", "Clear Force Cut", "mdi:flash-auto", "force_cut_clear"),
                ("button", "btn_eco_mode_on", "Eco Mode ON", "mdi:leaf", "eco_mode_on"),
                ("button", "btn_eco_mode_off", "Eco Mode OFF", "mdi:leaf-off", "eco_mode_off"),
                ("button", "btn_turbo_charging_on", "Turbo Charging ON", "mdi:battery-charging-wireless", "turbo_charging_on"),
                ("button", "btn_turbo_charging_off", "Turbo Charging OFF", "mdi:battery-charging-wireless-outline", "turbo_charging_off"),
                ("button", "btn_extra_backup_on", "Extra Backup ON", "mdi:battery-plus", "extra_backup_on"),
                ("button", "btn_extra_backup_off", "Extra Backup OFF", "mdi:battery-minus", "extra_backup_off"),
                ("button", "btn_holiday_mode_on", "Holiday Mode ON", "mdi:beach", "holiday_mode_on"),
                ("button", "btn_holiday_mode_off", "Holiday Mode OFF", "mdi:home", "holiday_mode_off"),
            ]
            for domain, suffix, friendly_name, icon, cmd_name in button_mappings:
                entity_id = f"{domain}.{self.prefix}_{suffix}"
                url = f"{self.ha_url}/api/states/{entity_id}"
                payload = {
                    "state": "idle",
                    "attributes": {
                        "friendly_name": f"V-Guard Inverter {friendly_name}",
                        "icon": icon,
                        "command": cmd_name,
                        "available": is_available,
                        "last_synced": now_str,
                        "device_info": device_info
                    }
                }
                try:
                    status, _ = _http_request(url, method='POST', headers=headers, payload=payload, timeout=2.5)
                    if status in (200, 201):
                        pushed_count += 1
                except Exception as e:
                    logger.debug(f"Failed pushing button {entity_id} to HA: {e}")
            self._buttons_pushed = True

        self._last_push_time = now_t
        if is_heartbeat:
            self._last_heartbeat_time = now_t

        if pushed_count > 0:
            self.last_status = f"Synced {pushed_count} updated states at {now_str} (Available: {is_available})"
            logger.info(f"[HASS-SYNC] {self.last_status}")
        else:
            self.last_status = f"States in sync at {now_str} (Available: {is_available})"
        return True
