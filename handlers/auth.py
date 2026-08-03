import logging

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    PhoneCodeExpiredError, PhoneCodeInvalidError,
    SessionPasswordNeededError, FloodWaitError,
    PhoneNumberInvalidError,
)
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import config
from database import load_user, save_user, active_users_count, MAX_USERS
from keyboards import main_keyboard
from services.userbot import set_client, get_client

logger = logging.getLogger(__name__)

WAIT_PHONE, WAIT_CODE, WAIT_2FA = 1, 2, 3
WAIT_QR = 10
MAIN = 0

_DEVICE = dict(
    device_model="Samsung Galaxy S23",
    system_version="Android 14",
    app_version="10.3.2",
    lang_code="uz",
    system_lang_code="uz-UZ",
)

# Auth jarayonidagi pending clientlar (xotira ichida)
_pending: dict[int, dict] = {}


def _main_text(data: dict) -> str:
    status = "✅ Ishlayapti" if data["is_running"] else "⏸ To'xtatilgan"
    phone = data.get("phone") or "—"
    return (
        f"🤖 *Reklama Boti*\n\n"
        f"📱 Telefon: `{phone}`\n"
        f"Holat: {status}\n"
        f"Guruhlar: {len(data['groups'])} ta\n"
        f"Shablonlar: {len(data['templates'])} ta\n\n"
        f"Bo'limni tanlang:"
    )


async def _finish(update_or_bot, chat_id: int, user_id: int, phone: str, client: TelegramClient):
    from handlers.payment import has_active_subscription, get_user_price, start_trial

    session_str = client.session.save()
    data = load_user(user_id)
    is_new_trial = start_trial(data)
    data["phone"] = phone
    data["session_string"] = session_str
    save_user(user_id, data)

    set_client(user_id, client)
    me = await client.get_me()
    logger.info(f"[{user_id}] Login OK: @{me.username}")

    _pending.pop(user_id, None)

    bot = update_or_bot if not hasattr(update_or_bot, 'message') else update_or_bot.get_bot()
    if hasattr(update_or_bot, 'message'):
        send = update_or_bot.message.reply_text
    else:
        async def send(text, **kw): return await update_or_bot.send_message(chat_id, text, **kw)

    price = get_user_price(user_id)
    if is_new_trial:
        await send(
            f"✅ *Muvaffaqiyatli kirildi!*\n\n"
            f"👤 {me.first_name} (@{me.username or 'yo`q'})\n\n"
            f"🎁 Sizga *{config.TRIAL_DAYS} kunlik bepul sinov* muddati taqdim etildi!\n\n"
            "/start bosing.",
            parse_mode="Markdown",
        )
    elif has_active_subscription(user_id):
        await send(
            f"✅ *Muvaffaqiyatli kirildi!*\n\n"
            f"👤 {me.first_name} (@{me.username or 'yo`q'})\n\n"
            "/start bosing.",
            parse_mode="Markdown",
        )
    else:
        await send(
            f"✅ *Kirildi: {me.first_name}*\n\n"
            f"Botdan foydalanish uchun obuna kerak.\n"
            f"💳 Narxi: *{price:,} so'm / oy*\n\n"
            "/subscribe — to'lov qilish",
            parse_mode="Markdown",
        )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id

    from handlers.payment import has_active_subscription

    data = load_user(user_id)

    if data.get("session_string"):
        if not has_active_subscription(user_id):
            from handlers.payment import get_user_price
            price = get_user_price(user_id)
            was_trial = bool(data.get("trial_expires")) and not data.get("subscription_expires")
            title = "⏸ *Bepul sinov muddati tugadi!*" if was_trial else "⏸ *Obuna tugagan!*"
            await update.message.reply_text(
                f"{title}\n\n"
                f"Botdan foydalanish uchun obuna kerak.\n"
                f"💳 Narxi: *{price:,} so'm / oy*\n\n"
                "/subscribe — to'lov qilish",
                parse_mode="Markdown")
            return ConversationHandler.END

        if not get_client(user_id):
            client = TelegramClient(StringSession(data["session_string"]), config.API_ID, config.API_HASH, **_DEVICE)
            await client.connect()
            if await client.is_user_authorized():
                set_client(user_id, client)
            else:
                await client.disconnect()

        if config.AUTH_SERVER_URL:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardRemove
            url = f"{config.AUTH_SERVER_URL.rstrip('/')}/app?user_id={user_id}"
            stats = data.get("stats", {})
            status = "✅ Ishlayapti" if data["is_running"] else "⏸ To'xtatilgan"
            active = sum(1 for t in data.get("templates", []) if t.get("is_active"))
            # Klaviaturani o'chirish uchun avval bo'sh xabar
            await update.message.reply_text("✋", reply_markup=ReplyKeyboardRemove())
            await update.message.reply_text(
                f"🤖 *Reklama Boti*\n\n"
                f"📱 `{data.get('phone', '—')}`\n"
                f"Holat: {status}\n"
                f"👥 Guruhlar: *{len(data['groups'])}* ta\n"
                f"📝 Shablonlar: *{active}/{len(data['templates'])}* faol\n"
                f"📤 Yuborildi: *{stats.get('total_sent', 0)}*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📱 Boshqarish", web_app=WebAppInfo(url=url))
                ]]))
            return MAIN

        await update.message.reply_text(
            _main_text(data),
            reply_markup=main_keyboard(data["is_running"], is_admin=(user_id == config.ADMIN_ID)),
            parse_mode="Markdown")
        return MAIN

    count = active_users_count()
    if count >= MAX_USERS and user_id != config.ADMIN_ID:
        await update.message.reply_text(
            f"❌ *Botda joy yo'q!*\n\nHozirda {count}/{MAX_USERS} ta foydalanuvchi bor.",
            parse_mode="Markdown")
        return ConversationHandler.END

    # Eski pending clientni tozalaymiz
    old = _pending.pop(user_id, None)
    if old:
        try:
            await old["client"].disconnect()
        except Exception:
            pass

    # Mini App orqali login
    if config.AUTH_SERVER_URL:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
        url = f"{config.AUTH_SERVER_URL.rstrip('/')}/auth?user_id={user_id}"
        await update.message.reply_text(
            "👋 *Xush kelibsiz!*\n\n"
            "Hisobingizga kirish uchun quyidagi tugmani bosing:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔐 Kirish", web_app=WebAppInfo(url=url))
            ]])
        )
        return WAIT_PHONE

    await update.message.reply_text(
        "👋 *Xush kelibsiz!*\n\n"
        "Telegram raqamingizni kiriting:\n"
        "📱 Misol: `+998901234567`",
        parse_mode="Markdown")
    return WAIT_PHONE


