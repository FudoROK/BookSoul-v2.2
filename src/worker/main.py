from fastapi import FastAPI, Query
from google.cloud import firestore
from datetime import datetime, timezone
import httpx, os, json
from openai import OpenAI

app = FastAPI()
db = firestore.Client()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


@app.get("/")
def health():
    return {"status": "ok", "service": "booksoul-worker"}


@app.get("/tg_self")
def tg_self():
    """
    Диагностика: показывает, каким ботом мы являемся (username, id).
    """
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
    try:
        with httpx.Client(timeout=15) as c:
            r = c.get(url)
        return {"status_code": r.status_code, "json": r.json()}
    except Exception as e:
        return {"ok": False, "error": f"getMe failed: {e}"}


@app.get("/echo")
def echo(chat_id: int = Query(...), text: str = Query("test")):
    """
    Диагностика: пробная отправка сообщения в конкретный chat_id.
    """
    ok, info = send_message(chat_id, text)
    return {"ok": ok, "info": info}


@app.get("/tick")
def tick():
    """
    Плановый обработчик:
    1) Транзакционно «лизуем» pending-задачи
    2) Отправляем быстрый баннер
    3) Если есть ключ — ответ GPT, иначе мягкий фолбэк
    4) status -> done
    """
    now = datetime.now(timezone.utc)
    processed = 0

    jobs = lease_pending_jobs(db, limit=3)

    for job in jobs:
        doc_id = job["id"]
        chat_id = job.get("chat_id")
        text = job.get("user_text", "")

        try:
            if chat_id:
                send_message(chat_id, "📖 𝗕𝗼𝗼𝗸𝗦𝗼𝘂𝗹 · AI Soul Factory 🌿")

            if text and chat_id:
                gpt_reply = generate_reply(text)
                if gpt_reply:
                    send_message(chat_id, gpt_reply)

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
    leased = []
    try:
        candidates = (
            db_client.collection("jobs_inbox")
            .where("status", "==", "pending")
            .limit(limit)
            .stream()
        )
    except Exception as e_query:
        print("lease query error:", e_query)
        return leased

    for snap in candidates:
        doc_ref = snap.reference
        tx = db_client.transaction()

        @firestore.transactional
        def _lease(transaction, ref):
            current = ref.get(transaction=transaction)
            data = current.to_dict() or {}
            if data.get("status") == "pending":
                transaction.update(ref, {
                    "status": "processing",
                    "updated_at": firestore.SERVER_TIMESTAMP,
                })
                return {"id": ref.id, **data}
            return None

        try:
            result = _lease(tx, doc_ref)
            if result:
                leased.append(result)
        except Exception as e_tx:
            print("Lease transaction failed:", e_tx)

    return leased


def send_message(chat_id: int, text: str):
    """
    Возвращает (ok: bool, info: dict) и ЛОГИРУЕТ полный ответ Telegram.
    Больше никаких ложных «✅ Sent…».
    """
    if not TELEGRAM_BOT_TOKEN:
        msg = "❌ TELEGRAM_BOT_TOKEN not set"
        print(msg)
        return False, {"error": msg}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(url, data=data)
        info = {"status_code": r.status_code}
        # пытаемся распарсить json
        try:
            j = r.json()
            info["json"] = j
            ok = bool(j.get("ok"))
            desc = j.get("description")
            if ok:
                print(f"✅ Telegram OK → chat_id={chat_id}")
            else:
                print(f"❌ Telegram FAIL → chat_id={chat_id} | {desc}")
            return ok, info
        except Exception:
            info["text"] = r.text
            print(f"❌ Telegram non-JSON → chat_id={chat_id} | {r.status_code} | {r.text[:200]}")
            return False, info
    except Exception as e:
        print(f"send_message error: {e}")
        return False, {"error": str(e)}


def get_openai_client() -> OpenAI | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ℹ️ OPENAI_API_KEY is not set — skipping GPT call")
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:
        print("OpenAI init error:", e)
        return None


def generate_reply(prompt: str) -> str | None:
    client_ai = get_openai_client()
    if client_ai is None:
        return "Я принял ваше сообщение. Вернусь с ответом чуть позже. ✨"

    try:
        completion = client_ai.responses.create(
            model="gpt-5",
            input=f"User said: {prompt}\n\nAnswer as BookSoul: be clear, kind, short.",
        )
        message = completion.output[0].content[0].text
        return message.strip()
    except Exception as e:
        print("GPT error:", e)
        return "Веду обработку сообщения. Пожалуйста, подождите немного. 🤖"
