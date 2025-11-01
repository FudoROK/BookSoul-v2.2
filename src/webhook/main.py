# src/webhook/main.py
# BookSoul Webhook — v2.3 (ядро, прод)
# ACK мгновенно; баннеры/сервисные сообщения — строго фоном.
# Приветствия и статусы оформлены в стиле ⚡ Неоновый цифровой.

from __future__ import annotations
import os, time, asyncio
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.cloud import firestore

# --- HTTP (Telegram) ---
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

# Логотип (предпочтительно file_id, иначе URL)
LOGO_FILE_ID = os.getenv("LOGO_FILE_ID", "")
LOGO_URL = os.getenv("LOGO_URL", "")

# Включение баннеров (перво-контакт/ре-контакт)
SEND_ACK_BANNER = os.getenv("SEND_ACK_BANNER", "true").lower() == "true"

# Паузы
RECONNECT_HOURS = int(os.getenv("RECONNECT_HOURS", "24"))   # мягкое приветствие
SESSION_WAIT_HOURS = int(os.getenv("SESSION_WAIT_HOURS", "1"))  # статус ожидания

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
SYSTEM_PROMPT = (
    "You are the Director (Технолог) of BookSoul Factory. "
    "Отвечай кратко и по делу о создании детской книги. "
    "Если данных не хватает — задай один уточняющий вопрос. "
    "Тон: технологичный, уверенный, дружелюбный."
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

# ---------- utils ----------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _hours_ago(dt_iso: str | None, hours: int) -> bool:
    if not dt_iso: return True
    try:
        return (_utcnow() - datetime.fromisoformat(dt_iso)) > timedelta(hours=hours)
    except Exception:
        return True

def _chat_ref(chat_id: int):
    return db.collection("chats").document(str(chat_id))

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

# ---------- Telegram ----------
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

async def _tg_send_photo(chat_id: int, caption: str | None = None) -> bool:
    if not (TELEGRAM_API and httpx and chat_id): return False
    async with httpx.AsyncClient(timeout=20) as client:
        # 1) file_id (быстрее)
        if LOGO_FILE_ID:
            try:
                r = await client.post(f"{TELEGRAM_API}/sendPhoto", data={
                    "chat_id": chat_id,
                    "photo": LOGO_FILE_ID,
                    "caption": caption or "",
                    "parse_mode": "HTML",
                })
                if r.status_code == 200: return True
            except Exception as e:
                _dlog("sendPhoto(file_id) error", repr(e))
        # 2) URL
        if LOGO_URL:
            try:
                r = await client.post(f"{TELEGRAM_API}/sendPhoto", data={
                    "chat_id": chat_id,
                    "photo": LOGO_URL,
                    "caption": caption or "",
                    "parse_mode": "HTML",
                })
                if r.status_code == 200: return True
            except Exception as e:
                _dlog("sendPhoto(url) error", repr(e))
    return False

# ---------- Брендовые сообщения ----------
BRAND_TEXT = (
    "<b>BookSoul</b> — <b>AI Soul</b> <b>Fabrica</b>\n"
    "✨ <i>Технологии, которые дарят время</i> ✨"
)

SESSION_WAIT_TEXT = (
    "📚 <b>BookSoul</b>  «Ваше сообщение обрабатывается… ✏️»\n"
    "─── ⋆⋅☆⋅⋆ ── <b>AI Soul Fabrica</b> ── ⋆⋅☆⋅⋆ ───\n"
    "✨ <i>Технологии, которые дарят время</i> ✨"
)

async def _send_brand_banner(chat_id: int):
    await _tg_send_photo(chat_id)           # логотип
    await _tg_send_text(chat_id, BRAND_TEXT)
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
    await _send_brand_banner(chat_id)
    _update_chat_profile(chat_id, last_brand_banner_at_iso=_utcnow().isoformat())

async def _maybe_send_first_or_reconnect_banner(chat_id: int):
    """Фоново: первое общение (полный баннер) или мягкое приветствие после 24h."""
    profile = _get_chat_profile(chat_id)

    # Первое сообщение вообще
    if not profile or profile.get("greeted") is not True:
        await _send_brand_banner(chat_id)
        _update_chat_profile(
            chat_id,
            greeted=True,
            first_seen_at_iso=_utcnow().isoformat(),
            last_brand_banner_at_iso=_utcnow().isoformat(),
        )
        return

    # Мягкое приветствие после паузы (24h)
    last_msg_iso = profile.get("last_message_at_iso")
    if _hours_ago(last_msg_iso, RECONNECT_HOURS):
        # антиспам: не чаще раза в 24h
        last_brand_iso = profile.get("last_brand_banner_at_iso")
        if last_brand_iso and not _hours_ago(last_brand_iso, 24):
            return
        await _send_reconnect_then_brand(chat_id)

async def _maybe_send_session_wait_banner(chat_id: int):
    """Фоново: статус ожидания для паузы >1h и <24h."""
    profile = _get_chat_profile(chat_id)
    if not profile: return
    last_msg_iso = profile.get("last_message_at_iso")
    # >1h — показываем статус ожидания; >24h — этим занимается reconnect-баннер
    if _hours_ago(last_msg_iso, SESSION_WAIT_HOURS) and not _hours_ago(last_msg_iso, RECONNECT_HOURS):
        await _tg_send_text(chat_id, SESSION_WAIT_TEXT)
        try:
            db.collection("events").add({
                "type": "session_wait_banner",
                "chat_id": chat_id,
                "created_at": firestore.SERVER_TIMESTAMP,
                "stage": "session_wait_banner",
            })
        except Exception as e:
            _dlog("events session_wait_banner error", repr(e))

# ---------- OpenAI ----------
def _openai_client():
    if not OPENAI_API_KEY or OpenAI is None:
        _dlog("openai skipped", {"key": bool(OPENAI_API_KEY), "sdk": OpenAI is not None})
        return None
    try:
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        _dlog("OpenAI init error", repr(e))
        return None

async def _router_answer(user_text: str) -> str:
    if not OPENAI_API_KEY:
        return "Техническая пауза ядра. Повторим чуть позже."
    client = _openai_client()
    if client is None:
        return "Временная недоступность мозгового центра. Давай повторим запрос позже."

    # 1) Responses API
    try:
        _dlog("responses.create", {"model": OPENAI_MODEL})
        resp = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.2,
            max_output_tokens=700,
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
            max_tokens=700,
        )
        text = (ch.choices[0].message.content if ch and ch.choices else "" or "").strip()
        if text: return text
        _dlog("chat empty")
    except Exception as e:
        _dlog("chat error", repr(e))

    return "Я на связи, но сейчас техническое окно. Повтори, пожалуйста, мысль — проверю цепочку."

