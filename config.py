"""
Configuration for V-Guard Smart 2.0 Control Panel
Protocol: ASCII UART-over-BLE (plain text, no binary header)

Commands confirmed from APK decompilation (BluetoothLeService.kt / PlugDashboardViewModel.kt):
  Read:  send "read:VGxxx"  → device replies "VGxxx:value" via BLE notification
  Write: send "VGxxx:value" → device applies setting

Smart Plug 2.0 VG code reference (confirmed from PlugDashboardViewModel + C2337b.B()):
  VG092  = Power on/off state        (0=off, 1=on)  — toggle read
  VG094  = Power toggle command      (write VG094:1 = ON, VG094:0 = OFF)
  VG273  = Input voltage             (V)
  VG003  = Load current              (A)
  VG295  = Active power              (W)
  VG192  = Energy consumed           (kWh)
  VG004  = Firmware / model info
  VG030  = Model string
  VG302  = Schedule state
  VG300  = Timer state
  VG278  = Some parameter
  VG191  = ?
  VG014  = High-cut voltage
  VG045  = Last sync time
  VG251  = ? (Wi-Fi SSID?)
  VG197  = ? (signal/info)
  VG195  = ?
  VG132  = ?
  VG136  = ?
  VG012  = ?
"""

# Flask
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5000
FLASK_DEBUG = True
SECRET_KEY = 'vguard-smart-2.0-secret-key'

# Bluetooth scan
BLUETOOTH_SCAN_DURATION = 5   # seconds

# BLE GATT UUIDs — confirmed from BluetoothLeService.java (f17898I / f17899J / f17900K)
# Service UUID list: 0003cdd0  and  0000fee9
# RX char (device→app, notify):  0003cdd1  and  d44bc439-abfd-45a2-b575-925416129601
# TX char (app→device, write):   0003cdd2  and  d44bc439-abfd-45a2-b575-925416129600
BLE_SERVICE_UUID  = "0003cdd0-0000-1000-8000-00805f9b0131"
BLE_RX_CHAR_UUID  = "0003cdd1-0000-1000-8000-00805f9b0131"   # Notify  (device→app)
BLE_TX_CHAR_UUID  = "0003cdd2-0000-1000-8000-00805f9b0131"   # Write   (app→device)

# Fallback alternative UUIDs (some devices use the fee9 service)
BLE_SERVICE_UUID_ALT  = "0000fee9-0000-1000-8000-00805f9b34fb"
BLE_RX_CHAR_UUID_ALT  = "d44bc439-abfd-45a2-b575-925416129601"
BLE_TX_CHAR_UUID_ALT  = "d44bc439-abfd-45a2-b575-925416129600"

BLE_SERVICE_UUIDS = {BLE_SERVICE_UUID.lower(), BLE_SERVICE_UUID_ALT.lower()}
BLE_RX_UUIDS = {BLE_RX_CHAR_UUID.lower(), BLE_RX_CHAR_UUID_ALT.lower()}
BLE_TX_UUIDS = {BLE_TX_CHAR_UUID.lower(), BLE_TX_CHAR_UUID_ALT.lower()}

# Device identity
VGUARD_DEVICE_NAME    = 'VG_SMART_BT_WF_2'
VGUARD_PACKAGE_NAME   = 'com.vguard.smartv2'
VGUARD_VERSION        = '2.0.17'

# Logging
LOG_LEVEL  = 'DEBUG'
LOG_FILE   = 'vguard_app.log'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# UI
UI_REFRESH_INTERVAL      = 5000   # ms
UI_NOTIFICATION_TIMEOUT  = 5000   # ms

# ---------------------------------------------------------------
# ASCII command protocol
# ---------------------------------------------------------------
# Read format:  "read:VGxxx"   (UTF-8, no newline)
# Write format: "VGxxx:value"  (UTF-8, no newline)
# Response:     "VGxxx:value"  (UTF-8, via BLE notification on RX char)

VG_READ_PREFIX = "read:"

