"""
Probe both GATT service pairs from BluetoothLeService.java:
  Service 1: 0003cdd0 (already tested, SN ack works)
  Service 2: 0000fee9 (NEW - from f17898I list in APK)

Also discover all services/chars and try subscribing to FEE9 chars.
"""
import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("probe")

from bleak import BleakClient

ADDRESS = "48:F6:EE:F4:D1:76"
# From BluetoothLeService.java
TX_CHAR_1 = "0003cdd2-0000-1000-8000-00805f9b0131"  # f17900K[0]
RX_CHAR_1 = "0003cdd1-0000-1000-8000-00805f9b0131"  # f17899J[0]
TX_CHAR_2 = "d44bc439-abfd-45a2-b575-925416129600"  # f17900K[1]
RX_CHAR_2 = "d44bc439-abfd-45a2-b575-925416129601"  # f17899J[1]

def notify(sender, data):
    raw = bytes(data)
    try:
        text = raw.decode("utf-8", errors="replace").strip()
    except Exception:
        text = "??"
    logger.info(f"NOTIFY [{str(sender)[-8:]}] hex={raw.hex()} | text={repr(text)}")

async def main():
    logger.info(f"Connecting to {ADDRESS}...")
    async with BleakClient(ADDRESS, timeout=15.0) as client:
        logger.info("Connected")

        # Dump ALL services and characteristics
        logger.info("=== ALL GATT SERVICES & CHARS ===")
        for svc in client.services:
            logger.info(f"SERVICE: {svc.uuid}")
            for ch in svc.characteristics:
                logger.info(f"  CHAR: {ch.uuid} props={ch.properties}")
                for desc in ch.descriptors:
                    logger.info(f"    DESC: {desc.uuid}")

        # Subscribe to all notify-capable chars
        logger.info("=== SUBSCRIBING TO ALL NOTIFIABLE CHARS ===")
        for svc in client.services:
            for ch in svc.characteristics:
                if "notify" in ch.properties or "indicate" in ch.properties:
                    try:
                        await client.start_notify(ch.uuid, notify)
                        logger.info(f"  Subscribed: {ch.uuid}")
                    except Exception as e:
                        logger.warning(f"  Cannot subscribe {ch.uuid}: {e}")
        await asyncio.sleep(1.0)

        # Now do the full auth on TX_CHAR_1
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        logger.info(f">> SN:VG_SMART_BT_WF_2")
        await client.write_gatt_char(TX_CHAR_1, b"SN:VG_SMART_BT_WF_2", response=True)
        await asyncio.sleep(1.0)

        logger.info(f">> VG008:{ts}")
        await client.write_gatt_char(TX_CHAR_1, f"VG008:{ts}".encode(), response=True)
        await asyncio.sleep(1.0)

        # Try writing to TX_CHAR_2 if it exists
        try:
            logger.info(">> Sending SN: to TX_CHAR_2")
            await client.write_gatt_char(TX_CHAR_2, b"SN:VG_SMART_BT_WF_2", response=True)
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.info(f"TX_CHAR_2 not available: {e}")

        # Send read:VG005 (voltage) on TX_CHAR_1 and wait
        logger.info(">> read:VG005 (voltage)")
        await client.write_gatt_char(TX_CHAR_1, b"read:VG005", response=True)
        await asyncio.sleep(3.0)

        # Try read_gatt_char on both RX chars
        for rx_uuid in [RX_CHAR_1, RX_CHAR_2]:
            try:
                val = await client.read_gatt_char(rx_uuid)
                logger.info(f"READ {rx_uuid[-8:]}: hex={bytes(val).hex()} text={repr(bytes(val).decode('utf-8', errors='replace'))}")
            except Exception as e:
                logger.info(f"READ {rx_uuid[-8:]} failed: {e}")

        logger.info("Waiting 5s for any notifications...")
        await asyncio.sleep(5.0)

asyncio.run(main())
