# API da Anthropic (Claude) no TITAN — externa e paga

O TITAN pode responder no chat usando o Claude, da Anthropic. Isso é **opcional**
e vem **desligado**. Ao ligar, o TITAN deixa de ser 100% local: entra em
**modo híbrido**.

## O que muda na privacidade

| Fica no notebook | Vai para a Anthropic |
|---|---|
| banco de dados, logs, auditoria, senhas, `.env`, arquivos | o texto das conversas: a cada mensagem, até as 40 últimas mensagens da conversa |

A chave da API fica só no `.env` do notebook (permissão 600). Ela nunca vai
para a tela, os logs, o Git ou a interface, e o servidor a envia apenas à
Anthropic. A interface mostra **"MODELO EXTERNO ATIVO"** e **"MODO HÍBRIDO"**
sempre que a Anthropic estiver ligada.

## Custo e orçamento (aplicado pelo servidor)

A Anthropic cobra por uso, dos créditos da sua conta (não há uso gratuito da
API). O TITAN protege seu bolso assim:

1. **Orçamento diário em R$**, definido por você (máximo R$ 1000; sem orçamento,
   o servidor nem liga a Anthropic).
2. **Antes de cada envio**, o TITAN reserva o custo **máximo possível** da
   chamada, calculado com o modelo mais caro da tabela (para cobrir o fallback
   automático). Se o gasto do dia mais essa reserva passar do orçamento, a
   mensagem **não é enviada** e aparece o aviso.
3. Depois da resposta, a reserva vira o custo real, informado pela Anthropic
   (tokens × preço oficial × sua cotação do dólar).
4. Em erro de conexão ou timeout (quando não dá para saber se houve cobrança),
   a reserva fica contada como gasto (conservador). Erros HTTP como chave
   inválida ou falta de créditos não contam.
5. Sem novas tentativas automáticas, e respostas limitadas a
   `TITAN_MODEL_MAX_OUTPUT_TOKENS` (2048 por padrão).
6. Reenviar a mesma mensagem (mesma chave de idempotência) **não** gera uma
   nova cobrança.

Preços usados (US$ por milhão de tokens, entrada/saída), conforme a tabela
oficial (cache de 2026-10-06):

| Modelo | Entrada | Saída | Observação |
|---|---|---|---|
| `claude-opus-5-5` | 4,00 | 20,00 | padrão, mais capaz |
| `claude-sonnet-5-5` | 2,00 | 10,00 | metade do preço |
| `claude-haiku-5-5` | 0,10 (até 100K) | 0,50 | o mais barato; o TITAN calcula pela faixa acima de 100K (0,50/2,50) por segurança |

Por exemplo, com `claude-opus-5-5`, uma mensagem curta com resposta de ~500
tokens custa cerca de US$ 0,01 (≈ R$ 0,06 com dólar a R$ 5,60). O valor exato
depende do tamanho da conversa.

O gasto aparece no painel: "gasto hoje R$ X de R$ Y". O dia é o do relógio do
notebook.

Também é bom definir um limite de gastos no próprio painel da Anthropic
(console.anthropic.com), como uma segunda trava.

## Como ligar (no notebook)

```sh
cd ~/Projetos/TITAN/titan
git pull
sh scripts/enable_anthropic.sh
```

O script instala a biblioteca oficial `anthropic` (só pacotes prontos), mostra
os avisos e pergunta:

- o modelo (padrão `claude-opus-5-5`);
- o orçamento máximo por dia em R$;
- a cotação do dólar em R$ (use um valor um pouco acima do atual, por segurança);
- a chave da API, colada sem aparecer na tela (use a mesma do Zax, se quiser);
- a palavra **AUTORIZO**.

Ele **não faz nenhuma chamada de teste**. Depois disso, reinicie o servidor
(`Ctrl+C` e `.venv/bin/titan serve`). A primeira mensagem no chat já é o teste
real.

## Como desligar

```sh
.venv/bin/titan disable-external           # volta ao modo 100% local e remove a chave do .env
.venv/bin/titan disable-external --keep-key   # desliga, mas mantém a chave guardada
```

Cada alteração cria uma cópia `.env.bak-DATA` (permissão 600). A cópia de antes
do desligamento ainda contém a chave; apague-a com `rm` se não quiser mantê-la.

## Configurações (`.env`)

| Variável | Significado |
|---|---|
| `TITAN_MODEL_PROVIDER=anthropic` | usa a Anthropic no chat |
| `TITAN_MODEL_NAME` | modelo (ex.: `claude-opus-5-5`) |
| `TITAN_LOCAL_ONLY=false` | deixa de ser 100% local (obrigatório para a Anthropic) |
| `TITAN_ALLOW_EXTERNAL_MODELS=true` | autoriza um provedor externo |
| `TITAN_ALLOW_PAID_APIS=true` | autoriza um provedor pago |
| `TITAN_DAILY_PAID_BUDGET_BRL` | orçamento diário em R$ (> 0) |
| `TITAN_USD_BRL_RATE` | cotação usada no cálculo |
| `TITAN_MODEL_MAX_OUTPUT_TOKENS` | tamanho máximo da resposta (padrão 2048) |
| `TITAN_MODEL_EFFORT` | esforço de raciocínio: `low` (padrão, mais barato) a `max` |
| `TITAN_ANTHROPIC_FALLBACKS` | `true` (padrão): se o modelo recusar por política, a Anthropic tenta outro modelo na mesma chamada |
| `ANTHROPIC_API_KEY` | sua chave (fica só no `.env`) |

Se faltar qualquer item obrigatório, o servidor **não inicia** e lista o que
falta. Não existe troca automática para outro provedor.
