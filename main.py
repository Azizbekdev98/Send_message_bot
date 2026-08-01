import logging
import time
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)
from telegram.request import HTTPXRequest

import config
from database import all_user_ids, session_exists
from services.userbot import connect_all_users, disconnect_all
from services.sender import send_for_user

from handlers.auth import (
    cmd_start,
    msg_phone, msg_code, msg_2fa,
    cmd_add_user,
    WAIT_PHONE, WAIT_CODE, WAIT_2FA, WAIT_QR,
)
from handlers.templates import (
    cb_templates, cb_tpl_view, cb_add_template,
    msg_tpl_name, msg_tpl_photo, msg_tpl_text, msg_tpl_caption,
    cb_tpl_select, cb_tpl_edit_start, msg_tpl_edit, cb_tpl_delete,
    cb_tpl_interval, cb_tpl_set_interval,
    WAIT_TPL_NAME, WAIT_TPL_MEDIA, WAIT_TPL_CAPTION, WAIT_EDIT_TEXT,
)
from handlers.groups import (
    cb_groups, cb_fetch_groups, cb_toggle_group, cb_dlg_page, cb_remove_group,
)
from handlers.settings import (
    cb_settings,
    cb_start_sending, cb_stop_sending, cb_stats,
)
from handlers.payment import cmd_subscribe, cb_check_payment, subscription_required
from handlers.admin import cmd_admin, cb_admin_panel, cb_admin_gift, cb_gift_user, cb_admin_back, cb_admin_broadcast, cb_broadcast_tpl
from handlers.support import (
    cb_support, msg_support, cb_admin_reply, msg_admin_reply, WAIT_SUPPORT_MSG
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

MAIN = 0

scheduler = AsyncIOScheduler()


async def _fallback_any_callback(update, context):
    """Istalgan holatda tugma bosilsa — asosiy menyuga qaytaradi."""
    if update.callback_query:
        await update.callback_query.answer("Qayta ulanmoqda...")
    return await cmd_start(update, context)


async def cb_main_menu(update, context):
    from database import load_user
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = load_user(user_id)
    phone = data.get("phone") or "—"
    status = "✅ Ishlayapti" if data["is_running"] else "⏸ To'xtatilgan"
    try:
        await query.edit_message_text(
            f"🤖 *Reklama Boti*\n\n"
            f"📱 Telefon: `{phone}`\n"
            f"Holat: {status}\n"
            f"Guruhlar: {len(data['groups'])} ta\n"
            f"Shablonlar: {len(data['templates'])} ta\n\n"
            f"Pastdagi tugmalardan birini tanlang:",
            parse_mode="Markdown",
        )
    except Exception:
        pass
    return MAIN


async def msg_btn(update, context):
    if config.AUTH_SERVER_URL:
        return MAIN

    from database import load_user, save_user
    from keyboards import main_keyboard, templates_keyboard, groups_keyboard, back_reply_keyboard
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from datetime import datetime, timedelta

    text = update.message.text
    user_id = update.effective_user.id
    data = load_user(user_id)
    is_admin = (user_id == config.ADMIN_ID)

    PAID_BUTTONS = {"📝 Shablonlar", "👥 Guruhlar", "⚙️ Sozlamalar", "📊 Statistika", "▶️ Boshlash"}
    if text in PAID_BUTTONS:
        from handlers.payment import has_active_subscription, get_user_price
        if not has_active_subscription(user_id):
            price = get_user_price(user_id)
            await update.message.reply_text(
                f"⏸ *Obuna tugagan yoki mavjud emas!*\n\n"
                f"Bu bo'limdan foydalanish uchun obuna kerak.\n"
                f"💳 Narxi: *{price:,} so'm / oy*\n\n"
                "/subscribe — to'lov qilish",
                parse_mode="Markdown",
            )
            return MAIN

    STICKERS = {
        "📝 Shablonlar":  "CAACAgEAAxUAAWpWqfSgnmDJodVs-Y1T9JMertlOAAIiAwACZr6hRjnro5jznq9LPQQ",
        "👥 Guruhlar":    "CAACAgEAAxUAAWpWqfQo6sbN7Z-7Mm-oweSnyyIkAAJrAwACqeWgRtx2e_Bppv63PQQ",
        "⚙️ Sozlamalar":  "CAACAgEAAxUAAWpWqfS8rnLxL8dm_Op4GnsUuq9ZAAIrAgACIk8hRA8-ZYEyA3wDPQQ",
        "📊 Statistika":  "CAACAgEAAxUAAWpWqfS7Zz0rcfZzcP-0XUU3PmlUAAKKAgACkUkgRBWlqYgvjawKPQQ",
        "▶️ Boshlash":    "CAACAgEAAxUAAWpWqfT8dbJBKBjVoDdIPuIQ_GcNAAL6AQACjLEgRHhzeIjneBzEPQQ",
        "⏹ To'xtatish":  "CAACAgEAAxUAAWpWqfR-HnroRL7-PbIGAeCKV1jMAAK0AgACtAoZRAIkX7S-piKVPQQ",
        "📞 Yordam":      "CAACAgEAAxUAAWpWqfRl1dg5B2v1aoJDajV0eDASAAIsAgACnJUgRM-8cI9E3TjGPQQ",
        "🛠 Admin Panel": "CAACAgEAAxUAAWpWqfToQUykA2F_bE8o2BJDirQMAAI0AgACB4bpR5rG_vaZC31EPQQ",
        "❌ Xato guruhlar": "CAACAgEAAxUAAWpWqfR-HnroRL7-PbIGAeCKV1jMAAK0AgACtAoZRAIkX7S-piKVPQQ",
    }
    if text in STICKERS:
        try:
            await context.bot.send_sticker(chat_id=user_id, sticker=STICKERS[text])
        except Exception:
            pass

    if text == "🔙 Orqaga":
        await update.message.reply_text(
            "🏠 Asosiy menyu:",
            reply_markup=main_keyboard(data["is_running"], is_admin=is_admin)
        )
        return MAIN

    if text == "📝 Shablonlar":
        templates = data["templates"]
        msg = "📝 *Shablonlar*\n\nShablon tanlang:" if templates else "📝 *Shablonlar*\n\nHali shablon yo'q. Yangi qo'shing."
        await update.message.reply_text(msg, reply_markup=templates_keyboard(templates), parse_mode="Markdown")

    elif text == "👥 Guruhlar":
        await update.message.reply_text(
            "👥 *Guruhlar*\n\nQo'shilgan guruhlar:",
            reply_markup=groups_keyboard(data["groups"]),
            parse_mode="Markdown"
        )

    elif text == "⚙️ Sozlamalar":
        templates = data["templates"]
        buttons = []
        for t in templates:
            m = t.get("interval_minutes", 180)
            h, mn = m // 60, m % 60
            time_str = f"{h}s {mn}d" if mn else f"{h} soat"
            icon = "✅" if t.get("is_active") else "⏸"
            buttons.append([InlineKeyboardButton(
                f"{icon} {t['name']} — {time_str}",
                callback_data=f"tpl_interval_{t['id']}"
            )])
        text_msg = "⚙️ *Sozlamalar*\n\nInterval o'zgartirish uchun shablon bosing:" if templates else "⚙️ *Sozlamalar*\n\nHali shablon yo'q."
        await update.message.reply_text(
            text_msg,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
            parse_mode="Markdown"
        )

    elif text == "📊 Statistika":
        stats = data["stats"]
        last_sent = stats.get("last_sent")
        if last_sent:
            try:
                last_sent = datetime.fromisoformat(last_sent).strftime("%d.%m.%Y %H:%M")
            except Exception:
                last_sent = "Hali yuborilmagan"
        else:
            last_sent = "Hali yuborilmagan"
        active = [t for t in data["templates"] if t.get("is_active")]
        tpl_lines = "\n".join(f"• {t['name']} — {t.get('interval_minutes', 180) // 60}s" for t in active) or "Tanlanmagan"
        status = "✅ Ishlayapti" if data["is_running"] else "⏸ To'xtatilgan"
        failed_groups = data.get("failed_groups", {})
        failed_count = len(failed_groups)
        failed_label = f"❌ Xato guruhlar ({failed_count} ta)" if failed_count else "✅ Xato guruhlar yo'q"
        await update.message.reply_text(
            f"📊 *Statistika*\n\n"
            f"🔄 Holat: {status}\n"
            f"👥 Guruhlar: {len(data['groups'])} ta\n"
            f"📝 Faol shablonlar:\n{tpl_lines}\n\n"
            f"📤 Jami yuborildi: {stats['total_sent']}\n"
            f"✅ Muvaffaqiyatli: {stats['successful']}\n"
            f"❌ Xatolik: {stats['failed']}\n"
            f"🕐 Oxirgi: {last_sent}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(failed_label, callback_data="failed_groups")
            ]]),
            parse_mode="Markdown"
        )

    elif text == "▶️ Boshlash":
        from services.userbot import is_connected
        from services.sender import send_template
        active = [t for t in data["templates"] if t.get("is_active")]
        if not active:
            await update.message.reply_text("❌ Avval shablon faollashtiring!")
            return MAIN
        if not data["groups"]:
            await update.message.reply_text("❌ Avval guruh qo'shing!")
            return MAIN
        if not is_connected(user_id):
            await update.message.reply_text("❌ Sessiya ulanmagan! /start bosing.")
            return MAIN
        data["is_running"] = True
        save_user(user_id, data)
        for tpl in active:
            job_id = f"send_{user_id}_tpl_{tpl['id']}"
            scheduler.add_job(
                send_template, trigger="interval",
                minutes=tpl.get("interval_minutes", 180),
                args=[context.bot, user_id, tpl["id"]],
                id=job_id, replace_existing=True,
                next_run_time=datetime.now() + timedelta(minutes=tpl.get("interval_minutes", 180)),
            )
            context.application.create_task(send_template(context.bot, user_id, tpl["id"]))
        await update.message.reply_text(
            f"✅ {len(active)} ta shablon yuborilmoqda!",
            reply_markup=main_keyboard(True, is_admin=is_admin)
        )

    elif text == "⏹ To'xtatish":
        data["is_running"] = False
        save_user(user_id, data)
        for tpl in data["templates"]:
            job_id = f"send_{user_id}_tpl_{tpl['id']}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        await update.message.reply_text(
            "⏸ Yuborish to'xtatildi!",
            reply_markup=main_keyboard(False, is_admin=is_admin)
        )

    elif text == "🛠 Admin Panel":
        await cmd_admin(update, context)

    elif "Xato guruhlar" in text:
        failed = data.get("failed_groups", {})
        if not failed:
            await update.message.reply_text("✅ Xato guruhlar yo'q — hamma guruhlar ishlayapti!")
            return MAIN
        txt, markup = _failed_groups_view(failed)
        await update.message.reply_text(txt, reply_markup=markup, parse_mode="Markdown")

    elif text == "📞 Yordam":
        await update.message.reply_text(
            "📞 *Yordam*\n\nQuyidagi tugmani bosib xabar yozing:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✍️ Xabar yozish", callback_data="support")]
            ]),
            parse_mode="Markdown"
        )

    return MAIN