async def msg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    phone = update.message.text.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    await update.message.reply_text("⏳ Kod yuborilmoqda...")

    client = TelegramClient(StringSession(), config.API_ID, config.API_HASH, **_DEVICE)
    try:
        await client.connect()
        result = await client.send_code_request(phone)
        _pending[user_id] = {"client": client, "phone": phone, "phone_code_hash": result.phone_code_hash}
        await update.message.reply_text(
            "✅ *Kod yuborildi!*\n\n"
            "Telegramdan kelgan kodni yuboring:\n"
            "_(Misol: 12345)_",
            parse_mode="Markdown")
        return WAIT_CODE

    except PhoneNumberInvalidError:
        await client.disconnect()
        await update.message.reply_text("❌ Telefon raqam noto'g'ri. Qayta kiriting:\n📱 Misol: `+998901234567`", parse_mode="Markdown")
        return WAIT_PHONE

    except FloodWaitError as e:
        await client.disconnect()
        await update.message.reply_text(f"⏳ Telegram cheklovi: {e.seconds} soniya kuting, keyin qayta /start bosing.")
        return ConversationHandler.END

    except Exception as e:
        await client.disconnect()
        logger.error(f"[{user_id}] send_code_request xato: {e}")
        await update.message.reply_text(f"❌ Xato: {e}\n\n/start bosib qayta kiring.")
        return ConversationHandler.END


async def msg_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    code = update.message.text.strip().replace(" ", "").replace("-", "")

    pending = _pending.get(user_id)
    if not pending:
        await update.message.reply_text("❌ Sessiya topilmadi. /start bosing.")
        return ConversationHandler.END

    client = pending["client"]
    phone = pending["phone"]
    phone_code_hash = pending["phone_code_hash"]

    await update.message.reply_text("⏳ Tekshirilmoqda...")

    try:
        if not client.is_connected():
            await client.connect()
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        await _finish(update, update.effective_chat.id, user_id, phone, client)
        return MAIN

    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔐 *2FA parol kerak*\n\n"
            "Telegram parolingizni yuboring:",
            parse_mode="Markdown")
        return WAIT_2FA

    except PhoneCodeInvalidError:
        await update.message.reply_text("❌ Kod noto'g'ri. Qayta yuboring:")
        return WAIT_CODE

    except PhoneCodeExpiredError:
        # Yangi kod avtomatik yuboriladi — /start kerak emas
        try:
            if not client.is_connected():
                await client.connect()
            result = await client.send_code_request(phone)
            _pending[user_id]["phone_code_hash"] = result.phone_code_hash
            await update.message.reply_text(
                "⏰ Kod muddati o'tdi — yangi kod yuborildi!\n\nYangi kodni yuboring:")
            return WAIT_CODE
        except Exception as e2:
            _pending.pop(user_id, None)
            try:
                await client.disconnect()
            except Exception:
                pass
            await update.message.reply_text(f"❌ Yangi kod yuborishda xato: {e2}\n\n/start bosing.")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"[{user_id}] sign_in xato: {e}")
        await update.message.reply_text(f"❌ Xato: {e}\n\n/start bosib qayta kiring.")
        return ConversationHandler.END


async def msg_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    password = update.message.text.strip()

    pending = _pending.get(user_id)
    if not pending:
        await update.message.reply_text("❌ Sessiya topilmadi. /start bosing.")
        return ConversationHandler.END

    client = pending["client"]
    phone = pending["phone"]

    await update.message.reply_text("⏳ Tekshirilmoqda...")

    try:
        await client.sign_in(password=password)
        await _finish(update, update.effective_chat.id, user_id, phone, client)
        return MAIN

    except Exception as e:
        logger.error(f"[{user_id}] 2FA xato: {e}")
        await update.message.reply_text("❌ Parol noto'g'ri. Qayta yuboring:")
        return WAIT_2FA


async def cmd_add_user(update, context): pass
