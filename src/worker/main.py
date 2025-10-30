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
    """
    Периодический обработчик:
    1) Бронирует pending-задачи (status -> processing) в транзакции
    2) Шлёт быстрый баннер-ACK
    3) Получает ответ от GPT и шлёт его
    4) Помечает задачу как done
    """
    now = datetime.now(timezone.utc)
    processed = 0

    # 1) Лизинг задач (без падений, корректная транзакция Firestore)
    jobs = lease_pending_jobs(db, limit=3)

    for job in jobs:
        doc_id = job["id"]
        chat_id = job.get("chat_id")
        text = job.get("user_text", "")

        try:
            # 2) быстрый фирменный отклик-баннер
            if chat_id:
                send_message(chat_id, "📖 𝗕𝗼𝗼𝗸𝗦𝗼𝘂𝗹 · AI Soul Factory 🌿")

            # 3) мягкий ответ GPT (если есть текст)
            if text and chat_id:
                gpt_reply = generate_reply(text)
                if gpt_reply:
                    send_message(chat_id, gpt_reply)

            # 4) финализация: status -> done
            try:
                db.collection("jobs_inbox").document(doc_id).update({
                    "status": "done",
                    "updated_at": firestore.SERVER_TIMESTAMP,
                })
            except Exception as e_upd:
                print(f"finalize error [{doc_id}]: {e_upd}")

            processed += 1

        except Exception as e:
            print(f"job error [{doc_id}]: {e}")

    return {"processed_jobs": processed, "time": now.isoformat()}


def lease_pending_jobs(db_client: firestore.Client, limit: int = 3):
    """
    Бронируем pending-задачи транзакционно:
    - читаем документы со status='pending'
    - для каждого пробуем в транзакции сменить статус на 'processing'
    - возвращаем только успешно «забронированные» задачи
    """
    leased = []
    try:
        # читаем кандидатов (stream, чтобы не грузить всё)
        candidates = db_client.collection("jobs_inbox") \
                              .where("status", "==", "pending") \
                              .limit(limit) \
                              .stream()
    except Exception as e_query:
        print("lease query error:", e_query)
        return leased

    for snap in candidates:
        doc_ref = snap.reference

        try:
            # корректная транзакция в Python SDK
            tx = db_client.transaction()

            # читаем внутри транзакции
            current = doc_ref.get(transaction=tx)
            data = current.to_dict() or {}

            if data.get("status") == "pending":
                # меняем статус на processing
                tx.update(doc_ref, {
                    "status": "processing",
                    "updated_at": firestore.SERVER_TIMESTAMP,
                })
                # важный момент: фиксируем транзакцию вручную
                tx.commit()

                # кладём в список для дальнейшей обработки
                leased.append({
                    "id": doc_ref.id,
                    **data
                })
            else:
                # ничего не делаем, не pending
                pass

        except Exception as e_tx:
            print("Lease transaction failed:", e_tx)

    return leased


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
        # нейтральный fallback
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
