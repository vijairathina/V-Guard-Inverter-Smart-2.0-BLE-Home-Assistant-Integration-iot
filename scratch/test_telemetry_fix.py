import sys
import os
import time

sys.path.insert(0, os.path.abspath('.'))

from bluetooth_manager import BluetoothManager

def test_telemetry_derivation():
    bm = BluetoothManager()
    
    # 1. Test App Startup (no reg 305 raw yet)
    bm._calculate_derived_inverter_telemetry()
    tel = bm.get_telemetry()
    print("1. Startup telemetry (unpolled):", {
        'forced_power_cut': tel.get('forced_power_cut'),
        'utility_fail': tel.get('utility_fail'),
        'ac_input_voltage': tel.get('ac_input_voltage'),
        'power_state': tel.get('power_state')
    })
    assert tel.get('forced_power_cut') is False, "Startup should default forced_power_cut to False"
    assert tel.get('utility_fail') is None, "Startup should leave utility_fail as None until hardware status is read"

    # 2. Test Physical Inverter Reg 305 = 0 (Forced Power Cut active on hardware)
    bm._handle_inverter_frame(bytes([0xFF, 0xFF, 0xFF, 0x2E, 0x0C, 0x01, 0x00, 0x00])) # reg 305, raw=0
    tel = bm.get_telemetry()
    print("2. Reg 305=0 telemetry (Forced Power Cut Active):", {
        'forced_power_cut': tel.get('forced_power_cut'),
        'utility_fail': tel.get('utility_fail'),
        'ac_input_voltage': tel.get('ac_input_voltage'),
    })
    assert tel.get('forced_power_cut') is True, "Reg 305=0 should set forced_power_cut to True"
    assert tel.get('utility_fail') is True, "Reg 305=0 should set utility_fail to True"

    # 3. Test Clearing Forced Cut via user action or Reg 305 = 1
    bm.send_inverter_command('force_cut_clear')
    tel = bm.get_telemetry()
    print("3. Clear force cut telemetry:", {
        'forced_power_cut': tel.get('forced_power_cut'),
        'utility_fail': tel.get('utility_fail'),
        'ac_input_voltage': tel.get('ac_input_voltage'),
        'power_state': tel.get('power_state')
    })
    assert tel.get('forced_power_cut') is False, "Cleared force cut should set forced_power_cut to False"
    assert tel.get('utility_fail') is False, "Cleared force cut should set utility_fail to False"
    assert tel.get('ac_input_voltage') == 206.2, "Cleared force cut should restore grid voltage"

    # 4. Test Hardware Reg 603 = 0 (Natural Grid Power Cut from electricity board) & Reg 305 = 1 (Force Cut Disabled)
    bm._force_cut_cleared_time = 0.0 # reset recently_cleared override
    bm._handle_inverter_frame(bytes([0xFF, 0xFF, 0xFF, 0x2E, 0x0C, 0x01, 0x01, 0x00])) # reg 305, raw=1
    bm._handle_inverter_frame(bytes([0xFF, 0xFF, 0xFF, 0x08, 0x0C, 0x01, 0x00, 0x00])) # reg 603 (ac_input_v), raw=0
    tel = bm.get_telemetry()
    print("4. Reg 603=0 telemetry (Natural Power Cut):", {
        'forced_power_cut': tel.get('forced_power_cut'),
        'utility_fail': tel.get('utility_fail'),
        'ac_input_voltage': tel.get('ac_input_voltage'),
    })
    assert tel.get('forced_power_cut') is False, "Natural power cut should leave forced_power_cut as False"
    assert tel.get('utility_fail') is True, "Natural power cut should set utility_fail to True"
    assert tel.get('ac_input_voltage') == 0.0, "Natural power cut should set ac_input_voltage to 0.0"

    print("\nALL TELEMETRY DERIVATION TESTS PASSED OK!")

if __name__ == '__main__':
    test_telemetry_derivation()
