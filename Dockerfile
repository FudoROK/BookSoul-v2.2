# =======================
# BookSoul Webhook Dockerfile
# =======================

# 1. Базовый образ с Python
FROM python:3.11-slim

# 2. Рабочая директория внутри контейнера
WORKDIR /app

# 3. Копируем requirements и ставим зависимости
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 4. Копируем всё содержимое проекта
COPY . /app
# --- BookSoul branding assets ---
COPY assets/ /app/assets/


# 5. Принудительно обновляем main.py — чтобы Docker не тянул кэшированный слой
COPY src/webhook/main.py /app/src/webhook/main.py

# 6. Окружение: отключаем буферизацию логов, выставляем порт
ENV PYTHONUNBUFFERED=1 \
    PORT=8080

# 7. Команда запуска (Uvicorn)
CMD ["uvicorn", "src.webhook.main:app", "--host", "0.0.0.0", "--port", "8080"]
