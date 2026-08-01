"""
Telethon session yaratish uchun local script.
Ishlatish: python3 generate_session.py
"""
import asyncio
import json
import os
from telethon import TelegramClient
from telethon.sessions import StringSession

import config

API_ID = config.API_ID
API_HASH = config.API_HASH


async def main():
    print("=" * 50)
    print("  Telegram Session Yaratish")
    print("=" * 50)

    phone = input("\nTelefon raqam (+998...): ").strip()
    target_id = input("Foydalanuvchi Telegram ID (bo'sh qoldiring = o'zingiz): ").strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    client = TelegramClient(
        StringSession(),
        API_ID,
        API_HASH,
        device_model="Samsung Galaxy S23",
        system_version="Android 14",
        app_version="10.3.2",
        lang_code="uz",
        system_lang_code="uz-UZ",
    )

    await client.connect()
    print(f"\nTelegramga ulandi (DC: {client.session.dc_id})")

    await client.send_code_request(phone)
    print(f"\nKod yuborildi: {phone}")
    print("Telegramga kelgan kodni kiriting (bot orqali EMAS, bu yerga yozing):")

    code = input("Kod: ").strip().replace(" ", "").replace("-", "")

    try:
        await client.sign_in(phone=phone, code=code)
    except Exception as e:
        if "password" in str(e).lower() or "SessionPassword" in type(e).__name__:
            password = input("2FA parol: ").strip()
            await client.sign_in(password=password)
        else:
            print(f"\nXato: {e}")
            await client.disconnect()
            return

    me = await client.get_me()
    session_str = client.session.save()

    print(f"\n✅ Muvaffaqiyatli kirildi: {me.first_name} (@{me.username})")

    # users/ papkasiga saqlaymiz
    save_id = int(target_id) if target_id.strip() else me.id
    user_file = f"users/{save_id}.json"
    os.makedirs("users", exist_ok=True)

    if os.path.exists(user_file):
        with open(user_file) as f:
            data = json.load(f)
    else:
        data = {
            "user_id": me.id,
            "phone": phone,
            "groups": [],
            "templates": [],
            "active_template_id": None,
            "interval_minutes": 180,
            "is_running": False,
            "next_template_id": 1,
            "stats": {"total_sent": 0, "successful": 0, "failed": 0, "last_sent": None},
        }

    data["phone"] = phone
    data["session_string"] = session_str

    with open(user_file, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Session {user_file} ga saqlandi!")
    if target_id.strip():
        print(f"\nBotda adminga /add_{save_id} yuboring.")
    print("\nEndi Docker botni restart qiling:")
    print("  docker restart reklama_bot")

    await client.disconnect()


asyncio.run(main())
