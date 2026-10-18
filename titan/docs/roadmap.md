# Roadmap

## Fase 1 — Fundação ✔ (esta entrega)

Ver relatório no histórico do commit e `docs/architecture.md`.

## Fase 2 — Orquestração e aprovações (próxima)

1. `titan/tasks/state_machine.py`: estados RECEIVED … FAILED com tabela de
   transições permitidas; transições gravadas em `audit_events` na mesma
   transação; troca de estado com `UPDATE … WHERE status = :esperado`
   (concorrência otimista) para evitar transições duplicadas.
2. Planos versionados em `task_steps` (`plan_version`); `tasks.plan_version`
   aponta a versão vigente. Planejador determinístico/manual primeiro (sem
   LLM), interface pronta para o modelo da Fase 4.
3. Aprovações: `scope_hash = sha256(action_type, parâmetros canônicos,
   plan_version, task_id)`. Execução só começa se existir aprovação
   `APPROVED` com hash idêntico, verificada no servidor no momento da
   execução. Nova versão de plano marca aprovações incompatíveis como
   `INVALIDATED`. O ator `model` nunca pode decidir aprovações.
4. Idempotência: `tasks.idempotency_key` (único por usuário) +
   cabeçalho `Idempotency-Key`.
5. Cancelamento (`CANCEL_REQUESTED → CANCELLED`) e retomada: na
   inicialização, tarefas em `RUNNING/VERIFYING` viram `INTERRUPTED`;
   `resume` só reexecuta etapas sem resultado verificado.
6. SSE em `/api/v1/tasks/{id}/events` lendo `audit_events` por id
   (reconexão com `Last-Event-ID`), sem fila externa.
7. Endpoints: tasks, cancel, resume, events, approvals, decision, audit.
8. Testes de aceitação 3, 4, 5, 6, 12 e 13.

## Fase 3 — Laboratório isolado

Escolher o mecanismo conforme `scripts/audit_host.sh` (ordem de preferência:
bubblewrap → Podman rootless → Docker restrito). Testes de fuga (leitura fora
do workspace, rede, fork bomb, memória, tempo, tamanho de arquivo) devem
passar antes de habilitar `TITAN_SANDBOX_ENABLED`.

## Fase 4 — Modelos

Adaptador Ollama/llama.cpp somente se o hardware suportar; medir RAM e
latência; descarregar o modelo quando ocioso.

## Fase 5 — Consolidação

Backup/restauração automatizados e testados, revisão de dependências,
HTTPS local opcional, documentação de implantação futura.
