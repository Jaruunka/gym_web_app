FROM python:3.11.8-slim

WORKDIR /app

COPY . .

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

ENV PORT=10000

ENTRYPOINT ["sh", "-c", "exec gunicorn app:app --bind 0.0.0.0:$PORT --workers 1"]