<div align="center">

# 📢 Telegram Reklama Boti

**Shaxsiy akkauntingizdan guruh va kanallarga avtomatik reklama yuboruvchi bot**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-22.7-blue?style=for-the-badge&logo=telegram)](https://github.com/python-telegram-bot/python-telegram-bot)
[![Telethon](https://img.shields.io/badge/Telethon-1.43-2CA5E0?style=for-the-badge&logo=telegram)](https://github.com/LonamiWebs/Telethon)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

</div>

---

## ✨ Xususiyatlar

| Xususiyat | Tavsif |
|-----------|--------|
| 👤 **Userbot** | Xabarlar bot nomidan emas, **sizning akkauntingizdan** yuboriladi |
| 📷 **Media shablon** | Rasm + caption yoki faqat matn shablonlari |
| 👥 **Auto-detect guruhlar** | Azo bo'lgan guruh va kanallarni avtomatik yuklaydi |
| ⏱ **Scheduler** | 1 daqiqadan 12 soatgacha sozlanuvchi interval |
| 🎛 **Inline UI** | Barcha boshqaruv inline tugmalar orqali |
| 🔒 **Admin-only** | Faqat belgilangan admin foydalana oladi |
| 🐳 **Docker** | Production-ready Docker va Docker Compose |
| 💾 **JSON storage** | Yengil va tez JSON fayl bazasi |

---

## 🖼 Interfeys

```
🤖 Reklama Boti
─────────────────────────
📝 Shablonlar
👥 Mening Guruhlarim
⚙️ Sozlamalar
📊 Statistika
▶️ Boshlash
```

**Shablon turlari:**
- `📷 Rasm + caption` — Rasm va uning ostida matn
- `✏️ Faqat matn` — Oddiy matn xabari

**Guruh tanlash:**
- 🔄 Guruhlarni yuklash tugmasi barcha guruh va kanallarni ko'rsatadi
- ✅ / ➕ bosib tanlash yoki olib tashlash
- Sahifalash (20 tadan)

---

## 🏗 Arxitektura

```
send_messag_bot/
├── bot.py              # Asosiy bot (python-telegram-bot)
├── auth.py             # Bir martalik userbot autentifikatsiya
├── config.py           # BOT_TOKEN, ADMIN_ID, API_ID, API_HASH
├── config.example.py   # Namuna konfiguratsiya
├── requirements.txt    # Python paketlar
├── Dockerfile
├── docker-compose.yml
├── DEPLOYMENT.md       # Oracle Cloud deploy qo'llanmasi
└── media/              # Shablon rasmlari (avtomatik yaratiladi)
```

**Texnologiyalar:**

| Kutubxona | Maqsad |
|-----------|--------|
| `python-telegram-bot 22.7` | Bot boshqaruv interfeysi |
| `Telethon 1.43` | Userbot — xabar yuborish |
| `APScheduler 3.10` | Vaqtli yuborish |

---

## 🚀 O'rnatish

### Talablar

- Python 3.11+
- Telegram bot token — [@BotFather](https://t.me/BotFather)
- Telegram API kalitlari — [my.telegram.org](https://my.telegram.org/apps)
- Sizning Telegram ID — [@userinfobot](https://t.me/userinfobot)

### 1. Reponi klonlash

```bash
git clone https://github.com/YOUR_USERNAME/send_messag_bot.git
cd send_messag_bot
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
BOT_TOKEN = "1234567890:AAH..."   # @BotFather
ADMIN_ID  = 987654321             # Sizning ID
API_ID    = 12345678              # my.telegram.org
API_HASH  = "abcdef1234..."       # my.telegram.org
```

### 4. Userbot autentifikatsiya (bir marta)

```bash
python3 auth.py
```

Telefon raqam (`+998XXXXXXXXX`) va SMS kodni kiriting.  
`userbot_session.session` fayli yaratiladi — bu fayl keyingi ishga tushirishlarda avtomatik ishlatiladi.

### 5. Ishga tushirish

```bash
python3 bot.py
```

---

## 🐳 Docker bilan ishga tushirish

```bash
# Avval autentifikatsiya (bir marta, lokal)
python3 auth.py

# Docker bilan ishga tushirish
docker compose up -d --build

# Loglarni kuzatish
docker compose logs -f
```

> Oracle Cloud Ubuntu serveriga deploy qilish uchun [DEPLOYMENT.md](DEPLOYMENT.md) ga qarang.

---

## 📋 Foydalanish

### Shablon qo'shish

1. `📝 Shablonlar` → `➕ Yangi Shablon`
2. Nom kiriting
3. **Rasm yuboring** (rasm + caption) **yoki matn yozing** (faqat matn)
4. Caption kiriting (rasm yuborgan bo'lsangiz)
5. Shablonni faollashtirish: `☑️ Faollashtirish`

### Guruh/kanal qo'shish

1. `👥 Mening Guruhlarim` → `🔄 Guruhlarni yuklash`
2. Ro'yxatdan keraklilarini `➕` bosib tanlang
3. (Faqat azo bo'lgan guruhlar va admin bo'lgan kanallar ko'rinadi)

### Auto-yuborish

1. `⚙️ Sozlamalar` — intervalini tanlang (1 daqiqa – 12 soat)
2. `▶️ Boshlash` — yuborish boshlanadi
3. `📊 Statistika` — holat va natijalarni ko'ring
4. `⏹ To'xtatish` — to'xtatish

---

## ⚙️ Sozlamalar

| Parametr | Qiymatlar | Standart |
|----------|-----------|---------|
| Interval | 1 daqiqa, 1/2/3/6/12 soat | 3 soat |
| Flood protection | Guruhlar orasida `asyncio.sleep(2)` | ✅ |
| FloodWait | Avtomatik kutish | ✅ |

---

## 🛡 Xavfsizlik

- `config.py` va `*.session` fayllar `.gitignore` da — repoga tushmaydi
- Faqat `ADMIN_ID` ga mos foydalanuvchi boshqara oladi
- Banned/chiqarib yuborilgan guruhlar xatosi ushlab logga yoziladi

---

## 📄 Litsenziya

[MIT](LICENSE) © 2026
