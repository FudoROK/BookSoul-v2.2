# src/main.py  (или src/webhook/main.py)

import os
import sys
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, Request
import httpx

# === Универсальная настройка путей (работает и для src/, и для src/webhook/) ===
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = CURRENT_DIR if os.path.basename(CURRENT_DIR) == "src" else os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
for p in (SRC_DIR, PROJECT_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# --- наши модули ---
from config import settings
from router.assistant_openai import handle_user_message  # «мозг» фабрики

# === Firestore (ADC, без JSON-ключа) ===
try:
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, {"projectId": settings.gcp_project_id})

    db = firestore.client()
    print("✅ Firestore initialized with ApplicationDefault()")
except Exception as e:
    print("❌ Firestore init failed:", e)
    db = None

app = FastAPI()
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

async def send_message(chat_id: int, text: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"{TELEGRAM_API_BASE}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        )

async def call_brain(user_text: str) -> str:
    if asyncio.iscoroutinefunction(handle_user_message):
        return await handle_user_message(user_text)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, handle_user_message, user_text)

def create_job_in_firestore(chat_id: int, user_text: str):
    if db is None:
        print("⚠ Firestore is not available, job not saved.")
        return None
    try:
        now = datetime.now(timezone.utc)
        job_doc = {
            "chat_id": chat_id,
            "user_text": user_text,
            "status": "awaiting_outline",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        ref = db.collection("jobs").add(job_doc)
        job_id = ref[1].id  # add() -> (write_result, reference)
        print(f"📘 Firestore job created: {job_id}")
        return job_id
    except Exception as e:
        print("❌ Firestore write failed:", e)
        return None

@app.post("/telegram_webhook")
async def telegram_webhook(request: Request):
    data = await request.json()

    message = data.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    user_text = message.get("text", "")

    if not user_text or chat_id is None:
        if chat_id is not None:
            await send_message(chat_id, "Я получил сообщение без текста. Напиши словами, какую книгу ты хочешь 📘")
        return {"ok": True}

    job_id = create_job_in_firestore(chat_id, user_text)

    try:
        reply_text = await call_brain(user_text)
    except Exception as e:
        print("❌ Assistant failed:", e)
        reply_text = "Сейчас фабрика не смогла обработать задачу технически. Текст я не потерял 🌿"

    final_reply = reply_text + (f"\n\n(id заявки: {job_id})" if job_id else "")
    await send_message(chat_id, final_reply)
    return {"ok": True}
