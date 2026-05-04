"""
Birinchi marta ishga tushiring:
    python3 auth.py

Telefon raqam va OTP kiritilgandan so'ng userbot_session.session fayli yaratiladi.
Keyingi safar bot.py avtomatik shu fayldan foydalanadi.
"""
import asyncio
from telethon import TelegramClient
import config


async def main():
    print("=== Userbot autentifikatsiya ===\n")
    client = TelegramClient("userbot_session", config.API_ID, config.API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"\n✅ Muvaffaqiyatli kirildi!")
    print(f"   Ism     : {me.first_name} {me.last_name or ''}")
    username = me.username or "yo'q"
    print(f"   Username: @{username}")
    print(f"   ID      : {me.id}")
    print("\nuserbot_session.session fayli saqlandi.")
    print("Endi 'python3 bot.py' bilan botni ishga tushirishingiz mumkin.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
