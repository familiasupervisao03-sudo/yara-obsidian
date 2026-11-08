#!/bin/sh
# Instala o SearXNG LOCAL (opcional): metabuscador que roda no próprio notebook e
# dá ao TITAN busca geral na internet (notícias, preços, clima...), sem chave e sem custo.
# Fica em ~/.local/share/titan-searxng (fora do TITAN), escuta só em 127.0.0.1:8888.
set -eu
cd "$(dirname "$0")/.."
TITAN_DIR="$(pwd)"
SX_DIR="${TITAN_SEARXNG_DIR:-$HOME/.local/share/titan-searxng}"
PY="${PYTHON:-python3}"

cat <<TXT
SearXNG local para o TITAN — o que será feito (gratuito):
  * Baixar o código do SearXNG (github.com/searxng/searxng) em: $SX_DIR
  * Criar um ambiente Python próprio com as bibliotecas dele (~150 MB em disco)
  * Configurar para escutar SÓ no notebook (127.0.0.1:8888), formato JSON ligado
  * Criar o serviço de usuário 'titan-searxng' (liga junto com o login; dá para desligar)
Memória medida em teste: ~100 MB enquanto roda.
Como funciona: o SearXNG repassa a sua pesquisa a buscadores públicos (Google,
Bing, DuckDuckGo...). Eles podem recusar ou limitar pedidos; quando isso
acontece, aquele buscador fica de fora por um tempo — nada é contornado.
TXT
command -v git >/dev/null || { echo "Precisa do git: sudo apt install git"; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Precisa de Python 3.10 ou mais novo."; exit 1; }
mkdir -p "$(dirname "$SX_DIR")"; FREE_KB="$(df -Pk "$(dirname "$SX_DIR")" | awk 'NR==2 {print $4}')"
[ "${FREE_KB:-0}" -gt 409600 ] || { echo "Espaço livre insuficiente (precisa de ~400 MB)."; exit 1; }
printf "Digite 'sim' para instalar: "
read -r OK
[ "$OK" = "sim" ] || { echo "Cancelado. Nada foi instalado."; exit 1; }

if [ -d "$SX_DIR/src/.git" ]; then
  echo "Atualizando o código do SearXNG..."
  git -C "$SX_DIR/src" pull --ff-only
else
  mkdir -p "$SX_DIR"
  git clone --depth 1 https://github.com/searxng/searxng.git "$SX_DIR/src"
fi
[ -x "$SX_DIR/venv/bin/python" ] || "$PY" -m venv "$SX_DIR/venv"
"$SX_DIR/venv/bin/python" -m pip install -q -U pip setuptools wheel
# Só pacotes já compilados: nada é compilado no notebook.
"$SX_DIR/venv/bin/python" -m pip install -q --only-binary=:all: -r "$SX_DIR/src/requirements.txt"
"$SX_DIR/venv/bin/python" -m pip install -q --no-build-isolation -e "$SX_DIR/src"

# Processador antigo: confere num processo separado se as bibliotecas compiladas
# rodam (sem AVX, algumas derrubam o processo com "instrução ilegal").
if ! "$SX_DIR/venv/bin/python" -c "import lxml.etree, msgspec, curl_cffi, flask, babel, searx" >/dev/null 2>"$SX_DIR/teste-importacao.log"; then
  echo "ERRO: o SearXNG não consegue rodar neste processador/sistema."
  echo "Detalhes em $SX_DIR/teste-importacao.log. O TITAN continua usando a Wikipédia."
  exit 1
fi

if [ ! -f "$SX_DIR/settings.yml" ]; then
  SECRET="$("$PY" -c 'import secrets; print(secrets.token_hex(32))')"
  umask 077
  cat > "$SX_DIR/settings.yml" <<YML
use_default_settings: true
general:
  instance_name: "TITAN busca local"
search:
  safe_search: 1
  default_lang: "pt-BR"
  formats: [html, json]
server:
  bind_address: "127.0.0.1"
  port: 8888
  secret_key: "$SECRET"
  limiter: false
  image_proxy: false
outgoing:
  request_timeout: 4.0
YML
  umask 022
fi

cat > "$SX_DIR/iniciar.sh" <<EOF2
#!/bin/sh
export SEARXNG_SETTINGS_PATH="$SX_DIR/settings.yml"
exec nice -n 5 "$SX_DIR/venv/bin/python" -m searx.webapp
EOF2
chmod +x "$SX_DIR/iniciar.sh"

if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/titan-searxng.service" <<EOF2
[Unit]
Description=SearXNG local do TITAN (127.0.0.1:8888)

[Service]
ExecStart=$SX_DIR/iniciar.sh
Restart=on-failure
RestartSec=10
MemoryMax=400M

[Install]
WantedBy=default.target
EOF2
  systemctl --user daemon-reload
  systemctl --user enable --now titan-searxng.service
  echo "Serviço 'titan-searxng' ligado. Desligar: systemctl --user disable --now titan-searxng"
else
  echo "Sem systemd de usuário: inicie à mão quando quiser:  $SX_DIR/iniciar.sh &"
  nohup "$SX_DIR/iniciar.sh" > "$SX_DIR/searxng.log" 2>&1 &
fi

printf "Esperando o SearXNG responder"
i=0
until "$PY" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8888/healthz', timeout=2)" 2>/dev/null; do
  i=$((i + 1)); [ $i -lt 30 ] || { echo; echo "Não respondeu em 60 s. Veja: journalctl --user -u titan-searxng"; exit 1; }
  printf "."; sleep 2
done
echo " ok."
cat <<TXT

SearXNG instalado e rodando em http://127.0.0.1:8888 (só neste notebook).
Para o TITAN usar, rode:
  cd "$TITAN_DIR"
  .venv/bin/titan enable-web --searxng http://127.0.0.1:8888
  .venv/bin/titan pesquisar "cotação do dólar hoje"
TXT