ERROR_UZ = {
    "ChatSendPhotosForbiddenError": "Rasm yuborish taqiqlangan",
    "ChatSendMediaForbiddenError": "Fayl/rasm yuborish taqiqlangan",
    "ChatWriteForbiddenError": "Bu guruhda faqat adminlar yoza oladi",
    "ChatRestrictedError": "Guruh cheklangan",
    "SlowModeWaitError": "Guruhda sekin rejim — tez-tez yuborish mumkin emas",
    "UserNotParticipantError": "Siz bu guruhga a'zo emassiz",
    "UserBannedInChannelError": "Siz bu guruhdan ban qilingansiz",
    "ChannelPrivateError": "Bu guruh yopiq yoki o'chirilgan",
}


def _failed_groups_view(failed: dict):
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    items = list(failed.items())[:20]
    lines = []
    buttons = []
    for i, (cid, info) in enumerate(items, 1):
        title = info.get("title", cid)
        raw_reason = info.get("reason", "Noma'lum")
        reason = ERROR_UZ.get(raw_reason, raw_reason)
        lines.append(f"{i}. *{title}*\n    ❌ {reason}")
        buttons.append([InlineKeyboardButton(f"🗑 {i}-ni o'chir", callback_data=f"del_confirm_{cid}")])
    text = f"❌ *Xato guruhlar* ({len(failed)} ta)\n\n" + "\n\n".join(lines)
    return text, InlineKeyboardMarkup(buttons)


