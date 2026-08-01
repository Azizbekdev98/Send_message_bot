"""Step 2: Saqlangan session bilan sign_in"""
import asyncio, json, sys
from telethon import TelegramClient
from telethon.sessions import StringSession

import config

API_ID = config.API_ID
API_HASH = config.API_HASH
CODE = sys.argv[1] if len(sys.argv) > 1 else ""

async def main():
    with open("/tmp/test_state.json") as f:
        state = json.load(f)
    phone = state["phone"]
    session_str = state["session"]
    print(f"Phone: {phone}")
    print(f"Code:  {CODE}")

    # Saqlangan session bilan qayta ulanamiz
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    print(f"DC: {client.session.dc_id}")

    try:
        # Variant A: Telethon ichki hash (sign_in'ga hash bermaymiz)
        print("sign_in (ichki hash bilan) sinab ko'rilmoqda...")
        await client.sign_in(phone=phone, code=CODE)
        me = await client.get_me()
        print(f"MUVAFFAQIYAT! @{me.username}")
    except Exception as e:
        print(f"A varianti xato: {type(e).__name__}: {e}")
        try:
            # Variant B: Saqlangan hash bilan
            print("sign_in (saqlangan hash bilan) sinab ko'rilmoqda...")
            from telethon import functions
            result = await client(functions.auth.SignInRequest(
                phone_number=phone,
                phone_code_hash=state["hash"],
                phone_code=str(CODE)
            ))
            print(f"MUVAFFAQIYAT! {result}")
        except Exception as e2:
            print(f"B varianti xato: {type(e2).__name__}: {e2}")

    await client.disconnect()

asyncio.run(main())
