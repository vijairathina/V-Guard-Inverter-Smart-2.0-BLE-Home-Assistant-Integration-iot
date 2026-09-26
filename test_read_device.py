import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("test_read")

from bleak import BleakClient

DEVICE_ADDR = "48:F6:EE:F4:D1:76"
RX_UUID = "0003cdd1-0000-1000-8000-00805f9b0131"
TX_UUID = "0003cdd2-0000-1000-8000-00805f9b0131"

def notification_callback(sender, data: bytearray):
    raw = bytes(data)
    logger.info(f"==> NOTIFICATION from {sender}: hex={raw.hex()} repr={repr(raw)}")

async def main():
    logger.info(f"Connecting to {DEVICE_ADDR}...")
    async with BleakClient(DEVICE_ADDR, timeout=20.0) as client:
        logger.info(f"Connected: {client.is_connected}")

        # Subscribe to notifications
        try:
            await client.start_notify(RX_UUID, notification_callback)
            logger.info(f"Subscribed to RX {RX_UUID}")
        except Exception as e:
            logger.error(f"Cannot subscribe RX: {e}")

        try:
            await client.start_notify(TX_UUID, notification_callback)
            logger.info(f"Subscribed to TX {TX_UUID}")
        except Exception as e:
            logger.error(f"Cannot subscribe TX: {e}")

        await asyncio.sleep(1.0)

        # Test 1: Write read:VG092 with response=False
        cmd = b"read:VG092"
        logger.info(f"\n--- TEST 1: Write response=False : {cmd} ---")
        await client.write_gatt_char(TX_UUID, cmd, response=False)
        await asyncio.sleep(2.0)
        
        rx_val = await client.read_gatt_char(RX_UUID)
        logger.info(f"Read RX after test 1: hex={rx_val.hex()} repr={repr(rx_val)}")

        # Test 2: Write read:VG092 with response=True
        logger.info(f"\n--- TEST 2: Write response=True : {cmd} ---")
        await client.write_gatt_char(TX_UUID, cmd, response=True)
        await asyncio.sleep(2.0)

        rx_val = await client.read_gatt_char(RX_UUID)
        logger.info(f"Read RX after test 2: hex={rx_val.hex()} repr={repr(rx_val)}")

        # Test 3: Write read:VG005 (voltage) with response=False
        cmd2 = b"read:VG005"
        logger.info(f"\n--- TEST 3: Write response=False : {cmd2} ---")
        await client.write_gatt_char(TX_UUID, cmd2, response=False)
        await asyncio.sleep(2.0)

        rx_val = await client.read_gatt_char(RX_UUID)
        logger.info(f"Read RX after test 3: hex={rx_val.hex()} repr={repr(rx_val)}")

        # Test 4: Write to RX characteristic instead of TX
        logger.info(f"\n--- TEST 4: Write to RX char : {cmd2} ---")
        try:
            await client.write_gatt_char(RX_UUID, cmd2, response=False)
            logger.info("Wrote to RX OK")
            await asyncio.sleep(2.0)
            rx_val = await client.read_gatt_char(RX_UUID)
            logger.info(f"Read RX after test 4: hex={rx_val.hex()} repr={repr(rx_val)}")
        except Exception as e:
            logger.warning(f"Write to RX failed: {e}")

asyncio.run(main())
