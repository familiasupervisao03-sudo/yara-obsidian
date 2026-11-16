#!/bin/sh
# TITAN — instala (se preciso), verifica e inicia o servidor local.
# Seguro para rodar de novo: não sobrescreve .env, banco nem usuários.
# Não usa sudo, não abre portas, não envia dados. Servidor só em 127.0.0.1.
# Uso (na pasta titan/):  sh scripts/install_and_start.sh
set -eu
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

step() { printf '\n=== %s ===\n' "$1"; }

step "1/6 Auditoria do computador (somente leitura)"
AUDIT="$(dirname "$(dirname "$ROOT")")/titan-auditoria.txt"
sh scripts/audit_host.sh > "$AUDIT" 2>&1 || true
grep -E "Distribuição|Arquitetura|Userland|RAM total|RAM disponível|Disco livre|python3 |node |AVISO" "$AUDIT" || true
echo "Relatório completo salvo em: $AUDIT"

step "2/6 Ambiente Python, dependências, .env e banco SQLite"
TITAN_EXTRAS="${TITAN_EXTRAS:-dev}" sh scripts/setup.sh

step "3/6 Interface web"
if [ -f apps/web/dist/index.html ]; then
  echo "Interface já compilada."
elif command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 \
  && node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>20||(a===20&&b>=19)?0:1)' 2>/dev/null; then
  echo "Node $(node --version) encontrado; compilando (só dentro desta pasta)..."
  npm ci --no-audit --no-fund && npm run build
else
  echo "AVISO: Node.js 20.19+ não encontrado ($(node --version 2>/dev/null || echo ausente))."
  echo "O servidor e a API funcionam, mas a tela do navegador mostrará 'Interface não compilada'."
  echo "Nada foi instalado. Veja docs/notebook-install.md (Etapa 4) para as opções."
fi

step "4/6 Conta administrativa"
USERS="$(.venv/bin/python -c '
from titan.config.settings import get_settings
from titan.db.engine import make_engine
from sqlalchemy import text
e = make_engine(get_settings().database_url)
with e.connect() as c: print(c.execute(text("select count(*) from users")).scalar())
e.dispose()')"
if [ "$USERS" = "0" ]; then
  printf "Nome do usuário administrador (ex.: seu primeiro nome): "
  read -r NAME
  .venv/bin/titan create-user "$NAME"
else
  echo "Já existe(m) $USERS usuário(s); nenhum criado."
fi

step "5/6 Verificação (instância temporária; seus dados não são tocados)"
if ! .venv/bin/python scripts/verify_local.py; then
  echo
  echo "Alguma verificação falhou (veja acima). O servidor NÃO será iniciado automaticamente."
  echo "Se a única falha for 'Interface web servida', você pode iniciar mesmo assim com:"
  echo "  cd $ROOT && .venv/bin/titan serve"
  exit 1
fi

step "6/6 Iniciando o servidor"
PORT="$(.venv/bin/python -c 'from titan.config.settings import get_settings; print(get_settings().port)')"
echo "Abra no navegador DESTE computador:  http://127.0.0.1:$PORT"
echo "Para parar: Ctrl+C.   Para iniciar depois:  cd $ROOT && .venv/bin/titan serve"
exec .venv/bin/titan serve
