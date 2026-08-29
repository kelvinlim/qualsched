# Build the Vite app from the monorepo root so `ui/` is on the workspace.
# Context MUST be the qualsched repo root (see docker-compose.yml and scripts/deploy.sh).
# Then serve the static bundle via nginx (which also reverse-proxies the
# backend API so the SPA stays same-origin — no CORS).
FROM node:20-alpine AS build
WORKDIR /src
# Production default: asset + fetch URLs live under /qualsched/. Host nginx strips
# that prefix; this container still serves at /. Local compose overrides VITE_BASE=/.
ARG VITE_BASE=/qualsched/
ENV VITE_BASE=$VITE_BASE
COPY package.json package-lock.json ./
COPY ui/package.json ui/package.json
COPY desktop/package.json desktop/package.json
COPY web/frontend/package.json web/frontend/package.json
RUN npm ci
COPY ui ui
COPY web/frontend web/frontend
WORKDIR /src/web/frontend
RUN npm run build

FROM nginx:alpine
COPY web/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/web/frontend/dist /usr/share/nginx/html
COPY web/frontend/30-set-resolver.sh /docker-entrypoint.d/30-set-resolver.sh
RUN chmod +x /docker-entrypoint.d/30-set-resolver.sh
EXPOSE 80
