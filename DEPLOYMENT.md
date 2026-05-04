# Oracle Cloud Ubuntu — Bot Deployment

## 1. Serverga ulanish

```bash
ssh ubuntu@<your-server-ip>
```

## 2. Docker o'rnatish

```bash
sudo apt update && sudo apt upgrade -y

# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# Docker Compose plugin
sudo apt install -y docker-compose-plugin

# Tekshirish
docker --version
docker compose version
```

## 3. Fayllarni yuklash

**Variant A — SCP bilan (lokal kompyuterdan):**
```bash
scp -r /path/to/send_messag_bot ubuntu@<your-server-ip>:~/reklama_bot
```

**Variant B — Serverda to'g'ridan-to'g'ri yaratish:**
```bash
mkdir ~/reklama_bot && cd ~/reklama_bot
nano bot.py        # kodni joylashtiring
nano config.py
nano requirements.txt
nano Dockerfile
nano docker-compose.yml
```

## 4. config.py ni sozlash

```bash
cd ~/reklama_bot
nano config.py
```

Quyidagilarni to'ldiring:
```python
BOT_TOKEN = "1234567890:AAH..."   # @BotFather dan olingan token
ADMIN_ID = 987654321              # Sizning Telegram ID ingiz (@userinfobot dan bilib olish mumkin)
```

Saqlash: `Ctrl+O`, `Enter`, `Ctrl+X`

## 5. data.json yaratish (birinchi marta)

```bash
touch ~/reklama_bot/data.json
```

## 6. Botni ishga tushirish

```bash
cd ~/reklama_bot
docker compose up -d --build
```

## 7. Foydali buyruqlar

```bash
# Loglarni ko'rish (real-time)
docker compose logs -f

# Oxirgi 50 qator log
docker compose logs --tail=50

# Botni to'xtatish
docker compose down

# Botni qayta ishga tushirish
docker compose restart

# Konteyner holati
docker compose ps
```

## 8. Bot yangilanishi (kod o'zgarganda)

```bash
cd ~/reklama_bot
docker compose down
docker compose up -d --build
```

## 9. Oracle Cloud Firewall (agar kerak bo'lsa)

Bot faqat outbound ulanishlardan foydalanadi — portlar ochish shart emas.

## 10. Muammolar

| Muammo | Yechim |
|--------|--------|
| Bot javob bermayapti | `docker compose logs -f` bilan xatoni toping |
| `Unauthorized` xatosi | `BOT_TOKEN` ni tekshiring |
| `Chat not found` | Botni guruhga qo'shing va admin qiling |
| Konteyner tushib qolyapti | `restart: always` avtomatik qayta ishga tushiradi |
