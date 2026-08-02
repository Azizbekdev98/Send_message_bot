"""
Auth + Mini App Server — barcha funksiyalar web orqali.
"""
import asyncio
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, request, jsonify, redirect

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeExpiredError,
    PhoneCodeInvalidError, PhoneNumberInvalidError, FloodWaitError,
)

import config

API_ID            = config.API_ID
API_HASH          = config.API_HASH
BOT_TOKEN         = config.BOT_TOKEN
USERS_DIR         = Path("/app/users")
MEDIA_DIR         = Path("/app/users/media")
INPAY_BASE        = "https://inpay.uz/api/v1"
INPAY_MERCHANT_ID = config.INPAY_MERCHANT_ID
INPAY_MERCHANT_TOKEN = config.INPAY_MERCHANT_TOKEN
SUBSCRIPTION_PRICE= config.SUBSCRIPTION_PRICE
SUBSCRIPTION_DAYS = config.SUBSCRIPTION_DAYS
ADMIN_ID          = config.ADMIN_ID

_DEVICE = dict(
    device_model="Samsung Galaxy S23",
    system_version="Android 14",
    app_version="10.3.2",
    lang_code="uz",
    system_lang_code="uz-UZ",
)

_auth_sessions: dict[str, dict] = {}
_lock = threading.Lock()
_bearer_cache = {"token": None, "expires": 0}

app = Flask(__name__)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


# ── Helpers ────────────────────────────────────────────────────────────

def _load(uid: str) -> dict:
    path = USERS_DIR / f"{uid}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_data(uid: str, data: dict):
    path = USERS_DIR / f"{uid}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _uid(req) -> str:
    if req.method == "GET":
        return req.args.get("user_id", "")
    d = req.get_json(silent=True) or {}
    return str(d.get("user_id", ""))


def _has_sub(uid: str) -> bool:
    if uid and int(uid) == ADMIN_ID:
        return True
    data = _load(uid)
    exp = data.get("subscription_expires")
    if not exp:
        return False
    return datetime.fromisoformat(exp) > datetime.now()


def _sub_text(uid: str) -> str:
    if uid and int(uid) == ADMIN_ID:
        return "Admin (cheksiz)"
    data = _load(uid)
    exp = data.get("subscription_expires")
    if not exp:
        return "Obuna yo'q"
    dt = datetime.fromisoformat(exp)
    if dt < datetime.now():
        return "Obuna muddati o'tgan"
    days = (dt - datetime.now()).days
    return f"Obuna: {days} kun qoldi ({dt.strftime('%d.%m.%Y')})"


def _notify(uid: str, text: str):
    try:
        params = urllib.parse.urlencode({
            "chat_id": uid, "text": text, "parse_mode": "Markdown"
        }).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=params, timeout=10)
    except Exception:
        pass


def _get_bearer() -> str:
    if _bearer_cache["token"] and time.time() < _bearer_cache["expires"]:
        return _bearer_cache["token"]
    try:
        url = (f"{INPAY_BASE}/authorization/"
               f"?merchant_id={INPAY_MERCHANT_ID}&merchant_token={INPAY_MERCHANT_TOKEN}")
        resp = urllib.request.urlopen(url, timeout=15)
        d = json.loads(resp.read())
        tok = d.get("bearer_token")
        if tok:
            _bearer_cache["token"] = tok
            _bearer_cache["expires"] = time.time() + 23 * 3600
            return tok
    except Exception:
        pass
    return ""


def _run_in_thread(coro, timeout=60):
    result, error, done = [None], [None], threading.Event()
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result[0] = loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
        except Exception as e:
            error[0] = e
        finally:
            loop.close()
            done.set()
    threading.Thread(target=run, daemon=True).start()
    done.wait(timeout + 5)
    if error[0]:
        raise error[0]
    return result[0]


# ── Auth (login) session helpers ────────────────────────────────────────

def _ensure_loop(uid: str):
    with _lock:
        if uid not in _auth_sessions:
            loop = asyncio.new_event_loop()
            client = TelegramClient(StringSession(), API_ID, API_HASH, **_DEVICE)
            _auth_sessions[uid] = {"client": client, "loop": loop, "phone": None, "hash": None}
        sess = _auth_sessions[uid]
    if not sess["loop"].is_running():
        threading.Thread(target=sess["loop"].run_forever, daemon=True).start()
    return sess


def _run_auth(uid: str, coro):
    sess = _ensure_loop(uid)
    return asyncio.run_coroutine_threadsafe(coro, sess["loop"]).result(timeout=30)


def _save_auth(uid: str, phone: str, session_str: str):
    path = USERS_DIR / f"{uid}.json"
    d = json.loads(path.read_text()) if path.exists() else {
        "user_id": int(uid), "phone": phone, "groups": [],
        "templates": [], "is_running": False, "next_template_id": 1,
        "stats": {"total_sent": 0, "successful": 0, "failed": 0, "last_sent": None},
    }
    d["phone"] = phone
    d["session_string"] = session_str
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    path.chmod(0o777)
    with _lock:
        _auth_sessions.pop(uid, None)


# ── AUTH HTML ──────────────────────────────────────────────────────────

AUTH_HTML = """<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Reklama Bot — Kirish</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:var(--tg-theme-bg-color,#fff);
  color:var(--tg-theme-text-color,#000);padding:20px;min-height:100vh}
.container{max-width:400px;margin:0 auto;padding-top:20px}
h2{font-size:20px;margin-bottom:8px}
.hint{font-size:14px;color:var(--tg-theme-hint-color,#888);margin-bottom:20px}
input{width:100%;padding:14px;border-radius:10px;
  border:1.5px solid var(--tg-theme-hint-color,#ccc);
  background:var(--tg-theme-secondary-bg-color,#f5f5f5);
  color:var(--tg-theme-text-color,#000);
  font-size:16px;margin-bottom:12px;outline:none;display:block}
input:focus{border-color:#0088cc}
.btn{width:100%;padding:14px;background:var(--tg-theme-button-color,#0088cc);
  color:var(--tg-theme-button-text-color,#fff);border:none;border-radius:10px;
  font-size:16px;font-weight:600;cursor:pointer;display:block;text-align:center;margin-bottom:10px}
.btn:disabled{opacity:.55;cursor:default}
.ghost{background:transparent;color:var(--tg-theme-hint-color,#888);font-weight:400;font-size:14px;padding:8px}
.err{color:#e53935;font-size:14px;margin:6px 0 10px;min-height:18px}
.step{display:none}.step.active{display:block}
.done{text-align:center;padding:50px 0}
.done .icon{font-size:64px;margin-bottom:16px}
.done h2{font-size:22px;color:#43a047}
</style>
</head>
<body>
<div class="container">
  <div class="step active" id="s-phone">
    <h2>📱 Kirish</h2>
    <p class="hint">Telegram raqamingizni kiriting</p>
    <input id="i-phone" type="tel" placeholder="+998901234567" autocomplete="tel">
    <div class="err" id="e-phone"></div>
    <button class="btn" id="b-phone">Davom etish &rarr;</button>
  </div>
  <div class="step" id="s-code">
    <h2>&#128272; Tasdiqlash kodi</h2>
    <p class="hint">Telegramga yuborilgan kodni kiriting</p>
    <input id="i-code" type="text" placeholder="12345" inputmode="numeric" maxlength="8">
    <div class="err" id="e-code"></div>
    <button class="btn" id="b-code">Tasdiqlash &rarr;</button>
    <button class="btn ghost" id="b-resend">Kodni qayta yuborish</button>
  </div>
  <div class="step" id="s-2fa">
    <h2>&#128273; 2FA parol</h2>
    <p class="hint">Telegram parolingizni kiriting</p>
    <input id="i-2fa" type="password" placeholder="Parol">
    <div class="err" id="e-2fa"></div>
    <button class="btn" id="b-2fa">Kirish &rarr;</button>
  </div>
  <div class="step" id="s-done">
    <div class="done">
      <div class="icon">&#9989;</div>
      <h2>Muvaffaqiyatli!</h2>
      <p class="hint" style="margin-top:12px">Botga qayting va /start bosing</p>
    </div>
  </div>
</div>
<script>
var tg=window.Telegram&&window.Telegram.WebApp;
if(tg){tg.ready();tg.expand();}
var uid=new URLSearchParams(location.search).get('user_id');
if(!uid&&tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user)uid=String(tg.initDataUnsafe.user.id);

function show(n){document.querySelectorAll('.step').forEach(function(s){s.classList.remove('active')});document.getElementById('s-'+n).classList.add('active')}
function err(id,m){var e=document.getElementById(id);if(e)e.textContent=m||''}
function busy(id,b,lbl){var e=document.getElementById(id);if(!e)return;e.disabled=b;if(!b&&lbl)e.textContent=lbl}

function post(path,body,cb){
  body.user_id=uid;
  var x=new XMLHttpRequest();
  x.open('POST',path,true);
  x.setRequestHeader('Content-Type','application/json');
  x.onreadystatechange=function(){if(x.readyState===4){try{cb(null,JSON.parse(x.responseText))}catch(e){cb('Server xatosi',null)}}};
  x.onerror=function(){cb('Tarmoq xatosi',null)};
  x.send(JSON.stringify(body));
}

document.getElementById('b-phone').addEventListener('click',function(){
  var p=document.getElementById('i-phone').value.trim();
  if(!p){err('e-phone','Raqam kiriting');return}
  busy('b-phone',true);err('e-phone','');
  post('/api/send_code',{phone:p},function(e,r){
    busy('b-phone',false,'Davom etish →');
    if(e){err('e-phone',e);return}
    if(r.ok)show('code');else err('e-phone',r.error||'Xato');
  });
});

document.getElementById('b-code').addEventListener('click',function(){
  var c=document.getElementById('i-code').value.trim().replace(/[\s\-]/g,'');
  if(!c){err('e-code','Kodni kiriting');return}
  busy('b-code',true);err('e-code','');
  post('/api/sign_in',{code:c},function(e,r){
    busy('b-code',false,'Tasdiqlash →');
    if(e){err('e-code',e);return}
    if(r.ok){show('done');if(tg)setTimeout(function(){tg.close()},2000)}
    else if(r.need_2fa)show('2fa')
    else if(r.code_expired){document.getElementById('i-code').value='';err('e-code',"Kod muddati o'tdi — yangi kod yuborildi!")}
    else err('e-code',r.error||'Xato');
  });
});

document.getElementById('b-resend').addEventListener('click',function(){
  var p=document.getElementById('i-phone').value.trim();
  if(!p){show('phone');return}
  err('e-code','⏳ Yuborilmoqda...');
  post('/api/send_code',{phone:p},function(e,r){
    err('e-code',e||(r.ok?'✅ Yangi kod yuborildi':(r.error||'Xato')));
  });
});

document.getElementById('b-2fa').addEventListener('click',function(){
  var p=document.getElementById('i-2fa').value;
  if(!p){err('e-2fa','Parol kiriting');return}
  busy('b-2fa',true);err('e-2fa','');
  post('/api/sign_in_2fa',{password:p},function(e,r){
    busy('b-2fa',false,'Kirish →');
    if(e){err('e-2fa',e);return}
    if(r.ok){show('done');if(tg)setTimeout(function(){tg.close()},2000)}
    else err('e-2fa',r.error||"Noto'g'ri parol");
  });
});
</script>
</body>
</html>"""


