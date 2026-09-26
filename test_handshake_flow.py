import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("flow")

from bleak import BleakClient

address = "48:F6:EE:F4:D1:76"
TX_CHAR = "0003cdd2-0000-1000-8000-00805f9b0131"
RX_CHAR = "0003cdd1-0000-1000-8000-00805f9b0131"

def notification_handler(sender, data):
    raw = bytes(data)
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = str(raw)
    logger.info(f"==> NOTIFICATION: hex={raw.hex()} repr={repr(text)}")

async def main():
    logger.info(f"Connecting to {address}...")
    async with BleakClient(address, timeout=15.0) as client:
        logger.info(f"Connected: {client.is_connected}")
        await client.start_notify(RX_CHAR, notification_handler)
        await client.start_notify(TX_CHAR, notification_handler)
        await asyncio.sleep(1.0)

        # 1. Send SN:
        sn_cmd = "SN:VG_SMART_BT_WF_2"
        logger.info(f"Sending: {sn_cmd}")
        await client.write_gatt_char(TX_CHAR, sn_cmd.encode("utf-8"), response=True)
        await asyncio.sleep(1.0)

        # 2. Send VG008 timestamp sync
        now_str = datetime.now().strftime("%Y%m%d%H%M%S")
        time_cmd = f"VG008:{now_str}"
        logger.info(f"Sending: {time_cmd}")
        await client.write_gatt_char(TX_CHAR, time_cmd.encode("utf-8"), response=True)
        await asyncio.sleep(1.0)

        # 3. Read telemetry VG codes
        cmds = ["read:VG092", "read:VG005", "read:VG003", "read:VG295", "read:VG273"]
        for cmd in cmds:
            logger.info(f"Sending: {cmd}")
            await client.write_gatt_char(TX_CHAR, cmd.encode("utf-8"), response=True)
            await asyncio.sleep(1.5)
            
            # Also poll read RX char
            rx_val = await client.read_gatt_char(RX_CHAR)
            logger.info(f"Read RX after {cmd}: hex={bytes(rx_val).hex()} text={repr(bytes(rx_val).decode('utf-8', errors='replace'))}")

asyncio.run(main())
