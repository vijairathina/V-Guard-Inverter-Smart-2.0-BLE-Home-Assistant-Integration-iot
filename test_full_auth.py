"""
Test the full V-Guard handshake as seen in C1034h0.java line 194:
  SN:VG_SMART_BT_WF_2
  VG008:YYYYMMDDHHMMSS
  read:VG012
  read:VG136
  read:VG132
Then poll the main telemetry registers.
"""
import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("vg_test")

from bleak import BleakClient

ADDRESS  = "48:F6:EE:F4:D1:76"
TX_CHAR  = "0003cdd2-0000-1000-8000-00805f9b0131"
RX_CHAR  = "0003cdd1-0000-1000-8000-00805f9b0131"

def notify(sender, data):
    raw = bytes(data)
    try:
        text = raw.decode("utf-8", errors="replace").strip()
    except Exception:
        text = "??"
    logger.info(f"NOTIFY [{str(sender)[-4:]}] hex={raw.hex()} | text={repr(text)}")

async def send(client, cmd, delay=0.8):
    logger.info(f"  >> SEND: {cmd}")
    await client.write_gatt_char(TX_CHAR, cmd.encode("utf-8"), response=True)
    await asyncio.sleep(delay)

async def main():
    logger.info(f"Connecting to {ADDRESS}...")
    async with BleakClient(ADDRESS, timeout=15.0) as client:
        logger.info("Connected")
        await client.start_notify(RX_CHAR, notify)
        await client.start_notify(TX_CHAR, notify)
        await asyncio.sleep(1.0)

        # Step 1: SN handshake
        await send(client, "SN:VG_SMART_BT_WF_2", delay=1.0)

        # Step 2: VG008 timestamp sync
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        await send(client, f"VG008:{ts}", delay=1.0)

        # Step 3: Auth-completion reads (from C1034h0.java line 194)
        await send(client, "read:VG012", delay=1.5)
        await send(client, "read:VG136", delay=1.5)
        await send(client, "read:VG132", delay=1.5)

        logger.info("=== Auth sequence done. Now polling telemetry ===")

        # Step 4: Main telemetry reads (from C2337b.B() — Smart Plug full batch)
        for cmd in [
            "read:VG092",  # power state
            "read:VG094",  # switch/relay state
            "read:VG273",  # temperature
            "read:VG295",  # power W
            "read:VG005",  # voltage V
            "read:VG003",  # current A
            "read:VG302",  # ?
            "read:VG192",  # energy kWh
        ]:
            await send(client, cmd, delay=2.0)

        logger.info("Done. Waiting for any final notifications...")
        await asyncio.sleep(3.0)

asyncio.run(main())
