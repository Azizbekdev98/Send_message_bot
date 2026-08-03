import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import config
from database import load_user, save_user

logger = logging.getLogger(__name__)

INPAY_BASE = "https://inpay.uz/api/v1"
CALLBACK_URL = "https://169-58-21-48.sslip.io/payment_callback"

# Bearer token cache (24 soat amal qiladi)
_bearer_cache = {"token": None, "expires": 0}


def _get_bearer() -> str:
    """Bearer tokenni olish (cache dan yoki yangi)."""
    if _bearer_cache["token"] and time.time() < _bearer_cache["expires"]:
        return _bearer_cache["token"]

    url = (f"{INPAY_BASE}/authorization/"
           f"?merchant_id={config.INPAY_MERCHANT_ID}"
           f"&merchant_token={config.INPAY_MERCHANT_TOKEN}")
    try:
        req = urllib.request.urlopen(url, timeout=15)
        data = json.loads(req.read())
        token = data.get("bearer_token")
        if token:
            _bearer_cache["token"] = token
            _bearer_cache["expires"] = time.time() + 23 * 3600  # 23 soat
            return token
    except Exception as e:
        logger.error(f"inPay auth xato: {e}")
    return ""


def get_user_price(user_id: int) -> int:
    """Foydalanuvchining individual narxini qaytaradi, aks holda standart narx."""
    data = load_user(user_id)
    return data.get("custom_price", config.SUBSCRIPTION_PRICE)


