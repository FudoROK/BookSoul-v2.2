# src/webhook/main.py

import os
import sys
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, Request
import httpx

# === ПРАВИЛЬНЫЕ ПУТИ ===
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))      # .../src/webhook
SRC_DIR = os.path.dirname(CURRENT_DIR)                         # .../src
PROJECT_ROOT = os.path.dirname(SRC_DIR)                        # .../
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# --- наши модули ---
from config import settings
from router.assistant_openai import handle_user_message  # ассистент = мозг фабрики

# === Firestore инициализация ===
# По нашей архитектуре: цеха не трогают базу.
# Вебхук только регистрирует входящий запрос как job,
# чтобы фабрика знала, что родитель что-то попросил.
try:
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        # Без локального JSON-ключа.
        # Cloud Run сам даёт креды через сервисный аккаунт
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, {
            "projectId": settings.gcp_project_id
        })

    db = firestore.client()
    print("✅ Firestore initialized with ApplicationDefault()")
except Exception as e:
    print("❌ Firestore init failed:", e)
    db = None



app = FastAPI()

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


async def send_message(chat_id: int, text: str):
    """
    Отправка ответа обратно пользователю в Telegram.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"{TELEGRAM_API_BASE}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
        )


async def call_brain(user_text: str) -> str:
    """
    Обёртка над мозгом фабрики BookSoul.
    Внутри дергаем ассистента (GPT-5-pro),
    который решает, что с этим делать.
    """
    if asyncio.iscoroutinefunction(handle_user_message):
        # если когда-то сделаем ассистента async
        return await handle_user_message(user_text)

    # сейчас ассистент синхронный
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, handle_user_message, user_text)


def create_job_in_firestore(chat_id: int, user_text: str):
    """
    Регистрируем новый запрос родителя как job в Firestore.
    Это не генерация книги. Это факт заявки.
    Ассистент потом уже будет дополнять этот job.
    """
    if db is None:
        print("⚠ Firestore is not available, job not saved.")
        return None

    try:
        now = datetime.now(timezone.utc)
        job_doc = {
            "chat_id": chat_id,
            "user_text": user_text,
            "status": "awaiting_outline",  # первый статус цепочки
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
    """
    Входная дверь. Telegram шлёт сюда апдейты.
    Здесь мы:
    1. Читаем сообщение
    2. Создаём запись job в Firestore
    3. Спрашиваем мозг (ассистента)
    4. Возвращаем ответ человеку
    """
    data = await request.json()

    # 1. Вытаскиваем данные из апдейта
    message = data.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    user_text = message.get("text", "")

    # Если текста нет — не ломаемся, отвечаем мягко
    if not user_text or chat_id is None:
        if chat_id is not None:
            await send_message(
                chat_id,
                "Я получил сообщение без текста. Напиши словами, какую книгу или правку ты хочешь 📘"
            )
        return {"ok": True}

    # 2. Создаём запись о заявке в Firestore
    job_id = create_job_in_firestore(chat_id, user_text)

    # 3. Дёргаем ассистента — он думает, уточняет, генерит, решает
    try:
        reply_text = await call_brain(user_text)
    except Exception as e:
        print("❌ Assistant failed:", e)
        reply_text = (
            "Сейчас фабрика не смогла обработать задачу технически. "
            "Текст я не потерял. 🌿"
        )

    # 4. Если job_id есть, добавим его в ответ (прозрачно для родителя)
    final_reply = reply_text
    if job_id:
        final_reply += f"\n\n(id заявки: {job_id})"

    # 5. Отправляем ответ родителю в Telegram
    await send_message(chat_id, final_reply)

    # 6. Telegram ждёт JSON {"ok": true}
    return {"ok": True}
