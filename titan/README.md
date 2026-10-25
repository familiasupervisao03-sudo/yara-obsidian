# TITAN

IA pessoal com interface de centro de comando tático, executada **no seu
notebook**, com privacidade local, orçamento de APIs pagas de **R$ 0/dia** e
nenhuma ação apresentada como concluída sem verificação.

**Estado: Fase 2 — Tarefas e aprovações.** Funciona hoje: servidor local, login,
chat em streaming com histórico, modo de voz (local com Vosk/Piper, opcional),
tarefas com planos versionados, aprovações humanas, cancelamento/retomada e
eventos ao vivo, backups testados, interface mobile/PWA, integração opcional com
a Anthropic com orçamento. Preparado mas **desligado**: acesso pelo celular via
HTTPS local, laboratório de código (Fase 3 — execução bloqueada até validar o
isolamento).

## Início rápido

```sh
cd titan
sh scripts/audit_host.sh          # 1. audite o notebook (somente leitura)
sh scripts/setup.sh               # 2. venv, dependências, .env com segredo, migrações
npm install && npm run build      # 3. interface (precisa de Node 20.19+, só para compilar)
.venv/bin/titan create-user seu_nome
.venv/bin/titan serve             # http://127.0.0.1:8000
```

**Instalação no notebook, passo a passo:** [`docs/notebook-install.md`](docs/notebook-install.md).
Detalhes, celular na Wi-Fi, PostgreSQL e backup: [`docs/setup.md`](docs/setup.md).
Início automático (avaliação): [`docs/autostart.md`](docs/autostart.md).

## Documentação

- [`docs/architecture.md`](docs/architecture.md) — arquitetura, estrutura, consumo de recursos
- [`docs/security.md`](docs/security.md) — o que está protegido, como foi testado e limitações
- [`docs/api.md`](docs/api.md) — contratos da API e erros
- [`docs/environment-audit.md`](docs/environment-audit.md) — Fase Zero
- [`docs/voice.md`](docs/voice.md) — modo de voz, privacidade e medições
- [`docs/voice-eval.md`](docs/voice-eval.md) — avaliação reproduzível da voz
- [`docs/simulacao.md`](docs/simulacao.md) — simulação contínua (`titan simular`) e parada segura
- [`docs/pesquisa-internet.md`](docs/pesquisa-internet.md) — pesquisa na internet (desligada por padrão), SearXNG local e proteções
- [`docs/mobile.md`](docs/mobile.md) — acesso pelo celular (HTTPS local)
- [`docs/backup.md`](docs/backup.md) — backup e recuperação
- [`docs/sandbox.md`](docs/sandbox.md) — preparação do laboratório isolado
- [`docs/anthropic.md`](docs/anthropic.md) — API da Anthropic (opcional, paga)
- [`docs/roadmap.md`](docs/roadmap.md) — próximas fases

## Regras que o código aplica

- APIs pagas desligadas por padrão (R$ 0/dia). A Anthropic (Claude) pode ser ligada por você com
  `sh scripts/enable_anthropic.sh`: exige orçamento diário, chave e a palavra AUTORIZO, e o
  servidor recusa qualquer chamada que possa passar do orçamento ([`docs/anthropic.md`](docs/anthropic.md)).
- Sem autorização completa, provedores externos são recusados na configuração e antes de cada chamada.
- Escuta só em `127.0.0.1` por padrão; LAN exige lista de redes privadas explícita.
- Sem túneis, encaminhamento de portas, telemetria ou recursos externos na interface.
- Execução de código desativada até existir um sandbox validado por testes.

## Testes

```sh
.venv/bin/pytest                    # backend: unit, integration, security, acceptance
npm test                            # lógica do modo de voz (node:test)
npm run typecheck && npm run build
```
