"""
V-Guard Inverter BLE Protocol — confirmed from APK decompilation (InverterDashboardViewModel.kt,
InverterCommands.kt, BleCommunicationHelper.kt).

Binary 8-byte frame protocol (NOT the ASCII VGxxx protocol used by Smart Plug):

  READ  frame: FF FF FF [cmd_id] 0C 01 FF FF  → device responds with telemetry
  WRITE frame: FF [val_lo] [val_hi] [cmd_id] 0C 00 FF FF

  Response: 8 bytes — value = (byte[7] << 8) | byte[6]  (little-endian at indices 6–7)
  Partial frames: device may send < 8 bytes; accumulate until total = 8 bytes.

Register ID → (cmd_byte, field_name, scale_divisor, unit)
  From s0() / r0() / t0() in InverterDashboardViewModel.kt
"""

from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# divisor=1 means raw value, divisor=10 means /10, divisor=100 means /100
INVERTER_REGISTER_MAP: Dict[int, Tuple[str, int, str]] = {
    # register_id: (field_name, divisor, unit)
    # Verified directly against APK bytecode (P7/U.java p0() method) and live hardware
    601: ('battery_voltage',         100, 'V'),    # cmd=0x06, raw/100 -> battery voltage (e.g. 1363 -> 13.63V)
    603: ('ac_input_voltage',        10,  'V'),    # cmd=0x08, raw/10  -> mains grid voltage (e.g. 2185 -> 218.5V)
    602: ('load_current',            10,  'A'),    # cmd=0x0C, raw/10  -> load current (e.g. 0 -> 0.0A)
    110: ('load_pct',                1,   '%'),    # cmd=0x2C, raw     -> load percentage (e.g. 0%)
    111: ('battery_pct_raw',         1,   ''),     # cmd=0x3C, raw     -> raw battery parameter (27000)
    112: ('backup_time_mins',        1,   'min'),  # cmd=0x38, raw     -> battery remaining backup mins
    113: ('battery_count',           1,   ''),     # cmd=0x74, raw     -> number of batteries (1 or 2)
    115: ('model_id',                1,   ''),     # cmd=0xCA0B, raw   -> model ID (17)
    116: ('solar_current',           100, 'A'),    # cmd=0x76, raw/100 -> solar current
    117: ('charge_current',          10,  'A'),    # cmd=0x10, raw/10  -> mains charging current
    118: ('solar_watts',             10,  'W'),    # cmd=0x90, raw/10  -> solar power
    119: ('solar_v',                 10,  'V'),    # cmd=0x96, raw/10  -> solar voltage
    121: ('charge_hours',            1,   'h'),    # cmd=0xCC0B, raw   -> battery capacity / charge hours
    122: ('alarm_status',            1,   ''),     # cmd=0x1E, raw     -> alarm bitmask (bit 0=power cut, 1=low bat, 6=overload)
    106: ('power_state',             1,   '0/1'),  # cmd=0x16, raw     -> inverter output ON (1) / OFF (0)
    108: ('backup_mode',             1,   ''),     # cmd=0x1E, raw     -> backup mode register
    201: ('voltage_regulator',       1,   ''),     # cmd=0x24, raw     -> voltage regulator setting
    204: ('forced_power_cut',        1,   '0/1'),  # cmd=0x28, raw     -> forced cut active (1) or disabled (0)
    207: ('forced_power_cut_mins',   1,   'min'),  # cmd=0x2A, raw     -> forced cut duration / remaining mins
    209: ('turbo_charging',          1,   '0/1'),  # cmd=0x30, raw     -> turbo charging enabled (1)
    211: ('appliance_mode',          1,   '0/1'),  # cmd=0x26, raw     -> appliance mode enabled (1)
    213: ('extra_backup',            1,   '0/1'),  # cmd=0x6E, raw==1000 -> extra backup enabled
    215: ('holiday_mode',            1,   '0/1'),  # cmd=0x32, raw     -> holiday mode enabled (1)
    217: ('solar_kwh_today',         10,  'kWh'),  # cmd=0x90, raw/10  -> solar energy today
    301: ('power_mode',              1,   ''),     # cmd=0x18, raw     -> power mode
    303: ('charging_mode',           1,   ''),     # cmd=0x1A, raw     -> charging mode
    304: ('battery_type',            1,   ''),     # cmd=0x1C, raw     -> battery type (1=tubular, etc)
    305: ('inverter_charging_curr',  1,   'A'),    # cmd=0x2E, raw     -> charging current setting
    307: ('solar_input_v',           10,  'V'),    # cmd=0x80, raw/10  -> solar input V
    308: ('solar_input_a',           10,  'A'),    # cmd=0x84, raw/10  -> solar input A
    311: ('solar_total_kwh',         10,  'kWh'),  # cmd=0x86, raw/10  -> solar total energy
    501: ('high_cut_voltage',        1,   'V'),    # cmd=0x3A, raw     -> high cut voltage setting
    503: ('appliance_mode_hi',       1,   '0/1'),  # cmd=0x3E, raw==1100 -> appliance mode
    505: ('battery_cutoff',          1,   '%'),    # cmd=0x20, raw     -> battery cutoff
    701: ('power_cut_mins',          1,   'min'),  # cmd=0x7C, raw     -> day 1 power cut duration
    702: ('power_cut_count',         1,   ''),     # cmd=0x7E, raw     -> day 1 power cut count
    703: ('backup_time_raw',         1,   's'),    # cmd=0x7A, raw     -> remaining backup duration ticks
}