# ── MAIN APP HTML (SPA) ────────────────────────────────────────────────

APP_HTML = """<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Reklama Bot</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:var(--tg-theme-secondary-bg-color,#f2f2f7);
  color:var(--tg-theme-text-color,#000);
  height:100vh;display:flex;flex-direction:column;overflow:hidden}
.content{flex:1;overflow-y:auto;padding:12px;padding-bottom:68px}
/* Nav */
.nav{position:fixed;bottom:0;left:0;right:0;height:56px;
  background:var(--tg-theme-bg-color,#fff);
  border-top:1px solid rgba(0,0,0,.1);display:flex;z-index:100}
.nb{flex:1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;background:none;border:none;cursor:pointer;
  color:var(--tg-theme-hint-color,#888);font-size:10px;padding:4px 0;gap:2px}
.nb .ic{font-size:20px;line-height:1}
.nb.on{color:var(--tg-theme-button-color,#0088cc)}
/* Tab */
.tab{display:none}.tab.on{display:block}
/* Card */
.card{background:var(--tg-theme-bg-color,#fff);border-radius:12px;padding:14px;margin-bottom:10px}
/* Buttons */
.btn{width:100%;padding:13px;background:var(--tg-theme-button-color,#0088cc);
  color:var(--tg-theme-button-text-color,#fff);border:none;border-radius:10px;
  font-size:15px;font-weight:600;cursor:pointer;margin-bottom:8px;display:block}
.btn:disabled{opacity:.5}
.btn.red{background:#e53935}.btn.green{background:#43a047}
.btn.out{background:transparent;border:1.5px solid var(--tg-theme-button-color,#0088cc);
  color:var(--tg-theme-button-color,#0088cc)}
.btn.sm{width:auto;padding:6px 14px;font-size:13px;border-radius:8px;margin-bottom:0}
.big-toggle{display:block;width:100%;padding:18px;font-size:18px;font-weight:700;
  border:none;border-radius:16px;color:#fff;cursor:pointer;
  transition:transform .1s,opacity .2s;letter-spacing:.3px}
.big-toggle.green{background:linear-gradient(135deg,#22c55e,#16a34a);
  box-shadow:0 4px 15px rgba(34,197,94,.35)}
.big-toggle.red{background:linear-gradient(135deg,#ef4444,#dc2626);
  box-shadow:0 4px 15px rgba(239,68,68,.35)}
.big-toggle:active{transform:scale(.97)}
.big-toggle:disabled{opacity:.6;transform:none}
/* Input */
.inp{width:100%;padding:12px;background:var(--tg-theme-secondary-bg-color,#f2f2f7);
  border:1.5px solid transparent;border-radius:10px;font-size:15px;
  color:var(--tg-theme-text-color,#000);margin-bottom:10px;outline:none;display:block}
.inp:focus{border-color:var(--tg-theme-button-color,#0088cc)}
textarea.inp{resize:none}
/* List item */
.li{display:flex;align-items:center;padding:11px 0;
  border-bottom:1px solid rgba(0,0,0,.06)}
.li:last-child{border:none}
/* Toggle */
.tgl{width:42px;height:24px;background:#ccc;border-radius:12px;
  position:relative;cursor:pointer;transition:background .2s;flex-shrink:0}
.tgl.on{background:#43a047}
.tgl::after{content:'';width:20px;height:20px;background:#fff;border-radius:50%;
  position:absolute;top:2px;left:2px;transition:left .2s}
.tgl.on::after{left:20px}
/* Stats grid */
.sg{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.sc{background:var(--tg-theme-bg-color,#fff);border-radius:12px;padding:12px;text-align:center}
.sv{font-size:22px;font-weight:700}
.sl{font-size:11px;color:var(--tg-theme-hint-color,#888);margin-top:2px}
/* Badge */
.badge{display:inline-flex;align-items:center;padding:3px 10px;border-radius:20px;font-size:13px;font-weight:600}
.b-on{background:#e8f5e9;color:#2e7d32}.b-off{background:#f5f5f5;color:#757575}
/* Section label */
.slbl{font-size:12px;font-weight:600;color:var(--tg-theme-hint-color,#888);
  text-transform:uppercase;letter-spacing:.5px;margin:12px 0 6px 4px}
/* Modal */
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:200;align-items:flex-end}
.modal.show{display:flex}
.mc{background:var(--tg-theme-bg-color,#fff);border-radius:20px 20px 0 0;
  padding:20px;width:100%;max-height:85vh;overflow-y:auto}
.mtitle{font-size:17px;font-weight:700;margin-bottom:14px}
/* Interval grid */
.ivg{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.ivb{padding:8px;border-radius:8px;border:1.5px solid #ddd;background:transparent;
  font-size:13px;cursor:pointer;color:var(--tg-theme-text-color,#000)}
.ivb.sel{border-color:var(--tg-theme-button-color,#0088cc);
  background:var(--tg-theme-button-color,#0088cc);
  color:var(--tg-theme-button-text-color,#fff)}
/* Spinner */
.spin{width:28px;height:28px;border:3px solid rgba(0,0,0,.1);
  border-top-color:var(--tg-theme-button-color,#0088cc);
  border-radius:50%;animation:sp .7s linear infinite;margin:20px auto;display:block}
@keyframes sp{to{transform:rotate(360deg)}}
.hint-txt{font-size:13px;color:var(--tg-theme-hint-color,#888);text-align:center;padding:16px 0}
.err-txt{color:#e53935;font-size:13px;margin-bottom:8px}
/* Admin */
.ag{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.ac{background:var(--tg-theme-bg-color,#fff);border-radius:12px;padding:12px;text-align:center}
.ac .av{font-size:20px;font-weight:700}
.ac .al{font-size:10px;color:var(--tg-theme-hint-color,#888);margin-top:2px;text-transform:uppercase;letter-spacing:.3px}
.ua{display:flex;align-items:center;gap:10px;padding:11px 0;border-bottom:1px solid rgba(0,0,0,.06)}
.ua:last-child{border:none}
.ua .dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.ua .dot.g{background:#22c55e}.ua .dot.y{background:#f59e0b}.ua .dot.gray{background:#bbb}
.ua .ui{flex:1;min-width:0}
.ua .up{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ua .us{font-size:11px;color:var(--tg-theme-hint-color,#888);margin-top:1px}
.ua .ub{font-size:11px;font-weight:700;padding:5px 9px;border-radius:8px;border:none;
  background:var(--tg-theme-button-color,#0088cc);color:var(--tg-theme-button-text-color,#fff);
  cursor:pointer;flex-shrink:0}
.ua .ub:disabled{opacity:.5}
.chip{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;border-radius:6px;margin-left:6px}
.chip.run{background:#e3f2fd;color:#1565c0}
.search{width:100%;padding:10px 12px;background:var(--tg-theme-secondary-bg-color,#f2f2f7);
  border:1.5px solid transparent;border-radius:10px;font-size:14px;
  color:var(--tg-theme-text-color,#000);margin-bottom:10px;outline:none;display:block}
.tpl-pick{display:flex;align-items:center;gap:10px;padding:12px;border-radius:10px;
  border:1.5px solid #ddd;margin-bottom:8px;cursor:pointer}
.tpl-pick.sel{border-color:var(--tg-theme-button-color,#0088cc);background:rgba(0,136,204,.06)}
.bres{padding:12px;border-radius:10px;background:var(--tg-theme-secondary-bg-color,#f2f2f7);font-size:13px;line-height:1.7}
</style>
</head>
<body>

<nav class="nav">
  <button class="nb on" data-p="dash"><span class="ic">&#127968;</span>Bosh</button>
  <button class="nb" data-p="groups"><span class="ic">&#128101;</span>Guruhlar</button>
  <button class="nb" data-p="tpl"><span class="ic">&#128221;</span>Shablonlar</button>
  <button class="nb" data-p="stats"><span class="ic">&#128202;</span>Statistika</button>
  <button class="nb" data-p="admin" id="nb-admin" style="display:none"><span class="ic">&#128737;&#65039;</span>Admin</button>
</nav>

<div class="content">

  <!-- DASHBOARD -->
  <div id="p-dash" class="tab on">
    <div class="card" style="text-align:center;padding:22px 14px">
      <div id="d-phone" style="font-size:13px;color:var(--tg-theme-hint-color,#888);margin-bottom:12px">&#128241; —</div>
      <div id="d-badge" class="badge b-off" style="display:inline-flex;margin:0 auto 18px">&#9208; To'xtatilgan</div>
      <button class="big-toggle green" id="b-toggle">&#9654; Boshlash</button>
    </div>
    <div class="sg">
      <div class="sc"><div class="sv" id="d-gc">—</div><div class="sl">&#128101; Guruhlar</div></div>
      <div class="sc"><div class="sv" id="d-tc">—</div><div class="sl">&#128221; Shablonlar</div></div>
      <div class="sc"><div class="sv" id="d-sent">—</div><div class="sl">&#128228; Yuborildi</div></div>
      <div class="sc"><div class="sv" id="d-fail">—</div><div class="sl">&#10060; Xatolik</div></div>
    </div>
    <div class="card">
      <div id="d-sub" style="font-size:13px;color:var(--tg-theme-hint-color,#888)">&#128179; Yuklanmoqda...</div>
      <button class="btn out" id="b-sub" style="display:none;margin-top:10px">&#128179; Obuna olish</button>
    </div>
  </div>

  <!-- GROUPS -->
  <div id="p-groups" class="tab">
    <button class="btn" id="b-fetch">&#128260; Telegramdan yuklash</button>
    <div id="g-loading" style="display:none"><span class="spin"></span></div>
    <div id="g-dialogs" style="display:none">
      <div class="slbl" id="g-dlbl">Guruhlar</div>
      <div class="card" id="g-dlist"></div>
    </div>
    <div class="slbl">Tanlangan guruhlar</div>
    <div id="g-myload"><span class="spin"></span></div>
    <div class="card" id="g-mylist" style="display:none"></div>
    <div id="g-empty" class="hint-txt" style="display:none">Hali guruh qo'shilmagan</div>
  </div>

  <!-- TEMPLATES -->
  <div id="p-tpl" class="tab">
    <button class="btn" id="b-addtpl">&#10133; Yangi shablon qo'shish</button>
    <div id="t-loading"><span class="spin"></span></div>
    <div id="t-list" style="display:none"></div>
    <div id="t-empty" class="hint-txt" style="display:none">Hali shablon yo'q</div>
  </div>

  <!-- STATS -->
  <div id="p-stats" class="tab">
    <div class="card">
      <div class="slbl" style="margin-top:0">&#128202; Statistika</div>
      <div id="st-body"><span class="spin"></span></div>
    </div>
    <div class="card">
      <div class="slbl" style="margin-top:0">&#128179; Obuna</div>
      <div id="sub-body"><span class="spin"></span></div>
    </div>
  </div>

  <!-- ADMIN -->
  <div id="p-admin" class="tab">
    <div class="ag" id="ao-grid">
      <div class="ac"><div class="av" id="ao-total">—</div><div class="al">Jami</div></div>
      <div class="ac"><div class="av" id="ao-sub">—</div><div class="al">Obunali</div></div>
      <div class="ac"><div class="av" id="ao-run">—</div><div class="al">Yubormoqda</div></div>
      <div class="ac"><div class="av" id="ao-nosess">—</div><div class="al">Sessiyasiz</div></div>
      <div class="ac" style="grid-column:1/3"><div class="av" id="ao-groups">—</div><div class="al">Jami guruhlar</div></div>
    </div>

    <div class="slbl">&#128101; Foydalanuvchilar</div>
    <input class="search" id="au-search" placeholder="Telefon yoki ID bo'yicha qidirish...">
    <div id="au-loading"><span class="spin"></span></div>
    <div class="card" id="au-list" style="display:none"></div>
    <div id="au-empty" class="hint-txt" style="display:none">Foydalanuvchi topilmadi</div>

    <div class="slbl">&#128226; Barcha guruhlarga yuborish</div>
    <div class="card" id="ab-card">
      <div id="ab-loading"><span class="spin"></span></div>
      <div id="ab-body" style="display:none"></div>
    </div>
  </div>

</div>

<!-- Modal: qo'shish -->
<div class="modal" id="m-add">
  <div class="mc">
    <div class="mtitle">&#128221; Yangi Shablon</div>
    <input class="inp" id="mn-name" placeholder="Shablon nomi">
    <div style="margin-bottom:10px">
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-bottom:8px">
        <input type="radio" name="mtype" value="text" checked> Matnli shablon
      </label>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
        <input type="radio" name="mtype" value="photo"> Rasmli shablon
      </label>
    </div>
    <input type="file" id="mn-photo" accept="image/*" style="display:none;margin-bottom:10px">
    <textarea class="inp" id="mn-text" placeholder="Shablon matni..." rows="4"></textarea>
    <div class="err-txt" id="mn-err"></div>
    <button class="btn" id="mn-save">&#9989; Saqlash</button>
    <button class="btn out" id="mn-cancel">&#10060; Bekor qilish</button>
  </div>
</div>

<!-- Modal: tahrirlash -->
<div class="modal" id="m-edit">
  <div class="mc">
    <div class="mtitle">&#9999;&#65039; Shablonni tahrirlash</div>
    <input type="hidden" id="me-id">
    <input type="hidden" id="me-type">
    <div id="me-photo-wrap" style="display:none;margin-bottom:14px">
      <div id="me-photo-preview" style="display:none;margin-bottom:10px">
        <img id="me-photo-img" src="" alt="" style="width:100%;max-height:180px;object-fit:cover;border-radius:10px;display:block">
      </div>
      <label id="me-photo-label" style="display:flex;align-items:center;justify-content:center;gap:10px;cursor:pointer;padding:14px;border:2px dashed var(--tg-theme-button-color,#0088cc);border-radius:12px;font-size:15px;color:var(--tg-theme-button-color,#0088cc);font-weight:600">
        &#128247; Rasmni almashtirish
        <input type="file" id="me-photo" accept="image/*" style="display:none">
      </label>
      <div id="me-photo-name" style="display:none;font-size:13px;color:var(--tg-theme-hint-color,#888);margin-top:6px;text-align:center"></div>
    </div>
    <textarea class="inp" id="me-text" placeholder="Shablon matni..." rows="6" style="font-size:15px"></textarea>
    <div class="err-txt" id="me-err"></div>
    <button class="btn" id="me-save" style="padding:15px;font-size:16px">&#9989; Saqlash</button>
    <button class="btn out" id="me-cancel">&#10060; Bekor qilish</button>
  </div>
</div>

<!-- Modal: interval -->
<div class="modal" id="m-iv">
  <div class="mc">
    <div class="mtitle" id="iv-title">&#9201;&#65039; Interval</div>
    <input type="hidden" id="iv-id">
    <div class="ivg" id="iv-grid"></div>
    <button class="btn out" id="iv-cancel">Bekor qilish</button>
  </div>
</div>

<!-- Modal: sovga -->
<div class="modal" id="m-gift">
  <div class="mc">
    <div class="mtitle">&#127873; Obuna sovga qilish</div>
    <div id="gf-who" style="font-size:14px;color:var(--tg-theme-hint-color,#888);margin-bottom:12px"></div>
    <div class="ivg" id="gf-days">
      <button class="ivb" data-d="7">7 kun</button>
      <button class="ivb sel" data-d="30">30 kun</button>
      <button class="ivb" data-d="90">90 kun</button>
    </div>
    <div class="err-txt" id="gf-err"></div>
    <button class="btn" id="gf-save">&#9989; Sovga qilish</button>
    <button class="btn out" id="gf-cancel">&#10060; Bekor qilish</button>
  </div>
</div>

<script>
var tg=window.Telegram&&window.Telegram.WebApp;
if(tg){tg.ready();tg.expand();}
var uid=new URLSearchParams(location.search).get('user_id');
if(!uid&&tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user)uid=String(tg.initDataUnsafe.user.id);
if(!uid){document.body.innerHTML='<div style="padding:40px;text-align:center;font-family:sans-serif"><p style="font-size:16px">&#128274; Botni Telegram orqali oching</p></div>';}

var _dialogs=[],_myGroups=[],_tpls=[];

var IVLIST=[
  {l:'30 daqiqa',v:30},{l:'1 soat',v:60},{l:'2 soat',v:120},
  {l:'3 soat',v:180},{l:'4 soat',v:240},{l:'6 soat',v:360},
  {l:'8 soat',v:480},{l:'12 soat',v:720},{l:'24 soat',v:1440}
];

/* ── Nav ── */
document.querySelectorAll('.nb').forEach(function(b){
  b.addEventListener('click',function(){
    var p=this.getAttribute('data-p');
    document.querySelectorAll('.nb').forEach(function(x){x.classList.remove('on')});
    document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('on')});
    this.classList.add('on');
    document.getElementById('p-'+p).classList.add('on');
    if(p==='groups')loadGroups();
    if(p==='tpl')loadTpl();
    if(p==='stats')loadStats();
    if(p==='admin')loadAdmin();
  });
});

/* ── XHR helpers ── */
function xhr(method,path,data,cb){
  var x=new XMLHttpRequest(),url=path;
  if(method==='GET'&&data){
    url+='?'+Object.keys(data).map(function(k){return encodeURIComponent(k)+'='+encodeURIComponent(data[k])}).join('&');
  }
  x.open(method,url,true);
  if(method!=='GET')x.setRequestHeader('Content-Type','application/json');
  x.onreadystatechange=function(){if(x.readyState===4){try{cb(null,JSON.parse(x.responseText))}catch(e){cb('Server xatosi',null)}}};
  x.onerror=function(){cb('Tarmoq xatosi',null)};
  if(method==='GET')x.send();
  else x.send(JSON.stringify(Object.assign({},data||{},{user_id:uid})));
}

function xhrForm(path,fd,cb){
  fd.append('user_id',uid);
  var x=new XMLHttpRequest();
  x.open('POST',path,true);
  x.onreadystatechange=function(){if(x.readyState===4){try{cb(null,JSON.parse(x.responseText))}catch(e){cb('Server xatosi',null)}}};
  x.onerror=function(){cb('Tarmoq xatosi',null)};
  x.send(fd);
}

function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

/* ── Dashboard ── */
function loadDash(){
  xhr('GET','/api/data',{user_id:uid},function(e,d){
    if(e||!d){return;}
    if(d.need_auth){location.href='/auth?user_id='+uid;return;}
    var run=d.is_running;
    var badge=document.getElementById('d-badge');
    var btn=document.getElementById('b-toggle');
    badge.className='badge '+(run?'b-on':'b-off');
    badge.innerHTML=run?'&#9989; Ishlayapti':"&#9208; To'xtatilgan";
    btn.innerHTML=run?"&#9209; To'xtatish":"&#9654; Boshlash";
    btn.className='big-toggle '+(run?'red':'green');
    document.getElementById('d-phone').textContent='📱 '+(d.phone||'—');
    document.getElementById('d-gc').textContent=d.groups_count;
    document.getElementById('d-tc').textContent=(d.active_tpl||0)+'/'+d.tpl_count;
    document.getElementById('d-sent').textContent=d.stats.total_sent;
    document.getElementById('d-fail').textContent=d.stats.failed;
    var sub=document.getElementById('d-sub');
    sub.textContent='💳 '+d.sub_text;
    document.getElementById('b-sub').style.display=d.sub_active?'none':'block';
  });
}

document.getElementById('b-toggle').addEventListener('click',function(){
  var btn=this,run=btn.classList.contains('red');
  btn.disabled=true;
  xhr('POST',run?'/api/stop':'/api/start',{},function(e,r){
    btn.disabled=false;
    if(e){alert(e);return}
    if(r&&r.ok)loadDash();
    else alert((r&&r.error)||'Xato');
  });
});

document.getElementById('b-sub').addEventListener('click',function(){
  var btn=this;btn.disabled=true;btn.innerHTML='&#9203; Yuklanmoqda...';
  xhr('POST','/api/subscribe',{},function(e,r){
    btn.disabled=false;btn.innerHTML='&#128179; Obuna olish';
    if(e){alert(e);return}
    if(r&&r.pay_url){
      if(tg)tg.openLink(r.pay_url);else window.open(r.pay_url,'_blank');
      var bsub=document.getElementById('b-sub');
      if(bsub){
        bsub.style.display='none';
        var chk=document.createElement('button');
        chk.className='btn out';chk.style.marginTop='8px';
        chk.innerHTML='&#9989; To&#x2019;ladim &#8212; tekshirish';
        chk.onclick=function(){
          chk.disabled=true;chk.innerHTML='&#9203; Tekshirilmoqda...';
          xhr('POST','/api/check_payment',{},function(e2,r2){
            chk.disabled=false;
            if(e2){chk.innerHTML='&#9989; To&#x2019;ladim &#8212; tekshirish';alert(e2);return}
            if(r2&&r2.activated){
              chk.parentNode.innerHTML='<div style="color:#2e7d32;font-weight:600">&#9989; Obuna faollashtirildi!</div>';
              loadDash();
            } else {
              chk.innerHTML='&#9989; To&#x2019;ladim &#8212; tekshirish';
              alert("To\x27lov hali tasdiqlanmadi. 1-2 daqiqa kuting.");
            }
          });
        };
        bsub.parentNode.insertBefore(chk,bsub.nextSibling);
      }
    } else alert((r&&r.error)||"To\x27lov tizimida xato");
  });
});

/* ── Groups ── */
function loadGroups(){
  document.getElementById('g-myload').style.display='block';
  document.getElementById('g-mylist').style.display='none';
  document.getElementById('g-empty').style.display='none';
  xhr('GET','/api/groups',{user_id:uid},function(e,r){
    document.getElementById('g-myload').style.display='none';
    if(e||!r)return;
    _myGroups=r.groups||[];
    renderMyGroups();
  });
}

function renderMyGroups(){
  var el=document.getElementById('g-mylist');
  if(!_myGroups.length){el.style.display='none';document.getElementById('g-empty').style.display='block';return}
  el.style.display='block';document.getElementById('g-empty').style.display='none';
  el.innerHTML=_myGroups.map(function(g){
    return '<div class="li"><span style="flex:1">'+esc(g.title)+'</span>'+
      '<button class="btn red sm" onclick="rmGroup('+g.chat_id+')">&#128465;</button></div>';
  }).join('');
}

function rmGroup(cid){
  xhr('POST','/api/groups/remove',{chat_id:cid},function(e,r){
    if(e){alert(e);return}
    if(r&&r.ok){_myGroups=_myGroups.filter(function(g){return g.chat_id!==cid});renderMyGroups();renderDialogs();}
  });
}

document.getElementById('b-fetch').addEventListener('click',function(){
  var btn=this;btn.disabled=true;btn.textContent='⏳ Yuklanmoqda...';
  document.getElementById('g-loading').style.display='block';
  document.getElementById('g-dialogs').style.display='none';
  xhr('GET','/api/dialogs',{user_id:uid},function(e,r){
    btn.disabled=false;btn.textContent='🔄 Telegramdan yuklash';
    document.getElementById('g-loading').style.display='none';
    if(e){alert(e);return}
    if(!r||!r.dialogs){alert((r&&r.error)||'Xato');return}
    _dialogs=r.dialogs;
    document.getElementById('g-dlbl').textContent='Guruhlar ('+_dialogs.length+' ta)';
    renderDialogs();
    document.getElementById('g-dialogs').style.display='block';
  });
});

function renderDialogs(){
  var ids=_myGroups.map(function(g){return g.chat_id});
  document.getElementById('g-dlist').innerHTML=_dialogs.map(function(d,i){
    var on=ids.indexOf(d.chat_id)!==-1;
    return '<div class="li"><span style="flex:1">'+esc(d.title)+'</span>'+
      '<div class="tgl '+(on?'on':'')+'" onclick="tglDlg('+i+')"></div></div>';
  }).join('');
}

function tglDlg(i){
  var d=_dialogs[i];
  var ids=_myGroups.map(function(g){return g.chat_id});
  var inList=ids.indexOf(d.chat_id)!==-1;
  xhr('POST','/api/groups/toggle',{chat_id:d.chat_id,title:d.title,username:d.username||''},function(e,r){
    if(e){alert(e);return}
    if(r&&r.ok){
      if(inList)_myGroups=_myGroups.filter(function(g){return g.chat_id!==d.chat_id});
      else _myGroups.push({chat_id:d.chat_id,title:d.title});
      renderDialogs();renderMyGroups();
    }
  });
}

/* ── Templates ── */
function loadTpl(){
  document.getElementById('t-loading').style.display='block';
  document.getElementById('t-list').style.display='none';
  document.getElementById('t-empty').style.display='none';
  xhr('GET','/api/templates',{user_id:uid},function(e,r){
    document.getElementById('t-loading').style.display='none';
    if(e||!r)return;
    _tpls=r.templates||[];
    renderTpl();
  });
}

function ivStr(m){var h=Math.floor(m/60),mn=m%60;return mn?(h+'s '+mn+'d'):(h+' soat')}

function renderTpl(){
  var el=document.getElementById('t-list');
  if(!_tpls.length){el.style.display='none';document.getElementById('t-empty').style.display='block';return}
  document.getElementById('t-empty').style.display='none';el.style.display='block';
  el.innerHTML=_tpls.map(function(t){
    var ic=t.type==='photo'?'&#128247;':'&#128221;';
    var txt=esc(t.text.substring(0,80))+(t.text.length>80?'...':'');
    return '<div class="card" style="margin-bottom:10px">'+
      '<div style="display:flex;align-items:center;margin-bottom:8px">'+
        '<div class="tgl '+(t.is_active?'on':'')+'" onclick="tglTpl('+t.id+')" style="margin-right:10px"></div>'+
        '<span style="flex:1;font-weight:600">'+ic+' '+esc(t.name)+'</span>'+
      '</div>'+
      '<div style="font-size:13px;color:var(--tg-theme-hint-color,#888);margin-bottom:10px">'+txt+'</div>'+
      '<div style="display:flex;gap:6px">'+
        '<span style="font-size:12px;color:var(--tg-theme-hint-color,#888);align-self:center;flex:1">&#9201;&#65039; '+ivStr(t.interval_minutes||180)+'</span>'+
        '<button class="btn out sm" onclick="openIv('+t.id+')">&#9201;&#65039;</button>'+
        '<button class="btn out sm" onclick="openEdit('+t.id+')">&#9999;&#65039;</button>'+
        '<button class="btn red sm" onclick="delTpl('+t.id+')">&#128465;</button>'+
      '</div>'+
      '</div>';
  }).join('');
}

function tglTpl(id){
  xhr('POST','/api/templates/toggle',{tpl_id:id},function(e,r){
    if(e){alert(e);return}
    if(r&&r.ok){var t=_tpls.find(function(x){return x.id===id});if(t)t.is_active=!t.is_active;renderTpl();}
  });
}

function delTpl(id){
  if(!confirm("Bu shablonni o'chirasizmi?"))return;
  xhr('POST','/api/templates/delete',{tpl_id:id},function(e,r){
    if(e){alert(e);return}
    if(r&&r.ok){_tpls=_tpls.filter(function(x){return x.id!==id});renderTpl();}
  });
}

/* Add modal */
document.getElementById('b-addtpl').addEventListener('click',function(){
  document.getElementById('mn-name').value='';
  document.getElementById('mn-text').value='';
  document.getElementById('mn-err').textContent='';
  document.getElementById('mn-photo').value='';
  document.getElementById('mn-photo').style.display='none';
  document.querySelector('input[name="mtype"][value="text"]').checked=true;
  document.getElementById('m-add').classList.add('show');
});
document.querySelectorAll('input[name="mtype"]').forEach(function(r){
  r.addEventListener('change',function(){
    document.getElementById('mn-photo').style.display=this.value==='photo'?'block':'none';
  });
});
document.getElementById('mn-cancel').addEventListener('click',function(){document.getElementById('m-add').classList.remove('show')});
document.getElementById('mn-save').addEventListener('click',function(){
  var btn=this;
  var nm=document.getElementById('mn-name').value.trim();
  var tx=document.getElementById('mn-text').value.trim();
  var tp=document.querySelector('input[name="mtype"]:checked').value;
  var ph=document.getElementById('mn-photo').files[0];
  if(!nm){document.getElementById('mn-err').textContent='Nom kiriting';return}
  if(!tx){document.getElementById('mn-err').textContent='Matn kiriting';return}
  if(tp==='photo'&&!ph){document.getElementById('mn-err').textContent='Rasm tanlang';return}
  btn.disabled=true;document.getElementById('mn-err').textContent='';
  var fd=new FormData();
  fd.append('name',nm);fd.append('text',tx);fd.append('type',tp);
  if(ph)fd.append('photo',ph);
  xhrForm('/api/templates/add',fd,function(e,r){
    btn.disabled=false;
    if(e){document.getElementById('mn-err').textContent=e;return}
    if(r&&r.ok){document.getElementById('m-add').classList.remove('show');loadTpl();}
    else document.getElementById('mn-err').textContent=(r&&r.error)||'Xato';
  });
});

/* Edit modal */
function openEdit(id){
  var t=_tpls.find(function(x){return x.id===id});if(!t)return;
  document.getElementById('me-id').value=id;
  document.getElementById('me-type').value=t.type||'text';
  document.getElementById('me-text').value=t.text||'';
  document.getElementById('me-err').textContent='';
  document.getElementById('me-photo').value='';
  document.getElementById('me-photo-name').style.display='none';
  document.getElementById('me-photo-preview').style.display='none';
  var isPhoto=t.type==='photo';
  document.getElementById('me-photo-wrap').style.display=isPhoto?'block':'none';
  document.getElementById('m-edit').classList.add('show');
}
document.getElementById('me-photo').addEventListener('change',function(){
  var f=this.files[0];
  var nm=document.getElementById('me-photo-name');
  var pv=document.getElementById('me-photo-preview');
  var img=document.getElementById('me-photo-img');
  if(f){
    nm.textContent='&#9989; '+f.name;nm.style.display='block';
    var rd=new FileReader();
    rd.onload=function(e){img.src=e.target.result;pv.style.display='block';};
    rd.readAsDataURL(f);
  } else {
    nm.style.display='none';pv.style.display='none';
  }
});
document.getElementById('me-cancel').addEventListener('click',function(){document.getElementById('m-edit').classList.remove('show')});
document.getElementById('me-save').addEventListener('click',function(){
  var btn=this,id=parseInt(document.getElementById('me-id').value);
  var tx=document.getElementById('me-text').value.trim();
  var ph=document.getElementById('me-photo').files[0];
  if(!tx){document.getElementById('me-err').textContent='Matn kiriting';return}
  btn.disabled=true;btn.textContent='&#9203; Saqlanmoqda...';
  if(ph){
    var fd=new FormData();
    fd.append('tpl_id',id);fd.append('text',tx);fd.append('photo',ph);
    xhrForm('/api/templates/edit',fd,function(e,r){
      btn.disabled=false;btn.innerHTML='&#9989; Saqlash';
      if(e){document.getElementById('me-err').textContent=e;return}
      if(r&&r.ok){document.getElementById('m-edit').classList.remove('show');loadTpl();}
      else document.getElementById('me-err').textContent=(r&&r.error)||'Xato';
    });
  } else {
    xhr('POST','/api/templates/edit',{tpl_id:id,text:tx},function(e,r){
      btn.disabled=false;btn.innerHTML='&#9989; Saqlash';
      if(e){document.getElementById('me-err').textContent=e;return}
      if(r&&r.ok){document.getElementById('m-edit').classList.remove('show');var t=_tpls.find(function(x){return x.id===id});if(t)t.text=tx;renderTpl();}
      else document.getElementById('me-err').textContent=(r&&r.error)||'Xato';
    });
  }
});

/* Interval modal */
function openIv(id){
  var t=_tpls.find(function(x){return x.id===id});if(!t)return;
  document.getElementById('iv-id').value=id;
  document.getElementById('iv-title').textContent='⏱️ '+t.name;
  var cur=t.interval_minutes||180;
  document.getElementById('iv-grid').innerHTML=IVLIST.map(function(iv){
    return '<button class="ivb'+(iv.v===cur?' sel':'')+'" onclick="setIv('+iv.v+')">'+iv.l+'</button>';
  }).join('');
  document.getElementById('m-iv').classList.add('show');
}
document.getElementById('iv-cancel').addEventListener('click',function(){document.getElementById('m-iv').classList.remove('show')});
function setIv(min){
  var id=parseInt(document.getElementById('iv-id').value);
  xhr('POST','/api/templates/interval',{tpl_id:id,minutes:min},function(e,r){
    if(e){alert(e);return}
    if(r&&r.ok){document.getElementById('m-iv').classList.remove('show');var t=_tpls.find(function(x){return x.id===id});if(t)t.interval_minutes=min;renderTpl();}
  });
}

/* ── Stats ── */
function loadStats(){
  xhr('GET','/api/data',{user_id:uid},function(e,d){
    if(e||!d)return;
    var s=d.stats;
    var ls=s.last_sent?(s.last_sent.replace('T',' ').substring(0,16)):"Hali yuborilmagan";
    document.getElementById('st-body').innerHTML=
      '<div class="li"><span>&#128228; Jami yuborildi</span><strong>'+s.total_sent+'</strong></div>'+
      '<div class="li"><span>&#9989; Muvaffaqiyatli</span><strong>'+s.successful+'</strong></div>'+
      '<div class="li"><span>&#10060; Xatolik</span><strong>'+s.failed+'</strong></div>'+
      '<div class="li" style="border:0"><span>&#128336; Oxirgi</span><strong style="font-size:12px">'+esc(ls)+'</strong></div>';
    document.getElementById('sub-body').innerHTML=
      '<div style="margin-bottom:10px">'+esc(d.sub_text)+'</div>'+
      (d.sub_active?'':'<button class="btn" onclick="doSub()">&#128179; Obuna olish</button>');
  });
}

function doSub(){var b=document.getElementById("b-sub");if(b)b.click();}

/* ── Admin ── */
var _adminChecked=false,_auUsers=[],_abTpls=[],_abSelId=null;

function checkAdmin(){
  xhr('GET','/api/admin/overview',{user_id:uid},function(e,r){
    _adminChecked=true;
    if(!e&&r&&r.ok){document.getElementById('nb-admin').style.display='flex';}
  });
}

function loadAdmin(){
  loadAdminOverview();
  loadAdminUsers();
  loadAdminBroadcast();
}

function loadAdminOverview(){
  xhr('GET','/api/admin/overview',{user_id:uid},function(e,r){
    if(e||!r||!r.ok)return;
    document.getElementById('ao-total').textContent=r.total;
    document.getElementById('ao-sub').textContent=r.active_sub;
    document.getElementById('ao-run').textContent=r.running;
    document.getElementById('ao-nosess').textContent=r.no_session;
    document.getElementById('ao-groups').textContent=r.total_groups;
  });
}

function loadAdminUsers(){
  document.getElementById('au-loading').style.display='block';
  document.getElementById('au-list').style.display='none';
  document.getElementById('au-empty').style.display='none';
  xhr('GET','/api/admin/users',{user_id:uid},function(e,r){
    document.getElementById('au-loading').style.display='none';
    if(e||!r||!r.ok)return;
    _auUsers=r.users||[];
    renderAdminUsers();
  });
}

function renderAdminUsers(){
  var q=(document.getElementById('au-search').value||'').trim().toLowerCase();
  var list=_auUsers.filter(function(u){
    if(!q)return true;
    return String(u.user_id).indexOf(q)!==-1||(u.phone||'').toLowerCase().indexOf(q)!==-1;
  });
  var el=document.getElementById('au-list');
  if(!list.length){el.style.display='none';document.getElementById('au-empty').style.display='block';return}
  el.style.display='block';document.getElementById('au-empty').style.display='none';
  el.innerHTML=list.map(function(u){
    var dot=u.has_session?(u.sub_active?'g':'y'):'gray';
    var subTxt=u.sub_active?('&#9989; '+u.sub_days+' kun qoldi'):"&#10060; obuna yo'q";
    var runChip=u.is_running?'<span class="chip run">&#128226; yubormoqda</span>':'';
    return '<div class="ua">'+
      '<span class="dot '+dot+'"></span>'+
      '<div class="ui">'+
        '<div class="up">'+esc(u.phone||('ID '+u.user_id))+runChip+'</div>'+
        '<div class="us">'+subTxt+' &middot; '+u.groups_count+' guruh &middot; '+u.tpl_count+' shablon</div>'+
      '</div>'+
      '<button class="ub" onclick="openGift('+u.user_id+',\\''+esc(u.phone||String(u.user_id))+'\\')">&#127873;</button>'+
      '</div>';
  }).join('');
}

document.getElementById('au-search').addEventListener('input',renderAdminUsers);

function openGift(targetId,label){
  document.getElementById('gf-who').textContent=label+' (ID '+targetId+')';
  document.getElementById('gf-err').textContent='';
  document.getElementById('m-gift').dataset.target=targetId;
  document.querySelectorAll('#gf-days .ivb').forEach(function(b){b.classList.toggle('sel',b.dataset.d==='30')});
  document.getElementById('m-gift').classList.add('show');
}
document.querySelectorAll('#gf-days .ivb').forEach(function(b){
  b.addEventListener('click',function(){
    document.querySelectorAll('#gf-days .ivb').forEach(function(x){x.classList.remove('sel')});
    this.classList.add('sel');
  });
});
document.getElementById('gf-cancel').addEventListener('click',function(){document.getElementById('m-gift').classList.remove('show')});
document.getElementById('gf-save').addEventListener('click',function(){
  var btn=this,modal=document.getElementById('m-gift');
  var target=modal.dataset.target;
  var sel=document.querySelector('#gf-days .ivb.sel');
  var days=sel?parseInt(sel.dataset.d):30;
  btn.disabled=true;btn.textContent='&#9203; Yuborilmoqda...';
  xhr('POST','/api/admin/gift',{target_id:target,days:days},function(e,r){
    btn.disabled=false;btn.innerHTML='&#9989; Sovga qilish';
    if(e){document.getElementById('gf-err').textContent=e;return}
    if(r&&r.ok){modal.classList.remove('show');loadAdminUsers();loadAdminOverview();}
    else document.getElementById('gf-err').textContent=(r&&r.error)||'Xato';
  });
});

function loadAdminBroadcast(){
  document.getElementById('ab-loading').style.display='block';
  document.getElementById('ab-body').style.display='none';
  xhr('GET','/api/admin/templates',{user_id:uid},function(e,r){
    document.getElementById('ab-loading').style.display='none';
    document.getElementById('ab-body').style.display='block';
    if(e||!r||!r.ok){document.getElementById('ab-body').innerHTML='<div class="hint-txt">Yuklab bo\\'lmadi</div>';return}
    _abTpls=r.templates||[];
    renderBroadcast();
  });
}

function renderBroadcast(){
  var el=document.getElementById('ab-body');
  if(!_abTpls.length){
    el.innerHTML='<div class="hint-txt">Sizda shablon yo\\'q. Avval "Shablonlar" bo\\'limida shablon yarating.</div>';
    return;
  }
  var picks=_abTpls.map(function(t){
    var ic=t.type==='photo'?'&#128247;':'&#128221;';
    return '<div class="tpl-pick'+(t.id===_abSelId?' sel':'')+'" onclick="pickBcTpl('+t.id+')">'+
      '<span style="flex:1">'+ic+' '+esc(t.name)+'</span>'+
      '<span class="tgl'+(t.id===_abSelId?' on':'')+'"></span>'+
      '</div>';
  }).join('');
  el.innerHTML=picks+
    '<button class="btn red" id="ab-send" style="margin-top:6px" '+(_abSelId?'':'disabled')+'>&#128226; Barcha guruhlarga yuborish</button>'+
    '<div id="ab-result" style="margin-top:10px"></div>';
  var sendBtn=document.getElementById('ab-send');
  if(sendBtn)sendBtn.addEventListener('click',sendBroadcast);
}

function pickBcTpl(id){_abSelId=(_abSelId===id)?null:id;renderBroadcast();}

function sendBroadcast(){
  if(!_abSelId)return;
  if(!confirm('Ushbu shablon barcha foydalanuvchilarning barcha guruhlariga yuboriladi. Davom etasizmi?'))return;
  var btn=document.getElementById('ab-send');
  btn.disabled=true;btn.textContent='&#9203; Yuborilmoqda... (bir necha daqiqa)';
  document.getElementById('ab-result').innerHTML='';
  xhr('POST','/api/admin/broadcast',{tpl_id:_abSelId},function(e,r){
    btn.disabled=false;btn.textContent='&#128226; Barcha guruhlarga yuborish';
    if(e){document.getElementById('ab-result').innerHTML='<div class="err-txt">'+e+'</div>';return}
    if(r&&r.ok){
      document.getElementById('ab-result').innerHTML=
        '<div class="bres">&#9989; Yuborish tugadi<br>'+
        '&#128204; Jami guruhlar: <strong>'+r.total+'</strong><br>'+
        '&#9989; Muvaffaqiyatli: <strong>'+r.sent+'</strong><br>'+
        '&#10060; Xato: <strong>'+r.failed+'</strong><br>'+
        '&#9203; O\\'tkazib yuborildi: <strong>'+r.skipped+'</strong></div>';
    } else {
      document.getElementById('ab-result').innerHTML='<div class="err-txt">'+((r&&r.error)||'Xato')+'</div>';
    }
  });
}

/* ── Init ── */
loadDash();
checkAdmin();
</script>
</body>
</html>"""


