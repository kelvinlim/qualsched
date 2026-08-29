#!/bin/sh
# Inject the container's DNS resolver into nginx.conf so the reverse proxy
# re-resolves `backend` per request and survives backend restarts.
set -e
RESOLVER=$(awk '/^nameserver / {print $2; exit}' /etc/resolv.conf)
sed -i "s|__DNS_RESOLVER__|${RESOLVER}|" /etc/nginx/conf.d/default.conf
echo "30-set-resolver: nginx using DNS resolver ${RESOLVER}"