# ---------- Processing pipeline ----------
async def _process_update(chat_id: int, update_id: int, user_text: str):
    out_id = f"{chat_id}:{update_id}"
    out_ref = db.collection("outbox").document(out_id)

    # уже отвечали на этот update?
    try:
        snap = out_ref.get()
        if snap.exists and snap.to_dict().get("sent") is True:
            _dlog("outbox skip", out_id)
            return
    except Exception as e:
        _dlog("outbox check error", repr(e))

    # session-wait баннер при паузе >1h (и <24h)
    asyncio.create_task(_maybe_send_session_wait_banner(chat_id))

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

    # ответ технолога
    answer = await _router_answer(user_text)

    # отправка ответа
    try:
        await _tg_send_text(chat_id, answer)
    except Exception as e:
        _dlog("telegram send error", repr(e))

    # журнал: отправлен
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
    # Парсим
    try:
        payload = await req.json()
    except Exception:
        return JSONResponse({"ok": True, "ack": "ignored_non_json"})

    update_id = payload.get("update_id")
    message = payload.get("message") or payload.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    user_text = (message.get("text") or "").strip()

    if not update_id or not chat_id:
        return JSONResponse({"ok": True, "ack": "ignored_missing_fields"})

    # inbox идемпотентно
    inbox_id = f"{chat_id}:{update_id}"
    inbox_ref = db.collection("inbox").document(inbox_id)

    @firestore.transactional
    def _create_inbox_once(tx: firestore.Transaction):
        snap = inbox_ref.get(transaction=tx)
        if snap.exists: return False
        now = _utcnow()
        tx.set(inbox_ref, {
            "chat_id": chat_id,
            "update_id": update_id,
            "text": user_text,
            "raw": payload,  # при желании выключить позже
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

    # журнал входящего
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

    # обновим профиль чата
    _update_chat_profile(chat_id, last_message_at_iso=_utcnow().isoformat())

    # ПРИВЕТСТВИЯ — фоном
    if SEND_ACK_BANNER:
        asyncio.create_task(_maybe_send_first_or_reconnect_banner(chat_id))

    # Запускаем обработку (директор/технолог)
    asyncio.create_task(_process_update(chat_id, update_id, user_text))

    # мгновенный ACK
    return JSONResponse({"ok": True, "inbox_created": created})