# ── Auth routes ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return "OK", 200


@app.route("/auth")
def auth_page():
    return AUTH_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/app")
def main_app():
    return APP_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/send_code", methods=["POST"])
def api_send_code():
    data = request.get_json() or {}
    uid   = str(data.get("user_id", ""))
    phone = str(data.get("phone", "")).strip()
    if not phone.startswith("+"):
        phone = "+" + phone
    sess = _ensure_loop(uid)
    async def _do():
        c = sess["client"]
        if not c.is_connected():
            await c.connect()
        r = await c.send_code_request(phone)
        sess["phone"] = phone
        sess["hash"]  = r.phone_code_hash
    try:
        _run_auth(uid, _do())
        return jsonify(ok=True)
    except PhoneNumberInvalidError:
        return jsonify(ok=False, error="Telefon raqam noto'g'ri")
    except FloodWaitError as e:
        return jsonify(ok=False, error=f"Telegram cheklovi: {e.seconds}s kuting")
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/api/sign_in", methods=["POST"])
def api_sign_in():
    data = request.get_json() or {}
    uid  = str(data.get("user_id", ""))
    code = str(data.get("code", "")).strip().replace(" ", "").replace("-", "")
    with _lock:
        sess = _auth_sessions.get(uid)
    if not sess or not sess.get("hash"):
        return jsonify(ok=False, error="Avval telefon raqam yuboring")
    async def _do():
        c = sess["client"]
        if not c.is_connected():
            await c.connect()
        await c.sign_in(phone=sess["phone"], code=code, phone_code_hash=sess["hash"])
        session_str = c.session.save()
        _save_auth(uid, sess["phone"], session_str)
    try:
        _run_auth(uid, _do())
        _notify(uid, "✅ *Muvaffaqiyatli kirildi!*\n\n/start bosing.")
        return jsonify(ok=True)
    except SessionPasswordNeededError:
        return jsonify(ok=False, need_2fa=True)
    except PhoneCodeInvalidError:
        return jsonify(ok=False, error="Kod noto'g'ri")
    except PhoneCodeExpiredError:
        async def _resend():
            c = sess["client"]
            if not c.is_connected():
                await c.connect()
            r = await c.send_code_request(sess["phone"])
            sess["hash"] = r.phone_code_hash
        try:
            _run_auth(uid, _resend())
            return jsonify(ok=False, code_expired=True)
        except Exception as e2:
            return jsonify(ok=False, error=f"Kod muddati o'tdi: {e2}")
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/api/sign_in_2fa", methods=["POST"])
def api_sign_in_2fa():
    data = request.get_json() or {}
    uid  = str(data.get("user_id", ""))
    pw   = str(data.get("password", ""))
    with _lock:
        sess = _auth_sessions.get(uid)
    if not sess:
        return jsonify(ok=False, error="Sessiya topilmadi")
    async def _do():
        c = sess["client"]
        if not c.is_connected():
            await c.connect()
        await c.sign_in(password=pw)
        session_str = c.session.save()
        _save_auth(uid, sess["phone"], session_str)
    try:
        _run_auth(uid, _do())
        _notify(uid, "✅ *Muvaffaqiyatli kirildi!*\n\n/start bosing.")
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error="Noto'g'ri parol" if "password" in str(e).lower() else str(e))


