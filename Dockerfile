FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Sao_Paulo

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY check_stocks.py list_options.py telegram_notify.py scheduler.py stocks.json ./

# Run as a non-root user
RUN useradd --create-home bot
USER bot

# Runs check_stocks.py --notify every hour, 10:00-18:00, Monday to Friday
CMD ["python", "scheduler.py"]
