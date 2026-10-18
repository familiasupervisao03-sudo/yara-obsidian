# Segurança e privacidade

Este documento descreve **o que está implementado e testado** na Fase 1 e o
que ainda não existe. Nenhuma afirmação aqui vai além do que os testes
sustentam; cada item cita o teste correspondente.

## Dados que permanecem no notebook

Tudo: banco (`var/titan.db` ou PostgreSQL local), logs (`var/logs/`),
workspaces (`var/workspaces/`), `.env` com o segredo de sessão. Não há
sincronização, telemetria, CDN ou fontes externas (a CSP só permite `'self'`).

## Operações que podem acessar a internet

| Operação | Quando |
|---|---|
| `pip install` / `npm install` | só na instalação, manualmente |
| Uso normal do TITAN | **nenhuma** — `test_no_outbound_connections` |
| Modelos externos | bloqueados (`TITAN_ALLOW_EXTERNAL_MODELS=false`, `LOCAL_ONLY=true`) |
| APIs pagas | bloqueadas (R$ 0/dia) |

## Políticas aplicadas no backend

| Regra | Onde | Teste |
|---|---|---|
| `TITAN_ALLOW_PAID_APIS=true` impede a inicialização | `titan/config/settings.py` | `test_unsafe_config_is_refused`, `test_paid_env_variable_blocks_startup` |
| Orçamento diferente de 0 impede a inicialização | idem | idem |
| Provedor não-local (openai, anthropic, …) recusado | idem | `test_external_provider_cannot_be_selected` |
| `LOCAL_ONLY` + `ALLOW_EXTERNAL_MODELS` = conflito | idem | `test_unsafe_config_is_refused` |
| Provedor pago/externo recusado **antes da chamada** | `titan/policies/model_gate.py` | `test_paid_provider_blocked_before_call`, `test_paid_blocked_even_if_settings_object_is_tampered` |
| Sem fallback automático | `titan/models/providers.py` | `test_none_provider_reports_unavailable` |
| Configurações não são alteráveis pela API (nem pelo modelo) | `GET /api/v1/settings` é somente leitura | `test_settings_endpoint_is_read_only` |
| Rede no sandbox não pode ser ligada | `settings.py` | `test_unsafe_config_is_refused` |

## Autenticação e sessões

- Usuários criados apenas pela linha de comando (`titan create-user`); não há
  cadastro público.
- Senhas com **scrypt** (n=2¹⁴, r=8; ~16 MB por verificação), sal aleatório.
- Login com tempo equalizado para usuário inexistente e mensagem única.
- Bloqueio temporário após `TITAN_LOGIN_MAX_ATTEMPTS` falhas por usuário+IP
  (`test_lockout_after_repeated_failures`). O contador fica em memória e zera
  ao reiniciar.
- Sessão: token aleatório de 256 bits em cookie `HttpOnly; SameSite=Strict`;
  o banco guarda só o HMAC-SHA256 do token
  (`test_session_token_not_stored_in_plaintext`). Logout revoga no servidor
  (`test_logout_revokes_token_server_side`). Expiração configurável
  (`test_expired_session_rejected`).
- Todas as rotas `/api/v1/*`, exceto login, exigem sessão — verificado
  automaticamente para cada rota do contrato OpenAPI
  (`test_every_api_route_requires_auth`).
- Isolamento entre usuários: conversa de outro usuário responde 404
  (`test_users_cannot_see_each_other`).

## CSRF, CORS e cabeçalhos

- Métodos que alteram estado exigem `X-Titan-Request: 1`
  (`test_state_changing_requests_require_csrf_header`, inclusive no login).
  Combinado com `SameSite=Strict` e ausência de CORS (`test_no_cors_headers`).
