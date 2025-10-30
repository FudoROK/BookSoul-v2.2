from fastapi import FastAPI
from google.cloud import firestore
from datetime import datetime, timedelta, timezone
import httpx, os
from openai import OpenAI

app = FastAPI()
db = firestore.Client()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client_ai = OpenAI(api_key=OPENAI_API_KEY)

@app.get("/tick")
def tick():
    now = datetime.now(timezone.utc)
    lease_time = now + timedelta(minutes=2)
    counter = 0

    docs = db.collection("jobs_inbox").where("status", "==", "pending").limit(3).get()

    for doc in docs:
        ref = doc.reference
        data = doc.to_dict()
        chat_id = data.get("chat_id")
        text = data.get("user_text", "")

        try:
            db.run_transaction(lambda tx: lease_job(tx, ref, data, lease_time))

            # 1️⃣ фирменный отклик
            if chat_id:
                send_message(chat_id, "📖 BookSoul · AI Soul Factory 🌿")

            # 2️⃣ ответ GPT-5
            if text and chat_id:
                gpt_reply = generate_reply(text)
                send_message(chat_id, gpt_reply)

            counter += 1
        except Exception as e:
            print("Lease error:", e)

    return {"processed_jobs": counter, "time": now.isoformat()}


def lease_job(tx, ref, data, lease_time):
    snap = tx.get(ref)
    if not snap.exists:
        return
    current = snap.to_dict()
    if current.get("status") != "pending":
        return
    tx.update(ref, {
        "status": "done",
        "lease_until": lease_time,
        "attempt": current.get("attempt", 0) + 1,
        "updated_at": firestore.SERVER_TIMESTAMP,
    })


def send_message(chat_id: int, text: str):
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    try:
        with httpx.Client(timeout=15) as client:
            client.post(url, data=data)
        print(f"✅ Sent to {chat_id}")
    except Exception as e:
        print(f"send_message error: {e}")


def generate_reply(prompt: str) -> str:
    """
    Вызов GPT-5 для генерации текста.
    """
    try:
        completion = client_ai.responses.create(
            model="gpt-5",
            input=f"User said: {prompt}\n\nWrite a friendly and clear reply from BookSoul.",
        )
        message = completion.output[0].content[0].text
        return message.strip()
    except Exception as e:
        print("GPT-5 error:", e)
        return "🤔 Ошибка при генерации ответа. Попробуйте позже."
