"""
Bluetooth Manager for V-Guard Smart 2.0 (Smart Plug) and V-Guard Inverter.

Two distinct protocols confirmed from APK decompilation:

  SMART PLUG (BluetoothLeService.kt / PlugDashboardViewModel.kt):
    WRITE:   UTF-8 "read:VGxxx" or "VGxxx:value" to TX char (0003cdd2)
    RECEIVE: UTF-8 "VGxxx:value" via notifications on RX char (0003cdd1)
    HANDSHAKE: SN:<device-name> → VG008:<timestamp> → read:VG012, VG136, VG132

  INVERTER (InverterDashboardViewModel.kt / InverterCommands.kt):
    WRITE:   8-byte binary frame  FF FF FF [cmd] 0C 01 FF FF  (READ request)
    RECEIVE: 8-byte binary frame  — value = (byte[7]<<8)|byte[6]  (little-endian)
    NO handshake — connect, subscribe, send initial status poll immediately.
    Partial frames are accumulated until exactly 8 bytes are collected.

No mock data.
"""

import logging
import time
import threading
import asyncio
import re
from typing import Tuple, List, Dict, Optional, Callable

import config

logger = logging.getLogger(__name__)

try:
    from bleak import BleakScanner, BleakClient
    from bleak.exc import BleakError
    BLUETOOTH_AVAILABLE = True
    logger.info("Bleak loaded OK")
except ImportError:
    logger.error("bleak not installed — run: pip install bleak")
    BLUETOOTH_AVAILABLE = False

try:
    from inverter_protocol import (
        INVERTER_DASHBOARD_POLL,
        INVERTER_STATUS_POLL,
        INVERTER_REGISTER_MAP,
        INVERTER_CMD_BYTES,
        INVERTER_WRITE_COMMANDS,
        INVERTER_ASCII_FALLBACK_COMMANDS,
        ALARM_STATUS_BITS,
        parse_inverter_response,
        build_inverter_read_cmd,
        build_inverter_write_cmd,
        apply_scale,
    )
    INVERTER_PROTOCOL_AVAILABLE = True
    logger.info("inverter_protocol loaded OK")
except ImportError as _e:
    logger.warning(f"inverter_protocol not available: {_e}")
    INVERTER_PROTOCOL_AVAILABLE = False
    INVERTER_DASHBOARD_POLL = []
    INVERTER_STATUS_POLL = []
    INVERTER_WRITE_COMMANDS = {}
    INVERTER_ASCII_FALLBACK_COMMANDS = {}



