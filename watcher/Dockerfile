# Blockchain Watcher: отдельный сервис, использует общие модели backend и БД.
# Приватные ключи и seed не используются — только чтение событий и запись в БД.
FROM python:3.11-slim

WORKDIR /app

# Build deps for ed25519-blake2b (bip_utils) C extension
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Общая БД и конфиг; код backend для моделей и сервисов
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
RUN pip install --no-cache-dir web3

COPY backend/src /app/backend/src
COPY watcher /app/watcher

ENV PYTHONPATH=/app/backend
WORKDIR /app/watcher

CMD ["python", "main.py"]
