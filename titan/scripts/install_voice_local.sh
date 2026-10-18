#!/bin/sh
# Instala a VOZ LOCAL do TITAN (opcional): Vosk (reconhecimento) + Piper (fala).
# Tudo roda no notebook; depois de instalado, áudio e texto não saem do computador.
set -eu
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Rode antes: sh scripts/install_and_start.sh"; exit 1; }

cat <<'TXT'
Voz local do TITAN — o que será baixado (gratuito):
  * Bibliotecas Python vosk + piper-tts (+ onnxruntime): ~230 MB em disco
  * Modelo de reconhecimento Vosk pequeno em português: ~32 MB (52 MB descompactado)
      origem: https://alphacephei.com/vosk/models
  * Voz pt_BR "faber" (Piper): ~63 MB
      origem: https://huggingface.co/rhasspy/piper-voices
Memória medida em teste (Xeon 2,1 GHz): ~370 MB com os dois carregados.
No seu notebook (3,8 GB) isso cabe, mas feche programas pesados se ficar lento.
Os modelos são carregados só quando a voz é usada pela primeira vez.
TXT
FREE_KB="$(df -Pk . | awk 'NR==2 {print $4}')"
[ "${FREE_KB:-0}" -gt 716800 ] || { echo "Espaço livre insuficiente (precisa de ~700 MB)."; exit 1; }
printf "Digite 'sim' para instalar: "
read -r OK
[ "$OK" = "sim" ] || { echo "Cancelado. Nada foi instalado."; exit 1; }

.venv/bin/python -m pip install --only-binary=:all: -e ".[voice]"
mkdir -p var/models/piper
chmod 700 var var/models
if [ ! -f var/models/vosk-model-small-pt-0.3/final.mdl ]; then
  curl -fL --progress-bar -o var/models/vosk.zip https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip
  .venv/bin/python -c "import zipfile; zipfile.ZipFile('var/models/vosk.zip').extractall('var/models')"
  rm -f var/models/vosk.zip
fi
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium
for f in pt_BR-faber-medium.onnx pt_BR-faber-medium.onnx.json; do
  [ -f "var/models/piper/$f" ] || curl -fL --progress-bar -o "var/models/piper/$f" "$BASE/$f"
done
echo
echo "Voz local instalada. Reinicie o servidor (Ctrl+C e .venv/bin/titan serve)."
echo "No navegador, abra o modo de voz: os mecanismos devem aparecer como 'local'."
