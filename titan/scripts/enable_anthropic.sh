#!/bin/sh
# Liga a API da Anthropic no TITAN (EXTERNA e PAGA). Pede orçamento, cotação,
# chave (sem mostrar) e a palavra AUTORIZO. Não faz nenhuma chamada de teste.
set -eu
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Rode antes: sh scripts/install_and_start.sh"; exit 1; }
echo "Instalando a biblioteca oficial da Anthropic (somente pacotes pré-compilados)..."
.venv/bin/python -m pip install -q --only-binary=:all: -e ".[anthropic]"
.venv/bin/titan enable-anthropic
echo
echo "Verificando a configuração (sem chamar a API)..."
.venv/bin/titan check-config | grep -E "model_provider|model_name|allow_paid|budget|usd_brl|external|local_only"
