# Backup e recuperação

Tudo é local. Nada vai para a nuvem.

## Fazer backup

```sh
cd ~/Projetos/TITAN/titan
.venv/bin/titan backup
```

O comando:
1. copia o banco com a **API de backup do SQLite**, que é consistente mesmo com
   o servidor ligado e gravando;
2. roda `PRAGMA integrity_check` na cópia;
3. **testa a restauração** numa pasta temporária separada (integridade, chaves
   estrangeiras e cadeia de auditoria), sem tocar no banco original;
4. apaga backups antigos além da retenção (`TITAN_BACKUP_KEEP`, padrão 7),
   **sem nunca apagar o último backup válido**.

Os arquivos ficam em `TITAN_BACKUP_DIR` (padrão `./backups`), com permissão 600.
Cada backup tem um `.json` com hash, tamanho, versão do esquema e a configuração
**sem segredos**.

Outros comandos:

```sh
.venv/bin/titan backup-list                 # lista os backups
.venv/bin/titan backup-verify               # testa a restauração do último backup válido
.venv/bin/titan backup-verify backups/titan-AAAAMMDD-....db
```

> O `.env` (com o segredo de sessão e a chave da Anthropic) **não** entra no
> backup, de propósito. Guarde uma cópia dele à parte (por exemplo, num pendrive
> criptografado). Sem o `.env`, basta gerar um novo segredo; todos fazem login
> de novo.

## Guardar fora do notebook

O backup no mesmo disco não protege contra falha de disco ou roubo. Copie a
pasta `backups/` periodicamente para um pendrive ou HD externo:

```sh
cp -a backups/ /media/$USER/MEU_PENDRIVE/titan-backups/
```

## Restaurar

1. **Pare o servidor** (`Ctrl+C` no terminal dele).
2. Rode:
   ```sh
   .venv/bin/titan restore backups/titan-AAAAMMDD-....db --yes
   ```
   O comando verifica o backup antes e guarda uma cópia do banco atual em
   `var/titan.db.antes-da-restauracao-DATA`.
3. Inicie de novo: `.venv/bin/titan serve`.

## Cenários de recuperação

| Situação | O que fazer |
|---|---|
| Atualização (`git pull`) quebrou algo | `git log` → `git checkout <commit anterior>`; o banco é compatível se a migração não rodou; se rodou, restaure o backup feito antes da atualização |
| Queda de energia/servidor travou | Inicie normalmente. Tarefas em andamento viram **INTERRUPTED**; use "Retomar" na interface. Etapas com resultado incerto pedem confirmação antes de repetir |
| Banco corrompido | Pare o servidor, `titan backup-verify` para achar o último backup bom, `titan restore ... --yes` |
| Disco do notebook falhou | Em outra máquina: clonar o repositório, `sh scripts/install_and_start.sh`, copiar o backup do pendrive, `titan restore ... --yes`, recolocar o `.env` guardado (ou gerar um novo) |
| `.env` perdido | `.venv/bin/titan gen-secret` e colocar em `TITAN_AUTH_SECRET`; reconfigurar a Anthropic com `sh scripts/enable_anthropic.sh` |

## Backup automático diário (opcional, não instalado)

Com um timer de usuário do systemd (sem sudo):

`~/.config/systemd/user/titan-backup.service`
```ini
[Unit]
Description=Backup do TITAN
[Service]
Type=oneshot
WorkingDirectory=%h/Projetos/TITAN/titan
ExecStart=%h/Projetos/TITAN/titan/.venv/bin/titan backup
Nice=15
```

`~/.config/systemd/user/titan-backup.timer`
```ini
[Unit]
Description=Backup diário do TITAN
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
```

Ativar: `systemctl --user daemon-reload && systemctl --user enable --now titan-backup.timer`.
Desfazer: `systemctl --user disable --now titan-backup.timer` e apagar os dois arquivos.

## PostgreSQL

Se você trocar para PostgreSQL, use `pg_dump -Fc` e `pg_restore` (o comando
`titan backup` é só para SQLite e avisa isso).
