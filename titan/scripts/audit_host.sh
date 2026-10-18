#!/bin/sh
# TITAN — auditoria do computador (somente leitura).
# Não instala, não altera nada e não acessa a internet.
# Uso: sh scripts/audit_host.sh   (pode salvar: sh scripts/audit_host.sh > auditoria.txt)

has() { command -v "$1" >/dev/null 2>&1; }
line() { printf '%-28s %s\n' "$1" "$2"; }
section() { printf '\n== %s ==\n' "$1"; }

section "Sistema"
if [ -r /etc/os-release ]; then . /etc/os-release; line "Distribuição" "${PRETTY_NAME:-desconhecida}"; fi
line "Kernel" "$(uname -r)"
ARCH="$(uname -m)"
line "Arquitetura" "$ARCH"
case "$ARCH" in
  x86_64|amd64) ;;
  i386|i486|i586|i686) echo "AVISO: sistema 32 bits — Docker oficial e a maioria dos modelos locais NÃO são suportados." ;;
  aarch64|arm64) echo "Nota: ARM 64 bits — verificar rodas Python/binários específicos." ;;
  arm*) echo "AVISO: ARM 32 bits — suporte limitado de ferramentas." ;;
esac
if has getconf; then line "Userland" "$(getconf LONG_BIT) bits"; fi

section "CPU"
if [ -r /proc/cpuinfo ]; then
  line "Modelo" "$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ //')"
  line "Núcleos lógicos" "$(grep -c '^processor' /proc/cpuinfo)"
  FLAGS="$(grep -m1 '^flags' /proc/cpuinfo)"
  for f in sse4_2 avx avx2 fma; do
    case " $FLAGS " in *" $f "*) line "  $f" "sim" ;; *) line "  $f" "não" ;; esac
  done
  echo "(AVX2 ausente => inferência local de LLM será muito lenta ou exigirá builds especiais)"
fi

section "Memória e disco"
if [ -r /proc/meminfo ]; then
  line "RAM total (MB)" "$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
  line "RAM disponível (MB)" "$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)"
  line "Swap total (MB)" "$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)"
fi
line "Disco livre (pasta atual)" "$(df -h . | awk 'NR==2 {print $4 " livres de " $2}')"
if has lsblk; then
  ROT="$(lsblk -dno ROTA 2>/dev/null | head -1)"
  [ "$ROT" = "1" ] && line "Disco" "HD mecânico (rotacional)" || line "Disco" "SSD/flash (ou não detectado)"
fi
if [ -d /sys/class/power_supply ]; then
  for b in /sys/class/power_supply/BAT*; do
    [ -r "$b/capacity" ] && line "Bateria" "$(cat "$b/capacity")% ($(cat "$b/status" 2>/dev/null))"
  done
fi

section "Ferramentas"
for t in python3 pip3 node npm git sqlite3 psql docker podman bwrap firejail nsjail unshare systemd-run ollama; do
  if has "$t"; then
    v="$("$t" --version 2>/dev/null | head -1)"
    line "$t" "${v:-presente}"
  else
    line "$t" "ausente"
  fi
done
if has python3; then
  line "Python sqlite3" "$(python3 -c 'import sqlite3;print(sqlite3.sqlite_version)' 2>/dev/null)"
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
    && line "Python >= 3.10" "sim" || line "Python >= 3.10" "NÃO (o TITAN exige 3.10+)"
fi

section "PostgreSQL"
if has pg_lsclusters; then pg_lsclusters 2>/dev/null; elif has psql; then echo "psql presente; servidor não verificado"; else echo "PostgreSQL não instalado (SQLite será usado)"; fi

section "Isolamento (sandbox)"
if has docker; then
  if docker info >/dev/null 2>&1; then line "Docker daemon" "acessível"; else line "Docker daemon" "inacessível (parado ou sem permissão)"; fi
fi
if [ -r /proc/sys/user/max_user_namespaces ]; then
  line "max_user_namespaces" "$(cat /proc/sys/user/max_user_namespaces)"
fi
if [ -r /proc/sys/kernel/unprivileged_userns_clone ]; then
  line "unprivileged_userns_clone" "$(cat /proc/sys/kernel/unprivileged_userns_clone)"
fi
if has unshare; then
  if unshare -Urn true 2>/dev/null; then line "userns sem root" "funciona"; else line "userns sem root" "bloqueado"; fi
fi
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
  line "cgroups" "v2 ($(cat /sys/fs/cgroup/cgroup.controllers))"
else
  line "cgroups" "v1 ou indisponível"
fi
grep -q Seccomp /proc/self/status 2>/dev/null && line "seccomp" "suportado pelo kernel" || line "seccomp" "não detectado"

section "Rede local (somente leitura)"
if has ip; then ip -4 -o addr show scope global 2>/dev/null | awk '{print "  " $2 ": " $4}'; fi

section "Recomendação automática (indicativa)"
MEM="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null)"
[ -n "$MEM" ] || MEM=0
if [ "$MEM" -lt 2048 ]; then
  echo "- RAM < 2 GB: use SQLite; NÃO rode PostgreSQL nem modelos locais."
elif [ "$MEM" -lt 4096 ]; then
  echo "- RAM 2–4 GB: SQLite recomendado; modelos locais apenas muito pequenos (<=1B, quantizados) e lentos."
elif [ "$MEM" -lt 8192 ]; then
  echo "- RAM 4–8 GB: SQLite ou PostgreSQL; modelos 1–3B quantizados possíveis se houver AVX2."
else
  echo "- RAM >= 8 GB: PostgreSQL viável; modelos 3–7B quantizados possíveis se houver AVX2."
fi
echo "Envie este relatório (sem dados pessoais) para ajustar a arquitetura."
