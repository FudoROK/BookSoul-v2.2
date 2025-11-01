# src/webhook/main.py
# BookSoul Webhook — v2.3 (прод-ядро)
# 1) Мгновенный 200 OK; все «второстепенные» действия — в фоне (create_task)
# 2) Первое сообщение: ЛОГОТИП → бренд-текст → слоган (один раз на чат)
# 3) Мягкое приветствие после паузы (>24h): «Снова на связи ⚡» → полный бренд-баннер
# 4) Журнал: incoming / router_start / router_sent / reconnect_banner / brand_banner / outbox_sent
# 5) Идемпотентность: inbox (<chat_id>:<update_id>) / outbox (<chat_id>:<update_id>)
# 6) Директор: Responses API → fallback Chat Completions; модель из ENV (OPENAI_MODEL, по умолчанию gpt-4o)
# 7) typing выключен по умолчанию; статичный «думаю…» (опционально) без правок/анимации

from __future__ import annotations
import os, time, asyncio
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.cloud import firestore

# --- HTTP к Telegram ---
try:
    import httpx
except Exception:
    httpx = None

# --- OpenAI SDK ---
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

app = FastAPI()
db = firestore.Client()  # ADC (Cloud Run SA)

# -------- ENV ----------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else ""

# Логотип для баннера: сначала пробуем file_id (быстрее), иначе URL
LOGO_FILE_ID = os.getenv("LOGO_FILE_ID", "")      # например: "AgACAgIAAxkBA..."
LOGO_URL = os.getenv("LOGO_URL", "")              # например: "https://.../logo.png"

# Баннер включён по умолчанию, отправляется ФОНОМ
SEND_ACK_BANNER = os.getenv("SEND_ACK_BANNER", "true").lower() == "true"

# «Мягкое приветствие после паузы» (часы)
RECONNECT_HOURS = int(os.getenv("RECONNECT_HOURS", "24"))

# Статичный статус «думаю…» (без анимации), отправляется фоном в начале обработки
THINKING_STATUS = os.getenv("THINKING_STATUS", "true").lower() == "true"
THINKING_TEXT = "BookSoul\n📚 Думаю над вашим сообщением... ✏️"

# typing (анимация Telegram-клиента) — выключено по умолчанию
TYPING_FEEDBACK = os.getenv("TYPING_FEEDBACK", "false").lower() == "true"
TYPING_DURATION_SEC = int(os.getenv("TYPING_DURATION_SEC", "8"))

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
SYSTEM_PROMPT = (
    "You are the Director of BookSoul Factory. "
    "Answer briefly, helpfully, and specifically about making a custom children's book. "
    "If info is missing, ask one clear follow-up question. Keep it practical."
)

# Debug
DEBUG_ROUTER = os.getenv("DEBUG_ROUTER", "false").lower() == "true"
def _dlog(*args):
    if DEBUG_ROUTER:
        try: print("[router]", *args)
        except Exception: pass
# -----------------------

@app.get("/")
def health():
    return {"status": "ok", "service": "booksoul-webhook2"}

# ---------- Telegram helpers ----------

async def _tg_send_text(chat_id: int, text: str):
    if not (TELEGRAM_API and httpx): return
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        _dlog("sendMessage", r.status_code)
        r.raise_for_status()

async def _tg_send_photo(chat_id: int, caption: str | None = None):
    """Отправка логотипа: сначала file_id (мгновенно), затем URL (если задан)."""
    if not (TELEGRAM_API and httpx and chat_id): return False
    async with httpx.AsyncClient(timeout=15) as client:
        # 1) file_id
        if LOGO_FILE_ID:
            try:
                r = await client.post(f"{TELEGRAM_API}/sendPhoto", data={
                    "chat_id": chat_id,
                    "photo": LOGO_FILE_ID,
                    "caption": caption or "",
                    "parse_mode": "HTML",
                })
                if r.status_code == 200:
                    _dlog("sendPhoto(file_id)=200")
                    return True
            except Exception as e:
                _dlog("sendPhoto file_id error", repr(e))
        # 2) URL
        if LOGO_URL:
            try:
                r = await client.post(f"{TELEGRAM_API}/sendPhoto", data={
                    "chat_id": chat_id,
                    "photo": LOGO_URL,
                    "caption": caption or "",
                    "parse_mode": "HTML",
                })
                if r.status_code == 200:
                    _dlog("sendPhoto(url)=200")
                    return True
            except Exception as e:
                _dlog("sendPhoto url error", repr(e))
    return False

async def _tg_send_typing(chat_id: int):
    if not (TYPING_FEEDBACK and TELEGRAM_API and httpx): return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{TELEGRAM_API}/sendChatAction", data={"chat_id": chat_id, "action": "typing"})
    except Exception as e:
        _dlog("typing error", repr(e))

async def _typing_loop(chat_id: int, seconds: int):
    remaining = max(0, seconds)
    while remaining > 0:
        await _tg_send_typing(chat_id)
        await asyncio.sleep(4)
        remaining -= 4