- CSP restritiva (`default-src 'self'`, sem scripts inline),
  `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, `Cache-Control: no-store`
  na API (`test_security_headers`).

## Rede local

- Padrão: escuta só em `127.0.0.1`.
- `TITAN_ALLOWED_NETWORKS` filtra o IP de origem antes de qualquer rota
  (`test_clients_outside_allowed_networks_are_refused`, validado também com
  servidor real: IP fora da lista → 403).
- `X-Forwarded-For` é ignorado (`proxy_headers=False`;
  `test_forwarded_header_does_not_bypass_allowlist`).
- A configuração recusa `0.0.0.0/0` e redes públicas.
- **Estar na Wi-Fi não autentica ninguém**: o login continua obrigatório
  (`test_lan_client_allowed_when_network_configured`).

### Limitações conhecidas (rede local)

- **Sem HTTPS.** Na Wi-Fi o tráfego (inclusive a senha no login) trafega sem
  cifragem; alguém na mesma rede pode interceptá-lo. Use somente em rede
  doméstica confiável com WPA2/WPA3. HTTPS local exige um certificado
  confiável no celular (ex.: CA local com `mkcert`) — decisão adiada; quando
  houver HTTPS, ative `TITAN_COOKIE_SECURE=true`.
- Filtro por IP não é prova de identidade (IPs podem ser falsificados na
  mesma rede). Ele reduz a superfície; a autenticação é o controle principal.

## Segredos

- `.env` e `var/` estão no `.gitignore` (`test_env_files_are_gitignored`);
  `.env.example` só tem valores de demonstração, e o valor de exemplo do
  segredo é recusado (`test_unsafe_config_is_refused`).
- Redação de segredos em logs (incluindo tracebacks) e em eventos de
  auditoria: chaves sensíveis, padrões de tokens/API keys, senha em URL de
  banco e o próprio `TITAN_AUTH_SECRET` (`test_secret_redacted_from_logs`,
  `test_secret_in_traceback_is_redacted`, `tests/unit/test_redaction.py`).
- Nenhum segredo em respostas da API, no OpenAPI ou no DOM
  (`test_secret_not_in_any_api_response`; smoke de UI).
- Diretórios de dados e workspaces com permissão `0700`
  (`test_data_dirs_are_private`); `.env` criado com `600` pelo setup.

## Auditoria

Eventos (`auth.login`, `auth.login_failed`, `auth.logout`,
`conversation.created`, `message.created`, `model.reply`, `user.created`) são
gravados com dados redigidos e encadeados por SHA-256. Alterar ou remover um
evento quebra a cadeia (`test_chain_detects_tampering`); verifique com
`titan audit-verify`. Limite: quem tem acesso de escrita ao banco pode
reescrever a cadeia inteira; a cadeia detecta adulteração parcial, não impede
um atacante com controle total do notebook.

## Sandbox (execução de código)

**Estado: DESATIVADO.** Nenhum código gerado é executado nesta fase, nem no
host nem em contêiner. `TITAN_SANDBOX_ENABLED=true` não habilita nada: o
executor ainda não existe e o status mostra "execução bloqueada".

Investigação inicial (no contêiner de desenvolvimento, **não** no notebook):
Docker CLI presente mas daemon inacessível; user namespaces sem root
funcionam; seccomp suportado; `bwrap`/`nsjail`/`firejail` ausentes. A escolha
do mecanismo para a Fase 3 depende da auditoria do notebook. Candidatos, do
mais leve ao mais pesado: **bubblewrap** (namespaces + seccomp, sem daemon) +
limites via `prlimit`/cgroups; **Podman rootless**; **Docker** com
`--network none --read-only --cap-drop ALL --security-opt no-new-privileges
--pids-limit --memory --cpus`, usuário não-root e sem montagens sensíveis. Em
qualquer caso, os controles serão validados por testes que tentam ler
arquivos fora do workspace e abrir conexões de rede; se falharem, a execução
permanece bloqueada.

## Riscos de perda ou roubo do notebook

- Os dados não são cifrados pelo TITAN. Quem tiver o disco tem as conversas.
  Recomendação: criptografia de disco (LUKS) ou, no mínimo, da pasta pessoal.
- Backup: mantenha cópias em mídia externa guardada separadamente (ver
  `docs/setup.md`). O `.env` deve ser guardado à parte; se vazar, gere outro
  segredo (isso invalida todas as sessões).
- Disco antigo pode falhar sem aviso: faça backups regulares.
