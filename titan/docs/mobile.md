# Acesso pelo celular (Android) — DESLIGADO por padrão

## Um comando só: notebook + celular no mesmo servidor

```sh
.venv/bin/titan ligar                  # na 1ª vez pede AUTORIZO; depois só liga
```

Liga o servidor **uma vez** para os dois: no notebook abre sozinho
`https://localhost:8000` e mostra o endereço do celular (`https://IP:8000`) e um
QR code da página de instalação (cadeado + app APK) por 15 minutos. Na primeira
vez também faz o Chrome/Chromium do notebook confiar no cadeado (precisa de
`sudo apt install libnss3-tools`). Se o notebook mudar de IP, o cadeado do
servidor é renovado sozinho — o celular não precisa reinstalar nada.
Opções: `--tailscale`, `--sem-navegador`, `--sem-pagina`.

## Fora de casa (4G, outra Wi-Fi): Tailscale

O TITAN não fica aberto na internet. Para usar de qualquer lugar, o notebook e o celular
entram na **mesma rede particular do Tailscale** (grátis para uso pessoal; só os
aparelhos da SUA conta enxergam o notebook).

1. Notebook: `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`
   (abra o link e entre com a sua conta).
2. Celular: app Tailscale, mesma conta, "Connected".
3. Notebook: `.venv/bin/titan ligar` — ele detecta o Tailscale sozinho, renova o cadeado
   para o endereço novo e mostra:
   - **em qualquer lugar**: `https://100.x.x.x:8000`
   - **Wi-Fi de casa (reserva)**: `https://192.168.x.x:8000`
4. Na página do QR code, toque em **CONFIGURAR O APP SOZINHO** (app 1.2+): o app guarda os
   dois endereços (ele pergunta antes). Se o principal não responder, usa a reserva.

O cadeado já instalado no celular continua valendo. Na primeira vez em cada endereço o
TITAN pede o login (a sessão é por endereço). Para não usar o Tailscale:
`titan ligar --sem-tailscale`.

## Só preparar o celular (sem ligar o servidor)

```sh
.venv/bin/pip install segno            # opcional: mostra o QR code no terminal
.venv/bin/titan ligar-celular          # pede AUTORIZO
.venv/bin/titan serve                  # reinicie o TITAN
```

O comando descobre o IP do notebook na Wi-Fi, cria o cadeado (HTTPS) só deste
notebook, ajusta o `.env` (só a sua rede local pode chegar; login obrigatório) e
abre por **15 minutos** uma página de instalação. Aponte a câmera do celular
para o QR code (ou digite o endereço mostrado) e siga os 3 passos da página:
baixar o cadeado, instalá-lo e "Adicionar à tela inicial".

A página de instalação é a única parte **sem cadeado**: ela entrega só o
certificado **público** do notebook e as instruções, aceita só aparelhos da sua
rede e fecha sozinha. Opções: `--sem-pagina` (você copia o certificado por cabo),
`--porta 8001` (porta da página).

**No notebook**, depois de ligar, use `https://localhost:8000`. Para o navegador
do notebook confiar no cadeado, importe `var/tls/titan-ca.crt` em Configurações →
Privacidade e segurança → Certificados → Autoridades.

**Fora de casa (opcional, grátis): Tailscale.** Instale o Tailscale no notebook
(`curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`) e o app
Tailscale no celular, com a mesma conta. Depois rode
`.venv/bin/titan ligar-celular --tailscale`. Assim o celular alcança o notebook
pelo 4G, numa rede privada só dos seus aparelhos: nada é aberto para a internet e
o login continua obrigatório. O Tailscale (empresa externa) sabe quais aparelhos
estão conectados, mas o conteúdo vai cifrado.

**Desligar:** `.venv/bin/titan desligar-celular` (com `--apagar-certificados`
apaga também o cadeado; remova-o do celular em Credenciais do usuário).

### No celular (app instalado)

- **Atalhos:** segure o ícone → Falar, Nova conversa, Nova vídeo-aula, Aprovações.
- **Compartilhar → TITAN:** em qualquer app, compartilhe um link ou texto com o
  TITAN e escolha: resumir, explicar em vídeo-aula, perguntar ou pesquisar mais
  (ler links precisa da pesquisa na internet ligada).
- **Voz:** botão grande; a tela não apaga enquanto a conversa por voz está ativa e
  o celular vibra quando o TITAN começa a ouvir.
- **Sem notebook:** aparece "Notebook fora do alcance", com nova tentativa a cada
  10 s; a mensagem que não foi enviada vai sozinha quando ele voltar.
- **Avisos:** em Sistema → Avisos. Aprovação pendente, vídeo-aula pronta e
  resposta pronta, com o TITAN aberto em segundo plano (gerados pelo próprio
  aparelho; com o app totalmente fechado não há avisos, porque isso exigiria um
  serviço de terceiros).
- **Aparência:** Sistema → Aparência (tema e modo leve), separado por aparelho.

## Jeito manual (detalhado)

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
