<div align="center">

# 📢 Telegram Reklama Bot

**Ko'p foydalanuvchili (multi-tenant) userbot platforma — har bir mijoz o'z Telegram akkaunti orqali guruh va kanallarga avtomatik reklama yuboradi**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-22.7-blue?style=for-the-badge&logo=telegram)](https://github.com/python-telegram-bot/python-telegram-bot)
[![Telethon](https://img.shields.io/badge/Telethon-1.43-2CA5E0?style=for-the-badge&logo=telegram)](https://github.com/LonamiWebs/Telethon)
[![Flask](https://img.shields.io/badge/Flask-Mini%20App-000000?style=for-the-badge&logo=flask)](https://flask.palletsprojects.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

</div>

---

## ✨ Xususiyatlar

| Xususiyat | Tavsif |
|-----------|--------|
| 👥 **Multi-user** | Har bir mijoz o'z Telegram akkaunti bilan mustaqil kirib ishlatadi |
| 👤 **Userbot** | Xabarlar bot emas, **foydalanuvchining o'z akkauntidan** yuboriladi (Telethon) |
| 💳 **Obuna tizimi** | inPay orqali oylik obuna, avtomatik to'lov tekshiruvi, admin sovg'a-obuna |
| 📷 **Media shablonlar** | Rasm + caption yoki faqat matn, bir nechta shablon, har biriga alohida interval |
| 👥 **Auto-detect guruhlar** | A'zo bo'lgan guruh/kanallarni avtomatik yuklaydi, sahifalab tanlash |
| ⏱ **Scheduler** | APScheduler orqali foydalanuvchi/shablon bo'yicha mustaqil intervalli yuborish |
| 🌐 **Mini App / Web login** | Flask asosidagi web autentifikatsiya va boshqaruv paneli (Telegram Mini App) |
| 🛠 **Admin panel** | Foydalanuvchilarga obuna sovg'a qilish, broadcast xabar yuborish |
| 💬 **Qo'llab-quvvatlash** | Foydalanuvchi ↔ admin ichki support chat oqimi |
| ❌ **Xatoliklarni kuzatish** | Yuborilmagan guruhlar sababi bilan ko'rsatiladi va o'chirish imkoniyati |
| 🐳 **Docker** | Production-ready Docker va Docker Compose |
| 💾 **JSON storage** | Har foydalanuvchi uchun alohida yengil JSON fayl bazasi |

---

## 🏗 Arxitektura

```
Send_message_bot/
├── main.py              # Bot kirish nuqtasi (python-telegram-bot), conversation/handler routing
├── auth_server.py        # Flask web server — Mini App, web login, payment webhook
├── auth_bridge.py        # Fon rejimida ishlaydigan userbot autentifikatsiya bridge
├── config.py              # Maxfiy sozlamalar (repoga tushmaydi, .gitignore da)
├── config.example.py     # Namuna konfiguratsiya
├── database.py            # Foydalanuvchi ma'lumotlarini JSON fayllarda saqlash/o'qish
├── keyboards.py           # Telegram klaviatura/tugma generatorlari
├── handlers/               # Har bir bo'lim uchun alohida handler modul
│   ├── auth.py             # Login (telefon/kod/2FA), /start oqimi
│   ├── templates.py        # Shablon yaratish/tahrirlash/o'chirish
│   ├── groups.py           # Guruh/kanal aniqlash va tanlash
│   ├── settings.py         # Interval sozlash, yuborishni boshlash/to'xtatish, statistika
│   ├── payment.py          # inPay integratsiyasi, obuna holati
│   ├── admin.py            # Admin panel — sovg'a obuna, broadcast
│   └── support.py          # Foydalanuvchi ↔ admin support chat
├── services/
│   ├── userbot.py          # Telethon client menejeri (connect/disconnect/cache)
│   └── sender.py           # Shablonni guruhlarga yuborish logikasi
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── start.sh                # Konteyner ichida barcha servislarni ishga tushiradi
└── DEPLOYMENT.md           # Server (Oracle Cloud) ga deploy qo'llanmasi
```

**Texnologiyalar:**

| Kutubxona | Maqsad |
|-----------|--------|
| `python-telegram-bot 22.7` | Bot boshqaruv interfeysi (bot tomoni) |
| `Telethon` | Userbot — mijoz akkauntidan xabar yuborish |
| `APScheduler 3.10` | Har foydalanuvchi/shablon uchun mustaqil vaqtli yuborish |
| `Flask` | Mini App va web autentifikatsiya serveri |

---

## 🚀 O'rnatish

### Talablar

- Python 3.11+
- Telegram bot token — [@BotFather](https://t.me/BotFather)
- Telegram API kalitlari — [my.telegram.org](https://my.telegram.org/apps)
- Sizning Telegram ID — [@userinfobot](https://t.me/userinfobot)
- (Ixtiyoriy) [inPay.uz](https://inpay.uz) merchant hisobi — pullik obuna uchun

### 1. Reponi klonlash

```bash
git clone https://github.com/Azizbekdev98/Send_message_bot.git
cd Send_message_bot
```

### 2. Virtual muhit va paketlar

```bash
python3 -m venv env
source env/bin/activate        # Windows: env\Scripts\activate
pip install -r requirements.txt
```

### 3. Konfiguratsiya

```bash
cp config.example.py config.py
nano config.py
```

```python
BOT_TOKEN = "1234567890:AAH..."      # @BotFather
ADMIN_ID  = 987654321                # Sizning Telegram ID
API_ID    = 12345678                 # my.telegram.org
API_HASH  = "abcdef1234..."          # my.telegram.org

AUTH_SERVER_URL = ""                 # Web login server manzili (bo'sh — manual login)
INPAY_MERCHANT_ID = ""               # inPay kassa ID (obuna funksiyasi uchun)
INPAY_MERCHANT_TOKEN = ""            # inPay kassa tokeni
SUBSCRIPTION_PRICE = 100000          # so'm / oy
SUBSCRIPTION_DAYS = 30
```

### 4. Ishga tushirish

```bash
python3 main.py
```

Foydalanuvchilar botga `/start` yozib, telefon raqam + SMS kod (kerak bo'lsa 2FA parol) orqali o'z akkauntlarini ulaydi — bu bir martalik jarayon, har bir foydalanuvchi uchun mustaqil.

---

## 🐳 Docker bilan ishga tushirish

```bash
docker compose up -d --build

# Loglarni kuzatish
docker compose logs -f
```

`start.sh` konteyner ichida uchta servisni birga ishga tushiradi: `auth_bridge.py`, `auth_server.py` (fonda) va `main.py` (asosiy bot).

> Oracle Cloud Ubuntu serveriga deploy qilish uchun [DEPLOYMENT.md](DEPLOYMENT.md) ga qarang.

---

## 📋 Foydalanuvchi oqimi

### 1. Ro'yxatdan o'tish
`/start` → telefon raqam → SMS kod → (kerak bo'lsa) 2FA parol → akkaunt ulanadi.

### 2. Obuna
- Obunasiz faqat login qilish mumkin; asosiy funksiyalar (shablon, guruh, yuborish) obuna talab qiladi
- `/subscribe` — inPay orqali to'lov havolasi yaratiladi
- To'lov tasdiqlangach obuna avtomatik faollashadi (`SUBSCRIPTION_DAYS` kun)

### 3. Shablon qo'shish
`📝 Shablonlar` → `➕ Yangi Shablon` → nom → rasm+caption yoki matn → faollashtirish

### 4. Guruh/kanal qo'shish
`👥 Guruhlar` → `🔄 Guruhlarni yuklash` → kerakli guruhlarni tanlash (faqat a'zo bo'lgan guruh/kanallar ko'rinadi)

### 5. Yuborishni boshlash
`⚙️ Sozlamalar` — har shablon uchun interval tanlanadi → `▶️ Boshlash` → `📊 Statistika` orqali natija kuzatiladi → `⏹ To'xtatish`

### 6. Qo'llab-quvvatlash
`📞 Yordam` orqali admin bilan to'g'ridan-to'g'ri chat.

---

## 🛡 Xavfsizlik

- `config.py`, `data.json`, `*.session`, `media/` — barchasi `.gitignore` da, repoga tushmaydi
- Bot tokeni, API kalitlari va to'lov tokenlari faqat `config.py` orqali o'qiladi (kodda hardcode qilinmagan)
- Har bir foydalanuvchi funksiyasi (`▶️ Boshlash` va h.k.) faol obunani tekshiradi
- Banned/chiqarib yuborilgan guruhlar xatosi ushlab logga yoziladi va foydalanuvchiga ko'rsatiladi

---

## 📄 Litsenziya

[MIT](LICENSE) © 2026
