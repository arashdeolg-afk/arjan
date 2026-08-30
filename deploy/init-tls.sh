#!/usr/bin/env bash
# Obtain the first TLS certificate for Deol Tech.
#
# There is a chicken-and-egg problem here worth naming: nginx refuses to start
# without a certificate, and Let's Encrypt cannot issue a certificate without
# nginx answering the HTTP-01 challenge. This script breaks the cycle the
# standard way — start nginx with a throwaway self-signed certificate, let
# certbot complete the challenge through it, then swap in the real one and
# reload.
#
#   DOMAIN=trade.example.com EMAIL=you@example.com ./deploy/init-tls.sh
#
# Re-running it is safe: an existing valid certificate is left alone.

set -euo pipefail

cd "$(dirname "$0")"

: "${DOMAIN:?Set DOMAIN, e.g. DOMAIN=trade.example.com}"
: "${EMAIL:?Set EMAIL — Let's Encrypt uses it for expiry warnings}"
STAGING="${STAGING:-0}"

COMPOSE=(docker compose -f docker-compose.yml)
CERT_DIR="./certs"

say() { printf '\n\033[1m==>\033[0m %s\n' "$1"; }

mkdir -p "$CERT_DIR"

if [ -s "$CERT_DIR/fullchain.pem" ] \
   && openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -checkend 604800 2>/dev/null \
   && ! openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -issuer 2>/dev/null \
        | grep -qi 'deoltech-bootstrap'; then
  say "A valid certificate is already in place. Nothing to do."
  exit 0
fi

say "Generating a temporary self-signed certificate so nginx can start"
# Clearly marked as bootstrap so the check above never mistakes it for real.
openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
  -keyout "$CERT_DIR/privkey.pem" -out "$CERT_DIR/fullchain.pem" \
  -subj "/CN=${DOMAIN}/O=deoltech-bootstrap" 2>/dev/null

say "Starting the stack"
"${COMPOSE[@]}" up -d

say "Waiting for the proxy to answer on port 80"
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null "http://localhost/.well-known/acme-challenge/probe" \
     || [ "$?" = "22" ]; then break; fi
  sleep 1
done

say "Requesting a certificate for ${DOMAIN} from Let's Encrypt"
STAGING_FLAG=()
[ "$STAGING" = "1" ] && STAGING_FLAG=(--staging)

"${COMPOSE[@]}" run --rm --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot \
  -d "$DOMAIN" --email "$EMAIL" \
  --agree-tos --no-eff-email --non-interactive \
  "${STAGING_FLAG[@]}"

say "Installing the certificate and reloading nginx"
"${COMPOSE[@]}" run --rm --entrypoint sh certbot -c \
  "cp -L /etc/letsencrypt/live/${DOMAIN}/fullchain.pem /certs-out/fullchain.pem && \
   cp -L /etc/letsencrypt/live/${DOMAIN}/privkey.pem   /certs-out/privkey.pem"
"${COMPOSE[@]}" exec proxy nginx -s reload

say "Done. https://${DOMAIN} is live."
echo
echo "Next:"
echo "  1. Create the first administrator:"
echo "       docker compose -f deploy/docker-compose.yml exec app \\"
echo "           python -m deoltech admin create"
echo "  2. Confirm Finviz is reachable from this host:"
echo "       docker compose -f deploy/docker-compose.yml exec app \\"
echo "           python -m deoltech probe"
echo "  3. Renewal runs automatically. Test it once with:"
echo "       ./deploy/renew-tls.sh"
