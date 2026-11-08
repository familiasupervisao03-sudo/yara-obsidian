# Pesquisa na internet

O TITAN pode pesquisar na internet, ler as páginas encontradas e responder
citando as fontes. **Vem desligado**: nada sai do notebook até você ligar, e
mesmo ligado ele só pesquisa quando você pede.

## Ligar

```sh
cd ~/Projetos/TITAN/titan
.venv/bin/titan enable-web            # pede AUTORIZO
.venv/bin/titan pesquisar "Curitiba"  # teste no terminal
.venv/bin/titan serve                 # reinicie o servidor
```

Desligar: `.venv/bin/titan disable-web` (ou `disable-external`, que desliga
tudo o que é externo).

## Como pedir

- **No chat:** toque no botão **Internet** (globo) ao lado de Enviar; ele fica
  aceso e as próximas mensagens são pesquisadas. Ou escreva o pedido:
  *"pesquisa na internet o preço do café"*.
- **Na voz:** fale *"pesquisa na internet ..."*, *"procura na internet ..."*,
  *"busca no Google ..."*. A resposta falada cita o site pelo nome ("segundo a
  Wikipédia") e não lê endereços.
- Sem o botão e sem pedir, o TITAN **não** pesquisa (ex.: "minha internet caiu"
  não dispara nada).

A resposta mostra a lista de fontes no fim, com links para você conferir.

## Fontes de busca

| Fonte | Para quê | Precisa |
|---|---|---|
| **Wikipédia** (padrão) | conceitos, história, lugares, pessoas | nada (API pública gratuita) |
| **SearXNG local** | busca geral: notícias, preços, clima, sites | instalar (abaixo) |

### SearXNG local (opcional)

Metabuscador que roda no próprio notebook e repassa a pesquisa a buscadores
públicos (Google, Bing, DuckDuckGo...). Sem chave e sem custo.

```sh
sh scripts/install_searxng.sh                          # pede 'sim'
.venv/bin/titan enable-web --searxng http://127.0.0.1:8888
.venv/bin/titan pesquisar "cotação do dólar hoje"
```

- Fica em `~/.local/share/titan-searxng`, escuta **só** em `127.0.0.1:8888` e
  roda como serviço de usuário `titan-searxng` (máx. 400 MB).
  Desligar: `systemctl --user disable --now titan-searxng`.
- Medido no ambiente de desenvolvimento: ~100 MB de memória; "cotação do dólar
  hoje" trouxe 26 resultados em ~4 s. **Ainda não medido no seu notebook.**
- O instalador testa num processo separado se as bibliotecas rodam no seu
  processador (sem AVX); se não rodarem, avisa e o TITAN continua com a Wikipédia.
- Os buscadores podem limitar ou recusar pedidos. Quando isso acontece o
  buscador fica de fora por um tempo; nada é contornado.

## O que sai do notebook

- O **texto da pesquisa** (não a conversa inteira) vai para a fonte de busca.
- O TITAN baixa as páginas encontradas (até 3 por pesquisa). Os sites veem o
  IP da sua casa, como numa visita normal, e um identificador "TITAN".
- **Nunca** são enviados: senhas, cookies, chaves, o cookie de login do TITAN
  ou qualquer dado do `.env`.
- Com a Anthropic ligada, o texto das fontes vai junto com a pergunta para a IA
  (mais tokens, dentro do orçamento diário, que continua valendo).

## Proteções

- **Só endereços públicos:** o nome do site é resolvido uma vez; se QUALQUER
  endereço for interno (127.x, 10.x, 192.168.x, 169.254.169.254, IPv6 local,
  IPv4 embutido em IPv6...), o acesso é recusado. A conexão vai para o endereço
  já conferido (sem troca de DNS no meio). `localhost`, `.local`, `.lan` são
  recusados pelo nome.
- **Só portas 80 e 443, só http/https**, sem usuário/senha no endereço.
  Exceção única e explícita: o SearXNG do próprio notebook, cujo endereço é
  validado na configuração (tem que ser 127.0.0.1/localhost).
- **Redirecionamentos** seguidos um a um (máx. 5), conferindo cada destino.
- **Limites:** 10 s por conexão, 2 MB por página, só tipos de texto; 6
  pesquisas por minuto e 150 por dia por usuário; cache de 10 min.
- **robots.txt respeitado**; site que recusa (403) ou proíbe robôs fica de fora
  e o TITAN usa só o resumo da busca, avisando.
- **Conteúdo não confiável:** o texto das páginas vai na mensagem do usuário,
  dentro de um bloco marcado como "não confiável", nunca no prompt do sistema;
  a IA é instruída a ignorar instruções que apareçam nele. Scripts, estilos e
  texto escondido (`display:none`, `hidden`) são descartados na extração, e a
  página não consegue "fechar" o bloco de fontes.
- **Nenhuma ação externa:** o TITAN só lê (GET). Não preenche formulários,
  não faz login, não compra nem publica nada.
- **Auditoria:** cada pesquisa registra fonte, nº de fontes, sites e tempo —
  sem o texto da pergunta e sem o conteúdo das páginas.

## Limitações conhecidas

- A pesquisa usa o texto do pedido quase literal (sem reescrever a pergunta).
  Perguntas longas funcionam melhor curtas e diretas.
- Páginas montadas só com JavaScript aparecem vazias (o TITAN não executa
  scripts das páginas); nesse caso fica o resumo da busca.
- A instrução para ignorar comandos nas páginas reduz, mas não elimina, o risco
  de a IA ser enganada por uma página maliciosa. Por isso as fontes aparecem
  sempre, e o TITAN não tem nenhuma ferramenta que altere dados lá fora.
