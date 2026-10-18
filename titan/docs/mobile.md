# Acesso pelo celular (Android) — DESLIGADO por padrão

O notebook continua sendo o servidor. O celular é só um navegador apontando
para ele, pela mesma Wi-Fi. **Nada disso está ativo** até você configurar.

## Riscos (leia antes)

- **HTTP simples não cifra nada.** Senha, cookie de sessão e conversas
  trafegariam abertos na Wi-Fi; qualquer pessoa conectada à mesma rede
  poderia capturar. Por isso o TITAN **recusa** escutar na rede sem HTTPS, a
  menos que você defina `TITAN_LAN_ACKNOWLEDGE_HTTP_RISK=true`.
- **O microfone do celular só funciona em HTTPS.** É uma regra do navegador:
  sem HTTPS, o modo de voz não abre o microfone no celular.
- Estar na Wi-Fi **não** autentica ninguém: o login continua obrigatório.
- O filtro de rede (`TITAN_ALLOWED_NETWORKS`) reduz quem alcança o servidor,
  mas IPs podem ser falsificados na mesma rede; ele não substitui o login.
- Não abra portas no roteador, não use túneis e não exponha à internet.

## Caminho recomendado: HTTPS com CA local

1. Descubra o IP do notebook na Wi-Fi: `ip -4 addr` (ex.: `192.168.0.10`).
   Se possível, reserve esse IP no roteador para ele não mudar.
2. Gere os certificados (só leitura/escrita em `var/tls/`):
   ```sh
   sh scripts/setup_https_local.sh 192.168.0.10
   ```
   Isso cria uma autoridade certificadora (CA) **só sua** e um certificado
   para o IP. A chave da CA fica no notebook (permissão 600).
3. Instale **apenas** `var/tls/titan-ca.crt` no celular (cabo USB) em
   Configurações → Segurança → Criptografia e credenciais → Instalar
   certificado → **Certificado de CA**. O Android mostrará um aviso de que a
   rede pode ser monitorada; isso é esperado para CAs instaladas pelo
   usuário. Nunca copie arquivos `.key`.
4. Quando decidir ligar, acrescente ao `.env` as linhas que o script mostra
   (`TITAN_HOST=0.0.0.0`, `TITAN_ALLOWED_NETWORKS=...`,
   `TITAN_TLS_CERT_FILE`, `TITAN_TLS_KEY_FILE`) e reinicie o servidor.
5. No celular, abra `https://192.168.0.10:8000`, faça login e, no menu do
   Chrome, use "Instalar app"/"Adicionar à tela inicial" (PWA).

Não aceite avisos de "conexão não segura" pulando a página: se aparecer, o
certificado não foi instalado corretamente; volte ao passo 3.

## Firewall (opcional, recomendado)

Se usar `ufw`, libere a porta só para a sua rede:
```sh
sudo ufw allow from 192.168.0.0/24 to any port 8000 proto tcp
```

## Desligar o acesso pela Wi-Fi

Remova `TITAN_HOST` e `TITAN_ALLOWED_NETWORKS` do `.env` (volta a
`127.0.0.1`) e reinicie. Para remover o HTTPS: apague as linhas `TITAN_TLS_*`,
remova o certificado do celular (Configurações → Credenciais do usuário) e
apague `var/tls/`.

## O que foi testado (no ambiente de desenvolvimento)

- Servidor HTTPS com a CA local: aparelho que confia na CA conecta; sem a CA o
  certificado é recusado; HTTP simples na porta TLS é recusado; o cookie de
  sessão sai com `Secure`.
- Interface no tamanho de celular (390×844): conversa, voz, tarefas e sistema
  sem rolagem horizontal e com o campo de mensagem visível.
- **Não testado:** um Android físico real (o ambiente não tem um).
