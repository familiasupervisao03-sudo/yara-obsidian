#!/bin/sh
# Liga a VOZ NATURAL ON-LINE do TITAN (Microsoft, gratuita). O texto das respostas
# faladas sai do notebook; o áudio da sua fala continua local (Vosk).
# Pede a voz e a palavra AUTORIZO. Para desligar: .venv/bin/titan disable-online-voice
set -eu
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Rode antes: sh scripts/install_and_start.sh"; exit 1; }
echo "Instalando a biblioteca edge-tts (~5 MB, somente pacotes pré-compilados)..."
.venv/bin/python -m pip install -q --only-binary=:all: -e ".[voice-online]"
.venv/bin/titan enable-online-voice
