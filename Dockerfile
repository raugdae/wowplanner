FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY wowplanner ./wowplanner

# Site web (activé par WEB_PORT, voir docker-compose.traefik.yml).
EXPOSE 8080

# UID/GID fixes : le dossier ./data de l'hôte doit appartenir à 1000:1000 (voir README).
RUN groupadd --gid 1000 bot && useradd --uid 1000 --gid 1000 --create-home bot \
    && mkdir -p /app/data && chown 1000:1000 /app/data
USER bot
VOLUME ["/app/data"]

CMD ["python", "-m", "wowplanner"]
