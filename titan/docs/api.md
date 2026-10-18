# API do TITAN (v1)

Contrato completo e sempre atualizado: `packages/api-contracts/openapi.json`
(gerado por `python scripts/export_openapi.py`; o teste
`test_openapi_contract_is_up_to_date` falha se estiver desatualizado). Tipos
TypeScript: `packages/api-contracts/src/index.ts`. Em `TITAN_ENV=development`,
a documentação interativa fica em `/docs`.

## Convenções

- Prefixo `/api/v1`; identificadores são UUID.
- Autenticação por cookie `titan_session` (HttpOnly, SameSite=Strict), obtido
  em `POST /api/v1/auth/login`.
- **Todo método que altera estado** (`POST/PUT/PATCH/DELETE` em `/api/`)
  exige o cabeçalho `X-Titan-Request: 1`.
- Requisições de IPs fora de `TITAN_ALLOWED_NETWORKS` recebem 403 antes de
  qualquer rota.
- Erros sempre no formato:

```json
{ "error": { "code": "not_found", "message": "Conversa não encontrada.", "details": null } }
```

| HTTP | `code` | Quando |
|---|---|---|
| 401 | `unauthorized` | sem sessão, sessão expirada/revogada, credenciais inválidas |
| 403 | `csrf_header_missing` | falta `X-Titan-Request` |
| 403 | `forbidden_network` | IP fora das redes autorizadas |
| 404 | `not_found` | recurso inexistente **ou de outro usuário** |
| 405 | `method_not_allowed` | método não suportado |
| 422 | `validation_error` | entrada inválida (`details` lista os campos) |
| 429 | `too_many_requests` | login bloqueado temporariamente (`Retry-After`) |
| 500 | `internal_error` | erro interno (detalhes só no log local) |
| 503 | — | `/ready` com dependência indisponível; `ui_not_built` em `/` |

## Rotas implementadas (Fase 1)

| Método e rota | Auth | Descrição |
|---|---|---|
| `GET /health` | não | processo ativo |
| `GET /ready` | não | banco acessível e migrações aplicadas (200/503) |
| `POST /api/v1/auth/login` | não | `{username, password}` → define cookie, retorna usuário e expiração |
| `POST /api/v1/auth/logout` | sim | revoga a sessão no servidor (204) |
| `GET /api/v1/auth/me` | sim | sessão atual |
| `POST /api/v1/conversations` | sim | `{title?}` → 201 |
| `GET /api/v1/conversations?limit&offset` | sim | `{items, total}` do usuário |
| `GET /api/v1/conversations/{id}` | sim | conversa com mensagens |
| `POST /api/v1/conversations/{id}/messages` | sim | `{content, client_request_id?}` → 201 |
| `GET /api/v1/settings` | sim | configuração efetiva sem segredos + políticas (somente leitura) |
| `GET /api/v1/system/status` | sim | estado dos serviços, bloqueios e integridade da auditoria |

### Mensagens

```json
POST /api/v1/conversations/{id}/messages
{ "content": "Olá", "client_request_id": "a1b2c3d4e5f6" }

201
{
  "user_message": { "id": "…", "role": "user", "content": "Olá", … },
  "reply": null,
  "model": { "available": false, "provider": "none",
             "detail": "Nenhum modelo de linguagem configurado (TITAN_MODEL_PROVIDER=none)." },
  "duplicate": false
}
```

- Sem modelo disponível, `reply` é `null` e `model.available` é `false`. A
  mensagem do usuário fica salva; nenhuma resposta é fabricada.
- `client_request_id` (8–64 caracteres `[A-Za-z0-9_-]`) torna o envio
  idempotente: um reenvio com a mesma chave devolve a mensagem original com
  `duplicate: true` e não cria nada novo.

## Fase 2 — tarefas e aprovações

| Método e rota | Descrição |
|---|---|
| `GET /api/v1/tasks/catalog` | ações permitidas (com risco e se exigem aprovação) e tipos de critério |
| `POST /api/v1/tasks` | `{title, description, steps?}`; cabeçalho `Idempotency-Key` evita duplicata (201/200) |
| `GET /api/v1/tasks` · `GET /api/v1/tasks/{id}` | lista · detalhe (etapas, aprovações, versões do plano, verificação) |
| `PUT /api/v1/tasks/{id}/plan` | nova versão do plano; invalida aprovações anteriores |
| `POST /api/v1/tasks/{id}/start` | inicia (só em READY) |
| `POST /api/v1/tasks/{id}/cancel` | cancela (CANCEL_REQUESTED se em execução) |
| `POST /api/v1/tasks/{id}/resume` | `{retry_uncertain}`; 409 `needs_confirmation` se houver etapa incerta |
| `POST /api/v1/tasks/{id}/reply` | resposta a uma etapa `wait_for_user` |
| `GET /api/v1/tasks/{id}/events` | SSE (`event: task`, `id` = evento de auditoria); `Last-Event-ID` retoma sem duplicar |
| `GET /api/v1/tasks/{id}/executions` · `/audit` | execuções · trilha de auditoria da tarefa |
| `GET /api/v1/approvals?status=` | aprovações do usuário (padrão PENDING) |
| `POST /api/v1/approvals/{id}/decision` | `{decision: approve\|reject, scope_hash, reason}` — o `scope_hash` exibido deve ser reenviado |

Estados: RECEIVED, PLANNING, PENDING_APPROVAL, READY, RUNNING, VERIFYING,
WAITING_FOR_USER, CANCEL_REQUESTED, CANCELLED, INTERRUPTED, COMPLETED, FAILED.

## Chat em streaming

`POST /api/v1/conversations/{id}/messages/stream` (SSE): `user_message`,
`delta {text}`, `done {message, metrics}`, `interrupted {message}`,
`error {detail}`. Fechar a conexão cancela a geração.
`POST /api/v1/conversations/{id}/messages/{mid}/interruption {spoken_chars}`
registra até onde a resposta foi falada.

## Voz (local)

| Rota | Descrição |
|---|---|
| `GET /api/v1/voice/status` | mecanismos (local/externo, disponível, motivo) |
| `POST /api/v1/voice/stt/sessions` | abre sessão de reconhecimento (503 se indisponível) |
| `POST /api/v1/voice/stt/sessions/{sid}/audio` | PCM 16 bits mono 16 kHz (≤256 KB por pedaço) → texto parcial |
| `POST /api/v1/voice/stt/sessions/{sid}/finish` | texto final (a sessão é encerrada) |
| `DELETE /api/v1/voice/stt/sessions/{sid}` | cancela |
| `POST /api/v1/voice/speak` | `{text}` → `audio/wav` (Piper) |