async def cb_del_group_confirm(update, context):
    """O'chirish tugmasi bosilganda tushuntirish va tasdiqlash so'raydi."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    from database import load_user
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = query.data.split("del_confirm_")[1]

    data = load_user(user_id)
    title = data.get("failed_groups", {}).get(str(chat_id), {}).get("title", chat_id)

    await query.edit_message_text(
        f"⚠️ *Diqqat!*\n\n"
        f"*{title}*\n\n"
        f"Bu tugma guruhni bot ro'yxatidan olib tashlaydi — bot bu guruhga endi reklama yubormaydi.\n\n"
        f"Guruhning o'zi Telegramdan o'chib ketmaydi.\n\n"
        f"Davom etasizmi?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"del_group_{chat_id}")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="failed_groups")],
        ]),
        parse_mode="Markdown"
    )
    return MAIN


async def cb_del_group(update, context):
    """Guruhni groups va failed_groups dan o'chiradi."""
    from database import load_user, save_user, clear_failed_group
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split("del_group_")[1])

    data = load_user(user_id)
    title = data.get("failed_groups", {}).get(str(chat_id), {}).get("title", str(chat_id))
    data["groups"] = [g for g in data["groups"] if g["chat_id"] != chat_id]
    save_user(user_id, data)
    clear_failed_group(user_id, chat_id)

    # Qolgan xato guruhlarni ko'rsat
    data = load_user(user_id)
    failed = data.get("failed_groups", {})
    if not failed:
        await query.edit_message_text(f"🗑 *{title}* o'chirildi.\n\n✅ Xato guruhlar yo'q!", parse_mode="Markdown")
        return MAIN

    txt, markup = _failed_groups_view(failed)
    await query.edit_message_text(
        f"🗑 *{title}* o'chirildi.\n\n" + txt,
        reply_markup=markup,
        parse_mode="Markdown"
    )
    return MAIN


