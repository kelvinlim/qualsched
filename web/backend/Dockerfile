FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

COPY . .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

# Wait for the DB, run migrations, then serve. Compose healthchecks are not enough
# on every runtime (podman-compose), so the wait lives here too.
CMD ["/entrypoint.sh"]
