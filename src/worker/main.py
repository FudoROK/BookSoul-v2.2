from fastapi import FastAPI
from google.cloud import firestore
from datetime import datetime, timedelta, timezone
import httpx, os
from openai import OpenAI

app = FastAPI()
db = firestore.Client()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

@app.get("/")
def health():
    return {"status": "ok", "service": "booksoul-worker"}

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
            db.run_transaction(lambda tx: lease_job(tx, ref))

            # 1) быстрый фирменный отклик
            if chat_id:
                send_message(chat_id, "📖 BookSoul · AI Soul Factory 🌿")

            # 2) ответ GPT-5 (мягко, без падений)
            if text and chat_id:
                gpt_reply = generate_reply(text)
                if gpt_reply:
                    send_message(chat_id, gpt_reply)

            counter += 1
        except Exception as e:
            print("Lease error:", e)

    return {"processed_jobs": counter, "time": now.isoformat()}


def lease_job(tx, ref):
    snap = tx.get(ref)
    if not snap.exists:
        return
    current = snap.to_dict()
    if current.get("status") != "pending":
        return
    tx.update(ref, {
        "status": "done",
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


def get_openai_client() -> OpenAI | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ℹ️ OPENAI_API_KEY is not set — skipping GPT-5 call")
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:
        print("OpenAI init error:", e)
        return None


def generate_reply(prompt: str) -> str | None:
    client_ai = get_openai_client()
    if client_ai is None:
        # Возвращаем нейтральный текст или None — на ваше усмотрение
        return "Я принял ваше сообщение. Вернусь с ответом чуть позже. ✨"

    try:
        completion = client_ai.responses.create(
            model="gpt-5",
            input=f"User said: {prompt}\n\nAnswer as BookSoul: be clear, kind, short.",
        )
        message = completion.output[0].content[0].text
        return message.strip()
    except Exception as e:
        print("GPT-5 error:", e)
        return "Веду обработку сообщения. Пожалуйста, подождите немного. 🤖"
