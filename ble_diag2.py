"""
BLE Diagnostic v2 - Focused on:
1. Does poll-reading RX char change after writing a command? (response via readable value, not notify)
2. Longer initial settle time (10s) before sending commands
3. Try command format variations
4. Check if 'services changed' is invalidating subscriptions

Run:  python ble_diag2.py
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
# Quieten bleak internals a bit so output is readable
logging.getLogger("bleak.backends.winrt.client").setLevel(logging.INFO)
logging.getLogger("bleak.backends.winrt").setLevel(logging.INFO)

DEVICE_ADDR = "48:F6:EE:F4:D1:76"
RX_UUID     = "0003cdd1-0000-1000-8000-00805f9b0131"   # notify + read (device→app)
TX_UUID     = "0003cdd2-0000-1000-8000-00805f9b0131"   # notify + write + read (app→device)

from bleak import BleakClient

notify_log = []

def notify_cb(sender, data: bytearray):
    raw = bytes(data)
    ts = time.strftime("%H:%M:%S.") + f"{int(time.time()*1000)%1000:03d}"
    try:
        text = raw.decode("utf-8")
        printable = sum(1 for c in text if c.isprintable()) / max(len(text), 1)
        logger.info(f"[{ts}][NOTIFY] sender={sender}  hex={raw.hex()}  pr={printable:.2f}  text={repr(text)}")
        notify_log.append({'hex': raw.hex(), 'text': text, 'ts': ts})
    except UnicodeDecodeError:
        logger.info(f"[{ts}][NOTIFY-BINARY] sender={sender}  hex={raw.hex()}")
        notify_log.append({'hex': raw.hex(), 'text': None, 'ts': ts})


async def poll_read(client, label, uuid):
    """Read a characteristic and return decoded text + raw hex."""
    try:
        val = await client.read_gatt_char(uuid)
        raw = bytes(val)
        try:
            text = raw.decode("utf-8", errors="replace").strip()
        except Exception:
            text = None
        logger.info(f"  poll_read [{label}] hex={raw.hex()}  text={repr(text)}")
        return raw, text
    except Exception as e:
        logger.warning(f"  poll_read [{label}] ERROR: {e}")
        return None, None


async def main():
    logger.info(f"Connecting to {DEVICE_ADDR}...")
    async with BleakClient(DEVICE_ADDR, timeout=30.0) as client:
        logger.info(f"Connected: {client.is_connected}")

        # ---- Phase 1: Subscribe to notifications ----
        logger.info("\n=== Subscribing to notifications ===")
        for svc in client.services:
            for ch in svc.characteristics:
                if "notify" in ch.properties or "indicate" in ch.properties:
                    try:
                        await client.start_notify(ch.uuid, notify_cb)
                        logger.info(f"  Subscribed: {ch.uuid}")
                    except Exception as e:
                        logger.warning(f"  Cannot subscribe {ch.uuid}: {e}")

        # ---- Phase 2: Settle time + baseline reads ----
        logger.info("\n=== Settling (10 seconds) — watching for spontaneous notifications ===")
        notify_log.clear()
        await asyncio.sleep(10.0)
        logger.info(f"Spontaneous notifications during settle: {len(notify_log)}")
        for n in notify_log:
            logger.info(f"  {n}")

        logger.info("\n=== Baseline poll-reads (before any commands) ===")
        rx_base, _ = await poll_read(client, "RX", RX_UUID)
        tx_base, _ = await poll_read(client, "TX", TX_UUID)

        # ---- Phase 3: Write then immediate poll-read ----
        logger.info("\n=== Write-then-poll-read test ===")
        test_cmds = [
            "read:VG092",
            "read:VG004",
            "read:VG005",
            "read:VG003",
        ]

        for cmd in test_cmds:
            payload = cmd.encode("utf-8")
            logger.info(f"\n--- Command: {repr(cmd)} ---")
            notify_log.clear()

            # Write with response
            try:
                await client.write_gatt_char(TX_UUID, payload, response=True)
                logger.info("  Write OK (with response)")
            except Exception as e:
                logger.warning(f"  Write failed: {e}")
                try:
                    await client.write_gatt_char(TX_UUID, payload, response=False)
                    logger.info("  Write OK (no response)")
                except Exception as e2:
                    logger.error(f"  Write completely failed: {e2}")
                    continue

            # Wait 3 seconds, checking every 200ms
            deadline = time.time() + 3.0
            while time.time() < deadline:
                await asyncio.sleep(0.2)
                if notify_log:
                    logger.info(f"  Got notification at {time.time() - (deadline-3.0):.2f}s: {notify_log[-1]}")

            # Poll-read both chars
            rx_after, rx_text = await poll_read(client, "RX-after", RX_UUID)
            tx_after, tx_text = await poll_read(client, "TX-after", TX_UUID)

            # Compare with baseline
            if rx_base and rx_after:
                changed = (rx_base != rx_after)
                logger.info(f"  RX changed: {changed}  (base={rx_base.hex()}, after={rx_after.hex()})")
            
            logger.info(f"  Notifications during this command: {len(notify_log)}")
            await asyncio.sleep(0.5)

        # ---- Phase 4: Try command format variations ----
        logger.info("\n=== Command format variations for VG092 ===")
        variants = [
            ("bare", b"VG092"),
            ("with-newline", b"read:VG092\n"),
            ("with-crlf", b"read:VG092\r\n"),
            ("uppercase", b"READ:VG092"),
            ("just-code", b"092"),
            ("question", b"VG092?"),
        ]

        for name, payload in variants:
            logger.info(f"\n--- Variant '{name}': {payload} ---")
            notify_log.clear()
            try:
                await client.write_gatt_char(TX_UUID, payload, response=True)
                logger.info("  Write OK")
            except Exception as e:
                logger.warning(f"  Write failed: {e}")
                try:
                    await client.write_gatt_char(TX_UUID, payload, response=False)
                    logger.info("  Write OK (no response)")
                except Exception as e2:
                    logger.error(f"  Write failed: {e2}")
                    continue

            await asyncio.sleep(3.0)
            rx_after, rx_text = await poll_read(client, "RX", RX_UUID)
            if rx_base and rx_after:
                logger.info(f"  RX changed: {rx_base != rx_after}  after={rx_after.hex()}")
            logger.info(f"  Notifications: {len(notify_log)} — {notify_log}")
            await asyncio.sleep(0.5)

        # ---- Phase 5: Write to RX instead of TX (reversed!) ----
        logger.info("\n=== Reversed: write to RX char (0003cdd1) ===")
        payload = b"read:VG092"
        notify_log.clear()
        try:
            # RX has 'write' property? Let's check
            rx_char = None
            for svc in client.services:
                for ch in svc.characteristics:
                    if ch.uuid == RX_UUID:
                        rx_char = ch
                        logger.info(f"RX char props: {ch.properties}")
            
            if rx_char and "write" in rx_char.properties:
                await client.write_gatt_char(RX_UUID, payload, response=True)
                logger.info("  Write to RX: OK")
                await asyncio.sleep(3.0)
                await poll_read(client, "TX-after-RX-write", TX_UUID)
            else:
                logger.info("  RX char has no 'write' property, skipping")
        except Exception as e:
            logger.error(f"  Write to RX error: {e}")

        logger.info(f"\nAll notifications received: {len(notify_log)}")
        logger.info("\nDone.")


asyncio.run(main())
