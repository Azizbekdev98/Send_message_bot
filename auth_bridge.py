"""
Auth Bridge — terminalda bir marta ishga tushiriladi.
Foydalanuvchilar bot orqali mustaqil kira oladi.
generate_session.py kabi — har user o'z threadida.

Ishlatish:
    python3 auth_bridge.py
"""
import asyncio
import time
import threading
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

import config

API_ID = config.API_ID
API_HASH = config.API_HASH
AUTH_DIR = Path("users/auth")

_DEVICE = dict(
    device_model="Samsung Galaxy S23",
    system_version="Android 14",
    app_version="10.3.2",
    lang_code="uz",
    system_lang_code="uz-UZ",
)


def auth_user(user_dir: Path, phone: str):
    """
    generate_session.py kabi: o'z threadida, o'z asyncio.run() da.
    time.sleep event loop ni bloklaydi → Telethon reconnect qilmaydi.
    """
    async def _run():
        print(f"\n[{user_dir.name}] Ulanmoqda: {phone}")
        client = TelegramClient(StringSession(), API_ID, API_HASH, **_DEVICE)
        try:
            await client.connect()
            await client.send_code_request(phone)
            print(f"[{user_dir.name}] Kod yuborildi ✓")
            (user_dir / "phone_saved").write_text(phone)
            (user_dir / "code_ready").write_text("1")

            # Kodni kutamiz — time.sleep bilan (event loop bloklanadi, xuddi input() kabi)
            code_file = user_dir / "code"
            timeout = 300  # 5 daqiqa
            elapsed = 0
            while not code_file.exists():
                time.sleep(0.5)
                elapsed += 0.5
                if elapsed >= timeout:
                    (user_dir / "error").write_text("Kod kiritilmadi (5 daqiqa)")
                    print(f"[{user_dir.name}] Timeout")
                    return

            code = code_file.read_text().strip()
            code_file.unlink(missing_ok=True)
            print(f"[{user_dir.name}] Kod qabul qilindi: {code}")

            try:
                await client.sign_in(phone=phone, code=code)

            except SessionPasswordNeededError:
                print(f"[{user_dir.name}] 2FA kerak")
                (user_dir / "needs_2fa").write_text("1")

                pass_file = user_dir / "2fa_pass"
                elapsed = 0
                while not pass_file.exists():
                    time.sleep(0.5)
                    elapsed += 0.5
                    if elapsed >= timeout:
                        (user_dir / "error").write_text("2FA kiritilmadi (5 daqiqa)")
                        return

                password = pass_file.read_text().strip()
                pass_file.unlink(missing_ok=True)
                await client.sign_in(password=password)
                print(f"[{user_dir.name}] 2FA OK ✓")

            session_str = client.session.save()
            (user_dir / "session").write_text(session_str)
            print(f"[{user_dir.name}] ✅ Login muvaffaqiyatli!")

        except Exception as e:
            (user_dir / "error").write_text(str(e))
            print(f"[{user_dir.name}] ❌ Xato: {e}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    asyncio.run(_run())


def main():
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 50)
    print("  Auth Bridge — foydalanuvchilar uchun")
    print("  Bot orqali avtomatik login (doim ishlaydi)")
    print("  To'xtatish: Ctrl+C")
    print("=" * 50)

    active: set[str] = set()

    while True:
        for phone_file in list(AUTH_DIR.glob("*/phone")):
            uid = phone_file.parent.name
            if uid in active:
                continue
            try:
                phone = phone_file.read_text().strip()
                phone_file.unlink(missing_ok=True)
            except Exception:
                continue

            active.add(uid)
            print(f"\n[{uid}] Yangi so'rov: {phone}")

            t = threading.Thread(
                target=auth_user,
                args=(phone_file.parent, phone),
                daemon=True,
            )
            t.start()

        # Tugaganlarni olib tashlaymiz
        for uid in list(active):
            d = AUTH_DIR / uid
            if (d / "session").exists() or (d / "error").exists():
                active.discard(uid)

        time.sleep(1)


if __name__ == "__main__":
    main()
