#!/bin/bash
set -e

mkdir -p /app/users/auth

# auth_bridge va auth_server ni fonda ishga tushiramiz
python auth_bridge.py &
python auth_server.py &

# asosiy bot
exec python main.py
