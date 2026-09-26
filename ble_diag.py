"""
Direct BLE diagnostic — bypasses Flask to see raw device responses.
Tests both notify and poll-read, and tries both write-with-response and write-without-response.
Run with:  python ble_diag.py

Key observations from V-Guard Smart 2.0 protocol:
  - Commands: send "read:VGxxx" (UTF-8, no newline) to TX char (0003cdd2)
  - Responses: device sends "VGxxx:value" via BLE notification on RX char (0003cdd1)
  - Fragmented responses: 20-byte chunks ending with "@"; final chunk has no "@"
  - Binary notifications (4-8 bytes with control chars) are device keep-alives, skip them
"""
import asyncio
import logging
import sys
import time

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger()

DEVICE_ADDR  = "48:F6:EE:F4:D1:76"
SERVICE_UUID = "0003cdd0-0000-1000-8000-00805f9b0131"
RX_UUID      = "0003cdd1-0000-1000-8000-00805f9b0131"   # notify  (device→app)
TX_UUID      = "0003cdd2-0000-1000-8000-00805f9b0131"   # write   (app→device)

from bleak import BleakClient, BleakScanner

received = []
rx_buffer = ""

def notify_cb(sender, data: bytearray):
    global rx_buffer
    raw = bytes(data)
    ts = time.strftime("%H:%M:%S")

    # Detect binary vs ASCII
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        logger.info(f"[{ts}][NOTIFY-BINARY] sender={sender} hex={raw.hex()} len={len(raw)}")
        return

    # Check printability
    printable_ratio = sum(1 for c in text if c.isprintable()) / max(len(text), 1)
    logger.info(f"[{ts}][NOTIFY-ASCII] sender={sender} hex={raw.hex()} printable={printable_ratio:.2f} text={repr(text)}")

    if printable_ratio < 0.7:
        logger.info(f"[{ts}][NOTIFY-SKIP] Low printable ratio — likely binary keep-alive")
        return

    # Handle "@"-fragmentation (per APK: 20-byte chunks, "@" at position ≥6)
    if len(text) == 20 and text.endswith("@"):
        at_pos = text.rfind("@", 6)
        if at_pos != -1:
            text = text[:at_pos]
        rx_buffer += text
        logger.info(f"[{ts}][FRAGMENT] Accumulated buffer: {repr(rx_buffer)}")
        return

    # Final/complete chunk
    full_text = rx_buffer + text
    rx_buffer = ""
    logger.info(f"[{ts}][COMPLETE] Full text: {repr(full_text)}")
    received.append(full_text)


async def main():
    logger.info(f"Connecting to {DEVICE_ADDR}...")
    async with BleakClient(DEVICE_ADDR, timeout=20.0) as client:
        logger.info(f"Connected: {client.is_connected}")

        # Log all services + characteristics
        logger.info("\n=== GATT Services ===")
        for svc in client.services:
            logger.info(f"Service: {svc.uuid}  ({svc.description})")
            for ch in svc.characteristics:
                props = ", ".join(ch.properties)
                desc = ch.description or ""
                logger.info(f"  Char: {ch.uuid}  props=[{props}]  desc={desc}")
                for d in ch.descriptors:
                    logger.info(f"    Desc: {d.uuid}  handle={d.handle}")

        logger.info("\n=== Subscribing to notifications ===")

        # Subscribe to all chars that support notify
        subscribed = []
        for svc in client.services:
            for ch in svc.characteristics:
                if "notify" in ch.properties or "indicate" in ch.properties:
                    try:
                        await client.start_notify(ch.uuid, notify_cb)
                        logger.info(f"Subscribed: {ch.uuid}")
                        subscribed.append(ch.uuid)
                    except Exception as e:
                        logger.warning(f"Cannot subscribe {ch.uuid}: {e}")

        logger.info(f"Subscribed to {len(subscribed)} characteristic(s)")
        await asyncio.sleep(1.5)   # let subscriptions settle

        logger.info("\n=== Testing VG commands ===")
        test_cmds = [
            "read:VG092",   # power on/off state
            "read:VG005",   # voltage
            "read:VG003",   # current
            "read:VG273",   # temperature/voltage
            "read:VG295",   # active power
            "read:VG192",   # energy (kWh)
            "read:VG004",   # firmware
            "read:VG030",   # model
        ]

        for cmd in test_cmds:
            payload = cmd.encode("utf-8")
            logger.info(f"\n{'='*60}")
            logger.info(f"Sending: {repr(cmd)} (hex={payload.hex()})")
            received.clear()
            ts_send = time.time()

            # Try write WITH response first
            try:
                await client.write_gatt_char(TX_UUID, payload, response=True)
                logger.info("Write (with response): OK")
            except Exception as e:
                logger.warning(f"Write (with response) failed: {e}")
                try:
                    await client.write_gatt_char(TX_UUID, payload, response=False)
                    logger.info("Write (no response): OK")
                except Exception as e2:
                    logger.error(f"Write (no response) also failed: {e2}")
                    continue

            # Wait up to 5 seconds for the response
            wait_until = ts_send + 5.0
            while time.time() < wait_until:
                await asyncio.sleep(0.2)
                # Check if we got a matching VG response
                vg_code = cmd[5:].upper()  # "read:VG092" -> "VG092"
                for r in received:
                    if r.upper().startswith(f"{vg_code}:"):
                        logger.info(f"✓ Got response: {repr(r)}")
                        break
                else:
                    continue
                break
            else:
                if received:
                    logger.info(f"Received (no exact match): {received}")
                else:
                    logger.warning(f"No response received for {cmd} within 5s")

            logger.info(f"Total notifications: {len(received)}, elapsed: {time.time()-ts_send:.2f}s")
            await asyncio.sleep(0.5)  # gap between commands

        logger.info("\n=== Ambient notifications (5s passthrough) ===")
        logger.info("Just listening — any spontaneous notifications from device:")
        received.clear()
        await asyncio.sleep(5.0)
        if received:
            logger.info(f"Ambient: {received}")
        else:
            logger.info("No ambient notifications")

        logger.info("\nDone. Disconnecting.")


asyncio.run(main())