# VG code → (field_name, description, unit)
# Confirmed from PlugDashboardViewModel.kt parsing methods
VG_FIELD_MAP = {
    # Power
    'VG092': ('power_state',   'Power on/off state',        '0/1'),   # main on/off read
    'VG094': ('power_state',   'Power toggle',              '0/1'),   # write command echo

    # Electrical measurements
    'VG273': ('temperature',   'Input voltage or temp',     'V'),     # confirmed float field
    'VG003': ('current',       'Load current',              'A'),
    'VG005': ('voltage',       'Input voltage (alt)',       'V'),
    'VG295': ('power',         'Active power',              'W'),
    'VG192': ('energy',        'Energy consumed',           'kWh'),

    # Device info
    'VG004': ('firmware',      'Firmware version',          ''),
    'VG030': ('model',         'Model string',              ''),

    # Schedule / timer
    'VG302': ('schedule_state','Schedule on/off state',     ''),
    'VG300': ('timer_state',   'Timer state',               ''),

    # Cut voltages / protection
    'VG014': ('high_cut',      'High-cut voltage',          'V'),
    'VG015': ('low_cut',       'Low-cut voltage',           'V'),

    # Extra info
    'VG278': ('param_278',     'Parameter 278',             ''),
    'VG191': ('param_191',     'Parameter 191',             ''),
    'VG197': ('param_197',     'Parameter 197',             ''),
    'VG195': ('param_195',     'Parameter 195',             ''),
    'VG045': ('last_sync',     'Last sync date',            ''),
    'VG251': ('param_251',     'Parameter 251',             ''),
    'VG132': ('param_132',     'Parameter 132',             ''),
    'VG136': ('param_136',     'Parameter 136',             ''),
    'VG012': ('param_012',     'Parameter 012',             ''),
    'VG301': ('param_301',     'Parameter 301',             ''),
}

# Telemetry poll order for Smart Plug — from C2337b.B() / C1024c0 collectTabStateFlow
# This matches what the Android app polls on the dashboard tab
TELEMETRY_POLL_COMMANDS = [
    'VG092',   # power state (on/off)
    'VG005',   # voltage or current
    'VG003',   # current
    'VG295',   # power (W)
    'VG192',   # energy (kWh)
    'VG273',   # temperature / voltage
    'VG004',   # firmware
    'VG030',   # model
]

# High-level command names → (VG code, value) or None for special handling
# Power write command confirmed: VG094:1 = ON, VG094:0 = OFF (from K0() in PlugDashboardViewModel)
COMMAND_CODES = {
    'power_on':      ('VG094', '1'),   # VG094:1
    'power_off':     ('VG094', '0'),   # VG094:0
    'get_state':     ('VG092', None),  # read power on/off state
    'get_voltage':   ('VG005', None),
    'get_current':   ('VG003', None),
    'get_power':     ('VG295', None),
    'get_energy':    ('VG192', None),
    'get_firmware':  ('VG004', None),
}

# Power state values
POWER_ON  = '1'
POWER_OFF = '0'

# ---------------------------------------------------------------
# Home Assistant REST API Push Settings
# ---------------------------------------------------------------
HA_URL = 'http://192.168.1.100:8123'
HA_TOKEN = 'my_test_token_123'
HA_PUSH_INTERVAL = 10
HA_ENTITY_PREFIX = "vguard_inverter" # prefix for entity IDs (e.g. sensor.vguard_inverter_battery_voltage)

# Battery scaling config: default 160 for 12V battery system (raw 2056 / 160 = 12.85V)
# Use 100 for 24V battery systems (raw 2056 / 100 = 20.56V)
BATTERY_VOLTAGE_DIVISOR = 160

# Auto-connect defaults
AUTO_CONNECT_ENABLED = True
AUTO_CONNECT_DEVICE = 'VG_SMART_BT_WF_2'
AUTO_CONNECT_RETRY_INTERVAL = 30   # seconds between scan attempts when disconnected


