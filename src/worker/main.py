# src/worker/main.py
from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Body
from fastapi.responses import JSONResponse
from google.cloud import firestore

# ---- ЛОГИ ----
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("booksoul-worker")

app = FastAPI(title="BookSoul Worker", version="0.1.0")

# ---- ENV HELPERS ----
def env(name: str) -> Optional[str]:
    v = os.getenv(name)
    if isinstance(v, str):
        v = v.strip()
    return v or None

def telegram_api_base() -> str:
    # Позволяет переопределить базу через TELEGRAM_API_BASE (напр., для прокси),
    # но по умолчанию используем официальный endpoint
    return env("TELEGRAM_API_BASE") or "https://api.telegram.org"

def telegram_token() -> Optional[str]:
    return env("TELEGRAM_BOT_TOKEN")

# ---- LAZY FIRESTORE ----
_db: Optional[firestore.Client] = None

def get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client()
        log.info("Firestore client initialized.")
    return _db

# ---- HTTP HELPERS ----
def tg_request(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполняет Telegram API вызов.
    method: 'sendMessage' | 'getMe' | ...
    payload: dict параметров метода
    """
    token = telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

    base = telegram_api_base().rstrip("/")
    # защитимся от двойного 'bot'
    if token.startswith("bot"):
        url = f"{base}/{token}/{method}"
    else:
        url = f"{base}/bot{token}/{method}"

    with httpx.Client(timeout=10) as client:
        r = client.post(url, json=payload)
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "status_code": r.status_code, "text": r.text}
        return data if isinstance(data, dict) else {"ok": False, "status_code": r.status_code, "raw": data}

# ---- ROUTES ----
@app.get("/")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "booksoul-worker"}

@app.get("/tg_self")
def tg_self():
    """
    Диагностика: дергает getMe у Telegram.
    Удобно, чтобы проверить: токен виден ли воркером, сетка работает ли.
    """
    token = telegram_token()
    if not token:
        return JSONResponse({"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"})
    try:
        base = telegram_api_base().rstrip("/")
        url = f"{base}/bot{token[3:] if token.startswith('bot') else token}/getMe"
        with httpx.Client(timeout=10) as client:
            r = client.get(url)
            return JSONResponse({"status_code": r.status_code, "json": r.json()})
    except Exception as e:
        log.exception("tg_self failed")
        return JSONResponse({"ok": False, "error": str(e)})

@app.post("/echo")
def echo(payload: Dict[str, Any] = Body(...)):
    """
    Простой эхо для проверки сети и JSON.
    Пример: Invoke-WebRequest -Uri "<SERVICE>/echo" -Method POST -Body '{"a":1}' -ContentType "application/json"
    """
    return {"ok": True, "payload": payload}

@app.get("/tick")
def tick():
    """
    Периодический запуск из Cloud Scheduler (каждую минуту).
    1) Ищем заявки в jobs_inbox со статусом "pending".
    2) Отправляем быстрый баннер в Telegram.
    3) Обновляем статус на "done".
    Никаких транзакций/локов — всё максимально просто и устойчиво.
    """
    db = get_db()

    try:
        docs = (
            db.collection("jobs_inbox")
            .where("status", "==", "pending")
            .limit(5)
            .get()
        )
    except Exception as e:
        log.exception("Firestore query failed: %s", e)
        return {"processed_jobs": 0, "error": str(e)}

    processed = 0
    for snap in docs:
        data = snap.to_dict() or {}
        doc_id = snap.id
        chat_id = data.get("chat_id")
        user_text = data.get("user_text") or ""
        log.info("Picked job %s (chat_id=%s, text=%s)", doc_id, chat_id, user_text[:60])

        # 1) Быстрый баннер
        token = telegram_token()
        if token and chat_id:
            try:
                banner = "📖 𝗕𝗼𝗼𝗸𝗦𝗼𝘂𝗹 · AI Soul Factory 🌿"
                resp = tg_request("sendMessage", {"chat_id": chat_id, "text": banner})
                if not resp.get("ok"):
                    log.error("Telegram sendMessage failed for job %s: %s", doc_id, resp)
                else:
                    log.info("✅ Banner sent to %s", chat_id)
            except Exception as e:
                log.exception("Telegram send failed for job %s: %s", doc_id, e)
        else:
            if not token:
                log.error("❌ TELEGRAM_BOT_TOKEN not set (job %s)", doc_id)
            if not chat_id:
                log.error("❌ chat_id missing (job %s)", doc_id)

        # 2) Отмечаем заявкой как обработанную
        try:
            db.collection("jobs_inbox").document(doc_id).update({"status": "done"})
            processed += 1
        except Exception as e:
            log.exception("Failed to update job %s to done: %s", doc_id, e)

    return {"processed_jobs": processed}
