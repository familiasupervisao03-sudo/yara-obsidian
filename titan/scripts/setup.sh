#!/bin/sh
# TITAN — configuração inicial local. Não sobrescreve um .env existente.
# Não usa sudo, não instala pacotes do sistema e não altera nada fora desta pasta.
set -eu
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "Python 3 não encontrado ($PY)."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
  || { echo "Python 3.10+ é necessário (encontrado: $("$PY" --version 2>&1)). Veja docs/notebook-install.md."; exit 1; }

# Espaço mínimo: ~300 MB (ambiente virtual + dados iniciais).
FREE_KB="$(df -Pk . | awk 'NR==2 {print $4}')"
if [ "${FREE_KB:-0}" -lt 307200 ]; then
  echo "Espaço livre insuficiente: $((FREE_KB / 1024)) MB (mínimo ~300 MB)."; exit 1
fi

if [ ! -d .venv ]; then
  "$PY" -m venv .venv 2>/dev/null || {
    echo "Não foi possível criar o ambiente virtual."
    echo "Em Debian/Ubuntu/Mint, o módulo venv vem no pacote python3-venv (exige sudo; peça autorização)."
    exit 1
  }
fi
.venv/bin/python -m pip install -q --upgrade pip
EXTRAS="${TITAN_EXTRAS:-}"   # ex.: TITAN_EXTRAS=dev  (dev = pytest, para os testes)
TARGET="."
[ -n "$EXTRAS" ] && TARGET=".[$EXTRAS]"
# Somente pacotes pré-compilados: nada é compilado neste computador.
.venv/bin/python -m pip install -q --only-binary=:all: -e "$TARGET" || {
  echo "Falha ao instalar dependências pré-compiladas para esta arquitetura ($(uname -m))."
  echo "Nada foi compilado nem instalado no sistema. Veja docs/notebook-install.md (seção Problemas)."
  exit 1
}

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
chmod 700 var 2>/dev/null || true

if [ -f apps/web/dist/index.html ]; then
  echo "Interface já compilada em apps/web/dist."
else
  echo "Interface ainda não compilada. Com Node.js 20.19+: npm ci && npm run build"
fi
echo "Crie seu usuário:  .venv/bin/titan create-user <nome>"
echo "Verifique:         .venv/bin/python scripts/verify_local.py"
echo "Inicie:            .venv/bin/titan serve"
