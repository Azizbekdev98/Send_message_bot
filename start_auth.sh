#!/bin/bash
# Auth server + tunnel ishga tushiradi, config.py ni yangilaydi
# Keyin: docker restart reklama_bot

cd "$(dirname "$0")"
mkdir -p logs

echo "Eski processlarni to'xtatmoqda..."
pkill -f "auth_server.py" 2>/dev/null
pkill -f "serveo.net" 2>/dev/null
lsof -ti :8000 | xargs kill -9 2>/dev/null
sleep 2

# Auth server
nohup python3 auth_server.py > logs/auth_server.log 2>&1 &
echo "Auth server ishga tushdi (PID: $!)"
sleep 3

# Serveo tunnel
nohup ssh -o StrictHostKeyChecking=no -R 80:localhost:8000 serveo.net > /tmp/serveo.log 2>&1 &
echo "Tunnel ishga tushdi (PID: $!)"

echo "URL kutilmoqda..."
URL=""
for i in {1..20}; do
  URL=$(grep -o 'https://[a-zA-Z0-9._-]*\.serveousercontent\.com' /tmp/serveo.log 2>/dev/null | head -1)
  [ -n "$URL" ] && break
  sleep 1
done

if [ -z "$URL" ]; then
  echo "⚠️  URL topilmadi. /tmp/serveo.log ni tekshiring."
  exit 1
fi

# URL ishlayotganini tekshiramiz
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/auth?user_id=1" --max-time 10)
if [ "$CODE" != "200" ]; then
  sleep 3
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/auth?user_id=1" --max-time 10)
fi

sed -i '' "s|AUTH_SERVER_URL = \".*\"|AUTH_SERVER_URL = \"$URL\"|" config.py

echo ""
echo "✅ Hammasi tayyor!"
echo "   URL: $URL (HTTP $CODE)"
echo ""
echo "Botni restart qiling:"
echo "   docker restart reklama_bot"
