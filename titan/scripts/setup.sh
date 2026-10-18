#!/bin/sh
# TITAN — configuração inicial local. Não sobrescreve um .env existente.
set -eu
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
  || { echo "Python 3.10+ é necessário."; exit 1; }

[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
EXTRAS="${TITAN_EXTRAS:-}"   # ex.: TITAN_EXTRAS=postgres,dev
if [ -n "$EXTRAS" ]; then .venv/bin/pip install -q -e ".[$EXTRAS]"; else .venv/bin/pip install -q -e .; fi

if [ ! -f .env ]; then
  umask 077
  SECRET="$(.venv/bin/python -m titan.cli gen-secret)"
  sed "s|^TITAN_AUTH_SECRET=.*|TITAN_AUTH_SECRET=$SECRET|" .env.example > .env
  chmod 600 .env
  echo ".env criado com segredo aleatório (permissão 600)."
else
  echo ".env já existe; mantido sem alterações."
fi

.venv/bin/python -m titan.cli check-config >/dev/null
.venv/bin/python -m titan.cli migrate

if [ -d apps/web/dist ]; then
  echo "Interface já compilada em apps/web/dist."
else
  echo "Interface ainda não compilada. Com Node.js 20.19+: npm install && npm run build"
fi
echo "Crie seu usuário:  .venv/bin/titan create-user <nome>"
echo "Inicie:            .venv/bin/titan serve"
