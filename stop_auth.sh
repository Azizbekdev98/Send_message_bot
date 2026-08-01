#!/bin/bash
pkill -f "auth_server.py" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
lsof -ti :8000 | xargs kill -9 2>/dev/null
echo "Auth server va tunnel to'xtatildi."
