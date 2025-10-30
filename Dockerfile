# ---- 1. Базовый образ Python ----
FROM python:3.11-slim

# ---- 2. Рабочая директория в контейнере ----
WORKDIR /app

# ---- 3. Копируем зависимости отдельно, чтобы слои кэшировались ----
COPY requirements.txt /app/requirements.txt

# ---- 4. Ставим зависимости ----
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# ---- 5. Копируем весь исходный код проекта внутрь контейнера ----
COPY . /app

# ---- 6. Важные переменные окружения ----
ENV PORT=8080

# ---- 7. Запускаем FastAPI через uvicorn ----
CMD ["uvicorn", "src.webhook.main:app", "--host", "0.0.0.0", "--port", "8080"]
