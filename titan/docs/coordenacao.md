# Caderno das conversas (coordenação)

Várias conversas do Claude trabalham no TITAN ao mesmo tempo, cada uma numa parte.
Este caderno existe para **uma não atrapalhar a outra**. Toda conversa:

1. **Lê este caderno inteiro** antes de começar (e o `CLAUDE.md` da raiz).
2. Trabalha **só na parte dela** (tabela abaixo). Arquivo de outra parte: **não mexe**; se
   precisar, pede ao Luiz para passar o recado à conversa dona daquela parte.
3. Antes de mexer num **arquivo compartilhado**, avisa o Luiz ("vou mexer em X, avise as
   outras conversas") e faz a mudança **pequena** e rápida de juntar.
4. **Ao terminar uma entrega**, escreve uma linha no **Diário** (no fim deste arquivo).

## Ramificações (as "cópias" do código no GitHub)

- **Principal:** `claude/zax-sydimx`. É dela que toda conversa nova parte, e é ela que o
  notebook do Luiz usa.
- Cada conversa trabalha na **sua própria ramificação** (a conversa recebe uma automaticamente).
- **Antes de começar** e **antes de entregar**: trazer as novidades da principal
  (`git fetch origin claude/zax-sydimx && git merge origin/claude/zax-sydimx`) e rodar os testes.
- Para entregar: push (só quando o Luiz pedir) e **PR para a principal**. Entra **um PR de cada
  vez**; as outras conversas atualizam depois que ele entrar.
- Conflito no `packages/api-contracts/openapi.json`: não resolver na mão, rodar
  `.venv/bin/python scripts/export_openapi.py`.

## Quem cuida de quê

### Conversa CENTRAL (tela da TV) — pode mexer à vontade em:
- `apps/web/src/central/**`, `apps/web/central.html`, `apps/web/public/central.webmanifest`
- `apps/api/titan_api/routers/central.py`, `titan/central/**`
- `tests/integration/test_central.py`, `apps/web/tests/central.test.ts`
- `docs/central.md`, `docs/prototipos/central/**`
- `apps/android/app/src/central/**` (manifesto, ícone, banner)

### Conversa CASA (automação) — pode mexer à vontade em:
- `apps/web/src/casa/**`, `apps/web/casa.html`, `apps/web/public/casa.webmanifest`
- `apps/api/titan_api/routers/casa.py`, `titan/casa/**`
- `tests/integration/test_casa.py`, `docs/casa.md`
- `apps/android/app/src/casa/**`

### Conversa TITAN (o app normal) — pode mexer à vontade em:
- `apps/web/src/components/**`, `apps/web/src/App.tsx`, `apps/web/src/main.tsx`,
  `apps/web/src/brain.ts`, `apps/web/src/reminders.ts`, `apps/web/src/notify.ts`
- routers `auth`, `brain`, `conversations`, `health`, `lessons`, `preferences`, `system`, `tasks`
- `titan/brain/**`, `titan/lessons/**`, `titan/memory/**`, `titan/tasks/**`, `titan/orchestrator/**`,
  `titan/tools/**`, `titan/models/**`, `titan/approvals/**`, `titan/audit/**`, `titan/sim/**`
- os testes e docs dessas partes
- **É a dona dos APKs**: só ela gera `apps/web/public/*.apk` (a chave de assinatura fica com o
  Luiz; peça a ele). As outras, se mudarem algo do Android, avisam e ela gera os 3 APKs.

### Compartilhados — avisar antes, mudança pequena:
| Arquivo / pasta | Por quê |
|---|---|
| `titan/config/settings.py` | configurações de todos |
| `titan/cli.py` | comandos `titan ...` de todos |
| `apps/api/titan_api/app.py`, `deps.py`, `schemas.py` | servidor de todos |
| `titan/db/models.py` e `migrations/versions/**` | banco de dados (ver regra de numeração) |
| `apps/web/src/voice/**`, `apps/web/src/api.ts` | voz e conexão usadas pelos 3 apps |
| `apps/web/src/styles.css`, `apps/web/src/theme/**`, `apps/web/public/sw.js`, `vite.config.ts` | visual e páginas de todos |
| `apps/web/src/components/Login.tsx`, `BootIntro.tsx`, `ErrorBoundary.tsx` | usados pelos 3 apps |
| `titan/voice/**`, `apps/api/titan_api/routers/voice.py` | voz e "abaixar a música" |
| `titan/mobile.py`, `titan/desktop.py` | instalação no celular e apps do menu |
| `apps/android/app/build.gradle`, `apps/android/app/src/main/**` | app Android dos 3 |
| `packages/api-contracts/openapi.json` | gerado: só rodar o script |
| `README.md`, `CLAUDE.md`, este caderno | todos lêem |

**Migrações do banco:** a próxima livre é a **0007**. Antes de criar uma, **reserve aqui**
(escreva "0007 — reservada pela conversa X para Y") e só então crie. Nunca duas com o mesmo número.

## Reservas (migrações e arquivos compartilhados em uso)

| O quê | Conversa | Desde | Para quê |
|---|---|---|---|
| — | — | — | — |

## Pendências conhecidas (de qualquer parte)

- Tablet (Android 4.4): fazer o TITAN Casa abrir no Chrome dele (Chrome antigo, ~81): esperando
  o Luiz mandar a versão do Chrome. APK não instala no 4.4 (WebView velho demais). — CASA
- Comandos de infravermelho (TV/ar) da Tuya ainda não testados em aparelho real. — CASA
- Voz "Andrew grave + robô nível 3": esperando o Luiz dar a ordem. — TITAN
- Ligação para o TITAN (modo ligação / Zadarma): para depois. — TITAN
- Simulação de qualidade (carteira) pausada: o trabalho está em `docs/pausado/simulacao-qualidade.patch`
  (aplicar com `git apply`). — TITAN
- "Abaixar a música": testado com Chromium e PulseAudio; falta confirmar no Firefox do notebook. — compartilhado

## Diário (mais recente embaixo)

Formato: `AAAA-MM-DD · CONVERSA · o que fez · arquivos compartilhados que mexeu`

- 2026-11-07 · inicial · TITAN, sócio, Casa, Central, apps no menu do Linux, abaixar a música; criou
  `CLAUDE.md` e este caderno · (todos, antes de dividir)
- 2026-11-07 · CENTRAL · a conversa original passa a ser a CENTRAL (sessão claude/g-ayvaxj); prompts
  das conversas CASA e TITAN entregues ao Luiz · (só este caderno)