# ── App API routes ───────────────────────────────────────────────────────

@app.route("/api/data")
def api_data():
    uid  = request.args.get("user_id", "")
    data = _load(uid)
    if not data or not data.get("session_string"):
        return jsonify(ok=False, need_auth=True, error="Foydalanuvchi topilmadi")
    stats  = data.get("stats", {"total_sent": 0, "successful": 0, "failed": 0, "last_sent": None})
    active = sum(1 for t in data.get("templates", []) if t.get("is_active"))
    return jsonify(
        ok=True,
        is_running=data.get("is_running", False),
        phone=data.get("phone"),
        groups_count=len(data.get("groups", [])),
        tpl_count=len(data.get("templates", [])),
        active_tpl=active,
        stats=stats,
        sub_text=_sub_text(uid),
        sub_active=_has_sub(uid),
    )


@app.route("/api/start", methods=["POST"])
def api_start():
    uid  = _uid(request)
    data = _load(uid)
    if not data:
        return jsonify(ok=False, error="Foydalanuvchi topilmadi")
    if not _has_sub(uid):
        return jsonify(ok=False, error="Obuna kerak")
    active = [t for t in data.get("templates", []) if t.get("is_active")]
    if not active:
        return jsonify(ok=False, error="Avval shablon faollashtiring")
    if not data.get("groups"):
        return jsonify(ok=False, error="Avval guruh qo'shing")
    data["is_running"]        = True
    data["_scheduler_update"] = True
    data["_send_now"]         = True
    _save_data(uid, data)
    return jsonify(ok=True)