# Command bytes per register_id (from APK source)
INVERTER_CMD_BYTES: Dict[int, bytes] = {
    601: bytes([0xFF, 0xFF, 0xFF, 0x06, 0x0C, 0x01, 0xFF, 0xFF]),  # batteryVoltage
    603: bytes([0xFF, 0xFF, 0xFF, 0x08, 0x0C, 0x01, 0xFF, 0xFF]),  # mainsVoltage
    602: bytes([0xFF, 0xFF, 0xFF, 0x0C, 0x0C, 0x01, 0xFF, 0xFF]),  # loadCurrent
    110: bytes([0xFF, 0xFF, 0xFF, 0x2C, 0x0C, 0x01, 0xFF, 0xFF]),  # loadPercentage
    111: bytes([0xFF, 0xFF, 0xFF, 0x3C, 0x0C, 0x01, 0xFF, 0xFF]),  # batteryPercentage
    112: bytes([0xFF, 0xFF, 0xFF, 0x38, 0x0C, 0x01, 0xFF, 0xFF]),  # batteryRemaining
    113: bytes([0xFF, 0xFF, 0xFF, 0x74, 0x0C, 0x01, 0xFF, 0xFF]),  # numberOfBatteries
    115: bytes([0xFF, 0xFF, 0xFF, 0xCA, 0x0B, 0x01, 0xFF, 0xFF]),  # modelId
    116: bytes([0xFF, 0xFF, 0xFF, 0x76, 0x0C, 0x01, 0xFF, 0xFF]),  # solarCurrent
    117: bytes([0xFF, 0xFF, 0xFF, 0x10, 0x0C, 0x01, 0xFF, 0xFF]),  # mainsChargingCurrent
    118: bytes([0xFF, 0xFF, 0xFF, 0x90, 0x0C, 0x01, 0xFF, 0xFF]),  # solarWatts
    119: bytes([0xFF, 0xFF, 0xFF, 0x96, 0x0C, 0x01, 0xFF, 0xFF]),  # solarGaugeStatus
    121: bytes([0xFF, 0xFF, 0xFF, 0xCC, 0x0B, 0x01, 0xFF, 0xFF]),  # batteryCapacity
    122: bytes([0xFF, 0xFF, 0xFF, 0x1E, 0x0C, 0x01, 0xFF, 0xFF]),  # alarmData (bitmask)
    106: bytes([0xFF, 0xFF, 0xFF, 0x16, 0x0C, 0x01, 0xFF, 0xFF]),  # isPowerOn
    108: bytes([0xFF, 0xFF, 0xFF, 0x1E, 0x0C, 0x01, 0xFF, 0xFF]),  # backupMode
    201: bytes([0xFF, 0xFF, 0xFF, 0x24, 0x0C, 0x01, 0xFF, 0xFF]),  # voltageRegulator
    204: bytes([0xFF, 0xFF, 0xFF, 0x28, 0x0C, 0x01, 0xFF, 0xFF]),  # isMainsForceCutEnabled
    207: bytes([0xFF, 0xFF, 0xFF, 0x2A, 0x0C, 0x01, 0xFF, 0xFF]),  # mainForceCutTime
    209: bytes([0xFF, 0xFF, 0xFF, 0x30, 0x0C, 0x01, 0xFF, 0xFF]),  # isTurboCharging
    211: bytes([0xFF, 0xFF, 0xFF, 0x26, 0x0C, 0x01, 0xFF, 0xFF]),  # isApplianceModeEnabled
    213: bytes([0xFF, 0xFF, 0xFF, 0x6E, 0x0C, 0x01, 0xFF, 0xFF]),  # isExtraBackupEnabled
    215: bytes([0xFF, 0xFF, 0xFF, 0x32, 0x0C, 0x01, 0xFF, 0xFF]),  # isHolidayModeEnabled
    217: bytes([0xFF, 0xFF, 0xFF, 0x90, 0x0C, 0x01, 0xFF, 0xFF]),  # solarToday
    301: bytes([0xFF, 0xFF, 0xFF, 0x18, 0x0C, 0x01, 0xFF, 0xFF]),  # powerMode
    303: bytes([0xFF, 0xFF, 0xFF, 0x1A, 0x0C, 0x01, 0xFF, 0xFF]),  # chargingMode
    304: bytes([0xFF, 0xFF, 0xFF, 0x1C, 0x0C, 0x01, 0xFF, 0xFF]),  # batteryType
    305: bytes([0xFF, 0xFF, 0xFF, 0x2E, 0x0C, 0x01, 0xFF, 0xFF]),  # inverterChargingCurrent
    307: bytes([0xFF, 0xFF, 0xFF, 0x80, 0x0C, 0x01, 0xFF, 0xFF]),  # solarInputV
    308: bytes([0xFF, 0xFF, 0xFF, 0x84, 0x0C, 0x01, 0xFF, 0xFF]),  # solarInputA
    311: bytes([0xFF, 0xFF, 0xFF, 0x86, 0x0C, 0x01, 0xFF, 0xFF]),  # solarTotalKwh
    501: bytes([0xFF, 0xFF, 0xFF, 0x3A, 0x0C, 0x01, 0xFF, 0xFF]),  # highCutVoltage
    503: bytes([0xFF, 0xFF, 0xFF, 0x3E, 0x0C, 0x01, 0xFF, 0xFF]),  # applianceMode
    505: bytes([0xFF, 0xFF, 0xFF, 0x20, 0x0C, 0x01, 0xFF, 0xFF]),  # batteryCutoff
    701: bytes([0xFF, 0xFF, 0xFF, 0x7C, 0x0C, 0x01, 0xFF, 0xFF]),  # powerCutTotalMins
    702: bytes([0xFF, 0xFF, 0xFF, 0x7E, 0x0C, 0x01, 0xFF, 0xFF]),  # powerCutCount
    703: bytes([0xFF, 0xFF, 0xFF, 0x7A, 0x0C, 0x01, 0xFF, 0xFF]),  # backupTimeSecs
}

