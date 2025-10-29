import os
import sys
from dataclasses import dataclass
from dotenv import load_dotenv

print("⚙️ config.py LOADED")

# === 1. Пути проекта и .env ===
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))      # .../src
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)                    # корень репозитория
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

# .env нужен только локально. В Cloud Run его нет — это нормально.
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)
else:
    print(f"⚠ ВНИМАНИЕ: .env не найден по пути {ENV_PATH} (это нормально для Cloud Run)")

# === 2. Settings — единый источник правды для всей фабрики BookSoul ===
@dataclass
class Settings:
    # --- Google / Firestore ---
    gcp_project_id: str
    firestore_collection_books: str
    gcs_bucket: str

    # --- Google Sheets панель контроля ---
    sheets_id: str

    # --- OpenAI ---
    openai_api_key: str
    openai_model_name: str

    # --- Gemini (опционально) ---
    gemini_api_key: str

    # --- Telegram бот ---
    telegram_bot_token: str

    # --- PDF / верстка ---
    reportlab_font: str

    def ensure_env_ready(self):
        """Готовим окружение для SDK."""
        if self.gcp_project_id:
            os.environ["GOOGLE_CLOUD_PROJECT"] = self.gcp_project_id

        # Больше не устанавливаем GOOGLE_APPLICATION_CREDENTIALS
        # Cloud Run использует Application Default Credentials (ADC)

        if self.openai_api_key:
            os.environ["OPENAI_API_KEY"] = self.openai_api_key

        print("🔹 SETTINGS INITIALIZED")
        print(f"   GOOGLE_CLOUD_PROJECT set: {bool(self.gcp_project_id)}")
        print("   GOOGLE_APPLICATION_CREDENTIALS set: False (ADC mode)")
        print(f"   OPENAI_API_KEY loaded: {bool(self.openai_api_key)}")
        print(f"   TELEGRAM_BOT_TOKEN loaded: {bool(self.telegram_bot_token)}")
        print(f"   SHEETS_ID present: {bool(self.sheets_id)}")
        print(f"   OPENAI_MODEL_NAME: {self.openai_model_name}")


def build_settings() -> Settings:
    """Сборка настроек (локально — из .env, в Cloud Run — из переменных окружения)."""
    return Settings(
        # --- GOOGLE / FIRESTORE ---
        gcp_project_id=os.getenv("GCP_PROJECT_ID", os.getenv("GOOGLE_PROJECT_ID", "")),
        firestore_collection_books=os.getenv("FIRESTORE_COLLECTION", "books"),
        gcs_bucket=os.getenv("GCS_BUCKET", ""),

        # --- SHEETS ---
        sheets_id=os.getenv("SHEETS_ID", ""),

        # --- OPENAI ---
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-5-pro"),

        # --- GEMINI ---
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),

        # --- TELEGRAM ---
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),

        # --- REPORTLAB ---
        reportlab_font=os.getenv("REPORTLAB_FONT", "HeiseiMin-W3"),
    )


# 3. создаём глобальный экземпляр настроек
settings = build_settings()

# 4. прогреваем окружение
settings.ensure_env_ready()
