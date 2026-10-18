# TITAN

IA pessoal com interface de centro de comando tático, executada **no seu
notebook**, com privacidade local, orçamento de APIs pagas de **R$ 0/dia** e
nenhuma ação apresentada como concluída sem verificação.

**Estado: Fase 1 — Fundação.** Funciona hoje: servidor local, login, chat com
histórico persistente, painel tático (desktop e celular), auditoria encadeada,
bloqueios de APIs pagas/externas. Ainda **não** existe: tarefas e aprovações
(Fase 2), execução de código em sandbox (Fase 3, desativada), modelo de IA
local (Fase 4).

## Início rápido

```sh
cd titan
sh scripts/audit_host.sh          # 1. audite o notebook (somente leitura)
sh scripts/setup.sh               # 2. venv, dependências, .env com segredo, migrações
npm install && npm run build      # 3. interface (precisa de Node 20.19+, só para compilar)
.venv/bin/titan create-user seu_nome
.venv/bin/titan serve             # http://127.0.0.1:8000
```

Detalhes, celular na Wi-Fi, PostgreSQL e backup: [`docs/setup.md`](docs/setup.md).

## Documentação

- [`docs/architecture.md`](docs/architecture.md) — arquitetura, estrutura, consumo de recursos
- [`docs/security.md`](docs/security.md) — o que está protegido, como foi testado e limitações
- [`docs/api.md`](docs/api.md) — contratos da API e erros
- [`docs/environment-audit.md`](docs/environment-audit.md) — Fase Zero
- [`docs/roadmap.md`](docs/roadmap.md) — próximas fases

## Regras que o código aplica

- `TITAN_ALLOW_PAID_APIS=true` ou orçamento ≠ 0 → o servidor **não inicia**.
- Provedores de IA externos → recusados na configuração e antes de cada chamada.
- Escuta só em `127.0.0.1` por padrão; LAN exige lista de redes privadas explícita.
- Sem túneis, encaminhamento de portas, telemetria ou recursos externos na interface.
- Execução de código desativada até existir um sandbox validado por testes.

## Testes

```sh
.venv/bin/pytest                    # unit, integration, security, acceptance
npm run typecheck && npm run build
```