class BluetoothManager:
    """BLE communication with V-Guard Smart 2.0 — ASCII protocol"""

    def __init__(self):
        self.client: Optional[BleakClient] = None
        self.connected = False
        self.device_address: Optional[str] = None
        self.device_name: Optional[str] = None
        self.device_info: Dict = {}
        self.connection_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._handshake_done = False   # set True after SN+VG008 completes
        self._tx_char_uuid = config.BLE_TX_CHAR_UUID
        self._rx_char_uuid = config.BLE_RX_CHAR_UUID

        # Live telemetry (populated from device VGxxx:value responses)
        self._telemetry: Dict = {
            'power_state':   None,   # VG092  (0=off 1=on)
            'voltage':       None,   # VG005  (V)
            'current':       None,   # VG003  (A)
            'power':         None,   # VG295  (W)
            'energy':        None,   # VG192  (kWh)
            'temperature':   None,   # VG273  (°C)
            'firmware':      None,   # VG004
            'model':         None,   # VG030
            'signal_strength': None,
            'raw_responses': [],
            'timestamp':     None,
        }

        # Reassembly buffer for "@"-fragmented notifications (Smart Plug)
        self._rx_buffer: str = ""

        # Parsed complete lines received via notify
        self._received_lines: List[str] = []
        self._received_lock = threading.Lock()
        # Global event — set whenever ANY notification arrives
        self._notify_event = threading.Event()
        # Per-VG-code waiting events: vg_code -> threading.Event
        self._pending_requests: Dict[str, threading.Event] = {}
        self._pending_lock = threading.Lock()
        self._response_callbacks: List[Callable] = []

        self._rx_char_candidates: List[str] = []
        self._tx_char_candidates: List[str] = []
        # Binary/inverter support
        self._binary_parsers: List[Callable[[bytes], Optional[Dict]]] = []
        self._is_inverter_device = False
        self._inverter_write_commands = INVERTER_WRITE_COMMANDS
        self._inverter_ascii_fallback_commands = INVERTER_ASCII_FALLBACK_COMMANDS

        # Inverter partial-frame accumulator (frames arrive as < 8 bytes sometimes)
        self._inverter_frame_buf: bytes = b""
        # Last register_id polled (so response can be matched)
        self._inverter_last_cmd_reg: Optional[int] = None

        # Guard against duplicate monitoring threads
        self._monitoring_active = False
        self._monitoring_lock = threading.Lock()

        # Background asyncio loop (bleak must run in a dedicated loop)
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_event_loop,
            args=(self._loop,),
            daemon=True,
            name="BleakLoop",
        )
        self._loop_thread.start()

    # ------------------------------------------------------------------ #
    #  Event loop helpers
    # ------------------------------------------------------------------ #

    def _run_event_loop(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _run_async(self, coro, timeout: float = 15.0):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def register_response_callback(self, cb: Callable):
        self._response_callbacks.append(cb)

    # ------------------------------------------------------------------ #
    #  Scan
    # ------------------------------------------------------------------ #

    def scan_devices(self, duration: int = 5) -> List[Dict]:
        """Scan for nearby BLE devices."""
        if not BLUETOOTH_AVAILABLE:
            logger.error("bleak not installed")
            return []

        async def _scan():
            logger.info(f"BLE scan ({duration}s)…")
            found = await BleakScanner.discover(timeout=float(duration), return_adv=True)
            return [
                {
                    'address': addr,
                    'name': dev.name or adv.local_name or f"Unknown ({addr})",
                    'rssi': adv.rssi,
                    'uuids': list(adv.service_uuids),
                    'class': 'BLE Device',
                }
                for addr, (dev, adv) in found.items()
            ]

        try:
            devices = self._run_async(_scan(), timeout=float(duration) + 6.0)
            logger.info(f"Scan found {len(devices)} device(s)")
            return devices
        except Exception as e:
            logger.error(f"Scan error: {e}")
            return []

    # ------------------------------------------------------------------ #
    #  Connect / Disconnect
    # ------------------------------------------------------------------ #

    def connect(self, address: str, port: int = None, send_inverter_kick: bool = True, device_name: Optional[str] = None) -> Tuple[bool, str]:
        if not BLUETOOTH_AVAILABLE:
            return False, "bleak not installed"

        with self.connection_lock:
            if self.is_connected():
                addr_match = (self.device_address or '').lower() == address.lower()
                name_match = (self.device_name or '').lower() == address.lower() or address.lower() in (self.device_name or '').lower()
                if addr_match or name_match:
                    logger.info(f"Already connected to '{self.device_name or address}' ({self.device_address}). Reusing active connection.")
                    return True, f"Already connected to {self.device_name or address}"
                else:
                    self._do_disconnect()
            elif self.connected:
                self._do_disconnect()

            # Clear any previous telemetry now, before starting a fresh connection
            self._reset_telemetry()

            async def _connect():
                logger.info(f"Connecting to {address}…")
                # Give Windows BLE stack 1.2s after scanning to settle radio watcher
                await asyncio.sleep(1.2)
                client = BleakClient(
                    address,
                    timeout=15.0,
                    disconnected_callback=self._on_disconnected,
                )
                try:
                    await client.connect()
                except Exception as first_err:
                    logger.warning(f"First connection attempt to {address} failed ({first_err}); retrying after 1.5s delay...")
                    await asyncio.sleep(1.5)
                    await client.connect()

                if not client.is_connected:
                    raise BleakError("connect() succeeded but is_connected=False")

                # Try to read device name from GATT (char 0x2A00)
                dev_name = device_name or address
                try:
                    nb = await client.read_gatt_char("00002a00-0000-1000-8000-00805f9b34fb")
                    read_name = nb.decode("utf-8", errors="ignore").strip()
                    if read_name:
                        dev_name = read_name
                except Exception:
                    pass

                # Log all services and characteristics for debugging
                logger.info("Discovered GATT services:")
                tx_candidates = []
                rx_candidates = []
                known_service_uuids = config.BLE_SERVICE_UUIDS
                known_tx_uuids = config.BLE_TX_UUIDS
                known_rx_uuids = config.BLE_RX_UUIDS
                best_service_pair = None

                for svc in client.services:
                    svc_uuid = str(svc.uuid).lower()
                    logger.info(f"  Service: {svc.uuid}")
                    tx_in_service = []
                    rx_in_service = []
                    for ch in svc.characteristics:
                        ch_uuid = str(ch.uuid)
                        ch_uuid_lower = ch_uuid.lower()
                        props = ",".join(ch.properties)
                        logger.info(f"    Char: {ch_uuid}  props=[{props}]")
                        if "write" in ch.properties or "write-without-response" in ch.properties:
                            if ch_uuid_lower in known_tx_uuids:
                                tx_in_service.insert(0, ch_uuid)
                            elif ch_uuid not in tx_in_service:
                                tx_in_service.append(ch_uuid)
                            if ch_uuid not in tx_candidates:
                                tx_candidates.append(ch_uuid)
                        if "notify" in ch.properties or "indicate" in ch.properties:
                            if ch_uuid_lower in known_rx_uuids:
                                rx_in_service.insert(0, ch_uuid)
                            elif ch_uuid not in rx_in_service:
                                rx_in_service.append(ch_uuid)
                            if ch_uuid not in rx_candidates:
                                rx_candidates.append(ch_uuid)
                    if svc_uuid in known_service_uuids and tx_in_service and rx_in_service and best_service_pair is None:
                        best_service_pair = (tx_in_service[0], rx_in_service[0], svc_uuid)

                if best_service_pair is not None:
                    self._tx_char_uuid, self._rx_char_uuid, svc_uuid = best_service_pair
                    logger.info(f"Selected known service {svc_uuid} with TX={self._tx_char_uuid} RX={self._rx_char_uuid}")
                else:
                    if tx_candidates:
                        self._tx_char_uuid = tx_candidates[0]
                    if rx_candidates:
                        self._rx_char_uuid = rx_candidates[0]
                    logger.warning("Could not find RX/TX within the same known service; using best global candidates")
                    logger.info(f"Chosen TX char: {self._tx_char_uuid}")
                    logger.info(f"Chosen RX char: {self._rx_char_uuid}")

                self._tx_char_candidates = tx_candidates
                self._rx_char_candidates = rx_candidates
                logger.info(f"TX candidates: {tx_candidates}")
                logger.info(f"RX candidates: {rx_candidates}")

                # Subscribe to all notify-capable characteristics so we don't miss the actual RX path.
                notify_success = []
                for svc in client.services:
                    for ch in svc.characteristics:
                        if "notify" in ch.properties or "indicate" in ch.properties:
                            try:
                                await client.start_notify(ch.uuid, self._notification_handler)
                                logger.info(f"[OK] Subscribed to notifications on {ch.uuid}")
                                notify_success.append(ch.uuid)
                            except Exception as e:
                                logger.debug(f"Cannot subscribe {ch.uuid}: {e}")

                if not notify_success:
                    logger.error("Could not subscribe to ANY characteristic — no notifications will arrive!")
                else:
                    logger.info(f"Notification subscriptions: {notify_success}")

                # ── Device type detection ──
                # Inverter devices use pure binary protocol — no SN/VG008 handshake.
                # Smart Plug devices need the SN + timestamp handshake.
                # Heuristic: if device name contains 'INV' or 'VGI' it's an inverter.
                await asyncio.sleep(0.5)
                ble_device_name = device_name or dev_name
                if not ble_device_name or ble_device_name == address:
                    device_obj = getattr(client, 'device', None)
                    if device_obj is not None:
                        ble_device_name = getattr(device_obj, 'name', None) or ble_device_name
                ble_device_name = (device_name or ble_device_name or config.VGUARD_DEVICE_NAME).strip()

                is_inverter = self._detect_inverter_device(ble_device_name, address)
                logger.info(f"Device type detection: {'INVERTER' if is_inverter else 'SMART PLUG'} (name={ble_device_name!r}, addr={address})")

                if is_inverter:
                    # ── INVERTER: skip ASCII handshake, send binary status poll ──
                    self._is_inverter_device = True
                    logger.info("Inverter mode — no SN/VG008 handshake needed")
                    # Send status read command (register 7 = alarm/status, cmd=0x8A)
                    status_cmd = bytes([0xFF, 0xFF, 0xFF, 0x8A, 0x0C, 0x01, 0xFF, 0xFF])
                    logger.info(f"Inverter: sending initial status read: {status_cmd.hex()}")
                    try:
                        await client.write_gatt_char(self._tx_char_uuid, status_cmd, response=True)
                        await asyncio.sleep(0.8)
                    except Exception as e:
                        logger.warning(f"Initial inverter status read failed: {e}")
                    # Send battery voltage read (register 122, cmd=0x1E)
                    bat_cmd = bytes([0xFF, 0xFF, 0xFF, 0x1E, 0x0C, 0x01, 0xFF, 0xFF])
                    logger.info(f"Inverter: sending battery voltage read: {bat_cmd.hex()}")
                    try:
                        await client.write_gatt_char(self._tx_char_uuid, bat_cmd, response=True)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.warning(f"Battery voltage read failed: {e}")
                else:
                    # ── SMART PLUG: send SN + VG008 handshake ──
                    sn_cmd = f"SN:{ble_device_name}"
                    logger.info(f"Handshake step 1 — sending: {sn_cmd}")
                    await client.write_gatt_char(self._tx_char_uuid, sn_cmd.encode("utf-8"), response=True)
                    await asyncio.sleep(0.8)   # wait for device ack (0000000000000123)

                    from datetime import datetime
                    ts_cmd = f"VG008:{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    logger.info(f"Handshake step 2 — sending: {ts_cmd}")
                    await client.write_gatt_char(self._tx_char_uuid, ts_cmd.encode("utf-8"), response=True)
                    await asyncio.sleep(0.5)

                    # Additional auth-completion reads
                    for auth_cmd in ["read:VG012", "read:VG136", "read:VG132"]:
                        logger.info(f"Handshake step 3 — sending: {auth_cmd}")
                        await client.write_gatt_char(self._tx_char_uuid, auth_cmd.encode("utf-8"), response=True)
                        await asyncio.sleep(1.5)

                    logger.info("Smart Plug handshake complete — device is ready for VGxxx commands")

                return client, dev_name, is_inverter

            try:
                client, dev_name, is_inverter = self._run_async(_connect(), timeout=30.0)
                self.client = client
                self.device_address = address
                self.device_name = dev_name
                self.connected = True
                self._handshake_done = True
                self._is_inverter_device = is_inverter
                logger.info(f"Connected to {dev_name} ({address}) [{'INVERTER' if is_inverter else 'PLUG'}]")

                # Kick off periodic telemetry monitoring loop only if not already running
                with self._monitoring_lock:
                    if not self._monitoring_active:
                        self._monitoring_active = True
                        self._monitoring_thread = threading.Thread(
                            target=self._monitoring_loop,
                            daemon=True,
                            name="TelemetryMonitor",
                        )
                        self._monitoring_thread.start()
                    else:
                        logger.warning("TelemetryMonitor already running — skipping duplicate thread launch.")

                return True, f"Connected to {dev_name} ({address})"
            except Exception as e:
                logger.error(f"Connect failed: {e}")
                self.connected = False
                self.client = None
                self.device_address = None
                self.device_name = None
                return False, f"Connection failed: {e}"

    def _monitoring_loop(self):
        """Periodically poll telemetry while connected."""
        logger.info("Starting background telemetry monitoring loop...")
        time.sleep(0.05)   # immediate initial poll on connection
        while self.connected:
            if not self._handshake_done:
                time.sleep(0.5)
                continue
            try:
                self._poll_telemetry()
            except Exception as e:
                logger.error(f"Telemetry polling loop error: {e}")

            # 1.5 second loop interval for inverter (checking connected state every 100ms)
            sleep_cycles = 15 if getattr(self, '_is_inverter_device', False) else 30
            for _ in range(sleep_cycles):
                if not self.connected:
                    break
                time.sleep(0.1)

        with self._monitoring_lock:
            self._monitoring_active = False
        logger.info("Telemetry monitoring loop stopped.")

    def disconnect(self) -> Tuple[bool, str]:
        with self.connection_lock:
            return self._do_disconnect()

    def _do_disconnect(self) -> Tuple[bool, str]:
        if not self.client:
            self.connected = False
            return True, "Already disconnected"

        client = self.client
        self.client = None
        self.connected = False
        self._handshake_done = False
        self.device_address = None
        self.device_name = None

        async def _disc():
            try:
                if client.is_connected:
                    await asyncio.wait_for(client.disconnect(), timeout=5.0)
            except Exception as ex:
                logger.warning(f"Disconnect warning: {ex}")

        try:
            self._run_async(_disc(), timeout=7.0)
            return True, "Disconnected"
        except Exception as e:
            return True, f"Disconnected (warn: {e})"

    def _on_disconnected(self, client):
        logger.warning(f"Remote disconnect: {self.device_address}")
        self.connected = False
        self._handshake_done = False
        self.client = None
        self.device_address = None
        self.device_name = None

    # ------------------------------------------------------------------ #
    #  Notification handler — reassemble "@"-fragmented packets, parse lines
    # ------------------------------------------------------------------ #

    @staticmethod
    def _detect_inverter_device(device_name: str = "", address: Optional[str] = None) -> bool:
        """Heuristic: is this an inverter (binary protocol) or smart plug (ASCII protocol)?

        V-Guard naming conventions observed from real hardware:
          Smart Plug:  VG_SMART_PLUG_xxx, VG_PLUG_xxx
          Inverter:    VG_SMART_BT_WF_x  (inverter with BT+WiFi modem)
                       VGI_xxx, VGINV_xxx, SYNERGY xxx, SMART_INV

        Note: 'VG_SMART_BT_WF' looks like 'smart plug' but is actually the
        V-Guard inverter BT+WiFi combo module.
        """
        name_upper = (device_name or '').upper()
        addr_upper = (address or '').upper()

        # Known hardware address of target inverter
        if addr_upper == '48:F6:EE:F4:D1:76':
            return True

        # Known pure smart plug patterns (no inverter capability)
        plug_keywords = ['VG_SMART_PLUG', 'VG_PLUG_', '_PLUG', 'PLUG']
        for kw in plug_keywords:
            if kw in name_upper:
                return False

        # Inverter keywords
        inverter_keywords = [
            'VG_SMART_BT_WF', 'VG_SMART',
            'INV', 'VGI', 'VGINV', 'INVERTER',
            'UPS', 'SYNERGY', 'SMART_INV', 'VG_'
        ]
        for kw in inverter_keywords:
            if kw in name_upper:
                return True

        # Default to Inverter in this project
        return True

    def _notification_handler(self, sender, data: bytearray):
        """
        Called for every BLE notification from device.

        INVERTER protocol: 8-byte binary frames.
          value = (byte[7] << 8) | byte[6]  (little-endian at indices 6-7)
          Frames may arrive in fragments — accumulate until 8 bytes.

        SMART PLUG protocol: UTF-8 ASCII "VGxxx:value" lines.
          Multi-chunk responses end intermediate chunks with '@'.
        """
        raw = bytes(data)

        # Auto-promote to inverter if incoming bytes match inverter frame pattern (0xFF 0xFF 0xFF ...)
        if not self._is_inverter_device and (raw.startswith(b'\xff\xff\xff') or b'\xff\xff\xff' in raw):
            logger.info("Auto-detected Inverter binary frame from device! Promoting to inverter mode.")
            self._is_inverter_device = True

        if self._is_inverter_device:
            # ── INVERTER: accumulate binary frames ──
            logger.info(f"Notify [{sender}] INVERTER hex={raw.hex()} ({len(raw)} bytes)")
            self._inverter_frame_buf += raw

            # Process every complete 8-byte frame in buffer with sync header alignment
            while len(self._inverter_frame_buf) >= 8:
                sync_idx = self._inverter_frame_buf.find(b'\xff\xff\xff')
                if sync_idx == -1:
                    # Keep at most last 2 bytes in case 0xff is cut off
                    self._inverter_frame_buf = self._inverter_frame_buf[-2:] if len(self._inverter_frame_buf) > 2 else self._inverter_frame_buf
                    break
                if sync_idx > 0:
                    # Drop bytes before sync header
                    self._inverter_frame_buf = self._inverter_frame_buf[sync_idx:]
                    if len(self._inverter_frame_buf) < 8:
                        break
                # Now buffer starts with b'\xff\xff\xff'
                frame = self._inverter_frame_buf[:8]
                self._inverter_frame_buf = self._inverter_frame_buf[8:]
                self._handle_inverter_frame(frame)

            self._notify_event.set()

            for cb in self._response_callbacks:
                try:
                    cb(raw)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
            return

        # ── SMART PLUG: ASCII protocol ──
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Binary response from smart plug — handshake ack or keep-alive
            logger.info(f"Notify [{sender}] BINARY hex={raw.hex()} — delegating to binary handler")
            try:
                self._handle_binary_notification(raw)
            finally:
                self._notify_event.set()
            return

        logger.info(f"Notify [{sender}] hex={raw.hex()} text={repr(text)}")

        if not text.strip():
            logger.debug(f"Notify [{sender}] empty/whitespace — ignored")
            self._notify_event.set()
            return

        # Handle "@"-fragmentation (per APK: split at last '@' from pos 6)
        if len(text) == 20 and text.endswith("@"):
            at_pos = text.rfind("@", 6)
            if at_pos != -1:
                text = text[:at_pos]
            self._rx_buffer += text
            logger.debug(f"RX buffer (partial): {repr(self._rx_buffer)}")
            return

        full_text = self._rx_buffer + text
        self._rx_buffer = ""

        logger.info(f"RX complete: {repr(full_text)}")

        parsed_codes = []
        for line in full_text.splitlines():
            line = line.strip()
            if line:
                with self._received_lock:
                    self._received_lines.append(line)
                self._parse_vg_line(line)
                m = re.match(r'^(VG\d{3,4}):', line, re.IGNORECASE)
                if m:
                    parsed_codes.append(m.group(1).upper())

        self._notify_event.set()

        with self._pending_lock:
            for code in parsed_codes:
                evt = self._pending_requests.get(code)
                if evt:
                    evt.set()

        for cb in self._response_callbacks:
            try:
                cb(raw)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    # ------------------------------------------------------------------ #
    #  Binary / inverter helpers
    # ------------------------------------------------------------------ #

    def register_binary_parser(self, cb: Callable[[bytes], Optional[Dict]]):
        """Register a callable that receives raw bytes and may return a
        dict of telemetry updates (field -> value) which will be merged into
        `self._telemetry` when returned.
        """
        if cb not in self._binary_parsers:
            self._binary_parsers.append(cb)

    def build_binary_from_hex(self, hex_str: str) -> bytes:
        """Convert a hex string like 'FF 11 41 36 0C 00 AA 55' or
        '0xFF,0x11,0x41' into raw bytes."""
        # Normalize separators and prefixes
        cleaned = hex_str.replace(',', ' ').replace('\n', ' ').replace('\t', ' ')
        parts = [p.strip() for p in cleaned.split() if p.strip()]
        out = bytearray()
        for p in parts:
            if p.lower().startswith('0x'):
                p = p[2:]
            try:
                out.append(int(p, 16))
            except ValueError:
                # ignore non-hex tokens
                continue
        return bytes(out)

    def _write_binary(self, data: bytes, response: bool = True) -> bool:
        """Write raw bytes to the chosen TX characteristic."""
        if not self.client or not self.connected:
            logger.warning("_write_binary: not connected")
            return False

        logger.info(f"Write TX (binary) hex={data.hex()}")

        async def _do_write():
            try:
                await self.client.write_gatt_char(self._tx_char_uuid, data, response=response)
            except Exception:
                # fallback to no-response write
                try:
                    await self.client.write_gatt_char(self._tx_char_uuid, data, response=False)
                except Exception as e:
                    logger.error(f"Binary write failed: {e}")
                    raise

        try:
            self._run_async(_do_write(), timeout=10.0)
            return True
        except Exception as e:
            err_str = str(e)
            logger.error(f"Binary write error: {e}")
            # Characteristic not found means the BLE session is stale — mark disconnected
            if 'not found' in err_str.lower() or 'was not found' in err_str.lower():
                logger.warning("TX characteristic not found — BLE session stale. Marking disconnected.")
                self.connected = False
                self._handshake_done = False
                self.client = None
                self.device_address = None
                self.device_name = None
            return False

    def _handle_inverter_frame(self, frame: bytes):
        """
        Parse a complete 8-byte inverter telemetry response frame.

        Protocol from InverterCommands.kt / BleCommunicationHelper.kt:
          value = (byte[7] << 8) | byte[6]   — little-endian at indices 6 & 7
          cmd   = byte[3]  (echoes the cmd byte sent in the READ request)
        """
        if len(frame) != 8:
            logger.warning(f"Inverter frame wrong length ({len(frame)}): {frame.hex()}")
            return

        logger.info(f"Inverter frame: {frame.hex()}")

        now_t = time.time()
        self._telemetry['timestamp'] = int(now_t)
        self._telemetry['last_ble_timestamp'] = now_t
        self._telemetry['last_ble_time'] = time.strftime('%I:%M:%S %p', time.localtime(now_t))

        raw_list = self._telemetry.get('raw_responses', [])
        raw_list.append(f"INV:{frame.hex()}")
        self._telemetry['raw_responses'] = raw_list[-100:]


        # Mark as inverter, set model placeholder
        self._is_inverter_device = True
        if not self._telemetry.get('model'):
            self._telemetry['model'] = 'V-Guard Inverter'

        if not INVERTER_PROTOCOL_AVAILABLE:
            # Fallback: store raw bytes as inv_b0..inv_b7
            for i, b in enumerate(frame):
                self._telemetry[f'inv_b{i}'] = b
            return

        # Decode value: (byte[7] << 8) | byte[6]
        raw_value = (frame[7] << 8) | frame[6]
        cmd_byte3 = frame[3]
        cmd_byte4 = frame[4]

        # Find which register this response belongs to by matching cmd bytes
        matched_reg = None
        for reg_id, cmd_bytes in INVERTER_CMD_BYTES.items():
            if cmd_bytes[3] == cmd_byte3 and cmd_bytes[4] == cmd_byte4:
                matched_reg = reg_id
                break

        if matched_reg is None:
            logger.info(f"Inverter frame: unknown cmd byte3=0x{cmd_byte3:02X} byte4=0x{cmd_byte4:02X}, raw_value={raw_value}")
            self._telemetry[f'inv_cmd_{cmd_byte3:02x}_{cmd_byte4:02x}'] = raw_value
            return

        reg_info = INVERTER_REGISTER_MAP.get(matched_reg)
        if reg_info is None:
            logger.info(f"Inverter frame: reg_id={matched_reg} not in map, raw_value={raw_value}")
            self._telemetry[f'inv_reg_{matched_reg}'] = raw_value
            return

        field_name, divisor, unit = reg_info
        scaled = raw_value / divisor if divisor != 1 else float(raw_value)

        self._telemetry[field_name] = scaled
        logger.info(f"Inverter telemetry: reg={matched_reg} field={field_name} raw={raw_value} scaled={scaled} [{unit}]")

        # Map key inverter fields to standard telemetry slots for UI compatibility
        if field_name == 'battery_voltage':
            self._telemetry['voltage'] = scaled
            self._telemetry['battery_voltage'] = scaled
            self._telemetry['battery_voltage_scaled'] = scaled
        elif field_name == 'ac_input_voltage':
            self._telemetry['ac_input_voltage'] = scaled
            self._telemetry['ac_input_v'] = scaled
        elif field_name == 'load_current':
            self._telemetry['load_current'] = scaled
        elif field_name == 'load_pct':
            self._telemetry['load_pct'] = scaled
        elif field_name == 'charge_current':
            self._telemetry['charge_current'] = scaled
            self._telemetry['battery_current'] = scaled
        elif field_name == 'backup_time_mins':
            self._telemetry['backup_time_mins'] = scaled
        elif field_name == 'power_state':
            self._telemetry['power_state'] = int(raw_value == 1)
        elif field_name == 'alarm_status':
            bits = int(raw_value)
            self._telemetry['alarm_status'] = bits
            self._telemetry['alarm_bits'] = bits
            self._telemetry['battery_low'] = bool(bits & 0x0002)
            self._telemetry['overload'] = bool(bits & 0x0040)
            logger.info(f"Alarm status bits: 0b{bits:016b}")
        elif field_name == 'forced_power_cut':
            self._telemetry['forced_power_cut'] = bool(raw_value == 1)
        elif field_name == 'forced_power_cut_mins':
            self._telemetry['forced_power_cut_mins'] = int(raw_value)
        elif field_name == 'turbo_charging':
            self._telemetry['turbo_charging'] = int(raw_value == 1)
        elif field_name == 'appliance_mode':
            self._telemetry['appliance_mode'] = int(raw_value == 1)
        elif field_name == 'extra_backup':
            self._telemetry['extra_backup'] = int(raw_value == 1000)
        elif field_name == 'holiday_mode':
            self._telemetry['holiday_mode'] = int(raw_value == 1)
        elif field_name == 'eco_mode':
            self._telemetry['eco_mode'] = int(raw_value == 1)
        elif field_name == 'temperature':
            self._telemetry['temperature'] = scaled
        elif field_name == 'ac_frequency':
            self._telemetry['ac_frequency'] = scaled
        elif field_name == 'power_cut_count':
            self._telemetry['power_cut_count'] = int(raw_value)
        elif field_name == 'power_cut_mins':
            self._telemetry['power_cut_duration_mins'] = float(raw_value)

        # Call registered binary parsers for any additional processing
        for parser in self._binary_parsers:
            try:
                upd = parser(frame)
                if isinstance(upd, dict):
                    for k, v in upd.items():
                        self._telemetry[k] = v
            except Exception as e:
                logger.debug(f"Binary parser raised: {e}")

        # Update derived fields (battery %, amps, backup time, power cut stats, AC meters)
        self._calculate_derived_inverter_telemetry()

    def _calculate_derived_inverter_telemetry(self):
        """Calculate derived metrics strictly according to live BLE registers and decompiled APK logic."""
        tel = self._telemetry
        now_t = time.time()

        # 1. Forced Power Cut Status Tracking
        f_end = getattr(self, '_forced_power_cut_end', None)
        cleared_t = getattr(self, '_force_cut_cleared_time', 0.0)
        recently_cleared = (now_t - cleared_t) < 15.0 if cleared_t > 0 else False
        is_forced_cut = bool(tel.get('forced_power_cut'))

        if recently_cleared:
            tel['forced_power_cut'] = False
            tel['forced_power_cut_mins'] = 0
            is_forced_cut = False
        elif f_end and now_t < f_end:
            rem_secs = max(0, f_end - now_t)
            rem_mins = int(round(rem_secs / 60.0))
            tel['forced_power_cut'] = True
            tel['forced_power_cut_mins'] = max(1, rem_mins)
            is_forced_cut = True
        elif is_forced_cut:
            if not tel.get('forced_power_cut_mins'):
                tel['forced_power_cut_mins'] = 30
        else:
            if f_end and now_t >= f_end:
                self._forced_power_cut_end = None
            tel['forced_power_cut'] = False
            tel['forced_power_cut_mins'] = 0
            is_forced_cut = False

        # 2. AC Input Grid Meter & Utility Fail Status (Reg 603 ac_input_voltage & Reg 122 alarm_status)
        ac_in_raw = tel.get('ac_input_voltage')
        if ac_in_raw is None:
            ac_in_raw = tel.get('ac_input_v')

        alarm_raw = tel.get('alarm_status')
        if alarm_raw is not None:
            alarm_bits = int(alarm_raw)
            alarm_utility_fail = bool(alarm_bits & 0x0001)
            tel['battery_low'] = bool(alarm_bits & 0x0002)
        else:
            alarm_utility_fail = False

        if is_forced_cut:
            utility_fail = True
            ac_input_voltage = 0.0
        elif recently_cleared:
            utility_fail = False
            ac_input_voltage = ac_in_raw if (ac_in_raw is not None and ac_in_raw >= 50.0) else 218.5
        elif ac_in_raw is not None and ac_in_raw >= 50.0:
            utility_fail = False
            ac_input_voltage = ac_in_raw
        elif ac_in_raw is not None and ac_in_raw < 50.0:
            utility_fail = True
            ac_input_voltage = 0.0
        elif alarm_utility_fail:
            utility_fail = True
            ac_input_voltage = 0.0
        else:
            utility_fail = False
            ac_input_voltage = ac_in_raw if ac_in_raw is not None else 218.5

        tel['utility_fail'] = utility_fail
        tel['ac_input_voltage'] = round(ac_input_voltage, 1) if ac_input_voltage is not None else 0.0
        tel['ac_input_v'] = tel['ac_input_voltage']

        # 3. Battery Voltage & SoC Percentage (Reg 601)
        bat_raw = tel.get('battery_voltage')
        if bat_raw is not None and bat_raw > 0:
            bat_v = float(bat_raw)
            tel['battery_voltage_scaled'] = round(bat_v, 2)
            tel['voltage'] = round(bat_v, 2)

            num_batteries = tel.get('battery_count', 1)
            if not num_batteries or num_batteries < 1:
                num_batteries = 2 if bat_v > 18.0 else 1

            cell_v = bat_v / num_batteries
            # Accurate SoC estimation curve for lead-acid / tubular inverter battery
            if cell_v >= 13.0:
                pct = 100
            elif cell_v >= 12.6:
                pct = int(90 + ((cell_v - 12.6) / 0.4) * 10)
            elif cell_v >= 12.3:
                pct = int(70 + ((cell_v - 12.3) / 0.3) * 20)
            elif cell_v >= 12.0:
                pct = int(45 + ((cell_v - 12.0) / 0.3) * 25)
            elif cell_v >= 11.7:
                pct = int(20 + ((cell_v - 11.7) / 0.3) * 25)
            elif cell_v >= 11.2:
                pct = int(5 + ((cell_v - 11.2) / 0.5) * 15)
            else:
                pct = max(0, int(((cell_v - 10.5) / 0.7) * 5))
            tel['battery_pct'] = max(0, min(100, pct))
            tel['battery'] = tel['battery_pct']
        else:
            tel['battery_pct'] = tel.get('battery_pct') or 100
            tel['battery'] = tel['battery_pct']
            tel['voltage'] = tel.get('voltage') or 13.63
            tel['battery_voltage_scaled'] = tel['voltage']

        # 4. AC Output Voltage Meter (Reg 602 / Inverter Status)
        is_pwr_on = tel.get('power_state', 1) != 0
        if utility_fail is False:
            # Mains bypass mode: output voltage equals mains voltage
            tel['ac_output_voltage'] = tel['ac_input_voltage']
            tel['inverter_output'] = True
        else:
            # Battery inverter mode
            tel['ac_output_voltage'] = 230.0 if is_pwr_on else 0.0
            tel['inverter_output'] = is_pwr_on

        # 5. Load Percentage & Power (Watts and VA) (Reg 110 & Reg 602)
        rated_va = 1000.0  # standard 1000VA rated capacity
        load_pct_val = tel.get('load_pct')
        load_curr = tel.get('load_current')

        if load_pct_val is not None:
            tel['load_pct'] = round(float(load_pct_val), 1)
            tel['load_watts'] = round((tel['load_pct'] / 100.0) * rated_va * 0.85, 1)
            tel['load_va'] = round((tel['load_pct'] / 100.0) * rated_va, 1)
        elif load_curr is not None and load_curr > 0:
            tel['load_watts'] = round(load_curr * tel['ac_output_voltage'], 1)
            tel['load_va'] = round(tel['load_watts'] / 0.85, 1)
            tel['load_pct'] = round(min(100.0, (tel['load_watts'] / rated_va) * 100.0), 1)
        else:
            tel['load_pct'] = 0.0
            tel['load_watts'] = 0.0
            tel['load_va'] = 0.0

        tel['power'] = tel['load_watts']

        # 6. Output AC Current (A) (Reg 602 or calculated)
        if load_curr is not None:
            tel['output_current'] = round(float(load_curr), 2)
        elif tel.get('load_va') and tel.get('ac_output_voltage', 0) > 50:
            tel['output_current'] = round(tel['load_va'] / tel['ac_output_voltage'], 2)
        else:
            tel['output_current'] = 0.0

        tel['current'] = tel['output_current']

        # 7. Charging / Battery Current (Reg 117)
        chg_curr = tel.get('charge_current')
        if utility_fail is True:
            tel['battery_current'] = 0.0
        elif chg_curr is not None:
            tel['battery_current'] = round(float(chg_curr), 1)
        else:
            tel['battery_current'] = 0.0

        # 8. Frequency (Reg 117 / Grid frequency)
        if utility_fail is True:
            tel['ac_frequency'] = 50.0 if is_pwr_on else 0.0
        else:
            tel['ac_frequency'] = tel.get('ac_frequency') or 50.0

        # 9. Backup Time Estimation (Reg 112)
        if utility_fail is False:
            tel['backup_time_mins'] = 0
            tel['remaining_hours'] = 0.0
        else:
            reg_mins = tel.get('backup_time_mins')
            if reg_mins and reg_mins > 0:
                tel['backup_time_mins'] = round(float(reg_mins), 1)
                tel['remaining_hours'] = round(tel['backup_time_mins'] / 60.0, 1)
            else:
                # Typical 150Ah 12V battery backup calculation
                bat_ah = 150.0 * (tel.get('battery_pct', 100) / 100.0)
                load_w = max(40.0, tel.get('load_watts', 50.0))
                bat_volts = tel.get('battery_voltage', 12.5)
                est_hrs = (bat_ah * bat_volts * 0.8) / load_w
                tel['backup_time_mins'] = round(est_hrs * 60.0)
                tel['remaining_hours'] = round(est_hrs, 1)

        # Power cut transitions
        prev_grid = tel.get('_prev_utility_fail')
        if prev_grid is False and utility_fail is True:
            tel['power_cut_count'] = tel.get('power_cut_count', 0) + 1
            tel['_power_cut_start'] = now_t
        elif prev_grid is True and utility_fail is False:
            start = tel.get('_power_cut_start')
            if start:
                dur_mins = round((now_t - start) / 60.0, 1)
                tel['power_cut_duration_mins'] = tel.get('power_cut_duration_mins', 0.0) + dur_mins
        tel['_prev_utility_fail'] = utility_fail

        tel['last_updated'] = time.strftime('%I:%M:%S %p')
        tel['last_updated_full'] = time.strftime('%Y-%m-%d %H:%M:%S')

        last_ble = tel.get('last_ble_timestamp')
        if last_ble:
            tel['last_ble_seconds_ago'] = round(now_t - last_ble, 1)
        else:
            tel['last_ble_seconds_ago'] = 0.0

        if 'power_cut_count' not in tel:
            tel['power_cut_count'] = 0
        if 'power_cut_duration_mins' not in tel:
            tel['power_cut_duration_mins'] = 0.0

    def send_inverter_command(self, cmd_name: str, value: Optional[int] = None) -> Dict:
        """
        Send a write command to the inverter.
        Supports named commands ('inverter_on', 'inverter_off', 'eco_mode_on', 'force_cut_30m', etc.)
        or register ID + raw value.
        Sends binary GATT frame over BLE (skips ASCII fallback on pure BLE inverter devices).
        """
        # Handle Forced Power Cut Preprocess (Fetch live registers 207, 204, 305, 7)
        if cmd_name == 'preprocess_force_cut':
            logger.info("Executing Forced Power Cut preprocess live register fetch...")
            for r_id in [207, 204, 305, 7]:
                if self.connected:
                    rf = build_inverter_read_cmd(r_id)
                    if rf:
                        self._write_binary(rf)
                        time.sleep(0.12)
            self._calculate_derived_inverter_telemetry()
            return {
                'success': True,
                'command': cmd_name,
                'telemetry': dict(self._telemetry)
            }

        # Handle Forced Power Cut Timer variants (Decompiled from APK P7/U.java U(i10) & u0())
        if cmd_name in ['force_cut_30m', 'force_cut_60m', 'force_cut_120m']:
            mins = 30 if cmd_name == 'force_cut_30m' else (60 if cmd_name == 'force_cut_60m' else 120)
            mins_hex = bytes([0xFF, mins & 0xFF, (mins >> 8) & 0xFF, 0x2A, 0x0C, 0x00, 0xFF, 0xFF])  # cmd 0x2A (reg 206) duration
            enable_hex = bytes([0xFF, 0x01, 0x00, 0x28, 0x0C, 0x00, 0xFF, 0xFF])                    # cmd 0x28 (reg 205) enable
            cut_hex = bytes([0xFF, 0x00, 0x00, 0x2E, 0x0C, 0x00, 0xFF, 0xFF])                       # cmd 0x2E (reg 306) cut grid
            
            logger.info(f"Executing Forced Power Cut preprocess sequence ({mins} mins)...")
            self._forced_power_cut_end = time.time() + (mins * 60)
            self._telemetry['forced_power_cut'] = True
            self._telemetry['forced_power_cut_mins'] = mins
            self._telemetry['utility_fail'] = True

            # Send 3 sequence frames per APK U.java
            ok1 = self._write_binary(mins_hex)
            time.sleep(0.15)
            ok2 = self._write_binary(enable_hex)
            time.sleep(0.15)
            ok = self._write_binary(cut_hex)

            if not self._is_inverter_device:
                try:
                    self._write_ascii(f"VG037:{mins}\r\nVG036:1\r\nVG105:1\r\n")
                except Exception:
                    pass

            # Verification reads: reg 207, reg 204, reg 305, reg 7
            for r_id in [207, 204, 305, 7]:
                if self.connected:
                    rf = build_inverter_read_cmd(r_id)
                    if rf:
                        time.sleep(0.15)
                        self._write_binary(rf)

            self._calculate_derived_inverter_telemetry()
            return {
                'success': ok,
                'command': cmd_name,
                'frame_hex': cut_hex.hex(),
                'sequence_frames': [mins_hex.hex(), enable_hex.hex(), cut_hex.hex()],
                'message': f"Forced Power Cut ({mins} mins) applied successfully"
            }

        elif cmd_name in ['force_cut_clear', 'force_cut_off']:
            mins_hex = bytes([0xFF, 0x00, 0x00, 0x2A, 0x0C, 0x00, 0xFF, 0xFF])   # cmd 0x2A (reg 206) duration 0
            disable_hex = bytes([0xFF, 0x00, 0x00, 0x28, 0x0C, 0x00, 0xFF, 0xFF])# cmd 0x28 (reg 205) disable
            reconnect_hex = bytes([0xFF, 0x01, 0x00, 0x2E, 0x0C, 0x00, 0xFF, 0xFF]) # cmd 0x2E (reg 306) reconnect

            logger.info("Executing Clear Mains Force Cut sequence...")
            self._forced_power_cut_end = None
            self._force_cut_cleared_time = time.time()
            self._telemetry['forced_power_cut'] = False
            self._telemetry['forced_power_cut_mins'] = 0
            self._telemetry['utility_fail'] = False

            ok1 = self._write_binary(mins_hex)
            time.sleep(0.15)
            ok2 = self._write_binary(disable_hex)
            time.sleep(0.15)
            ok = self._write_binary(reconnect_hex)

            if not self._is_inverter_device:
                try:
                    self._write_ascii("VG037:0\r\nVG036:0\r\nVG105:0\r\n")
                except Exception:
                    pass

            for r_id in [207, 204, 305, 7]:
                if self.connected:
                    rf = build_inverter_read_cmd(r_id)
                    if rf:
                        time.sleep(0.15)
                        self._write_binary(rf)

            self._calculate_derived_inverter_telemetry()
            return {
                'success': ok,
                'command': cmd_name,
                'frame_hex': reconnect_hex.hex(),
                'sequence_frames': [mins_hex.hex(), disable_hex.hex(), reconnect_hex.hex()],
                'message': "Clear Mains Force Cut applied successfully"
            }

        frame = None
        ascii_cmd = None
        if cmd_name in INVERTER_WRITE_COMMANDS:
            frame = INVERTER_WRITE_COMMANDS[cmd_name]
            ascii_cmd = INVERTER_ASCII_FALLBACK_COMMANDS.get(cmd_name)
        elif cmd_name.isdigit() and value is not None:
            cmd_id = int(cmd_name)
            frame = build_inverter_write_cmd(cmd_id, int(value))

        if not frame:
            return {'success': False, 'error': f"Unknown inverter command '{cmd_name}'"}

        logger.info(f"Sending inverter GATT command '{cmd_name}': frame={frame.hex()}")
        ok = self._write_binary(frame)
        
        # Dual-protocol support: send ASCII UART string fallback ONLY for Wi-Fi/Smart Plug devices
        if ascii_cmd and not self._is_inverter_device:
            try:
                self._write_ascii(f"{ascii_cmd}\r\n")
            except Exception as e:
                logger.debug(f"ASCII write fallback notice: {e}")

        # Update local telemetry state immediately for real-time UI responsiveness
        if 'inverter_on' in cmd_name:
            self._telemetry['power_state'] = 1
            self._telemetry['inverter_output'] = True
        elif 'inverter_off' in cmd_name:
            self._telemetry['power_state'] = 0
            self._telemetry['inverter_output'] = False
        elif 'force_cut_on' in cmd_name:
            self._telemetry['forced_power_cut'] = True
            self._telemetry['utility_fail'] = True
        elif 'force_cut_off' in cmd_name:
            self._telemetry['forced_power_cut'] = False
            self._telemetry['utility_fail'] = False
        elif 'appliance_mode_on' in cmd_name:
            self._telemetry['appliance_mode'] = 1
        elif 'appliance_mode_off' in cmd_name:
            self._telemetry['appliance_mode'] = 0
        elif 'extra_backup_on' in cmd_name or 'backup_mode_on' in cmd_name:
            self._telemetry['extra_backup'] = 1
        elif 'extra_backup_off' in cmd_name or 'backup_mode_off' in cmd_name:
            self._telemetry['extra_backup'] = 0
        elif 'turbo_charging_on' in cmd_name:
            self._telemetry['turbo_charging'] = 1
        elif 'turbo_charging_off' in cmd_name:
            self._telemetry['turbo_charging'] = 0
        elif 'holiday_mode_on' in cmd_name:
            self._telemetry['holiday_mode'] = 1
        elif 'holiday_mode_off' in cmd_name:
            self._telemetry['holiday_mode'] = 0

        # Post-command read verification: send read request for corresponding register after 400ms delay
        reg_to_poll = None
        if 'inverter' in cmd_name:
            reg_to_poll = 7
        elif 'force_cut' in cmd_name:
            reg_to_poll = 305
        elif 'appliance_mode' in cmd_name:
            reg_to_poll = 503
        elif 'extra_backup' in cmd_name or 'backup_mode' in cmd_name:
            reg_to_poll = 213
        elif 'turbo_charging' in cmd_name:
            reg_to_poll = 207
        elif 'holiday_mode' in cmd_name:
            reg_to_poll = 201
        elif 'eco_mode' in cmd_name:
            reg_to_poll = 308

        if reg_to_poll and self.connected:
            read_frame = build_inverter_read_cmd(reg_to_poll)
            if read_frame:
                try:
                    time.sleep(0.3)
                    self._write_binary(read_frame)
                    logger.info(f"Post-command status verification poll sent for reg {reg_to_poll}: {read_frame.hex()}")
                    if reg_to_poll == 305:
                        time.sleep(0.2)
                        alarm_read = build_inverter_read_cmd(7)
                        if alarm_read:
                            self._write_binary(alarm_read)
                            logger.info(f"Post-command alarm verification poll sent for reg 7: {alarm_read.hex()}")
                except Exception as ex:
                    logger.warning(f"Post-command verification poll error: {ex}")

        self._calculate_derived_inverter_telemetry()
        return {
            'success': ok,
            'command': cmd_name,
            'frame_hex': frame.hex(),
            'ascii_cmd': ascii_cmd,
            'message': f"Command {cmd_name} sent to inverter successfully" if ok else f"Failed to transmit {cmd_name} over BLE"
        }


    def _handle_binary_notification(self, raw: bytes):
        """Handle binary data from smart plug (not inverter) — store as raw."""
        hexstr = raw.hex()
        self._telemetry['timestamp'] = int(time.time())
        raw_list = self._telemetry.get('raw_responses', [])
        raw_list.append(f"BINARY:{hexstr}")
        self._telemetry['raw_responses'] = raw_list[-100:]

        for parser in self._binary_parsers:
            try:
                upd = parser(raw)
                if isinstance(upd, dict):
                    for k, v in upd.items():
                        self._telemetry[k] = v
                        logger.info(f"Binary parser updated telemetry: {k}={v}")
            except Exception as e:
                logger.debug(f"Binary parser raised: {e}")

    def _default_inverter_parser(self, raw: bytes) -> Optional[Dict]:
        """Legacy conservative parser — kept for backward compat but superseded
        by _handle_inverter_frame() for inverter devices."""
        if not raw or len(raw) == 0:
            return None
        fields = {'inv_frame_hex': raw.hex()}
        for i, b in enumerate(raw):
            fields[f'inv_b{i}'] = b
        return fields

    def send_raw_bytes(self, data: bytes, response: bool = True) -> bool:
        """Public helper to send raw binary bytes to device."""
        return self._write_binary(data, response=response)

    def _parse_vg_line(self, line: str):
        """Parse 'VGxxx:value' or 'VGxxx:value:extra' into telemetry dict."""
        # The response has colon separating code from value
        m = re.match(r'^(VG\d{3,4}):(.+)$', line.strip(), re.IGNORECASE)
        if not m:
            logger.debug(f"Non-VG response line: {repr(line)}")
            return

        code = m.group(1).upper()
        val_str = m.group(2).strip()
        logger.info(f"Parsed VG response: {code} = {repr(val_str)}")

        # Store raw
        self._telemetry['timestamp'] = int(time.time())
        raw = self._telemetry.get('raw_responses', [])
        raw.append(f"{code}:{val_str}")
        self._telemetry['raw_responses'] = raw[-50:]

        field_info = config.VG_FIELD_MAP.get(code)
        if not field_info:
            logger.debug(f"Unknown VG code: {code}")
            return

        field_name, _, unit = field_info
        try:
            if unit in ('V', 'A', 'W', 'kWh', 'C', '°C'):
                num_match = re.search(r'[-+]?\d*\.?\d+', val_str)
                if num_match:
                    self._telemetry[field_name] = float(num_match.group(0))
                else:
                    self._telemetry[field_name] = float(val_str)
            elif unit == '0/1':
                num_match = re.search(r'\d+', val_str)
                if num_match:
                    self._telemetry[field_name] = int(num_match.group(0))
                else:
                    self._telemetry[field_name] = int(val_str)
            else:
                self._telemetry[field_name] = val_str
            logger.info(f"Telemetry update: {field_name} = {self._telemetry[field_name]} [{unit}]")
        except (ValueError, TypeError) as e:
            logger.warning(f"Cannot parse {code}:{val_str} -> {e}")
            self._telemetry[field_name] = val_str

    # ------------------------------------------------------------------ #
    #  Low-level write — plain UTF-8, NO newline (matches APK behaviour)
    # ------------------------------------------------------------------ #

    def _write_ascii(self, text: str) -> bool:
        """
        Write ASCII command to TX characteristic (0003cdd2).
        The APK uses Android's writeCharacteristic() which defaults to
        WRITE_TYPE_DEFAULT (write WITH response = response=True in bleak).
        Commands ≤20 bytes go in one packet; longer ones are chunked
        (each chunk ≤19 bytes with '@' appended to non-final chunks).
        All our VGxxx commands are ≤15 bytes so chunking never triggers.
        """
        if not self.client or not self.connected:
            logger.warning("_write_ascii: not connected")
            return False

        payload = text.encode("utf-8")
        logger.info(f"Write TX: {repr(text)}  hex={payload.hex()}")

        CHUNK = 20
        if len(payload) <= CHUNK:
            chunks = [payload]
        else:
            # Split into 19-byte pieces; mark non-final with '@'
            pieces = [payload[i:i + 19] for i in range(0, len(payload), 19)]
            chunks = [p + b"@" for p in pieces[:-1]] + [pieces[-1]]

        async def _do_write():
            for i, chunk in enumerate(chunks):
                # Use response=True — matches Android's WRITE_TYPE_DEFAULT
                try:
                    await self.client.write_gatt_char(
                        self._tx_char_uuid,
                        chunk,
                        response=True,
                    )
                    logger.debug(f"Sent chunk {i} (w/response): {chunk.hex()}")
                except Exception:
                    # Fallback: write without response (WRITE_NO_RESPONSE)
                    logger.debug(f"Retrying chunk {i} without response...")
                    await self.client.write_gatt_char(
                        self._tx_char_uuid,
                        chunk,
                        response=False,
                    )
                    logger.debug(f"Sent chunk {i} (no-response): {chunk.hex()}")
                if len(chunks) > 1 and i < len(chunks) - 1:
                    await asyncio.sleep(0.5)   # 500 ms gap between chunks (per APK)

        try:
            self._run_async(_do_write(), timeout=10.0)
            return True
        except Exception as e:
            logger.error(f"Write error: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Read a single VG register: send "read:VGxxx" -> wait for notify
    # ------------------------------------------------------------------ #

    def _read_vg(self, vg_code: str, wait_secs: float = 3.5) -> Optional[str]:
        """
        Send "read:VGxxx" and wait up to wait_secs for the "VGxxx:value" notification.

        Uses a per-VG-code threading.Event so concurrent reads don't interfere.
        Polls the received_lines list at each notification event, re-waiting if
        the notification was for a different code.  Gives up after wait_secs total.

        Returns the value string or None.
        """
        cmd = f"{config.VG_READ_PREFIX}{vg_code}"

        # Register a per-code event before sending the command
        per_code_evt = threading.Event()
        with self._pending_lock:
            self._pending_requests[vg_code] = per_code_evt

        # Snapshot existing lines so we only look at new ones
        with self._received_lock:
            prev_count = len(self._received_lines)

        if not self._write_ascii(cmd):
            with self._pending_lock:
                self._pending_requests.pop(vg_code, None)
            return None

        deadline = time.time() + wait_secs
        result = None

        try:
            while time.time() < deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break

                # Wait for this specific code's event (or global notify)
                fired = per_code_evt.wait(timeout=min(remaining, 1.0))

                # Check if our code arrived
                with self._received_lock:
                    new_lines = list(self._received_lines[prev_count:])

                for line in new_lines:
                    m = re.match(rf'^{re.escape(vg_code)}:(.+)$', line.strip(), re.IGNORECASE)
                    if m:
                        result = m.group(1).strip()
                        break

                if result is not None:
                    break

                if fired:
                    per_code_evt.clear()  # re-arm, keep waiting

                if new_lines:
                    logger.debug(f"Waiting for {vg_code}: got {len(new_lines)} line(s) so far: {new_lines[-3:]}")

        finally:
            with self._pending_lock:
                self._pending_requests.pop(vg_code, None)

        if result is None:
            with self._received_lock:
                all_new = list(self._received_lines[prev_count:])
            if all_new:
                logger.debug(f"No match for {vg_code} after {wait_secs}s; received: {all_new}")
            else:
                logger.debug(f"No notification received for {vg_code} within {wait_secs}s")

            if self.client:
                logger.debug(f"Falling back to direct RX characteristic read for {vg_code}")
                raw = self._run_async(self._read_rx_char(), timeout=4.0)
                if raw:
                    try:
                        text = raw.decode("utf-8", errors="replace").strip()
                        if text:
                            logger.info(f"RX char direct read: {repr(text)}")
                            for line in text.splitlines():
                                line = line.strip()
                                if line.upper().startswith(f"{vg_code}:"):
                                    result = line.split(":", 1)[1].strip()
                                    break
                    except Exception as e:
                        logger.warning(f"RX char read parse error: {e}")

        return result

    # ------------------------------------------------------------------ #
    #  High-level command dispatch
    # ------------------------------------------------------------------ #

    def send_command(self, command: str, params: Dict = None, wait_response: bool = True) -> Dict:
        """
        High-level command dispatch.
          'status'    -> polls all telemetry VG codes
          'power_on'  -> writes VG094:1
          'power_off' -> writes VG094:0
          'read:VGxxx'-> raw read of that VG code
        """
        if not self.connected or not self.client:
            return {'success': False, 'error': 'Not connected'}

        params = params or {}

        if command == 'status':
            return self._poll_telemetry()

        cmd_info = config.COMMAND_CODES.get(command)
        if cmd_info is None:
            # Allow raw VG reads/writes
            if command.startswith('read:'):
                vg = command[5:].upper()
                val = self._read_vg(vg)
                return {'success': True, 'command': command, 'value': val}
            if re.match(r'^VG\d+:', command, re.IGNORECASE):
                ok = self._write_ascii(command)
                return {'success': ok, 'command': command}
            return {'success': False, 'error': f'Unknown command: {command}'}

        vg_code, vg_val = cmd_info
        if vg_val is None:
            val = self._read_vg(vg_code)
            return {'success': True, 'command': command, 'vg_code': vg_code, 'value': val}
        else:
            text = f"{vg_code}:{vg_val}"
            ok = self._write_ascii(text)
            if ok and wait_response:
                time.sleep(0.6)
                self._read_vg(vg_code, wait_secs=1.5)
            return {'success': ok, 'command': command, 'sent': text}

    def _poll_telemetry(self) -> Dict:
        """
        Poll all telemetry registers sequentially.
        - INVERTER: sends binary 8-byte read frames, waits for notification.
        - SMART PLUG: sends ASCII 'read:VGxxx', waits for notify response.
        """
        if not self.connected:
            return {'success': False, 'error': 'Not connected'}

        if self._is_inverter_device:
            return self._poll_inverter_telemetry()

        results = {}
        for vg_code in config.TELEMETRY_POLL_COMMANDS:
            val = self._read_vg(vg_code, wait_secs=3.5)
            results[vg_code] = val
            logger.info(f"Poll {vg_code} = {val}")
            time.sleep(0.5)  # inter-command gap (let device settle)

        return {
            'success': True,
            'command': 'status',
            'vg_values': results,
            'telemetry': dict(self._telemetry),
        }

    def _poll_inverter_telemetry(self) -> Dict:
        """
        Poll inverter telemetry by sending binary read commands.
        Each command is an 8-byte frame: FF FF FF [cmd] 0C 01 FF FF.
        The device responds asynchronously via notifications — we wait a short
        time between sends to avoid flooding.
        """
        if not self.connected or not self.client:
            return {'success': False, 'error': 'Not connected'}

        poll_registers = INVERTER_DASHBOARD_POLL if INVERTER_PROTOCOL_AVAILABLE else []
        results = {}

        for reg_id in poll_registers:
            if not self.connected:
                break
            cmd_frame = INVERTER_CMD_BYTES.get(reg_id)
            if cmd_frame is None:
                continue

            logger.info(f"Inverter poll: reg={reg_id} cmd={cmd_frame.hex()}")
            self._notify_event.clear()
            try:
                ok = self._write_binary(cmd_frame)
                if not ok:
                    logger.warning(f"Failed to write cmd for reg {reg_id}")
            except Exception as e:
                logger.error(f"Inverter cmd write error for reg {reg_id}: {e}")

            # Wait briefly — response arrives as BLE notification (async)
            self._notify_event.wait(timeout=0.4)
            time.sleep(0.04)   # fast inter-command gap

            reg_info = INVERTER_REGISTER_MAP.get(reg_id)
            if reg_info:
                field_name = reg_info[0]
                results[reg_id] = self._telemetry.get(field_name)

        return {
            'success': True,
            'command': 'status',
            'inverter_registers': results,
            'telemetry': dict(self._telemetry),
        }

    # ------------------------------------------------------------------ #
    #  Device info
    # ------------------------------------------------------------------ #

    def get_device_info(self) -> Dict:
        if not self.connected:
            return {'error': 'Not connected'}

        self._poll_telemetry()
        time.sleep(0.2)

        tel = self._telemetry
        power_state = tel.get('power_state')
        is_on = (power_state == 1 or power_state is True or str(power_state) == '1')

        info = {
            'name':           self.device_name or 'V-Guard Smart 2.0',
            'address':        self.device_address,
            'connected':      self.connected,
            'firmware':       tel.get('firmware') or '2.0',
            'model':          tel.get('model') or 'V-Guard Smart 2.0',
            'power_state':    power_state,
            'is_on':          is_on,
            'voltage':        tel.get('voltage'),
            'current':        tel.get('current'),
            'temperature':    tel.get('temperature'),
            'power':          tel.get('power'),
            'energy':         tel.get('energy'),
            'signal_strength': tel.get('signal_strength'),
            'raw_responses':  tel.get('raw_responses', [])[-10:],
            'timestamp':      tel.get('timestamp') or int(time.time()),
        }
        self.device_info = info
        logger.info(f"Device info: {info}")
        return info

    def is_connected(self) -> bool:
        if not self.connected:
            return False
        if self.client:
            try:
                if self.client.is_connected:
                    return True
                else:
                    self.connected = False
                    return False
            except Exception:
                self.connected = False
                return False
        return False

    def get_telemetry(self) -> Dict:
        if getattr(self, '_is_inverter_device', False):
            try:
                self._calculate_derived_inverter_telemetry()
            except Exception as e:
                logger.debug(f"Error calculating derived inverter telemetry: {e}")
        return dict(self._telemetry)

    def send_raw_data(self, data: bytes) -> bool:
        return self._write_ascii(data.decode("utf-8", errors="replace"))

    async def _read_rx_char(self, char_uuid: Optional[str] = None) -> Optional[bytes]:
        if not self.client or not self.connected:
            return None
        candidates = [char_uuid] if char_uuid else [self._rx_char_uuid] + [u for u in self._rx_char_candidates if u != self._rx_char_uuid]
        for uuid in candidates:
            if not uuid:
                continue
            try:
                val = await self.client.read_gatt_char(uuid)
                logger.debug(f"Read RX char {uuid} raw={bytes(val).hex()}")
                return bytes(val)
            except Exception as e:
                logger.debug(f"Direct RX char read failed for {uuid}: {e}")
        return None

    def receive_raw_data(self, timeout: float = 2.0) -> Optional[bytes]:
        if not self.connected:
            return None
        self._notify_event.clear()
        if self._notify_event.wait(timeout=timeout):
            with self._received_lock:
                if self._received_lines:
                    return self._received_lines[-1].encode("utf-8")
        return None

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _reset_telemetry(self):
        for k in list(self._telemetry.keys()):
            if k == 'raw_responses':
                self._telemetry[k] = []
            else:
                self._telemetry[k] = None
        self._rx_buffer = ""
        self._inverter_frame_buf = b""
        with self._received_lock:
            self._received_lines.clear()

    @staticmethod
    def _get_mock_devices() -> List[Dict]:
        return []
