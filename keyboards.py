from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton


def back_btn(cb: str, label: str = "🔙 Orqaga") -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=cb)


def back_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("🔙 Orqaga")]], resize_keyboard=True)


def main_keyboard(is_running: bool, is_admin: bool = False) -> ReplyKeyboardMarkup:
    toggle_label = "⏹ To'xtatish" if is_running else "▶️ Boshlash"
    rows = [
        [KeyboardButton("📝 Shablonlar"), KeyboardButton("👥 Guruhlar")],
        [KeyboardButton("⚙️ Sozlamalar"), KeyboardButton("📊 Statistika")],
        [KeyboardButton(toggle_label), KeyboardButton("❌ Xato guruhlar")],
    ]
    if is_admin:
        rows.append([KeyboardButton("🛠 Admin Panel")])
    else:
        rows.append([KeyboardButton("📞 Yordam")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def templates_keyboard(templates: list) -> InlineKeyboardMarkup:
    buttons = []
    for t in templates:
        icon = "✅" if t.get("is_active") else "⏸"
        interval = t.get("interval_minutes", 180)
        h = interval // 60
        m = interval % 60
        time_str = f"{h}s" if m == 0 else f"{h}s{m}d" if h else f"{m}d"
        buttons.append([InlineKeyboardButton(
            f"{icon} {t['name']} ({time_str})", callback_data=f"tpl_view_{t['id']}"
        )])
    buttons.append([InlineKeyboardButton("➕ Yangi Shablon", callback_data="add_template")])
    buttons.append([back_btn("main_menu")])
    return InlineKeyboardMarkup(buttons)


def template_detail_keyboard(tpl_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_label = "⏸ To'xtatish" if is_active else "▶️ Faollashtirish"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"tpl_select_{tpl_id}")],
        [InlineKeyboardButton("⏱ Interval o'zgartirish", callback_data=f"tpl_interval_{tpl_id}")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"tpl_edit_{tpl_id}")],
        [InlineKeyboardButton("🗑 O'chirish", callback_data=f"tpl_delete_{tpl_id}")],
        [back_btn("templates")],
    ])


def tpl_interval_keyboard(tpl_id: int, current: int) -> InlineKeyboardMarkup:
    options = [30, 60, 120, 180, 360, 720]

    def label(m: int) -> str:
        return f"{m} daqiqa" if m < 60 else f"{m // 60} soat"

    rows = []
    row = []
    for m in options:
        tick = "✅ " if m == current else ""
        row.append(InlineKeyboardButton(f"{tick}{label(m)}", callback_data=f"tpl_set_interval_{tpl_id}_{m}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([back_btn(f"tpl_view_{tpl_id}")])
    return InlineKeyboardMarkup(rows)


def groups_keyboard(groups: list) -> InlineKeyboardMarkup:
    buttons = []
    for g in groups:
        title = (g.get("title") or str(g["chat_id"]))[:30]
        buttons.append([InlineKeyboardButton(
            f"❌ {title}", callback_data=f"rm_group_{g['chat_id']}"
        )])
    buttons.append([InlineKeyboardButton("🔄 Guruhlarni yuklash", callback_data="fetch_groups")])
    buttons.append([back_btn("main_menu")])
    return InlineKeyboardMarkup(buttons)


def dialogs_keyboard(dialogs: list, existing_ids: set, page: int, page_size: int = 20) -> InlineKeyboardMarkup:
    start = page * page_size
    chunk = dialogs[start: start + page_size]
    buttons = []
    for i, d in enumerate(chunk):
        icon = "✅" if d["chat_id"] in existing_ids else "➕"
        buttons.append([InlineKeyboardButton(
            f"{icon} {d['title'][:28]}", callback_data=f"tgl_group_{start + i}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"dlg_page_{page - 1}"))
    if start + page_size < len(dialogs):
        nav.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"dlg_page_{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([back_btn("groups")])
    return InlineKeyboardMarkup(buttons)


def settings_keyboard(current: int) -> InlineKeyboardMarkup:
    options = [1, 60, 120, 180, 360, 720]

    def label(m: int) -> str:
        return f"{m} daqiqa" if m < 60 else f"{m // 60} soat"

    rows = []
    row = []
    for m in options:
        tick = "✅ " if m == current else ""
        row.append(InlineKeyboardButton(f"{tick}{label(m)}", callback_data=f"set_interval_{m}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([back_btn("main_menu")])
    return InlineKeyboardMarkup(rows)
