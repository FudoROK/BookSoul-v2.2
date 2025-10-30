# src/webhook/main.py
# Webhook BookSoul — Fast ACK + очередь jobs_inbox (дедуп по update_id)

from fastapi import FastAPI, Request
from google.cloud import firestore
from datetime import datetime, timezone
import time

app = FastAPI()

# Firestore по ADC (без JSON-ключа, Cloud Run подтянет сам)
db = firestore.Client()

@app.get("/")
def health():
    return {"status": "ok", "service": "booksoul-webhook2"}

@app.post("/telegram_webhook")
async def telegram_webhook(req: Request):
    """
    Fast ACK:
      1) принимаем апдейт от Telegram;
      2) атомарно кладём в Firestore (jobs_inbox) с дедупом по update_id;
      3) сразу отдаём 200 OK, НИЧЕГО не отправляя пользователю (ответ пришлёт воркер).
    """
    try:
        payload = await req.json()
    except Exception:
        # если прилетело что-то не JSON — молча ACK
        return {"ok": True}

    update_id = payload.get("update_id")

    # Берём либо message, либо edited_message (минимально достаточно)
    msg = payload.get("message") or payload.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    user_text = msg.get("text") or ""

    # Если это не текст/нет chat_id/нет update_id — просто ACK без записи
    if not update_id or not chat_id or not isinstance(user_text, str):
        return {"ok": True}

    # Документ = update_id (дедуп Telegram-ретраев)
    doc_id = str(update_id)
    doc_ref = db.collection("jobs_inbox").document(doc_id)

    # Транзакционно создаём, только если ещё не было
    @firestore.transactional
    def _create_if_absent(tx: firestore.Transaction):
        snap = doc_ref.get(transaction=tx)
        if snap.exists:
            return  # дубликат/повтор — просто выходим
        now_utc = datetime.now(timezone.utc)
        tx.set(doc_ref, {
            "status": "pending",
            "type": "storywriter",
            "source": "telegram",

            "chat_id": chat_id,
            "user_text": user_text,
            "update_id": update_id,

            # Политика времени:
            "created_at": firestore.SERVER_TIMESTAMP,  # серверное UTC
            "created_at_iso_utc": now_utc.isoformat(), # дубликат строкой
            "created_at_epoch": int(time.time()),      # дубликат числом

            # Можно добавить поля для будущей маршрутизации
            # "route": "gpt5.storywriter",
        })

    tx = db.transaction()
    try:
        _create_if_absent(tx)
    except Exception as e:
        # Логи оставляем на контейнер: webhook всегда должен вернуть 200
        print("jobs_inbox insert error:", e)

    # Мгновенный ответ Telegram (без ожидания ИИ)
    return {"ok": True}
