"""
Test script for V-Guard Smart 2.0 Bluetooth connection
This script demonstrates real device communication
"""

import logging
from bluetooth_manager import BluetoothManager, BLUETOOTH_AVAILABLE

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main test function"""
    
    logger.info("=" * 60)
    logger.info("V-Guard Smart 2.0 Bluetooth Test Script")
    logger.info("=" * 60)
    
    # Check Bluetooth availability
    if not BLUETOOTH_AVAILABLE:
        logger.error("❌ Bleak not available! Install with: pip install bleak")
        logger.info("This script requires real Bluetooth hardware.")
        return
    
    logger.info("✓ Bleak is available - Real Bluetooth support enabled")
    
    # Create manager
    bt_manager = BluetoothManager()
    
    # Test 1: Scan for devices
    logger.info("\n[TEST 1] Scanning for Bluetooth devices...")
    logger.info("Scanning for 10 seconds...")
    
    devices = bt_manager.scan_devices(duration=10)
    
    logger.info(f"✓ Found {len(devices)} devices:")
    for device in devices:
        logger.info(f"  - {device['name']} ({device['address']})")
    
    # Test 2: Connect to first V-Guard device
    vguard_devices = [
        d for d in devices 
        if 'vguard' in d['name'].lower() 
        or 'v-guard' in d['name'].lower()
        or d['name'].lower().startswith('vg_')
        or 'vg_smart' in d['name'].lower()
    ]
    
    if not vguard_devices:
        logger.warning("\n⚠ No V-Guard devices found in scan.")
        logger.info("You can still test the connection manually by entering a device address.")
        
        user_input = input("\nEnter Bluetooth address to test (or 'skip'): ").strip()
        if user_input.lower() == 'skip':
            logger.info("Test skipped.")
            return
        
        device_address = user_input
        device_name = f"Device {device_address}"
    else:
        device = vguard_devices[0]
        device_address = device['address']
        device_name = device['name']
    
    logger.info(f"\n[TEST 2] Connecting to {device_name} ({device_address})...")
    
    success, message = bt_manager.connect(device_address)
    
    if success:
        logger.info(f"✓ {message}")
    else:
        logger.error(f"✗ {message}")
        logger.info("Connection failed. Possible reasons:")
        logger.info("  - Device is not powered on")
        logger.info("  - Device is not in range")
        logger.info("  - Device doesn't support RFCOMM")
        logger.info("  - Device is already connected to another device")
        return
    
    # Test 3: Get device info
    logger.info("\n[TEST 3] Requesting device information...")
    
    info = bt_manager.get_device_info()
    
    if 'error' not in info:
        logger.info("✓ Device Info:")
        for key, value in info.items():
            if key not in ['status_response']:
                logger.info(f"  {key}: {value}")
    else:
        logger.warning(f"⚠ Could not get device info: {info['error']}")
    
    # Test 4: Send commands
    logger.info("\n[TEST 4] Testing commands...")
    
    commands_to_test = [
        ('status', {}),
        ('power', {'state': 'on'}),
        ('sensitivity', {'level': 5}),
    ]
    
    for cmd, params in commands_to_test:
        logger.info(f"  Sending '{cmd}' command...")
        response = bt_manager.send_command(cmd, params, wait_response=True)
        if response.get('success'):
            logger.info(f"  ✓ {cmd}: {response}")
        else:
            logger.warning(f"  ⚠ {cmd}: {response.get('error')}")
    
    # Test 5: Disconnect
    logger.info("\n[TEST 5] Disconnecting...")
    
    success, message = bt_manager.disconnect()
    
    if success:
        logger.info(f"✓ {message}")
    else:
        logger.error(f"✗ {message}")
    
    logger.info("\n" + "=" * 60)
    logger.info("Test Complete!")
    logger.info("=" * 60)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\nTest interrupted by user.")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