# ---------- Chat profile / banners ----------

def _chat_ref(chat_id: int):
    return db.collection("chats").document(str(chat_id))

def _utcnow():
    return datetime.now(timezone.utc)

def _hours_ago(dt: datetime, hours: int) -> bool:
    try:
        return (_utcnow() - dt) > timedelta(hours=hours)
    except Exception:
        return True

def _get_chat_profile(chat_id: int) -> dict:
    try:
        snap = _chat_ref(chat_id).get()
        return snap.to_dict() if snap.exists else {}
    except Exception as e:
        _dlog("chat profile read error", repr(e))
        return {}

def _update_chat_profile(chat_id: int, **fields):
    try:
        _chat_ref(chat_id).set(fields, merge=True)
    except Exception as e:
        _dlog("chat profile write error", repr(e))

def _should_reconnect_banner(p: dict) -> bool:
    # last_message_at -> если пауза > RECONNECT_HOURS — показываем «Снова на связи ⚡» + бренд-баннер
    last_at = p.get("last_message_at_iso")
    if not last_at: return False
    try:
        dt = datetime.fromisoformat(last_at)
    except Exception:
        return False
    return _hours_ago(dt, RECONNECT_HOURS)

async def _send_brand_banner(chat_id: int):
    """
    Полный бренд-баннер:
     1) логотип (photo)
     2) бренд-текст
     3) слоган
    """
    # 1) логотип
    await _tg_send_photo(chat_id)

    # 2) бренд-текст (цвета в Телеграм-тексте не поддерживаются — цвет в логотипе)
    brand_text = (
        "<b>BookSoul</b> — <b>AI Soul</b> <b>Fabrica</b>\n"
        "✨ <i>Технологии, которые дарят время</i> ✨"
    )
    await _tg_send_text(chat_id, brand_text)

    # журнал
    try:
        db.collection("events").add({
            "type": "brand_banner",
            "chat_id": chat_id,
            "created_at": firestore.SERVER_TIMESTAMP,
            "stage": "brand_banner",
        })
    except Exception as e:
        _dlog("events brand_banner error", repr(e))

async def _send_reconnect_then_brand(chat_id: int):
    # 1) короткое «Снова на связи ⚡»
    try:
        await _tg_send_text(chat_id, "Снова на связи ⚡")
        db.collection("events").add({
            "type": "reconnect_banner",
            "chat_id": chat_id,
            "created_at": firestore.SERVER_TIMESTAMP,
            "stage": "reconnect_banner",
        })
    except Exception as e:
        _dlog("events reconnect_banner error", repr(e))
    # 2) сразу полный бренд-баннер
    await _send_brand_banner(chat_id)
    # отметим момент показа баннера
    _update_chat_profile(chat_id, last_brand_banner_at_iso=_utcnow().isoformat())

async def _maybe_send_first_or_reconnect_banner(chat_id: int):
    """
    - если чата нет → первое приветствие (полный баннер), welcomed=true
    - если есть и пауза > 24h → «Снова на связи ⚡» → полный баннер (раз в 24h)
    - всё фоном; не блокирует ACK
    """
    # читаем профиль
    profile = _get_chat_profile(chat_id)

    # первое сообщение вообще (нет greeted)
    if not profile or profile.get("greeted") is not True:
        # полный баннер
        await _send_brand_banner(chat_id)
        _update_chat_profile(chat_id, greeted=True, first_seen_at_iso=_utcnow().isoformat(),
                             last_brand_banner_at_iso=_utcnow().isoformat())
        return

    # «мягкое приветствие после паузы»
    if _should_reconnect_banner(profile):
        # антиспам: не чаще раза в 24 часа
        last_brand_iso = profile.get("last_brand_banner_at_iso")
        if last_brand_iso:
            try:
                if not _hours_ago(datetime.fromisoformat(last_brand_iso), 24):
                    return
            except Exception:
                pass
        await _send_reconnect_then_brand(chat_id)

# ---------- OpenAI ----------

def _openai_client():
    if not OPENAI_API_KEY or OpenAI is None:
        _dlog("openai client skipped", {"key": bool(OPENAI_API_KEY), "sdk": OpenAI is not None})
        return None
    try:
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        _dlog("OpenAI init error", repr(e))
        return None

async def _router_answer(user_text: str) -> str:
    if not OPENAI_API_KEY:
        return "Техническая пауза: подключаю мозг. Напиши ещё раз через минуту."
    client = _openai_client()
    if client is None:
        return "Временная недоступность мозгового центра. Попробуем ещё раз чуть позже."

    # 1) Responses API
    try:
        _dlog("responses.create", {"model": OPENAI_MODEL, "len": len(user_text)})
        resp = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.2,
            max_output_tokens=600,
        )
        text = (getattr(resp, "output_text", "") or "").strip()
        if text: return text
        _dlog("responses empty")
    except Exception as e:
        _dlog("responses error", repr(e))

    # 2) Chat Completions (fallback)
    try:
        _dlog("chat.completions.create", {"model": OPENAI_MODEL})
        ch = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.2,
            max_tokens=600,
        )
        c0 = ch.choices[0].message.content if ch and ch.choices else ""
        text = (c0 or "").strip()
        if text: return text
        _dlog("chat empty")
    except Exception as e:
        _dlog("chat error", repr(e))

    return "Я на связи, но сейчас техническое окно. Повтори, пожалуйста, мысль — проверю цепочку."

