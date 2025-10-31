# src/webhook/main.py
# BookSoul Webhook — полный мейн:
# 1) Идемпотентный прием апдейта (inbox) + мгновенный 200 OK
# 2) Журнал событий (events): incoming_message, router_start, router_sent
# 3) Баннер на ПЕРВОЕ сообщение чата (один раз), опционально
# 4) Индикатор "печатает…" (typing) на короткое время
# 5) Вызов директора (GPT-5) на КАЖДОЕ сообщение и ответ в Telegram
# 6) outbox-дедуп ответов по ключу <chat_id>:<update_id>
# 7) DEBUG_ROUTER=true — расширенные логи вокруг вызова модели и отправки в Telegram

from __future__ import annotations
import os
import time
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from google.cloud import firestore

# --- Опциональные HTTP-вызовы к Telegram ---
try:
    import httpx
except Exception:
    httpx = None

# --- Опциональный клиент OpenAI (двойной fallback) ---
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

app = FastAPI()
db = firestore.Client()  # ADC: Cloud Run подтянет сервисный аккаунт

# ------------ ENV НАСТРОЙКИ ------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else ""

# Баннер приветствия включается однократно на чат
SEND_ACK_BANNER = os.getenv("SEND_ACK_BANNER", "true").lower() == "true"

# Индикатор "печатает…" (typing)
TYPING_FEEDBACK = os.getenv("TYPING_FEEDBACK", "true").lower() == "true"
TYPING_DURATION_SEC = int(os.getenv("TYPING_DURATION_SEC", "8"))

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-pro")  # название модели можно поменять в ENV

SYSTEM_PROMPT = (
    "You are the Director of BookSoul Factory. "
    "Answer the user briefly, helpfully, and specifically about making a custom children's book. "
    "If info is missing, ask one clear follow-up question. "
    "Avoid small talk. Keep it practical."
)

# Debug-флаг для расширенного логирования
DEBUG_ROUTER = os.getenv("DEBUG_ROUTER", "false").lower() == "true"

def _dlog(*args):
    """Безопасный печатный лог только при DEBUG_ROUTER=true (секреты не логируем)."""
    if DEBUG_ROUTER:
        try:
            print("[router]", *args)
        except Exception:
            pass

# ----------------------------------------


@app.get("/")
def health():
    return {"status": "ok", "service": "booksoul-webhook2"}


# =============== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===============

async def _tg_send_text(chat_id: int, text: str):
    if not (TELEGRAM_API and httpx):
        _dlog("telegram send skipped:", {"has_api": bool(TELEGRAM_API), "has_httpx": bool(httpx)})
        return
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        _dlog("telegram send status", r.status_code)
        r.raise_for_status()


async def _tg_send_typing(chat_id: int):
    if not (TYPING_FEEDBACK and TELEGRAM_API and httpx):
        _dlog("typing skipped:", {"TYPING_FEEDBACK": TYPING_FEEDBACK, "has_api": bool(TELEGRAM_API), "has_httpx": bool(httpx)})
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{TELEGRAM_API}/sendChatAction", data={
                "chat_id": chat_id,
                "action": "typing"
            })
            _dlog("typing status", r.status_code)
    except Exception as e:
        print("typing action error:", e)


async def _typing_loop(chat_id: int, seconds: int):
    remaining = max(0, seconds)
    while remaining > 0:
        await _tg_send_typing(chat_id)
        await asyncio.sleep(4)  # эффект держится ~5с, пульсируем раз в ~4с
        remaining -= 4


async def _send_banner_once(chat_id: int) -> bool:
    """Отправляет баннер только 1 раз на чат (ч/з коллекцию chats)."""
    if not (SEND_ACK_BANNER and TELEGRAM_API and httpx and chat_id):
        return False

    chats_ref = db.collection("chats").document(str(chat_id))

    @firestore.transactional
    def _ensure_welcomed(tx: firestore.Transaction) -> bool:
        snap = chats_ref.get(transaction=tx)
        if snap.exists and snap.to_dict().get("welcomed") is True:
            return False
        tx.set(chats_ref, {"welcomed": True}, merge=True)
        return True

    tx = db.transaction()
    should_send = False
    try:
        should_send = _ensure_welcomed(tx)
    except Exception as e:
        print("welcome flag error:", e)
        return False

    if not should_send:
        return False

    banner = (
        "📚 <b>BookSoul — AI Soul Factory</b>\n"
        "Запрос принят 👌 Начинаю сборку книги.\n"
        "Редактор подключится в ближайшую минуту."
    )
    try:
        await _tg_send_text(chat_id, banner)
        return True
    except Exception as e:
        print("telegram banner error:", e)
        return False


def _openai_client():
    if not OPENAI_API_KEY or OpenAI is None:
        _dlog("openai client skipped:", {"has_key": bool(OPENAI_API_KEY), "has_sdk": OpenAI is not None})
        return None
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        _dlog("openai client ok")
        return client
    except Exception as e:
        print("OpenAI client init error:", e)
        return None