async def cb_failed_groups(update, context):
    from database import load_user, clear_failed_group
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data.startswith("rm_failed_"):
        chat_id = int(query.data.split("rm_failed_")[1])
        clear_failed_group(user_id, chat_id)

    data = load_user(user_id)
    failed = data.get("failed_groups", {})

    if not failed:
        await query.edit_message_text("✅ Xato guruhlar yo'q!", parse_mode="Markdown")
        return MAIN

    text, markup = _failed_groups_view(failed)
    await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    return MAIN




async def _sync_scheduler(bot):
    """Mini App orqali o'zgartirilgan scheduler buyruqlarini qayta ishlash."""
    import json
    from pathlib import Path
    users_dir = Path("/app/users")
    if not users_dir.exists():
        return
    from services.sender import send_template
    for f in users_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if not data.get("_scheduler_update"):
                continue
            user_id = data.get("user_id")
            if not user_id:
                continue
            send_now = data.pop("_send_now", False)
            data.pop("_scheduler_update", None)
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            # Barcha job larni o'chirib qayta qurish
            from datetime import datetime
            for tpl in data.get("templates", []):
                job_id = f"send_{user_id}_tpl_{tpl['id']}"
                if scheduler.get_job(job_id):
                    scheduler.remove_job(job_id)
                if data.get("is_running") and tpl.get("is_active"):
                    extra = {"next_run_time": datetime.now()} if send_now else {}
                    scheduler.add_job(
                        send_template,
                        trigger="interval",
                        minutes=tpl.get("interval_minutes", 180),
                        args=[bot, user_id, tpl["id"]],
                        id=job_id,
                        replace_existing=True,
                        **extra,
                    )
            logger.info(f"[{user_id}] Scheduler yangilandi (send_now={send_now})")
        except Exception as e:
            logger.warning(f"_sync_scheduler xato {f.name}: {e}")