@app.route("/api/stop", methods=["POST"])
def api_stop():
    uid  = _uid(request)
    data = _load(uid)
    if not data:
        return jsonify(ok=False, error="Foydalanuvchi topilmadi")
    data["is_running"]        = False
    data["_scheduler_update"] = True
    _save_data(uid, data)
    return jsonify(ok=True)


@app.route("/api/groups")
def api_groups():
    uid  = request.args.get("user_id", "")
    data = _load(uid)
    return jsonify(ok=True, groups=data.get("groups", []))


@app.route("/api/dialogs")
def api_dialogs():
    uid  = request.args.get("user_id", "")
    data = _load(uid)
    session_str = data.get("session_string", "")
    if not session_str:
        return jsonify(ok=False, error="Session topilmadi. Avval kiring.")

    async def _fetch():
        c = TelegramClient(StringSession(session_str), API_ID, API_HASH, **_DEVICE)
        await c.connect()
        if not await c.is_user_authorized():
            await c.disconnect()
            raise Exception("Session eskirgan")
        result = []
        async for dlg in c.iter_dialogs():
            ent = dlg.entity
            is_grp = dlg.is_group
            is_sg  = dlg.is_channel and getattr(ent, "megagroup", False)
            is_bc  = dlg.is_channel and getattr(ent, "broadcast", False)
            can_post = (is_bc and getattr(ent, "admin_rights", None) is not None
                        and getattr(getattr(ent, "admin_rights", None), "post_messages", False))
            if is_grp or is_sg or can_post:
                result.append({
                    "chat_id": dlg.id,
                    "title":   dlg.title or str(dlg.id),
                    "username": getattr(ent, "username", None) or "",
                })
        await c.disconnect()
        return result

    try:
        dialogs = _run_in_thread(_fetch(), timeout=60)
        return jsonify(ok=True, dialogs=dialogs)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/api/groups/toggle", methods=["POST"])
