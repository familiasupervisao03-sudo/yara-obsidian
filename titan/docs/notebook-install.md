# Instalar o TITAN no notebook (servidor local)

Guia em etapas pequenas. Nenhum comando aqui usa `sudo`, abre portas ou
envia seus dados para fora. Pare em qualquer etapa que der erro e me mande a
saída.

O projeto fica em `~/Projetos/TITAN`. O repositório é o cofre
`yara-obsidian`, e o TITAN está na subpasta `titan/`, ou seja:
**`~/Projetos/TITAN/titan`**.

## Etapa 1 — Baixar (sem sobrescrever nada)

```sh
# 1a. Confirme que a pasta ainda NÃO existe (se existir, pare e me avise):
ls -la ~/Projetos/TITAN 2>/dev/null && echo "JÁ EXISTE — não continue" || echo "livre"

# 1b. Baixe só o branch das Fases 0 e 1:
mkdir -p ~/Projetos
git clone --branch claude/g-ayvaxj --single-branch \
  https://github.com/familiasupervisao03-sudo/yara-obsidian.git ~/Projetos/TITAN

# 1c. Confirme que o commit 75b5093 está no histórico:
cd ~/Projetos/TITAN
git merge-base --is-ancestor 75b5093 HEAD && echo "commit 75b5093 presente"
git log --oneline -5
```

O branch tem o commit `75b5093` (Fases 0 e 1) e, depois dele, um commit que
adiciona os scripts de instalação e verificação para o notebook (este guia).
Para ver exatamente o que mudou depois do `75b5093`:
`git diff --stat 75b5093 HEAD`.

## Etapa 2 — Auditar o notebook (somente leitura)

Leia o script antes de rodar (ele só consulta informações):

```sh
cd ~/Projetos/TITAN/titan
less scripts/audit_host.sh          # q para sair
sh scripts/audit_host.sh | tee ~/Projetos/titan-auditoria.txt
```

**Me envie esse relatório.** Com ele eu confirmo o plano. Pontos decisivos:

| Resultado | Consequência |
|---|---|
| Python < 3.10 | o TITAN não instala; precisamos decidir como obter um Python novo (ver Problemas) |
| Arquitetura `i686`/32 bits | pode faltar pacote pré-compilado; o setup avisa sem compilar nada |
| `python3-venv` ausente | precisa de `sudo apt install python3-venv` (só com sua autorização) |
| Node.js ausente ou < 20.19 | a interface não compila aqui (ver Etapa 4) |
| RAM < 2 GB | SQLite (padrão), sem PostgreSQL e sem modelos locais |

## Etapa 3 — Instalar e configurar

```sh
cd ~/Projetos/TITAN/titan
less scripts/setup.sh                # leia antes
TITAN_EXTRAS=dev sh scripts/setup.sh
```

O que ele faz (tudo dentro da pasta do projeto):

- cria `.venv/` e instala só pacotes **pré-compilados** (nada é compilado);
  `dev` adiciona o pytest para os testes (~5 MB);
- cria `.env` com um segredo aleatório, permissão `600`, **sem sobrescrever**
  um `.env` existente;
- valida a configuração (SQLite, `127.0.0.1:8000`, APIs pagas bloqueadas,
  R$ 0/dia, modelos externos bloqueados, execução de código desativada);
- cria o banco `var/titan.db` (pasta `var/` com permissão `700`).

## Etapa 4 — Interface web

Precisa de Node.js 20.19+ **só para compilar** (`node --version`).

```sh
npm ci && npm run build      # ~71 MB em node_modules/, ~250 KB no resultado
```

Se o Node do notebook for antigo ou ausente, **não instale nada ainda** — me
avise. Opções (você escolhe):
1. compilar em outro computador e copiar a pasta `apps/web/dist/`;
2. instalar um Node recente só no seu usuário (~100 MB, sem sudo);
3. usar só a API por enquanto (o servidor funciona sem a interface).

## Etapa 5 — Criar sua conta administrativa

```sh
.venv/bin/titan create-user seu_nome     # senha pedida no terminal, mín. 10 caracteres
```

A senha não aparece na tela, não vai para o histórico do shell e é guardada
só como hash scrypt.

## Etapa 6 — Verificar de verdade

```sh
.venv/bin/python scripts/verify_local.py
```

Roda os testes automatizados e sobe uma **instância temporária** (porta 8799,
banco descartável — seus dados reais não são tocados) para conferir: início do
servidor, `/ready`, interface, login, senha errada recusada, persistência
após reiniciar, bloqueio de APIs pagas, porta presa ao `127.0.0.1`, nenhuma
conexão externa, logs sem erros e sem segredos, permissões do `.env`.
Termina com um resumo `N OK, M falha(s)`. Me envie a saída.

## Etapa 7 — Usar

```sh
cd ~/Projetos/TITAN/titan
.venv/bin/titan serve        # iniciar (deixe o terminal aberto)
# Ctrl+C                     # parar
```

Abra `http://127.0.0.1:8000` no navegador **do próprio notebook**. Os dados
ficam em `~/Projetos/TITAN/titan/var/` e persistem entre reinícios.

Ver logs: `tail -n 50 var/logs/titan.log`
Integridade da auditoria: `.venv/bin/titan audit-verify`

## O que fica desativado (de propósito)

- **Acesso pelo celular/Wi-Fi:** desligado. Riscos e passos em
  `docs/setup.md` §4 e `docs/security.md` — só ativamos com sua autorização.
- **Início automático:** avaliado em `docs/autostart.md`, não configurado.
- **IA:** nenhum modelo configurado; o chat salva mensagens e avisa que não
  há resposta. Modelo local = etapa futura, conforme o hardware.
- **Execução de programas:** bloqueada até existir sandbox validado.

## Problemas

- **Python < 3.10:** não atualize o Python do sistema. Alternativas (decidir
  juntos): Python isolado só no seu usuário (ex.: `uv`, ~30–40 MB, sem
  sudo), ou versão do Python dos repositórios oficiais da distribuição.
- **Falha de pacote pré-compilado (32 bits/ARM):** o setup para sem compilar.
  Me envie a mensagem; compilar dependências (ex.: pydantic-core em Rust)
  num notebook antigo é pesado e só faremos com sua autorização.
- **Porta 8000 ocupada:** mude `TITAN_PORT` no `.env`.
- **Esqueceu a senha:** crie outro usuário com `create-user`.