async def post_init(application: Application) -> None:
    scheduler.start()
    # Mini App scheduler sync (har 30 soniyada)
    scheduler.add_job(
        _sync_scheduler,
        trigger="interval",
        seconds=30,
        id="webapp_scheduler_sync",
        args=[application.bot],
        replace_existing=True,
    )
    await connect_all_users(config.API_ID, config.API_HASH)

    # Avval ishlayotgan foydalanuvchilarni qayta ishga tushirish
    from datetime import datetime, timedelta
    from database import load_user
    from services.sender import send_template
    for uid in all_user_ids():
        if session_exists(uid):
            data = load_user(uid)
            if data["is_running"] and data["groups"]:
                for tpl in data["templates"]:
                    if tpl.get("is_active"):
                        job_id = f"send_{uid}_tpl_{tpl['id']}"
                        interval_min = tpl.get("interval_minutes", 180)

                        # Oxirgi yuborishdan hisoblash
                        extra = {}
                        last_sent_str = tpl.get("last_sent")
                        if last_sent_str:
                            try:
                                last_dt = datetime.fromisoformat(last_sent_str)
                                next_run = last_dt + timedelta(minutes=interval_min)
                                if next_run < datetime.now():
                                    next_run = datetime.now() + timedelta(seconds=15)
                                extra["next_run_time"] = next_run
                            except Exception:
                                pass

                        scheduler.add_job(
                            send_template,
                            trigger="interval",
                            minutes=interval_min,
                            args=[application.bot, uid, tpl["id"]],
                            id=job_id,
                            replace_existing=True,
                            **extra,
                        )
                        nxt = extra.get("next_run_time", "auto")
                        logger.info(f"User {uid} tpl={tpl['id']}: resumed, next={nxt}")

    logger.info(f"Bot ishga tushdi. Faol foydalanuvchilar: {len(all_user_ids())}")


async def post_shutdown(application: Application) -> None:
    await disconnect_all()
    if scheduler.running:
        scheduler.shutdown(wait=False)


