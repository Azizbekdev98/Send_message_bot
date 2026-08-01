"""Step 1: Kod yuborish va holatni faylga saqlash"""
import asyncio, json, sys
from telethon import TelegramClient
from telethon.sessions import StringSession

import config

API_ID = config.API_ID
API_HASH = config.API_HASH
PHONE = sys.argv[1] if len(sys.argv) > 1 else ""
if not PHONE:
    sys.exit("Ishlatish: python test_step1.py +998901234567")

async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    print(f"DC before: {client.session.dc_id}")
    result = await client.send_code_request(PHONE)
    print(f"DC after:  {client.session.dc_id}")
    print(f"Hash:      {result.phone_code_hash}")
    print(f"Type:      {type(result.type).__name__}")
    session_str = client.session.save()
    state = {"phone": PHONE, "hash": result.phone_code_hash, "session": session_str}
    with open("/tmp/test_state.json", "w") as f:
        json.dump(state, f)
    print("Holat /tmp/test_state.json ga saqlandi")
    print("Endi telegramdan kelgan kodni test_step2.py ga bering:")
    print("  python test_step2.py <KOD>")
    await client.disconnect()

asyncio.run(main())
