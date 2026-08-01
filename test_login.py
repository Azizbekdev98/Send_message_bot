"""
Telethon login test — bu faylni container ichida ishlatmang,
faqat debug uchun.
Ishlatish: python test_login.py
"""
import asyncio
import sys
from telethon import TelegramClient
from telethon.sessions import StringSession

import config

API_ID = config.API_ID
API_HASH = config.API_HASH


async def main():
    phone = input("Telefon raqam (+998...): ").strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    print("Yangi StringSession yaratilmoqda...")
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    print(f"Ulandi. DC: {client.session.dc_id}")

    print("Kod so'ralmoqda...")
    result = await client.send_code_request(phone)
    print(f"Kod yuborildi! DC: {client.session.dc_id}")
    print(f"Hash: {result.phone_code_hash}")
    print(f"Type: {type(result.type).__name__}")

    code = input("Kodni kiriting: ").strip().replace(" ", "").replace("-", "")
    print(f"Kiritilgan kod: '{code}'")
    print(f"sign_in oldida DC: {client.session.dc_id}")

    try:
        await client.sign_in(phone=phone, code=code)
        me = await client.get_me()
        print(f"MUVAFFAQIYAT! @{me.username}")
    except Exception as e:
        print(f"XATO: {type(e).__name__}: {e}")

    await client.disconnect()


asyncio.run(main())
