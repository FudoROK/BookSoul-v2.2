# src/webhook/main.py

import os
import sys
import asyncio
from fastapi import FastAPI, Request
import httpx

# === ПРАВИЛЬНЫЕ ПУТИ ===
# Здесь мы делаем то же самое, что у тебя сделано в assistant_openai.py:
# добавляем в sys.path и саму папку src, и корень проекта.
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))      # .../src/webhook
SRC_DIR = os.path.dirname(CURRENT_DIR)                         # .../src
PROJECT_ROOT = os.path.dirname(SRC_DIR)                        # .../
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Теперь, ВАЖНО:
# assistant_openai.py физически лежит в src/router/assistant_openai.py
# Значит, после добавления SRC_DIR в sys.path мы можем импортировать так:
# from router.assistant_openai import handle_user_message
from config import settings
from router.assistant_openai import handle_user_message


app = FastAPI()

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


async def send_message(chat_id: int, text: str):
    """
    Отправка ответа обратно пользователю в Telegram.
    Это простой POST на sendMessage.
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
    Забираем человеческий текст,
    передаём его в handle_user_message (директор/оркестратор),
    получаем человеко-понятный ответ.
    """
    if asyncio.iscoroutinefunction(handle_user_message):
        # будущее: если мы переведём мозг на async
        return await handle_user_message(user_text)

    # текущее: handle_user_message синхронный
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, handle_user_message, user_text)


@app.post("/telegram_webhook")
async def telegram_webhook(request: Request):
    """
    Это входная дверь. Telegram будет сюда стучать каждый раз,
    когда тебе кто-то пишет в бота.
    """
    data = await request.json()

    # 1. Достаём нужные поля из апдейта
    message = data.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    user_text = message.get("text", "")

    # Если нет текста — отвечаем мягко и без паники.
    if not user_text or chat_id is None:
        if chat_id is not None:
            await send_message(
                chat_id,
                "Я получил сообщение без текста. Напиши словами, какую книгу или правку ты хочешь 📘"
            )
        return {"ok": True}

    # 2. Гоним текст в мозг (Orchestrator → Router → Firestore)
    try:
        reply_text = await call_brain(user_text)
    except Exception:
        # По нашему правилу:
        # при ошибке сначала объясняем простыми словами,
        # не лезем чинить сами, ждём твоих указаний.
        reply_text = (
            "Сейчас фабрика не смогла обработать задачу технически. "
            "Текст я не потерял. 🌿"
        )

    # 3. Возвращаем человеку ответ
    await send_message(chat_id, reply_text)

    # 4. Говорим Телеграму 'ок'
    return {"ok": True}
