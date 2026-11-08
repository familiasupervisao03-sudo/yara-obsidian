# Arquitetura do TITAN

## Princípios

1. **O notebook é o servidor.** Backend, banco, auditoria e (futuramente) o
   orquestrador rodam localmente. Nenhum serviço de nuvem é necessário.
2. **Privacidade antes de conveniência.** Nada sai do notebook por padrão; não
   há telemetria; provedores externos de IA ficam bloqueados no backend.
3. **R$ 0/dia.** APIs pagas são recusadas na validação da configuração e,
   de novo, imediatamente antes de qualquer chamada a um provedor.
4. **Leve.** Um processo Python, SQLite por padrão, frontend estático
   compilado servido pelo próprio backend (sem Node em execução).
5. **Honestidade.** Módulos não implementados aparecem como "planejado" ou
   "desativado"; nada é simulado como real.

## Visão geral

```
 Navegador (notebook ou celular na Wi-Fi)
        │  HTTP (cookie HttpOnly + cabeçalho anti-CSRF)
        ▼
 ┌──────────────────────── processo único (uvicorn, 1 worker) ───────────────┐
 │ Middlewares: allowlist de rede → CSRF → cabeçalhos de segurança (CSP)     │
 │ apps/api/titan_api  (rotas REST, schemas Pydantic, erros padronizados)    │
 │        │                                                                  │
 │ titan/ auth · memory · audit · policies · models · config · db           │
 │        │                                                                  │
 │ SQLAlchemy 2 ──► SQLite (padrão)  ou  PostgreSQL (opcional)               │
 │ Arquivos: var/ (0700) → titan.db, logs/ (rotativos), workspaces/          │
 └───────────────────────────────────────────────────────────────────────────┘
```

## Estrutura do repositório

| Caminho | Responsabilidade | Estado |
|---|---|---|
| `apps/api/titan_api/` | Camada HTTP: app FastAPI, rotas, schemas, middlewares | Fase 1 ✔ |
| `apps/web/` | Interface React + TypeScript (Vite), compilada para `dist/` | Fase 1 ✔ |
| `packages/api-contracts/` | Tipos TS dos contratos + `openapi.json` gerado | Fase 1 ✔ |
| `titan/config/` | Configuração validada; falha segura em conflitos | Fase 1 ✔ |
| `titan/db/` | Modelos ORM, engine, migrações | Fase 1 ✔ |
| `titan/auth/` | Usuários, hash scrypt, sessões, bloqueio de tentativas | Fase 1 ✔ |
| `titan/memory/` | Conversas e mensagens (repositório) | Fase 1 ✔ |
| `titan/audit/` | Auditoria encadeada por hash, com redação de segredos | Fase 1 ✔ |
| `titan/policies/` | Bloqueio de provedores pagos/externos | Fase 1 ✔ |
| `titan/models/` | Interface de modelos; `none` e `mock` (testes) | parcial (Fase 4) |
| `titan/core/` | Redação de segredos, diretórios privados, logs | Fase 1 ✔ |
| `titan/tasks/`, `titan/orchestrator/`, `titan/approvals/` | Tarefas, planos, máquina de estados, aprovações | Fase 2 |
| `titan/sandbox/`, `titan/tools/`, `titan/verification/` | Executor isolado e verificação | Fase 3 |
| `migrations/` | Alembic (todas as 13 tabelas já criadas) | Fase 1 ✔ |
| `tests/{unit,integration,security,acceptance}` | Testes automatizados | Fase 1 ✔ |
| `scripts/` | Auditoria do host, setup, export OpenAPI, smoke de UI | Fase 1 ✔ |

**Desvio justificado da estrutura proposta:** a camada HTTP mora em
`apps/api/titan_api/` (pacote Python importável) para que o núcleo `titan/`
não dependa do FastAPI. `titan/db/` foi adicionado para concentrar modelos e
migrações, compartilhados por todos os módulos.

## Banco de dados

- **Padrão: SQLite** (WAL, `foreign_keys=ON`). Motivo: o notebook-alvo é
  antigo e ainda não foi auditado; SQLite não consome RAM em repouso e não
  exige serviço. PostgreSQL é suportado pela mesma camada (testado nesta
  entrega) e pode ser ativado só trocando `DATABASE_URL`.
- Tabelas: `users, sessions, conversations, messages, tasks, task_steps,
  approvals, executions, execution_artifacts, verification_results,
  audit_events, memory_items, app_settings`.
- Datas sempre em UTC com fuso (tipo `UTCDateTime`, também no SQLite).
- `audit_events` usa chave inteira sequencial porque a cadeia de hashes exige
  ordem estrita. `approvals.scope_hash` já está previsto para vincular a
  aprovação à ação, aos parâmetros e à versão do plano (Fase 2).
- Um teste (`test_models_match_migrations`) falha se um modelo mudar sem
  migração correspondente.

## Modelos de IA

`titan/models/providers.py` define a interface (`chat(history) -> ModelReply`).
`get_provider()` sempre chama `assert_provider_allowed()` antes de devolver um
provedor; provedores pagos ou externos são recusados. Não existe fallback.
Sem modelo, a mensagem do usuário é salva e a interface informa que não há
resposta — nada é inventado. Adaptadores locais (Ollama / llama.cpp) estão
previstos para a Fase 4, condicionados à auditoria do hardware.

## Consumo de recursos

| Item | Valor | Tipo |
|---|---|---|
| RSS do servidor ocioso (SQLite) | ~82 MB | **medido** no contêiner de desenvolvimento (x86_64, Python 3.13) |
| RSS após login + mensagens + UI | ~118 MB | **medido** idem |
| Tempo até `/health` responder | ~0,8 s | **medido** idem (CPU Xeon 2,1 GHz — será maior no notebook) |
| Frontend compilado | 248 KB (73 KB gzip de JS) | **medido** |
| PostgreSQL 16 ocioso (se usado) | ~30 MB processo principal + ~35 MB auxiliares | **medido** no contêiner |
| `node_modules` (só para compilar) | ~71 MB | **medido**; desnecessário em execução |
| Notebook antigo | desconhecido | **pendente**: rodar `scripts/audit_host.sh` |

Os números do notebook real só serão conhecidos após a auditoria.
