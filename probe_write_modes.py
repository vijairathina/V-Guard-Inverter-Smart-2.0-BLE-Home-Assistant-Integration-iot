"""
Test writing commands with response=False (WRITE_TYPE_NO_RESPONSE)
The Android app uses WRITE_TYPE_DEFAULT which ACKs, but WinRT may differ.
Also test writing directly to RX char (cdd1) instead of TX (cdd2).
Also test writing the MAC address format of SN: instead of device name.
"""
import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("probe2")

from bleak import BleakClient

ADDRESS = "48:F6:EE:F4:D1:76"
TX_CHAR  = "0003cdd2-0000-1000-8000-00805f9b0131"
RX_CHAR  = "0003cdd1-0000-1000-8000-00805f9b0131"

NOTIFS = []

def notify(sender, data):
    raw = bytes(data)
    try:
        text = raw.decode("utf-8", errors="replace").strip()
    except Exception:
        text = "??"
    logger.info(f"NOTIFY [{str(sender)[-8:]}] hex={raw.hex()} | text={repr(text)}")
    NOTIFS.append(raw.hex())

async def send_and_wait(client, char_uuid, cmd, response_mode, delay=2.0):
    logger.info(f"  WRITE (response={response_mode}): {repr(cmd)} -> {char_uuid[-8:]}")
    await client.write_gatt_char(char_uuid, cmd if isinstance(cmd, bytes) else cmd.encode(), response=response_mode)
    await asyncio.sleep(delay)

async def main():
    logger.info(f"Connecting to {ADDRESS}...")
    async with BleakClient(ADDRESS, timeout=15.0) as client:
        logger.info("Connected")
        await client.start_notify(RX_CHAR, notify)
        await client.start_notify(TX_CHAR, notify)
        await asyncio.sleep(1.0)

        # Full auth with response=True (known working for SN:)
        logger.info("=== Step 1: Auth handshake (response=True) ===")
        await send_and_wait(client, TX_CHAR, "SN:VG_SMART_BT_WF_2", True, 1.0)
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        await send_and_wait(client, TX_CHAR, f"VG008:{ts}", True, 1.0)

        logger.info(f"=== Step 2: read:VG005 with response=True ===")
        await send_and_wait(client, TX_CHAR, "read:VG005", True, 2.0)
        notifs_after = len(NOTIFS)

        logger.info(f"=== Step 3: read:VG005 with response=False ===")
        await send_and_wait(client, TX_CHAR, "read:VG005", False, 2.0)

        logger.info(f"=== Step 4: read:VG005 with newline ===")
        await send_and_wait(client, TX_CHAR, "read:VG005\r\n", True, 2.0)

        logger.info(f"=== Step 5: VG005 alone (no 'read:' prefix) ===")
        await send_and_wait(client, TX_CHAR, "VG005", True, 2.0)

        logger.info(f"=== Step 6: Try writing SN with MAC (no colons) ===")
        mac_no_colons = ADDRESS.replace(":", "")
        await send_and_wait(client, TX_CHAR, f"SN:{mac_no_colons}", True, 1.0)
        ts2 = datetime.now().strftime("%Y%m%d%H%M%S")
        await send_and_wait(client, TX_CHAR, f"VG008:{ts2}", True, 1.0)
        await send_and_wait(client, TX_CHAR, "read:VG005", True, 2.0)

        logger.info(f"=== Step 7: Try writing read:VG092 (power state, simpler) ===")
        await send_and_wait(client, TX_CHAR, "read:VG092", True, 2.0)
        await send_and_wait(client, TX_CHAR, "read:VG092", False, 2.0)

        logger.info(f"Total notifications received: {len(NOTIFS)}")
        logger.info(f"Notifications: {NOTIFS}")

asyncio.run(main())
