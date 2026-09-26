#!/usr/bin/env python
"""
V-Guard Smart 2.0 Command Line Interface
Direct Bluetooth device control without web interface
"""

import sys
import argparse
import logging
from bluetooth_manager import BluetoothManager, BLUETOOTH_AVAILABLE
import time

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class VGuardCLI:
    """Command Line Interface for V-Guard device control"""
    
    def __init__(self):
        self.bt_manager = BluetoothManager()
        self.device_address = None
        self.connected = False
    
    def scan(self, duration: int = 10):
        """Scan for available V-Guard devices"""
        logger.info(f"Scanning for devices ({duration} seconds)...")
        
        devices = self.bt_manager.scan_devices(duration=duration)
        
        if not devices:
            logger.warning("No devices found")
            return
        
        logger.info(f"Found {len(devices)} devices:\n")
        for idx, device in enumerate(devices, 1):
            is_vguard = ('vguard' in device['name'].lower() 
                         or 'v-guard' in device['name'].lower()
                         or device['name'].lower().startswith('vg_')
                         or 'vg_smart' in device['name'].lower())
            marker = "📱" if is_vguard else "🔵"
            print(f"{idx}. {marker} {device['name']}")
            print(f"   Address: {device['address']}")
            if 'rssi' in device:
                print(f"   Signal: {device['rssi']} dBm")
            print()
    
    def connect(self, address: str, port: int = None):
        """Connect to a device"""
        logger.info(f"Connecting to {address}...")
        
        success, message = self.bt_manager.connect(address, port)
        
        if success:
            logger.info(f"✓ {message}")
            self.device_address = address
            self.connected = True
        else:
            logger.error(f"✗ {message}")
        
        return success
    
    def disconnect(self):
        """Disconnect from device"""
        logger.info("Disconnecting...")
        
        success, message = self.bt_manager.disconnect()
        
        if success:
            logger.info(f"✓ {message}")
            self.connected = False
        else:
            logger.error(f"✗ {message}")
        
        return success
    
    def send_command(self, command: str, **params):
        """Send command to device"""
        if not self.connected:
            logger.error("Not connected to device. Use 'connect' first.")
            return False
        
        logger.info(f"Sending command: {command} {params}")
        
        response = self.bt_manager.send_command(command, params, wait_response=True)
        
        if response.get('success'):
            logger.info(f"✓ Command sent successfully")
            logger.info(f"Response: {response}")
        else:
            logger.error(f"✗ Command failed: {response.get('error')}")
        
        return response.get('success', False)
    
    def status(self):
        """Get device status"""
        if not self.connected:
            logger.error("Not connected to device")
            return
        
        logger.info("Getting device status...")
        
        info = self.bt_manager.get_device_info()
        
        if 'error' not in info:
            logger.info("Device Status:")
            for key, value in info.items():
                if key not in ['status_response', 'device_info']:
                    print(f"  {key}: {value}")
        else:
            logger.error(f"Failed to get status: {info['error']}")
    
    def power(self, state: str):
        """Control device power"""
        if state.lower() not in ['on', 'off']:
            logger.error("State must be 'on' or 'off'")
            return
        
        self.send_command('power', state=state)
    
    def sensitivity(self, level: int):
        """Adjust sensitivity"""
        if not 1 <= level <= 10:
            logger.error("Sensitivity level must be between 1 and 10")
            return
        
        self.send_command('sensitivity', level=level)
    
    def mode(self, mode: str):
        """Set device mode"""
        valid_modes = ['auto', 'manual', 'sleep', 'alert']
        if mode.lower() not in valid_modes:
            logger.error(f"Mode must be one of: {', '.join(valid_modes)}")
            return
        
        self.send_command('mode', mode=mode)
    
    def raw_send(self, hex_data: str):
        """Send raw hex data"""
        try:
            data = bytes.fromhex(hex_data.replace(' ', ''))
            success = self.bt_manager.send_raw_data(data)
            if success:
                logger.info(f"✓ Sent {len(data)} bytes")
            else:
                logger.error("Failed to send data")
        except ValueError:
            logger.error("Invalid hex format")
    
    def raw_recv(self, timeout: float = 1.0):
        """Receive raw data"""
        logger.info(f"Listening for {timeout} seconds...")
        
        data = self.bt_manager.receive_raw_data(timeout=timeout)
        
        if data:
            logger.info(f"✓ Received {len(data)} bytes: {data.hex()}")
        else:
            logger.warning("No data received")


def main():
    """Main CLI function"""
    parser = argparse.ArgumentParser(
        description='V-Guard Smart 2.0 Bluetooth Control',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Scan for devices
  python cli.py scan
  
  # Connect to device
  python cli.py connect 00:1A:7D:DA:71:13
  
  # Send commands
  python cli.py power on
  python cli.py sensitivity 7
  python cli.py mode manual
  python cli.py status
  
  # Send raw data
  python cli.py raw-send "AA BB 01 01 00"
  python cli.py raw-recv --timeout 2
        '''
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Scan command
    subparsers.add_parser('scan', help='Scan for V-Guard devices')
    
    # Connect command
    connect_parser = subparsers.add_parser('connect', help='Connect to device')
    connect_parser.add_argument('address', help='Device Bluetooth address (MAC)')
    connect_parser.add_argument('--port', type=int, help='RFCOMM port (auto-detect if not specified)')
    
    # Disconnect command
    subparsers.add_parser('disconnect', help='Disconnect from device')
    
    # Status command
    subparsers.add_parser('status', help='Get device status')
    
    # Power command
    power_parser = subparsers.add_parser('power', help='Control device power')
    power_parser.add_argument('state', choices=['on', 'off'], help='Power state')
    
    # Sensitivity command
    sensitivity_parser = subparsers.add_parser('sensitivity', help='Adjust sensitivity')
    sensitivity_parser.add_argument('level', type=int, choices=range(1, 11), help='Sensitivity level (1-10)')
    
    # Mode command
    mode_parser = subparsers.add_parser('mode', help='Set device mode')
    mode_parser.add_argument('mode', choices=['auto', 'manual', 'sleep', 'alert'], help='Device mode')
    
    # Raw send command
    raw_send_parser = subparsers.add_parser('raw-send', help='Send raw hex data')
    raw_send_parser.add_argument('data', help='Hex data to send (space-separated)')
    
    # Raw receive command
    raw_recv_parser = subparsers.add_parser('raw-recv', help='Receive raw data')
    raw_recv_parser.add_argument('--timeout', type=float, default=1.0, help='Receive timeout in seconds')
    
    args = parser.parse_args()
    
    # Check Bluetooth
    if not BLUETOOTH_AVAILABLE:
        logger.error("❌ Bleak not available. Install with: pip install bleak")
        sys.exit(1)
    
    logger.info("✓ Bluetooth support enabled")
    
    if not args.command:
        parser.print_help()
        sys.exit(0)
    
    cli = VGuardCLI()
    
    try:
        # Execute command
        if args.command == 'scan':
            cli.scan()
        
        elif args.command == 'connect':
            cli.connect(args.address, args.port)
        
        elif args.command == 'disconnect':
            cli.disconnect()
        
        elif args.command == 'status':
            cli.status()
        
        elif args.command == 'power':
            cli.power(args.state)
        
        elif args.command == 'sensitivity':
            cli.sensitivity(args.level)
        
        elif args.command == 'mode':
            cli.mode(args.mode)
        
        elif args.command == 'raw-send':
            cli.raw_send(args.data)
        
        elif args.command == 'raw-recv':
            cli.raw_recv(args.timeout)
    
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