# ---------- Processing pipeline ----------

async def _send_thinking_status(chat_id: int):
    if not THINKING_STATUS: return
    try:
        await _tg_send_text(chat_id, THINKING_TEXT)
    except Exception as e:
        _dlog("thinking status error", repr(e))

async def _process_update(chat_id: int, update_id: int, user_text: str):
    out_id = f"{chat_id}:{update_id}"
    out_ref = db.collection("outbox").document(out_id)

    # если уже отвечали — выходим
    try:
        snap = out_ref.get()
        if snap.exists and snap.to_dict().get("sent") is True:
            _dlog("outbox skip", out_id)
            return
    except Exception as e:
        _dlog("outbox check error", repr(e))

    # журнал: старт роутера
    try:
        db.collection("events").document(f"{out_id}:start").set({
            "type": "router_start",
            "chat_id": chat_id,
            "update_id": update_id,
            "user_text": user_text,
            "created_at": firestore.SERVER_TIMESTAMP,
            "stage": "router_start",
        }, merge=True)
    except Exception as e:
        _dlog("events router_start error", repr(e))

    # статичный статус ожидания (без анимации)
    asyncio.create_task(_send_thinking_status(chat_id))

    # по желанию: typing (оставлено на будущее, по умолчанию выключено)
    if TYPING_FEEDBACK:
        asyncio.create_task(_typing_loop(chat_id, TYPING_DURATION_SEC))

    # ответ директора
    answer = await _router_answer(user_text)

    # отправка ответа
    try:
        await _tg_send_text(chat_id, answer)
    except Exception as e:
        _dlog("telegram send error", repr(e))

    # журнал: ответ отправлен
    try:
        db.collection("events").document(f"{out_id}:sent").set({
            "type": "router_sent",
            "chat_id": chat_id,
            "update_id": update_id,
            "answer": answer,
            "created_at": firestore.SERVER_TIMESTAMP,
            "stage": "router_sent",
        }, merge=True)
    except Exception as e:
        _dlog("events router_sent error", repr(e))

    # отметка в outbox
    try:
        out_ref.set({"sent": True, "sent_at": firestore.SERVER_TIMESTAMP}, merge=True)
    except Exception as e:
        _dlog("outbox set error", repr(e))

# ---------- Webhook handler ----------

@app.post("/telegram_webhook")
async def telegram_webhook(req: Request):
    # 0) парсим апдейт
    try:
        payload = await req.json()
    except Exception:
        return JSONResponse({"ok": True, "ack": "ignored_non_json"})

    update_id = payload.get("update_id")
    message = payload.get("message") or payload.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    user_text = (message.get("text") or "").strip()

    # 1) фильтр
    if not update_id or not chat_id:
        return JSONResponse({"ok": True, "ack": "ignored_missing_fields"})

    # 2) inbox (идемпотентно)
    inbox_id = f"{chat_id}:{update_id}"
    inbox_ref = db.collection("inbox").document(inbox_id)

    @firestore.transactional
    def _create_inbox_once(tx: firestore.Transaction):
        snap = inbox_ref.get(transaction=tx)
        if snap.exists: return False
        now = datetime.now(timezone.utc)
        tx.set(inbox_ref, {
            "chat_id": chat_id,
            "update_id": update_id,
            "text": user_text,
            "raw": payload,  # можно выключить позже
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_at_iso_utc": now.isoformat(),
            "created_at_epoch": int(time.time()),
            "status": "received",
            "source": "telegram",
        })
        return True

    tx = db.transaction()
    created = False
    try:
        created = _create_inbox_once(tx)
    except Exception as e:
        _dlog("inbox write error", repr(e))

    # 3) журнал входящего
    try:
        db.collection("events").document(inbox_id).set({
            "type": "incoming_message",
            "chat_id": chat_id,
            "update_id": update_id,
            "text": user_text,
            "source": "telegram",
            "created_at": firestore.SERVER_TIMESTAMP,
            "stage": "incoming",
        }, merge=True)
    except Exception as e:
        _dlog("events incoming error", repr(e))

    # 4) обновим профиль чата (last_message_at)
    _update_chat_profile(chat_id, last_message_at_iso=_utcnow().isoformat())

    # 5) БАННЕРЫ / ПРИВЕТСТВИЯ — СТРОГО ФОНОМ
    if SEND_ACK_BANNER:
        asyncio.create_task(_maybe_send_first_or_reconnect_banner(chat_id))

    # 6) Запускаем асинхронную обработку (директор → ответ)
    asyncio.create_task(_process_update(chat_id, update_id, user_text))

    # 7) мгновенный ACK
    return JSONResponse({"ok": True, "inbox_created": created})