# Full dashboard poll list (strictly per official t0() in InverterDashboardViewModel.kt)
INVERTER_DASHBOARD_POLL: List[int] = [
    601,   # battery_voltage (raw / 100.0f = 13.63V)
    603,   # ac_input_voltage / mainsVoltage (raw / 10.0f = 218.5V)
    602,   # load_current (raw / 10.0f = 0.0A)
    110,   # load_pct (raw = 0%)
    117,   # charge_current / mainsChargingCurrent (raw / 10.0f = 0.3A)
    112,   # backup_time_mins / batteryRemaining
    106,   # power_state / isPowerOn (1=on, 0=off)
    122,   # alarm_status / alarmData bitmask
    204,   # forced_power_cut / isMainsForceCutEnabled (1=cut, 0=normal)
    207,   # forced_power_cut_mins / mainForceCutTime
    209,   # turbo_charging / isTurboCharging
    211,   # appliance_mode / isApplianceModeEnabled
    213,   # extra_backup / isExtraBackupEnabled
    215,   # holiday_mode / isHolidayModeEnabled
    113,   # battery_count (1 or 2)
    304,   # battery_type
    305,   # inverter_charging_current
    501,   # high_cut_voltage
    701,   # power_cut_mins
    702,   # power_cut_count
    703,   # backup_time_raw
]