def create_invoice(user_id: int) -> dict:
    """To'lov havolasi yaratish."""
    token = _get_bearer()
    if not token:
        return {}

    price = get_user_price(user_id)
    order_id = f"sub_{user_id}_{int(time.time())}"
    body = json.dumps({
        "merchant_id": config.INPAY_MERCHANT_ID,
        "token": config.INPAY_MERCHANT_TOKEN,
        "amount": price,
        "description": f"Reklama Bot — 30 kunlik obuna",
        "callback_url": CALLBACK_URL,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{INPAY_BASE}/create/",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        result["_our_order_id"] = order_id
        return result
    except Exception as e:
        logger.error(f"inPay invoice xato: {e}")
        return {}


def check_payment(order_id: str) -> str:
    """To'lov holatini tekshirish. Qaytaradi: success | pending | failed | cancelled | error"""
    try:
        url = f"{INPAY_BASE}/transactions/?order_id={order_id}"
        req = urllib.request.urlopen(url, timeout=15)
        data = json.loads(req.read())
        return data.get("status", "pending")
    except Exception as e:
        logger.error(f"inPay status xato: {e}")
        return "error"


def has_active_subscription(user_id: int) -> bool:
    if user_id == config.ADMIN_ID:
        return True
    data = load_user(user_id)
    now = datetime.now()
    expires = data.get("subscription_expires")
    if expires and datetime.fromisoformat(expires) > now:
        return True
    trial = data.get("trial_expires")
    if trial and datetime.fromisoformat(trial) > now:
        return True
    return False


def is_on_trial(user_id: int) -> bool:
    """Foydalanuvchi haqiqiy obunasi yo'q, faqat bepul sinov muddatida ekanini tekshiradi."""
    data = load_user(user_id)
    now = datetime.now()
    expires = data.get("subscription_expires")
    if expires and datetime.fromisoformat(expires) > now:
        return False
    trial = data.get("trial_expires")
    return bool(trial and datetime.fromisoformat(trial) > now)


def start_trial(data: dict) -> bool:
    """Foydalanuvchi birinchi marta login qilayotganda (data ali session_string
    o'rnatilmasdan oldin chaqiriladi) 3 kunlik bepul sinov beradi — data ichiga
    trial_expires yozadi, saqlashni chaqiruvchi bajaradi. Qaytaradi: sinov
    berilgan bo'lsa True (hech qachon sessiya/obuna/sinov bo'lmagan bo'lsa)."""
    if data.get("session_string") or data.get("trial_expires") or data.get("subscription_expires"):
        return False
    expires = datetime.now() + timedelta(days=config.TRIAL_DAYS)
    data["trial_expires"] = expires.isoformat()
    return True


def subscription_required(handler):
    """Callback/menu handlerlarni faol obunasi bo'lmagan foydalanuvchidan himoya qiladi."""
    import functools

    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not has_active_subscription(user_id):
            price = get_user_price(user_id)
            text = (
                f"⏸ *Obuna tugagan yoki mavjud emas!*\n\n"
                f"Bu bo'limdan foydalanish uchun obuna kerak.\n"
                f"💳 Narxi: *{price:,} so'm / oy*\n\n"
                "/subscribe — to'lov qilish"
            )
            if update.callback_query:
                await update.callback_query.answer("Obuna kerak!", show_alert=True)
                try:
                    await update.callback_query.edit_message_text(text, parse_mode="Markdown")
                except Exception:
                    pass
            else:
                await update.message.reply_text(text, parse_mode="Markdown")
            return 0
        return await handler(update, context)

    return wrapper


def activate_subscription(user_id: int):
    data = load_user(user_id)
    expires = datetime.now() + timedelta(days=config.SUBSCRIPTION_DAYS)
    data["subscription_expires"] = expires.isoformat()
    save_user(user_id, data)
    logger.info(f"[{user_id}] Obuna faollashtirildi: {expires.date()}")


def subscription_text(user_id: int) -> str:
    data = load_user(user_id)
    now = datetime.now()
    expires = data.get("subscription_expires")
    if expires:
        exp = datetime.fromisoformat(expires)
        if exp > now:
            days = (exp - now).days
            return f"Obuna: {days} kun qoldi ({exp.strftime('%d.%m.%Y')})"
    trial = data.get("trial_expires")
    if trial:
        exp = datetime.fromisoformat(trial)
        if exp > now:
            days = (exp - now).days
            return f"🎁 Bepul sinov: {days} kun qoldi ({exp.strftime('%d.%m.%Y')})"
        return "Bepul sinov muddati tugagan"
    return "Obuna: yo'q"


# ── Telegram handlers ────────────────────────────────────────────────

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if has_active_subscription(user_id):
        data = load_user(user_id)
        exp = datetime.fromisoformat(data["subscription_expires"]).strftime("%d.%m.%Y")
        await update.message.reply_text(
            f"✅ Obunangiz faol!\n\nMuddati: *{exp}* gacha",
            parse_mode="Markdown")
        return

    await update.message.reply_text("⏳ To'lov havolasi yaratilmoqda...")

    result = create_invoice(user_id)
    pay_url = result.get("pay_url")
    order_id = result.get("order_id")

    if not pay_url or not order_id:
        await update.message.reply_text(
            "❌ To'lov tizimida xato. Keyinroq urinib ko'ring.")
        logger.error(f"inPay javob: {result}")
        return

    # order_id ni saqlaymiz
    data = load_user(user_id)
    data["pending_order_id"] = order_id
    save_user(user_id, data)

    price = get_user_price(user_id)
    price_str = f"{price:,}".replace(",", " ")
    await update.message.reply_text(
        f"💳 *Obuna — {config.SUBSCRIPTION_DAYS} kun*\n\n"
        f"Narxi: *{price_str} so'm*\n\n"
        f"Payme, Click, inPAY va boshqalar orqali to'lang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("💳 To'lash", url=pay_url)
        ], [
            InlineKeyboardButton("✅ To'ladim", callback_data="check_payment")
        ]])
    )


async def cb_check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    data = load_user(user_id)
    order_id = data.get("pending_order_id")

    if not order_id:
        await query.edit_message_text("❌ To'lov topilmadi. /subscribe bosing.")
        return

    status = check_payment(order_id)

    if status == "success":
        activate_subscription(user_id)
        data.pop("pending_order_id", None)
        save_user(user_id, data)
        exp = (datetime.now() + timedelta(days=config.SUBSCRIPTION_DAYS)).strftime("%d.%m.%Y")
        await query.edit_message_text(
            f"✅ *To'lov qabul qilindi!*\n\n"
            f"Obuna *{config.SUBSCRIPTION_DAYS} kun* ga faollashtirildi.\n"
            f"Muddati: *{exp}* gacha\n\n"
            f"/start bosing.",
            parse_mode="Markdown")
    elif status in ("failed", "cancelled"):
        await query.edit_message_text(
            "❌ To'lov amalga oshmadi.\n\n/subscribe bosib qayta urinib ko'ring.")
    else:
        await query.edit_message_text(
            "⏳ To'lov hali tasdiqlanmadi.\n\n"
            "1-2 daqiqa kuting, keyin qayta tekshiring.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Qayta tekshirish", callback_data="check_payment")
            ]])
        )
