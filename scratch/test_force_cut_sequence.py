import sys
import time
import os
sys.path.insert(0, os.path.abspath('.'))
from bluetooth_manager import BluetoothManager

class MockClient:
    def __init__(self):
        self.is_connected = True
    async def write_gatt_char(self, char_uuid, data, response=True):
        pass

def test_force_cut_sequence():
    bm = BluetoothManager()
    bm.connected = True
    bm.client = MockClient()
    bm._tx_char_uuid = "0000ffe1-0000-1000-8000-00805f9b34fb"
    bm._is_inverter_device = True
    
    print("--- Test 1: Send force_cut_30m ---")
    res30 = bm.send_inverter_command('force_cut_30m')
    print("Result:", res30)
    print("Telemetry:", bm._telemetry)
    assert res30['success'] is True
    assert len(res30['sequence_frames']) == 3
    assert bm._telemetry['forced_power_cut'] is True
    assert bm._telemetry['forced_power_cut_mins'] == 30
    assert bm._telemetry['utility_fail'] is True
    
    print("\n--- Test 2: Send force_cut_clear ---")
    res_clear = bm.send_inverter_command('force_cut_clear')
    print("Result:", res_clear)
    print("Telemetry:", bm._telemetry)
    assert res_clear['success'] is True
    assert len(res_clear['sequence_frames']) == 3
    assert bm._telemetry['forced_power_cut'] is False
    assert bm._telemetry['forced_power_cut_mins'] == 0
    assert bm._telemetry['utility_fail'] is False
    
    print("\nALL MULTI-FRAME FORCE CUT TESTS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_force_cut_sequence()
