#!/usr/bin/env bash
# Deploy QualSched Web on the prod host (lnpitask, Podman Quadlets).
#
# Run this ON the host, after checking out the commit/tag you want to ship. It rebuilds the
# images (code is baked in), restarts the services (the backend's startup runs
# `alembic upgrade head` against the external DB on cnc3), and health-checks.
#
# Backend + frontend only. There is no qualsched-scheduler unit (unlike wearable-hub).
#
# Monorepo layout: checkout is /home/kolim/Projects/qualsched
#   .env lives at web/.env (never at the repo root — desktop secrets stay out of it)
#   backend image: built from web/backend
#   frontend image: built from the repo root (needs ui/)
#
# Usage: web/scripts/deploy.sh [backend|frontend|all]   (default: all)
set -euo pipefail

WEB="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$WEB/.." && pwd)"
cd "$WEB"
TARGET="${1:-all}"

# `sudo` strips proxy env on lnpitask; re-export the proxy from .env so the base-image and
# dependency pulls during the build can reach out (sudo -E then inherits these).
for v in HTTP_PROXY HTTPS_PROXY NO_PROXY; do
  val="$(sed -nE "s/^$v=(.*)/\1/p" .env | head -1)"
  if [ -n "$val" ]; then
    export "$v=$val"
    export "$(printf '%s' "$v" | tr '[:upper:]' '[:lower:]')=$val"
  fi
done

build_backend() {
  echo "==> Building backend image"
  sudo -E podman build -t "localhost/qualsched-backend:latest" "$WEB/backend"
}

build_frontend() {
  echo "==> Building frontend image (context: monorepo root so ui/ is included)"
  sudo -E podman build -t "localhost/qualsched-frontend:latest" \
    -f "$WEB/frontend/Dockerfile" "$REPO"
}

case "$TARGET" in
  backend)
    build_backend
    echo "==> Restarting services"
    sudo systemctl restart qualsched-backend.service ;;
  frontend)
    build_frontend
    echo "==> Restarting services"
    sudo systemctl restart qualsched-frontend.service ;;
  all)
    build_backend
    build_frontend
    echo "==> Restarting services"
    sudo systemctl restart qualsched-backend.service qualsched-frontend.service ;;
  *)
    echo "usage: $0 [backend|frontend|all]" >&2; exit 1 ;;
esac

echo "==> Waiting for backend (migrations run on startup)"
for _ in $(seq 1 30); do
  code="$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' http://localhost:8050/health || true)"
  [ "$code" = "200" ] && break
  sleep 2
done
curl -s --noproxy '*' http://localhost:8050/health \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('backend /health: version', d.get('version'), '| db', d.get('db'))" \
  2>/dev/null || echo "backend /health: not OK"
# Frontend container sees "/", not "/qualsched/" (host nginx strips the prefix).
curl -s --noproxy '*' -o /dev/null -w 'frontend: HTTP %{http_code}\n' http://localhost:8060/
echo "==> Done"