def api_groups_toggle():
    d    = request.get_json() or {}
    uid  = str(d.get("user_id", ""))
    cid  = d.get("chat_id")
    title= d.get("title", "")
    data = _load(uid)
    if not data:
        return jsonify(ok=False, error="Foydalanuvchi topilmadi")
    existing = next((g for g in data["groups"] if g["chat_id"] == cid), None)
    if existing:
        data["groups"] = [g for g in data["groups"] if g["chat_id"] != cid]
    else:
        data["groups"].append({
            "chat_id": cid,
            "title":   title,
            "added_at": datetime.now().isoformat(),
        })
    _save_data(uid, data)
    return jsonify(ok=True)


@app.route("/api/groups/remove", methods=["POST"])
def api_groups_remove():
    d    = request.get_json() or {}
    uid  = str(d.get("user_id", ""))
    cid  = d.get("chat_id")
    data = _load(uid)
    if not data:
        return jsonify(ok=False, error="Foydalanuvchi topilmadi")
    data["groups"] = [g for g in data["groups"] if g["chat_id"] != cid]
    _save_data(uid, data)
    return jsonify(ok=True)


@app.route("/api/templates")
def api_templates():
    uid  = request.args.get("user_id", "")
    data = _load(uid)
    return jsonify(ok=True, templates=data.get("templates", []))


