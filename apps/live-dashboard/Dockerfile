FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HOST=0.0.0.0 PORT=8050
EXPOSE 8050

# Shell form so $PORT (injected by Railway/Heroku/etc.) is expanded at runtime,
# falling back to 8050 for local `docker run`.
CMD gunicorn app:server --bind 0.0.0.0:${PORT:-8050} --workers 1 --timeout 120