async def _router_answer(user_text: str) -> str:
    """
    Вызов директора (GPT-5). Возвращает текст для Telegram.
    Делает два варианта вызова: Responses API (новый) и Chat Completions (fallback).
    """
    if not OPENAI_API_KEY:
        _dlog("no OPENAI_API_KEY")
        return "Техническая пауза: подключаю мозг. Напиши ещё раз через минуту."

    client = _openai_client()
    if client is None:
        _dlog("OpenAI client init failed")
        return "Временная недоступность мозгового центра. Попробуем ещё раз чуть позже."

    # Попытка 1: Responses API (новый стиль)
    try:
        _dlog("responses.create ->", {"model": OPENAI_MODEL, "len_user_text": len(user_text)})
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
        _dlog("responses.create ok", {"len_answer": len(text)})
        if text:
            return text
        else:
            _dlog("responses.create empty_text")
    except Exception as e:
        _dlog("responses.create error", repr(e))

    # Попытка 2: Chat Completions (fallback на более старый интерфейс)
    try:
        _dlog("chat.completions.create ->", {"model": OPENAI_MODEL, "len_user_text": len(user_text)})
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
        _dlog("chat.completions.create ok", {"len_answer": len(text)})
        if text:
            return text
        else:
            _dlog("chat.completions.create empty_text")
    except Exception as e:
        _dlog("chat.completions.create error", repr(e))

    return "Я на связи, но сейчас техническое окно. Повтори, пожалуйста, мысль — проверю цепочку."


async def _process_update(chat_id: int, update_id: int, user_text: str):
    """
    Асинхронный пайплайн на каждое сообщение:
     - events: router_start
     - typing-индикатор на время работы
     - вызов директора (GPT-5)
     - отправка ответа в Telegram
     - events: router_sent
     - outbox.sent=true (идемпотентность ответа)
    """

    out_id = f"{chat_id}:{update_id}"
    out_ref = db.collection("outbox").document(out_id)

    # Если мы уже отправляли ответ на этот update_id — выходим
    try:
        snap = out_ref.get()
        if snap.exists and snap.to_dict().get("sent") is True:
            _dlog("outbox skip duplicate", out_id)
            return
    except Exception as e:
        print("outbox check error:", e)

    # Событие: старт роутера
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
        print("events router_start error:", e)

    # Запускаем typing на время обработки (не блокирует ACK)
    try:
        asyncio.create_task(_typing_loop(chat_id, TYPING_DURATION_SEC))
    except Exception as e:
        print("typing loop spawn error:", e)

    # Вызов директора
    answer = await _router_answer(user_text)

    # Отправка ответа
    try:
        await _tg_send_text(chat_id, answer)
    except Exception as e:
        print("telegram send error:", e)

    # Событие: ответ отправлен
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
        print("events router_sent error:", e)

    # Отметка в outbox
    try:
        out_ref.set({"sent": True, "sent_at": firestore.SERVER_TIMESTAMP}, merge=True)
    except Exception as e:
        print("outbox set error:", e)


# =================== ОСНОВНОЙ ХЭНДЛЕР ===================

@app.post("/telegram_webhook")
async def telegram_webhook(req: Request):
    """
    Цепочка:
      1) принять апдейт → 2) идемпотентно записать в inbox → 3) баннер (первое сообщение) → 4) запуск фоновой обработки → 5) мгновенный 200 OK
    """
    # 0) Парсим апдейт
    try:
        payload = await req.json()
    except Exception:
        return JSONResponse({"ok": True, "ack": "ignored_non_json"})

    update_id = payload.get("update_id")
    message = payload.get("message") or payload.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    user_text = (message.get("text") or "").strip()

    # 1) Базовая фильтрация
    if not update_id or not chat_id:
        return JSONResponse({"ok": True, "ack": "ignored_missing_fields"})

    # 2) Идемпотентная запись в inbox: ключ <chat_id>:<update_id>
    inbox_id = f"{chat_id}:{update_id}"
    inbox_ref = db.collection("inbox").document(inbox_id)

    @firestore.transactional
    def _create_inbox_once(tx: firestore.Transaction):
        snap = inbox_ref.get(transaction=tx)
        if snap.exists:
            return False
        now = datetime.now(timezone.utc)
        tx.set(inbox_ref, {
            "chat_id": chat_id,
            "update_id": update_id,
            "text": user_text,
            "raw": payload,  # можно убрать позже
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
        print("inbox write error:", e)

    # 3) Журнал входящего события
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
        print("events incoming error:", e)

    # 4) Баннер — только 1 раз на чат (если включён)
    try:
        await _send_banner_once(chat_id)
    except Exception as e:
        print("send_banner_once runtime error:", e)

    # 5) Запуск фоновой обработки (директор + ответ) — НЕ блокирует ACK
    try:
        asyncio.create_task(_process_update(chat_id, update_id, user_text))
    except Exception as e:
        print("process_update spawn error:", e)

    # 6) Мгновенный ACK для Telegram — чтобы не было ретраев
    return JSONResponse({"ok": True, "inbox_created": created})
