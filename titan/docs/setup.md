# Instalação e operação local

> Todos os comandos abaixo rodam **no notebook**, a partir da pasta `titan/`.
> Nada é enviado à internet além do download inicial das dependências.

## 0. Auditar o notebook (recomendado antes de tudo)

```sh
sh scripts/audit_host.sh > auditoria.txt
```

Somente leitura: mostra arquitetura (32/64 bits), CPU/AVX2, RAM, disco,
Python/Node/Docker/PostgreSQL e o suporte a isolamento. Compartilhe o
resultado para ajustarmos as próximas fases.

## 1. Requisitos

| Item | Mínimo | Observação |
|---|---|---|
| Python | 3.10 | testado em 3.10 e 3.13 |
| Espaço em disco | ~150 MB | ambiente virtual + dados iniciais |
| Node.js | 20.19+ | **só para compilar a interface**; pode compilar em outra máquina e copiar `apps/web/dist/` |
| PostgreSQL | opcional | o padrão é SQLite |
| Docker | opcional | não é usado na Fase 1 |

## 2. Instalação

```sh
sh scripts/setup.sh
```

O script cria `.venv/`, instala as dependências mínimas, cria `.env` com um
`TITAN_AUTH_SECRET` aleatório (permissão 600; **não sobrescreve** um `.env`
existente), valida a configuração e aplica as migrações.

Interface (uma vez, em máquina com Node 20.19+):

```sh
npm install
npm run build          # gera apps/web/dist/, servido pelo backend
```

Crie o usuário (a senha é pedida no terminal, mínimo 10 caracteres):

```sh
.venv/bin/titan create-user seu_nome
```

## 3. Iniciar e parar

```sh
.venv/bin/titan serve        # aplica migrações pendentes e inicia
# Ctrl+C para parar
```

Abra `http://127.0.0.1:8000`. O backend não precisa de navegador aberto para
manter os dados. Não há serviço permanente instalado: o TITAN só roda
enquanto o comando estiver ativo.

Outros comandos:

```sh
.venv/bin/titan check-config   # mostra a configuração efetiva (sem segredos)
.venv/bin/titan migrate        # aplica migrações
.venv/bin/titan audit-verify   # verifica a integridade da auditoria
.venv/bin/titan gen-secret     # gera um novo segredo
```

## 4. Acesso pelo celular (Wi-Fi local)

Por padrão o TITAN escuta só em `127.0.0.1` (inacessível de fora). Para o
celular:

1. Descubra o IP do notebook: `ip -4 addr` (ex.: `192.168.0.10`) e a faixa da
   rede (ex.: `192.168.0.0/24`).
2. No `.env`:
   ```
   TITAN_HOST=0.0.0.0
   TITAN_ALLOWED_NETWORKS=127.0.0.1/32,192.168.0.0/24
   ```
   Para restringir a um único aparelho, use o IP dele com `/32`
   (ex.: `192.168.0.42/32`) e reserve esse IP no roteador.
3. Reinicie e acesse `http://192.168.0.10:8000` no celular. O login continua
   obrigatório.

A configuração é **recusada** se `TITAN_ALLOWED_NETWORKS` contiver
`0.0.0.0/0` ou redes públicas. O TITAN não cria túneis, não usa UPnP e não
abre portas no roteador. **Não configure encaminhamento de portas.**

Limitações (ver `docs/security.md`): sem HTTPS, o tráfego na Wi-Fi não é
cifrado. Use apenas em rede doméstica confiável com WPA2/WPA3.

Se o firewall do notebook estiver ativo (ex.: `ufw`), libere a porta só para
a rede local: `sudo ufw allow from 192.168.0.0/24 to any port 8000 proto tcp`.

## 5. PostgreSQL (opcional)

Use só se a auditoria mostrar RAM sobrando (sugestão: 4 GB+).

```sh
.venv/bin/pip install -e ".[postgres]"
# crie usuário/banco localmente, depois no .env:
DATABASE_URL=postgresql+psycopg://titan:SUA_SENHA@127.0.0.1:5432/titan
.venv/bin/titan migrate
```

Também há um `compose.yaml` opcional (PostgreSQL limitado a 256 MB e preso a
127.0.0.1) para quem já usa Docker.

## 6. Backup e restauração (manual nesta fase)

Backup automatizado e teste de restauração estão previstos para a Fase 5.
Até lá, com o servidor **parado**:

```sh
mkdir -p backups && chmod 700 backups
sqlite3 var/titan.db ".backup 'backups/titan-$(date +%F).db'"   # ou: cp var/titan.db backups/
```

Restaurar: pare o servidor e copie o arquivo de volta para `var/titan.db`.
Guarde também o `.env` (contém o segredo de sessão) em local seguro e
separado. Riscos de perda/roubo do notebook: ver `docs/security.md`.

## 7. Confirmar que chamadas externas estão desativadas

```sh
.venv/bin/titan check-config | grep -E "allow_paid|budget|external|provider|local_only"
```

Deve mostrar `allow_paid_apis = False`, `daily_paid_budget_brl = 0.0`,
`allow_external_models = False`, `local_only = True`. A interface exibe os
mesmos valores (vindos do servidor). O teste
`tests/security/test_no_network_by_default.py` comprova que nenhuma conexão
externa é aberta durante o uso normal.

## 8. Desenvolvimento

```sh
TITAN_EXTRAS=dev,postgres sh scripts/setup.sh
.venv/bin/pytest                                   # suíte completa (SQLite)
TITAN_TEST_DATABASE_URL=postgresql+psycopg://u:s@127.0.0.1/titan_test .venv/bin/pytest   # + PostgreSQL
npm run typecheck && npm run build
npm run dev           # Vite em 127.0.0.1:5173 com proxy para o backend
python scripts/export_openapi.py                   # após mudar contratos
```
