import asyncio
import logging
from bleak import BleakClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEVICE_ADDRESS = "48:F6:EE:F4:D1:76"
CHAR_DATA_READ = "0003cdd1-0000-1000-8000-00805f9b0131"
CHAR_DATA_WRITE = "0003cdd2-0000-1000-8000-00805f9b0131"

def notification_handler(sender: int, data: bytearray):
    hex_string = "-".join(f"{b:02X}" for b in data)
    print(f"[Data Stream] (0x) {hex_string}")

async def main():
    logger.info(f"Connecting to device: {DEVICE_ADDRESS}...")
    
    async with BleakClient(DEVICE_ADDRESS, timeout=15.0) as client:
        if client.is_connected:
            logger.info(f"Successfully connected to {DEVICE_ADDRESS}")
            await asyncio.sleep(1.0)
            
            # Step 1: Subscribe to data channel
            logger.info(f"Subscribing to data characteristic: {CHAR_DATA_READ}")
            try:
                await client.start_notify(CHAR_DATA_READ, notification_handler)
                logger.info("Subscription operational!")
            except Exception as e:
                logger.error(f"Subscription failed: {e}")
                return
            
            await asyncio.sleep(0.5)
            
            # Step 2: Send a kick-start poll command to the write channel
            # We use an empty status flag array which often tells the MCU to dump its current cache
            logger.info("Sending stream kick-start command...")
            # TRY OPTION 1 FIRST:
            kickstart_cmd = bytearray([0xFF, 0x11, 0x41, 0x36, 0x0C, 0x00, 0xAA, 0x55])
            try:
                await client.write_gatt_char(CHAR_DATA_WRITE, kickstart_cmd, response=False)
                logger.info("Kick-start bytes sent. Listening for data...")
            except Exception as e:
                logger.warning(f"Could not send kick-start (may not be required): {e}")

            # Keep alive loop to watch the data stream roll in
            while True:
                if not client.is_connected:
                    logger.warning("Device disconnected unexpectedly!")
                    break
                await asyncio.sleep(1.0)
        else:
            logger.error(f"Could not connect to {DEVICE_ADDRESS}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStream stopped by user. Exiting.")