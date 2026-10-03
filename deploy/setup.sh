#!/usr/bin/env bash
# One-command install on a fresh Ubuntu server (22.04/24.04), from the repo root:
#
#   sudo bash deploy/setup.sh you@example.com
#
# Installs Docker, writes .env.production with freshly generated secrets, and
# starts the production stack behind HTTPS. With no domain given it uses free
# sslip.io names built from the server's public IP, e.g.
#   https://app.203-0-113-7.sslip.io   and   https://files.203-0-113-7.sslip.io
# Pass your own domains as the 2nd and 3rd arguments once you have them:
#
#   sudo bash deploy/setup.sh you@example.com app.mydomain.com files.mydomain.com
#
# Re-running is safe: an existing .env.production is kept, and the stack is
# rebuilt and restarted with the current code.
set -euo pipefail

EMAIL="${1:?usage: sudo bash deploy/setup.sh you@example.com [app-domain] [files-domain]}"
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi

IP="$(curl -fsS https://api.ipify.org)"
DASHED="${IP//./-}"
APP_DOMAIN="${2:-app.${DASHED}.sslip.io}"
FILES_DOMAIN="${3:-files.${DASHED}.sslip.io}"

if [ ! -f .env.production ]; then
  echo "==> Writing .env.production with new secrets"
  hex() { openssl rand -hex 32; }
  # A Fernet key: 32 random bytes, URL-safe base64.
  FERNET="$(openssl rand -base64 32 | tr '+/' '-_')"
  cat > .env.production <<EOF
APP_DOMAIN=${APP_DOMAIN}
FILES_DOMAIN=${FILES_DOMAIN}
ACME_EMAIL=${EMAIL}

JWT_SECRET=$(hex)
ENCRYPTION_KEY=${FERNET}
POSTGRES_PASSWORD=$(hex)
REDIS_PASSWORD=$(hex)
S3_ACCESS_KEY=salesrobo
S3_SECRET_KEY=$(hex)

AI_ASSISTANT_PROVIDERS=openai,gemini
OPENAI_API_KEY=${OPENAI_API_KEY:-}
GEMINI_API_KEY=${GEMINI_API_KEY:-}

LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
EOF
  chmod 600 .env.production
else
  echo "==> Keeping the existing .env.production"
fi

if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp >/dev/null && ufw allow 80/tcp >/dev/null && ufw allow 443 >/dev/null
  ufw --force enable >/dev/null
fi

echo "==> Building and starting (the first build takes 5-10 minutes)"
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

APP="$(grep '^APP_DOMAIN=' .env.production | cut -d= -f2)"
echo
echo "Done. Open https://${APP}"
echo "(The HTTPS certificate is issued on the first visit; give it up to a minute.)"
echo
echo "Next:"
echo "  1. Sign up in the app."
echo "  2. Make yourself platform admin:"
echo "     docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \\"
echo "       psql -U salesrobo -c \"UPDATE users SET is_superuser = true WHERE email = '${EMAIL}';\""
echo "  3. Add AI keys: edit .env.production, then re-run this script."
echo "  4. Keep a copy of ENCRYPTION_KEY from .env.production somewhere safe."
