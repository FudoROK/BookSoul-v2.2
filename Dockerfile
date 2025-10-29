# 1. Базовый образ
FROM python:3.11-slim

# 2. Чтобы не было вопросов от apt
ENV DEBIAN_FRONTEND=noninteractive

# 3. Рабочая директория внутри контейнера
WORKDIR /app

# 4. Пробиваем кэш.
#    Эта переменная будет меняться на каждом билде и ломать кэш.
#    Можешь руками менять значение BUILD_TS если вдруг снова увидим "застрял на старом коде".
ARG BUILD_TS=2025-10-29-01
ENV BUILD_TS=${BUILD_TS}

# 5. Копируем зависимости отдельно (чтобы не пересобирать тяжёлые пакеты без нужды)
COPY requirements.txt /app/requirements.txt

# 6. Ставим зависимости
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# 7. Копируем весь проект
COPY . /app

# 8. Добавляем PYTHONPATH, чтобы можно было делать `from config import settings`
ENV PYTHONPATH=/app

# 9. Uvicorn слушает порт, который Cloud Run передаёт через $PORT
CMD exec uvicorn src.webhook.main:app --host 0.0.0.0 --port ${PORT}