def main() -> None:
    request = HTTPXRequest(
        connect_timeout=60.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=60.0,
    )
    persistence = PicklePersistence(filepath="users/bot_persistence")
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .request(request)
        .persistence(persistence)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            MAIN: [
                MessageHandler(
                    filters.TEXT & filters.Regex(
                        r"^(📝 Shablonlar|👥 Guruhlar|⚙️ Sozlamalar|📊 Statistika|▶️ Boshlash|⏹ To'xtatish|❌ Xato guruhlar|🛠 Admin Panel|📞 Yordam|🔙 Orqaga|Xato guruhlar)$"
                    ),
                    msg_btn
                ),
                CallbackQueryHandler(cb_main_menu, pattern="^main_menu$"),
                CallbackQueryHandler(cb_support, pattern="^support$"),
                # Templates
                CallbackQueryHandler(subscription_required(cb_templates), pattern="^templates$"),
                CallbackQueryHandler(subscription_required(cb_tpl_view), pattern=r"^tpl_view_\d+$"),
                CallbackQueryHandler(subscription_required(cb_add_template), pattern="^add_template$"),
                CallbackQueryHandler(subscription_required(cb_tpl_select), pattern=r"^tpl_select_\d+$"),
                CallbackQueryHandler(subscription_required(cb_tpl_interval), pattern=r"^tpl_interval_\d+$"),
                CallbackQueryHandler(subscription_required(cb_tpl_set_interval), pattern=r"^tpl_set_interval_\d+_\d+$"),
                CallbackQueryHandler(subscription_required(cb_tpl_edit_start), pattern=r"^tpl_edit_\d+$"),
                CallbackQueryHandler(subscription_required(cb_tpl_delete), pattern=r"^tpl_delete_\d+$"),
                # Groups
                CallbackQueryHandler(subscription_required(cb_groups), pattern="^groups$"),
                CallbackQueryHandler(subscription_required(cb_fetch_groups), pattern="^fetch_groups$"),
                CallbackQueryHandler(subscription_required(cb_toggle_group), pattern=r"^tgl_group_\d+$"),
                CallbackQueryHandler(subscription_required(cb_dlg_page), pattern=r"^dlg_page_\d+$"),
                CallbackQueryHandler(subscription_required(cb_remove_group), pattern=r"^rm_group_"),
                # Settings & controls
                CallbackQueryHandler(subscription_required(cb_settings), pattern="^settings$"),
                CallbackQueryHandler(subscription_required(cb_stats), pattern="^stats$"),
                CallbackQueryHandler(subscription_required(cb_start_sending), pattern="^start_sending$"),
                CallbackQueryHandler(cb_stop_sending, pattern="^stop_sending$"),
                # Failed groups
                CallbackQueryHandler(cb_failed_groups, pattern="^failed_groups$"),
                CallbackQueryHandler(cb_failed_groups, pattern=r"^rm_failed_-?\d+$"),
                CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"),
                CallbackQueryHandler(cb_del_group_confirm, pattern=r"^del_confirm_-?\d+$"),
                CallbackQueryHandler(cb_del_group, pattern=r"^del_group_-?\d+$"),
                # Admin
                CallbackQueryHandler(cb_admin_panel, pattern="^admin_panel$"),
                CallbackQueryHandler(cb_admin_gift, pattern="^admin_gift$"),
                CallbackQueryHandler(cb_gift_user, pattern=r"^gift_\d+$"),
                CallbackQueryHandler(cb_admin_back, pattern="^admin_back$"),
                CallbackQueryHandler(cb_admin_broadcast, pattern="^admin_broadcast$"),
                CallbackQueryHandler(cb_broadcast_tpl, pattern=r"^broadcast_tpl_\d+$"),
            ],
            WAIT_QR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_2fa),
            ],
            WAIT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_phone),
            ],
            WAIT_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_code),
            ],
            WAIT_2FA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_2fa),
            ],
            WAIT_TPL_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_name),
                CallbackQueryHandler(cb_templates, pattern="^templates$"),
            ],
            WAIT_TPL_MEDIA: [
                MessageHandler(filters.PHOTO, msg_tpl_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_text),
            ],
            WAIT_TPL_CAPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_caption),
            ],
            WAIT_EDIT_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_edit),
                CallbackQueryHandler(cb_tpl_view, pattern=r"^tpl_view_\d+$"),
                CallbackQueryHandler(cb_templates, pattern="^templates$"),
            ],
            WAIT_SUPPORT_MSG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_support),
                CallbackQueryHandler(cb_main_menu, pattern="^main_menu$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(cb_main_menu, pattern="^main_menu$"),
            CallbackQueryHandler(_fallback_any_callback),
            MessageHandler(filters.TEXT & ~filters.COMMAND, _fallback_any_callback),
        ],
        per_message=False,
        conversation_timeout=timedelta(hours=1),
    )

    application.add_handler(conv)

    # Admin javob berish conversation
    admin_reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_admin_reply, pattern=r"^reply_\d+$")],
        states={
            WAIT_SUPPORT_MSG: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & filters.User(config.ADMIN_ID),
                    msg_admin_reply
                ),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        per_message=False,
    )
    application.add_handler(admin_reply_conv)

    async def cmd_id(update, context):
        chat = update.effective_chat
        await update.message.reply_text(f"Chat ID: `{chat.id}`", parse_mode="Markdown")

    application.add_handler(CommandHandler("id", cmd_id))
    application.add_handler(CommandHandler("subscribe", cmd_subscribe))
    application.add_handler(CallbackQueryHandler(cb_failed_groups, pattern="^failed_groups$"))
    application.add_handler(CallbackQueryHandler(cb_failed_groups, pattern=r"^rm_failed_-?\d+$"))
    application.add_handler(CallbackQueryHandler(cb_del_group_confirm, pattern=r"^del_confirm_-?\d+$"))
    application.add_handler(CallbackQueryHandler(cb_del_group, pattern=r"^del_group_-?\d+$"))
    application.add_handler(CallbackQueryHandler(cb_check_payment, pattern="^check_payment$"))
    application.add_handler(CallbackQueryHandler(cb_admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(cb_admin_gift, pattern="^admin_gift$"))
    application.add_handler(CallbackQueryHandler(cb_gift_user, pattern=r"^gift_\d+$"))
    application.add_handler(CallbackQueryHandler(cb_admin_back, pattern="^admin_back$"))
    application.add_handler(CallbackQueryHandler(cb_admin_broadcast, pattern="^admin_broadcast$"))
    application.add_handler(CallbackQueryHandler(cb_broadcast_tpl, pattern=r"^broadcast_tpl_\d+$"))
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^/add_\d+$") & filters.User(config.ADMIN_ID),
        cmd_add_user,
    ))
    logger.info("Bot ishga tushdi...")
    while True:
        try:
            application.run_polling(drop_pending_updates=True)
            break
        except Exception as e:
            logger.error(f"Ulanish xatosi: {e}. 30 soniyadan so'ng qayta uriniladi...")
            time.sleep(30)


if __name__ == "__main__":
    main()