@app.route("/api/templates/add", methods=["POST"])
def api_templates_add():
    uid   = str(request.form.get("user_id", ""))
    name  = request.form.get("name", "").strip()
    text  = request.form.get("text", "").strip()
    ttype = request.form.get("type", "text")
    if not name or not text:
        return jsonify(ok=False, error="Nom va matn kerak")
    data = _load(uid)
    if not data:
        return jsonify(ok=False, error="Foydalanuvchi topilmadi")
    tpl_id = data.get("next_template_id", 1)
    tpl = {
        "id": tpl_id, "name": name, "type": ttype,
        "text": text, "interval_minutes": 180,
        "is_active": False, "created_at": datetime.now().isoformat(),
    }
    if ttype == "photo" and "photo" in request.files:
        f = request.files["photo"]
        path = str(MEDIA_DIR / f"{uid}_tpl_{tpl_id}.jpg")
        f.save(path)
        tpl["photo_path"] = path
    data["templates"].append(tpl)
    data["next_template_id"] = tpl_id + 1
    _save_data(uid, data)
    return jsonify(ok=True)


@app.route("/api/templates/toggle", methods=["POST"])
def api_templates_toggle():
    d      = request.get_json() or {}
    uid    = str(d.get("user_id", ""))
    tpl_id = d.get("tpl_id")
    data   = _load(uid)
    if not data:
        return jsonify(ok=False, error="Foydalanuvchi topilmadi")
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        return jsonify(ok=False, error="Shablon topilmadi")
    tpl["is_active"] = not tpl.get("is_active", False)
    data["_scheduler_update"] = True
    _save_data(uid, data)
    return jsonify(ok=True, is_active=tpl["is_active"])


@app.route("/api/templates/delete", methods=["POST"])
def api_templates_delete():
    d      = request.get_json() or {}
    uid    = str(d.get("user_id", ""))
    tpl_id = d.get("tpl_id")
    data   = _load(uid)
    if not data:
        return jsonify(ok=False, error="Foydalanuvchi topilmadi")
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if tpl and tpl.get("photo_path"):
        try:
            os.remove(tpl["photo_path"])
        except Exception:
            pass
    data["templates"] = [t for t in data["templates"] if t["id"] != tpl_id]
    data["_scheduler_update"] = True
    _save_data(uid, data)
    return jsonify(ok=True)


@app.route("/api/templates/interval", methods=["POST"])
def api_templates_interval():
    d      = request.get_json() or {}
    uid    = str(d.get("user_id", ""))
    tpl_id = d.get("tpl_id")
    mins   = int(d.get("minutes", 180))
    data   = _load(uid)
    if not data:
        return jsonify(ok=False, error="Foydalanuvchi topilmadi")
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        return jsonify(ok=False, error="Shablon topilmadi")
    tpl["interval_minutes"]   = mins
    data["_scheduler_update"] = True
    _save_data(uid, data)
    return jsonify(ok=True)


@app.route("/api/templates/edit", methods=["POST"])
def api_templates_edit():
    if request.content_type and "multipart" in request.content_type:
        uid    = str(request.form.get("user_id", ""))
        tpl_id = int(request.form.get("tpl_id", 0))
        text   = str(request.form.get("text", "")).strip()
    else:
        d      = request.get_json() or {}
        uid    = str(d.get("user_id", ""))
        tpl_id = d.get("tpl_id")
        text   = str(d.get("text", "")).strip()
    if not text:
        return jsonify(ok=False, error="Matn bo'sh bo'lishi mumkin emas")
    data = _load(uid)
    if not data:
        return jsonify(ok=False, error="Foydalanuvchi topilmadi")
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        return jsonify(ok=False, error="Shablon topilmadi")
    tpl["text"] = text
    if "photo" in request.files:
        f = request.files["photo"]
        if f and f.filename:
            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            ext = os.path.splitext(f.filename)[1] or ".jpg"
            path = str(MEDIA_DIR / f"{uid}_tpl{tpl_id}{ext}")
            old_path = tpl.get("photo_path", "")
            if old_path and old_path != path and os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass
            f.save(path)
            tpl["photo_path"] = path
            tpl["type"] = "photo"
    _save_data(uid, data)
    return jsonify(ok=True)


