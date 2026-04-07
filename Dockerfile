FROM python:3.12-slim

WORKDIR /app

COPY requirements.prod.txt .
RUN pip install --no-cache-dir -r requirements.prod.txt

COPY . .

ENV PYTHONPATH=/app

CMD ["sh", "-c", "echo \"DB_URL from env: ${DB_URL:-(not set, using config default)}\" | sed 's/:[^@]*@/:***@/' && alembic upgrade head && python -m bot.main"]
