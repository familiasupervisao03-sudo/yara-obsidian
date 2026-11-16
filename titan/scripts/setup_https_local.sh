#!/bin/sh
# Cria um certificado HTTPS LOCAL para acessar o TITAN pelo celular na Wi-Fi.
# - Gera uma autoridade certificadora (CA) só sua e um certificado para o IP do notebook.
# - A chave da CA fica em var/tls/ (permissão 600) e NÃO deve sair do notebook.
# - Nada é instalado no sistema e o .env não é alterado: as linhas são só impressas.
# Uso: sh scripts/setup_https_local.sh 192.168.0.10   (o IP do notebook na Wi-Fi)
set -eu
cd "$(dirname "$0")/.."
IP="${1:-}"
[ -n "$IP" ] || { echo "Informe o IP do notebook na Wi-Fi (veja com: ip -4 addr)."; exit 1; }
command -v openssl >/dev/null || { echo "openssl não encontrado."; exit 1; }
DIR=var/tls
mkdir -p "$DIR"
chmod 700 var "$DIR"
umask 077
if [ ! -f "$DIR/titan-ca.key" ]; then
  openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes \
    -keyout "$DIR/titan-ca.key" -out "$DIR/titan-ca.crt" \
    -subj "/CN=TITAN CA local ($(hostname))" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
fi
cat > "$DIR/server.ext" <<EXT
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:$IP,IP:127.0.0.1,DNS:localhost
EXT
openssl req -newkey rsa:2048 -nodes -keyout "$DIR/server.key" -out "$DIR/server.csr" -subj "/CN=$IP" 2>/dev/null
openssl x509 -req -in "$DIR/server.csr" -CA "$DIR/titan-ca.crt" -CAkey "$DIR/titan-ca.key" \
  -CAcreateserial -out "$DIR/server.crt" -days 397 -sha256 -extfile "$DIR/server.ext" 2>/dev/null
rm -f "$DIR/server.csr" "$DIR/server.ext"
chmod 600 "$DIR"/*
chmod 644 "$DIR/titan-ca.crt"
cat <<TXT

Certificados criados em $DIR/.

1) Instale SOMENTE o arquivo $DIR/titan-ca.crt no celular (nunca a .key):
   copie por cabo USB e, no Android: Configurações > Segurança > Criptografia e
   credenciais > Instalar certificado > Certificado de CA. (O nome do menu varia.)
2) Para ligar o acesso pela Wi-Fi (só quando decidir), acrescente ao .env:
   TITAN_HOST=0.0.0.0
   TITAN_ALLOWED_NETWORKS=127.0.0.1/32,$(echo "$IP" | awk -F. '{print $1"."$2"."$3".0/24"}')
   TITAN_TLS_CERT_FILE=$DIR/server.crt
   TITAN_TLS_KEY_FILE=$DIR/server.key
3) Reinicie o servidor e abra no celular: https://$IP:8000
Para desfazer: remova essas linhas do .env, remova o certificado do celular e apague $DIR/.
TXT
