"""
Test script: Connect to V-Guard Inverter via BLE and verify data reception.

Usage:
    python test_inverter_bt.py [--address XX:XX:XX:XX:XX:XX] [--scan]

If --address not provided, will scan for 8 seconds and list found devices.
"""

import asyncio
import sys
import time
import argparse
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-7s %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('inverter_test.log', mode='w', encoding='utf-8'),
    ]
)
logger = logging.getLogger('inverter_test')


def parse_args():
    p = argparse.ArgumentParser(description='Test V-Guard Inverter BLE connection')
    p.add_argument('--address', '-a', default=None, help='BLE MAC address of inverter')
    p.add_argument('--scan', '-s', action='store_true', help='Scan for BLE devices first')
    p.add_argument('--duration', '-d', type=int, default=30, help='How many seconds to collect data (default 30)')
    return p.parse_args()


def main():
    args = parse_args()

    from bluetooth_manager import BluetoothManager
    from inverter_protocol import (
        INVERTER_DASHBOARD_POLL,
        INVERTER_CMD_BYTES,
        INVERTER_REGISTER_MAP,
    )

    bt = BluetoothManager()

    # ── Step 1: Scan or use provided address ──
    if args.scan or not args.address:
        print("\n[SCAN] Scanning for BLE devices (10 seconds)...")
        devices = bt.scan_devices(duration=10)
        if not devices:
            print("[SCAN] No devices found.")
            sys.exit(1)

        # Sort by RSSI descending (strongest first)
        devices_sorted = sorted(devices, key=lambda d: d.get('rssi', -999), reverse=True)

        print(f"\n[SCAN] Found {len(devices_sorted)} device(s) — sorted by signal strength:\n")
        for i, d in enumerate(devices_sorted):
            rssi = d.get('rssi', '?')
            name = d['name']
            addr = d['address']
            # Highlight V-Guard devices
            tag = "  << V-Guard Smart Plug" if 'VG_SMART' in name.upper() else ""
            tag = "  << LIKELY INVERTER" if name.startswith('Unknown') and rssi != '?' and rssi > -70 else tag
            print(f"  [{i}] {name:<40} addr={addr}  rssi={rssi:>4} dBm{tag}")
        print()
        print("  TIP: The V-Guard inverter may appear as 'Unknown' with a strong signal.")
        print("       If the first connection fails with 'Unreachable', try another device.\n")

        if args.address:
            address = args.address
        else:
            try:
                idx = int(input("Enter device index to connect: ").strip())
                address = devices_sorted[idx]['address']
            except (ValueError, IndexError, KeyboardInterrupt):
                print("Aborted.")
                sys.exit(1)
    else:
        address = args.address

    print(f"\n[CONNECT] Connecting to {address}...")
    ok, msg = bt.connect(address)
    print(f"[CONNECT] {'OK' if ok else 'FAILED'}: {msg}")
    if not ok:
        sys.exit(1)

    is_inverter = bt._is_inverter_device
    print(f"[INFO] Device type: {'INVERTER (binary protocol)' if is_inverter else 'SMART PLUG (ASCII protocol)'}")

    if not is_inverter:
        print("\n[WARN] Device detected as SMART PLUG, not inverter.")
        print("       If you know this is an inverter, the device name may not match")
        print("       the expected patterns (INV, VGI, SYNERGY, etc.).")
        print("       Forcing inverter mode for testing...\n")
        bt._is_inverter_device = True

    # ── Step 2: Send all dashboard poll commands and collect data ──
    print(f"\n[POLL] Sending {len(INVERTER_DASHBOARD_POLL)} dashboard read commands...")
    for reg_id in INVERTER_DASHBOARD_POLL:
        cmd = INVERTER_CMD_BYTES.get(reg_id)
        if cmd is None:
            continue
        reg_info = INVERTER_REGISTER_MAP.get(reg_id, ('unknown', 1, ''))
        field_name, _, unit = reg_info
        print(f"  >> reg={reg_id:4d} field={field_name:<20} cmd={cmd.hex()}", end='  ', flush=True)
        ok = bt.send_raw_bytes(cmd)
        if ok:
            # Wait up to 2 seconds for notification
            bt._notify_event.clear()
            got = bt._notify_event.wait(timeout=2.0)
            time.sleep(0.3)
            val = bt.get_telemetry().get(field_name)
            print(f"val={val}")
        else:
            print("WRITE FAILED")

    # ── Step 3: Monitor for incoming data for N seconds ──
    print(f"\n[MONITOR] Monitoring for {args.duration}s — press Ctrl+C to stop early...\n")
    deadline = time.time() + args.duration
    last_print = 0
    try:
        while time.time() < deadline:
            bt._notify_event.clear()
            bt._notify_event.wait(timeout=1.0)
            now = time.time()
            if now - last_print >= 2.0:
                last_print = now
                tel = bt.get_telemetry()
                print(f"[{time.strftime('%H:%M:%S')}] Telemetry snapshot:")
                for k, v in sorted(tel.items()):
                    if v is not None and k != 'raw_responses':
                        print(f"    {k:<30} = {v}")
                raws = tel.get('raw_responses', [])
                if raws:
                    print(f"    raw_responses[-3:] = {raws[-3:]}")
                print()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted.")

    # ── Step 4: Final report ──
    tel = bt.get_telemetry()
    print("\n[RESULT] Final telemetry:")
    received_fields = 0
    for k, v in sorted(tel.items()):
        if v is not None and k != 'raw_responses':
            print(f"  {k:<35} = {v}")
            received_fields += 1

    raws = tel.get('raw_responses', [])
    print(f"\n[RESULT] raw_responses count: {len(raws)}")
    for r in raws[-10:]:
        print(f"  {r}")

    if received_fields == 0:
        print("\n[FAIL] No telemetry data received from inverter.")
        print("       Check:")
        print("       1. BLE device is powered on and within range")
        print("       2. Device name matches inverter pattern (INV/VGI/SYNERGY)")
        print("       3. Correct TX/RX characteristics were selected (see log)")
        print("       4. Check inverter_test.log for detailed BLE logs")
    else:
        print(f"\n[PASS] Received data in {received_fields} field(s). BLE inverter communication working!")

    bt.disconnect()
    print("[INFO] Disconnected.")


if __name__ == '__main__':
    main()