@app.route("/api/subscribe", methods=["POST"])
def api_subscribe():
    uid  = _uid(request)
    if _has_sub(uid):
        return jsonify(ok=False, error="Obuna allaqachon faol")
    token = _get_bearer()
    if not token:
        return jsonify(ok=False, error="To'lov tizimida xato")
    data = _load(uid)
    price = int(data.get("custom_price", SUBSCRIPTION_PRICE))
    body = json.dumps({
        "merchant_id": INPAY_MERCHANT_ID,
        "token": INPAY_MERCHANT_TOKEN,
        "amount": price,
        "description": "Reklama Bot — 30 kunlik obuna",
        "callback_url": "https://169-58-21-48.sslip.io/payment_callback",
    }).encode()
    try:
        req = urllib.request.Request(
            f"{INPAY_BASE}/create/",
            data=body,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json",
                     "Accept": "application/json"},
            method="POST")
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        pay_url  = result.get("pay_url")
        order_id = result.get("order_id")
        if not pay_url or not order_id:
            return jsonify(ok=False, error="To'lov havolasi yaratilmadi")
        data["pending_order_id"] = order_id
        _save_data(uid, data)
        return jsonify(ok=True, pay_url=pay_url, order_id=order_id)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/api/check_payment", methods=["POST"])
def api_check_payment():
    uid  = _uid(request)
    data = _load(uid)
    order_id = data.get("pending_order_id")
    if not order_id:
        return jsonify(ok=False, error="To'lov topilmadi")
    try:
        url  = f"{INPAY_BASE}/transactions/?order_id={order_id}"
        resp = urllib.request.urlopen(url, timeout=15)
        res  = json.loads(resp.read())
        status = res.get("status", "pending")
        if status == "success":
            exp = datetime.now() + timedelta(days=SUBSCRIPTION_DAYS)
            data["subscription_expires"] = exp.isoformat()
            data.pop("pending_order_id", None)
            _save_data(uid, data)
            return jsonify(ok=True, activated=True, expires=exp.strftime("%d.%m.%Y"))
        return jsonify(ok=True, activated=False, status=status)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/payment_callback", methods=["POST"])
def payment_callback():
    try:
        d = request.get_json() or {}
        order_id = d.get("order_id", "")
        status   = d.get("status", "")
        if status != "success":
            return jsonify(ok=True)
        for f in USERS_DIR.glob("*.json"):
            user_data = json.loads(f.read_text())
            if user_data.get("pending_order_id") == order_id:
                exp = datetime.now() + timedelta(days=SUBSCRIPTION_DAYS)
                user_data["subscription_expires"] = exp.isoformat()
                user_data.pop("pending_order_id", None)
                f.write_text(json.dumps(user_data, ensure_ascii=False, indent=2))
                uid = str(user_data.get("user_id", ""))
                if uid:
                    _notify(uid, f"✅ *To'lov qabul qilindi!*\n\nObuna *{exp.strftime('%d.%m.%Y')}* gacha faol.\n\n/start bosing.")
                break
    except Exception:
        pass
    return jsonify(ok=True)


# ── Admin panel API ──────────────────────────────────────────────────────

def _is_admin(uid: str) -> bool:
    try:
        return int(uid) == ADMIN_ID
    except (TypeError, ValueError):
        return False


def _all_user_files():
    for f in sorted(USERS_DIR.glob("*.json")):
        if f.name == "media":
            continue
        try:
            yield f, json.loads(f.read_text())
        except Exception:
            continue


def _collect_all_groups() -> dict:
    """Barcha userlarning guruhlarini chat_id bo'yicha jamlaydi (admin bo'lmagan userlar)."""
    result = {}
    for f, data in _all_user_files():
        uid = data.get("user_id")
        if uid == ADMIN_ID or not data.get("session_string"):
            continue
        for g in data.get("groups", []):
            chat_id = g.get("chat_id")
            if chat_id is not None and chat_id not in result:
                result[chat_id] = {"user_id": uid, "title": g.get("title", str(chat_id))}
    return result


@app.route("/api/admin/overview")
def api_admin_overview():
    uid = request.args.get("user_id", "")
    if not _is_admin(uid):
        return jsonify(ok=False, error="Ruxsat yo'q"), 403

    total = active_sub = running = no_session = 0
    for f, data in _all_user_files():
        if data.get("user_id") == ADMIN_ID:
            continue
        total += 1
        if not data.get("session_string"):
            no_session += 1
        if data.get("is_running"):
            running += 1
        exp = data.get("subscription_expires")
        if exp and datetime.fromisoformat(exp) > datetime.now():
            active_sub += 1

    return jsonify(
        ok=True,
        total=total,
        active_sub=active_sub,
        running=running,
        no_session=no_session,
        total_groups=len(_collect_all_groups()),
    )


@app.route("/api/admin/users")
def api_admin_users():
    uid = request.args.get("user_id", "")
    if not _is_admin(uid):
        return jsonify(ok=False, error="Ruxsat yo'q"), 403

    users = []
    for f, data in _all_user_files():
        u = data.get("user_id")
        if u == ADMIN_ID:
            continue
        exp = data.get("subscription_expires")
        sub_active = False
        sub_days = 0
        if exp:
            dt = datetime.fromisoformat(exp)
            if dt > datetime.now():
                sub_active = True
                sub_days = (dt - datetime.now()).days
        users.append({
            "user_id": u,
            "phone": data.get("phone") or "",
            "has_session": bool(data.get("session_string")),
            "is_running": bool(data.get("is_running")),
            "groups_count": len(data.get("groups", [])),
            "tpl_count": len(data.get("templates", [])),
            "sub_active": sub_active,
            "sub_days": sub_days,
            "total_sent": data.get("stats", {}).get("total_sent", 0),
        })
    users.sort(key=lambda x: (not x["is_running"], not x["sub_active"], x["user_id"]))
    return jsonify(ok=True, users=users)


@app.route("/api/admin/gift", methods=["POST"])
def api_admin_gift():
    d = request.get_json() or {}
    uid = str(d.get("user_id", ""))
    if not _is_admin(uid):
        return jsonify(ok=False, error="Ruxsat yo'q"), 403
    target = str(d.get("target_id", ""))
    days = int(d.get("days", SUBSCRIPTION_DAYS))
    if not target:
        return jsonify(ok=False, error="Foydalanuvchi tanlanmagan")

    data = _load(target)
    if not data:
        return jsonify(ok=False, error="Foydalanuvchi topilmadi")

    exp = data.get("subscription_expires")
    base = datetime.fromisoformat(exp) if exp else datetime.now()
    if base < datetime.now():
        base = datetime.now()
    new_exp = base + timedelta(days=days)
    data["subscription_expires"] = new_exp.isoformat()
    _save_data(target, data)

    exp_str = new_exp.strftime("%d.%m.%Y")
    _notify(target, f"🎁 *Sizga {days} kunlik obuna sovga qilindi!*\n\nMuddati: *{exp_str}* gacha\n\n/start bosing.")
    return jsonify(ok=True, expires=exp_str)


@app.route("/api/admin/templates")
def api_admin_templates():
    uid = request.args.get("user_id", "")
    if not _is_admin(uid):
        return jsonify(ok=False, error="Ruxsat yo'q"), 403
    data = _load(uid)
    return jsonify(ok=True, templates=data.get("templates", []))


@app.route("/api/admin/broadcast", methods=["POST"])
def api_admin_broadcast():
    d = request.get_json() or {}
    uid = str(d.get("user_id", ""))
    if not _is_admin(uid):
        return jsonify(ok=False, error="Ruxsat yo'q"), 403
    tpl_id = d.get("tpl_id")

    data = _load(uid)
    tpl = next((t for t in data.get("templates", []) if t["id"] == tpl_id), None)
    if not tpl:
        return jsonify(ok=False, error="Shablon topilmadi")

    all_groups = _collect_all_groups()
    if not all_groups:
        return jsonify(ok=False, error="Yuboriladigan guruh yo'q")

    by_user = {}
    for chat_id, info in all_groups.items():
        by_user.setdefault(info["user_id"], []).append((chat_id, info["title"]))

    async def _broadcast():
        ok = fail = skip = 0
        for owner_uid, chats in by_user.items():
            owner_data = _load(str(owner_uid))
            session_str = owner_data.get("session_string", "")
            if not session_str:
                skip += len(chats)
                continue
            c = TelegramClient(StringSession(session_str), API_ID, API_HASH, **_DEVICE)
            try:
                await c.connect()
                if not await c.is_user_authorized():
                    skip += len(chats)
                    continue
                for chat_id, title in chats:
                    try:
                        if tpl.get("type") == "photo" and os.path.exists(tpl.get("photo_path", "")):
                            try:
                                await c.send_file(chat_id, tpl["photo_path"], caption=tpl.get("text", ""))
                            except Exception:
                                await c.send_message(chat_id, tpl.get("text", ""))
                        else:
                            await c.send_message(chat_id, tpl.get("text", ""))
                        ok += 1
                    except Exception:
                        fail += 1
                    await asyncio.sleep(1.5)
            except Exception:
                skip += len(chats)
            finally:
                try:
                    await c.disconnect()
                except Exception:
                    pass
        return ok, fail, skip

    try:
        ok, fail, skip = _run_in_thread(_broadcast(), timeout=600)
        return jsonify(ok=True, total=len(all_groups), sent=ok, failed=fail, skipped=skip)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


if __name__ == "__main__":
    print("Server: http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