# Extended status poll (from r0() in InverterDashboardViewModel)
INVERTER_STATUS_POLL: List[int] = [
    122, 305, 304, 108, 209, 211, 215, 213, 207,
    301, 204, 201, 303, 501, 503, 505, 115,
]

# Write commands confirmed from APK decompilation (U.java / InverterDashboardViewModel / InverterCommands.kt)
# Format: 8-byte binary frame FF [val_lo] [val_hi] [cmd_byte] 0C 00 FF FF
INVERTER_WRITE_COMMANDS: Dict[str, bytes] = {
    'inverter_on':        bytes([0xFF, 0x01, 0x00, 0x16, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x16 (reg 106) val 1 (from Y() in U.java)
    'inverter_off':       bytes([0xFF, 0x00, 0x00, 0x16, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x16 (reg 106) val 0
    'eco_mode_on':        bytes([0xFF, 0x01, 0x00, 0x84, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x84 (reg 308) val 1 (from S() in U.java)
    'eco_mode_off':       bytes([0xFF, 0x00, 0x00, 0x84, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x84 (reg 308) val 0
    'bypass_on':          bytes([0xFF, 0x01, 0x00, 0x32, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x32 (reg 215) val 1 (from V() in U.java)
    'bypass_off':         bytes([0xFF, 0x00, 0x00, 0x32, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x32 (reg 215) val 0
    'ac_charge_on':       bytes([0xFF, 0x01, 0x00, 0x30, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x30 (reg 209) val 1 (from b0() in U.java)
    'ac_charge_off':      bytes([0xFF, 0x00, 0x00, 0x30, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x30 (reg 209) val 0
    'backup_mode_on':     bytes([0xFF, 0xE8, 0x03, 0x6E, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x6E (reg 213) val 1000 (from T() in U.java)
    'backup_mode_off':    bytes([0xFF, 0x00, 0x00, 0x6E, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x6E (reg 213) val 0
    'extra_backup_on':    bytes([0xFF, 0xE8, 0x03, 0x6E, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x6E (reg 213) val 1000
    'extra_backup_off':   bytes([0xFF, 0x00, 0x00, 0x6E, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x6E (reg 213) val 0
    'appliance_mode_on':  bytes([0xFF, 0x4C, 0x04, 0x3E, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x3E (reg 503) val 1100 (from X() in U.java)
    'appliance_mode_off': bytes([0xFF, 0x64, 0x00, 0x3E, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x3E (reg 503) val 100
    
    # Forced Power Cut Frames (From U(i10) & u0() in U.java)
    'force_cut_on':       bytes([0xFF, 0x00, 0x00, 0x2E, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x2E (reg 305/306) val 0
    'force_cut_off':      bytes([0xFF, 0x01, 0x00, 0x2E, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x2E (reg 305/306) val 1
    'force_cut_enable':   bytes([0xFF, 0x01, 0x00, 0x28, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x28 (reg 205) val 1
    'force_cut_disable':  bytes([0xFF, 0x00, 0x00, 0x28, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x28 (reg 205) val 0
    'force_cut_30m':      bytes([0xFF, 0x1E, 0x00, 0x2A, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x2A (reg 206) val 30 (0x1E)
    'force_cut_60m':      bytes([0xFF, 0x3C, 0x00, 0x2A, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x2A (reg 206) val 60 (0x3C)
    'force_cut_120m':     bytes([0xFF, 0x78, 0x00, 0x2A, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x2A (reg 206) val 120 (0x78)
    'force_cut_0m':       bytes([0xFF, 0x00, 0x00, 0x2A, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x2A (reg 206) val 0

    'holiday_mode_on':    bytes([0xFF, 0x01, 0x00, 0x24, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x24 (reg 201) val 1
    'holiday_mode_off':   bytes([0xFF, 0x00, 0x00, 0x24, 0x0C, 0x00, 0xFF, 0xFF]),  # cmd 0x24 (reg 201) val 0
}

# Corresponding ASCII fallback commands (for dual-protocol devices using ASCII UART)
INVERTER_ASCII_FALLBACK_COMMANDS: Dict[str, str] = {
    'inverter_on':        'VG094:1',
    'inverter_off':       'VG094:0',
    'eco_mode_on':        'VG185:1',
    'eco_mode_off':       'VG185:0',
    'bypass_on':          'VG100:1',
    'bypass_off':         'VG100:0',
    'ac_charge_on':       'VG099:1',
    'ac_charge_off':      'VG099:0',
    'backup_mode_on':     'VG072:1',
    'backup_mode_off':    'VG072:0',
    'extra_backup_on':    'VG072:1',
    'extra_backup_off':   'VG072:0',
    'appliance_mode_on':  'VG071:1',
    'appliance_mode_off': 'VG071:0',
    'force_cut_on':       'VG105:1',
    'force_cut_off':      'VG105:0',
    'force_cut_30m':      'VG037:30',
    'force_cut_60m':      'VG037:60',
    'force_cut_120m':     'VG037:120',
    'holiday_mode_on':    'VG035:1',
    'holiday_mode_off':   'VG035:0',
}

# Status bits from alarm_status (register 7) — from f0() in InverterDashboardViewModel
ALARM_STATUS_BITS = {
    'utility_fail':   1 << 0,   # bit 0: utility/grid failure (power cut)
    'battery_low':    1 << 1,   # bit 1: battery low
    'avr_active':     1 << 2,   # bit 2: AVR active
    'overload':       1 << 6,   # bit 6: overload
    'fan_fail':       1 << 7,   # bit 7: fan fail
    'battery_over_v': 1 << 8,   # bit 8: battery over voltage
    'inverter_fail':  1 << 9,   # bit 9: inverter fail
}


def build_inverter_write_cmd(cmd_id: int, val: int) -> bytes:
    """Build an 8-byte binary WRITE command frame for the inverter."""
    lo = val & 0xFF
    hi = (val >> 8) & 0xFF
    return bytes([0xFF, lo, hi, cmd_id, 0x0C, 0x00, 0xFF, 0xFF])



def build_inverter_read_cmd(register_id: int) -> Optional[bytes]:
    """Return the 8-byte READ command frame for a given register ID."""
    return INVERTER_CMD_BYTES.get(register_id)


def parse_inverter_response(frame: bytes) -> Optional[Tuple[int, int]]:
    """
    Parse an 8-byte inverter response frame.

    Response format (from BleCommunicationHelper.kt v1()):
      value = (byte[7] << 8) | byte[6]   →  little-endian at indices 6 & 7
      The register_id echoed back is at bytes[3] (the cmd byte of the read request).

    Returns (raw_value, cmd_byte) or None if frame is not 8 bytes.
    Partial frames should be accumulated by the caller.
    """
    if len(frame) != 8:
        return None
    # value = concat(hex(byte[7]), hex(byte[6])) parsed as int base-16
    # i.e., big-endian interpretation of [byte[7], byte[6]]
    raw_value = (frame[7] << 8) | frame[6]
    cmd_byte = frame[3]
    return raw_value, cmd_byte


# Build reverse map: cmd_byte -> register_id
_CMD_TO_REG: Dict[int, int] = {}
for _reg_id, _cmd_bytes in INVERTER_CMD_BYTES.items():
    _cmd = (_cmd_bytes[3] << 8) | _cmd_bytes[4]   # use bytes[3] and [4] as key
    _CMD_TO_REG[_cmd] = _reg_id


def lookup_register_by_cmd(cmd_byte3: int, cmd_byte4: int) -> Optional[int]:
    """Find register_id from the cmd byte pair (byte[3], byte[4]) in the frame."""
    return _CMD_TO_REG.get((cmd_byte3 << 8) | cmd_byte4)


def apply_scale(raw_value: int, register_id: int) -> float:
    """Apply the divisor scaling for a register to get its physical value."""
    info = INVERTER_REGISTER_MAP.get(register_id)
    if info is None:
        return float(raw_value)
    _, divisor, _ = info
    return raw_value / divisor if divisor != 1 else float(raw_value)
