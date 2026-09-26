import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("probe")

from bleak import BleakClient

DEVICE_ADDR = "48:F6:EE:F4:D1:76"

def notification_handler(sender, data: bytearray):
    raw = bytes(data)
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    logger.info(f"!!! NOTIFY from handle/uuid {sender}: hex={raw.hex()} text={repr(text)}")

async def main():
    logger.info(f"Connecting to {DEVICE_ADDR}...")
    async with BleakClient(DEVICE_ADDR, timeout=20.0) as client:
        logger.info(f"Connected: {client.is_connected}")

        logger.info("\n=== GATT SERVICES & CHARACTERISTICS DUMP ===")
        for service in client.services:
            logger.info(f"Service: {service.uuid} ({service.description})")
            for char in service.characteristics:
                props = ", ".join(char.properties)
                val_str = ""
                if "read" in char.properties:
                    try:
                        val = await client.read_gatt_char(char.uuid)
                        val_str = f" | val_hex={bytes(val).hex()} val_text={repr(bytes(val).decode('utf-8', errors='replace'))}"
                    except Exception as e:
                        val_str = f" | read_err={e}"
                logger.info(f"  Char: {char.uuid} ({char.description}) props=[{props}]{val_str}")
                for desc in char.descriptors:
                    try:
                        dval = await client.read_gatt_descriptor(desc.handle)
                        logger.info(f"    Desc: {desc.uuid} handle={desc.handle} val={bytes(dval).hex()}")
                    except Exception:
                        logger.info(f"    Desc: {desc.uuid} handle={desc.handle}")

        # Subscribe to all notify/indicate
        logger.info("\n=== SUBSCRIBING TO ALL NOTIFY/INDICATE ===")
        for service in client.services:
            for char in service.characteristics:
                if "notify" in char.properties or "indicate" in char.properties:
                    try:
                        await client.start_notify(char.uuid, notification_handler)
                        logger.info(f"Subscribed: {char.uuid}")
                    except Exception as e:
                        logger.warning(f"Subscribe failed for {char.uuid}: {e}")

        await asyncio.sleep(2.0)

        # Test writing commands
        test_payloads = [
            ("read:VG092", b"read:VG092"),
            ("read:VG005", b"read:VG005"),
            ("VG005", b"VG005"),
            ("read:VG273", b"read:VG273"),
            ("read:VG004", b"read:VG004"),
        ]

        # Find write chars
        write_chars = []
        for service in client.services:
            for char in service.characteristics:
                if "write" in char.properties or "write-without-response" in char.properties:
                    write_chars.append(char.uuid)

        logger.info(f"\nFound write characteristics: {write_chars}")

        for label, payload in test_payloads:
            logger.info(f"\n--- Testing payload '{label}' (hex={payload.hex()}) ---")
            for w_uuid in write_chars:
                # Try write_with_response and write_without_response
                for resp in [False, True]:
                    logger.info(f"Writing to {w_uuid} (response={resp})...")
                    try:
                        await client.write_gatt_char(w_uuid, payload, response=resp)
                        logger.info("  Write succeeded")
                    except Exception as e:
                        logger.warning(f"  Write error: {e}")
                    
                    await asyncio.sleep(1.0)

                    # Poll all readable characteristics to see if value changed
                    for service in client.services:
                        for char in service.characteristics:
                            if "read" in char.properties:
                                try:
                                    rval = await client.read_gatt_char(char.uuid)
                                    rbytes = bytes(rval)
                                    logger.info(f"  Poll-read {char.uuid}: hex={rbytes.hex()} text={repr(rbytes.decode('utf-8', errors='replace'))}")
                                except Exception:
                                    pass

        logger.info("\nListening 5 seconds for ambient notifications...")
        await asyncio.sleep(5.0)

asyncio.run(main())
