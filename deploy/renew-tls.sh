#!/usr/bin/env bash
# Renew the TLS certificate and reload nginx.
#
# The compose stack already runs certbot on a renewal loop; this script exists
# so renewal can be tested on demand, and so the copy-and-reload step is
# defined in one place rather than duplicated in a cron entry.
set -euo pipefail
cd "$(dirname "$0")"

: "${DOMAIN:?Set DOMAIN}"
COMPOSE=(docker compose -f docker-compose.yml)

"${COMPOSE[@]}" run --rm --entrypoint certbot certbot renew --webroot -w /var/www/certbot

# certbot exits 0 whether or not it renewed, so always re-copy: it is cheap and
# a missed copy means serving an expired certificate until someone notices.
"${COMPOSE[@]}" run --rm --entrypoint sh certbot -c \
  "cp -L /etc/letsencrypt/live/${DOMAIN}/fullchain.pem /certs-out/fullchain.pem && \
   cp -L /etc/letsencrypt/live/${DOMAIN}/privkey.pem   /certs-out/privkey.pem"
"${COMPOSE[@]}" exec proxy nginx -s reload
echo "Certificate renewed and nginx reloaded."
