import asyncio
import logging
import sys
from bleak import BleakClient

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

address = "48:F6:EE:F4:D1:76"
TX_CHAR = "0003cdd2-0000-1000-8000-00805f9b0131"
RX_CHAR = "0003cdd1-0000-1000-8000-00805f9b0131"

received = []

def notification_handler(sender, data):
    text = bytes(data).decode("utf-8", errors="replace")
    logger.info(f"Notify: hex={data.hex()} text={repr(text)}")
    received.append(text)

async def test_sn(sn_value):
    logger.info(f"\n================ Testing SN: {sn_value} ================")
    received.clear()
    try:
        async with BleakClient(address, timeout=10.0) as client:
            logger.info(f"Connected to {address}")
            await client.start_notify(RX_CHAR, notification_handler)
            await client.start_notify(TX_CHAR, notification_handler)
            
            payload = f"SN:{sn_value}".encode("utf-8")
            logger.info(f"Sending write: {payload}")
            await client.write_gatt_char(TX_CHAR, payload, response=True)
            
            # Wait for response
            for _ in range(10):
                await asyncio.sleep(0.5)
                if received:
                    break
            
            if received:
                logger.info(f"Received response: {received}")
                # Try sending a read command to see if it works now!
                payload_read = "read:VG092".encode("utf-8")
                await client.write_gatt_char(TX_CHAR, payload_read, response=True)
                await asyncio.sleep(2.0)
                logger.info(f"After read:VG092, received: {received}")
            else:
                logger.info("No response received.")
                
            await client.stop_notify(RX_CHAR)
            await client.stop_notify(TX_CHAR)
    except Exception as e:
        logger.error(f"Error during test: {e}")

async def main():
    # Test different SN options
    for sn in ["VG_SMART_BT_WF_2", "48F6EEF4D176", "48:F6:EE:F4:D1:76", "1234567890", ""]:
        await test_sn(sn)
        await asyncio.sleep(2.0)

if __name__ == "__main__":
    asyncio.run(main())
