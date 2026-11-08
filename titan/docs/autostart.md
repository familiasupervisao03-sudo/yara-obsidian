# Iniciar o TITAN automaticamente (avaliação — NÃO configurado)

Só faça isto **depois** de o início manual (`.venv/bin/titan serve`) e o
`scripts/verify_local.py` terem funcionado.

## Opção recomendada: serviço de usuário do systemd

Funciona na maioria das distribuições com systemd (verifique com
`systemctl --user status`; se der erro, sua distribuição pode não ter
systemd de usuário — me avise).

O que muda no sistema:

| Mudança | Onde | Precisa de sudo? |
|---|---|---|
| Um arquivo de serviço | `~/.config/systemd/user/titan.service` | não |
| Ativar o serviço | `systemctl --user enable --now titan` | não |
| (Opcional) iniciar no boot **sem** fazer login | `sudo loginctl enable-linger $USER` | **sim** |

Sem o "linger", o TITAN inicia quando você faz login na sessão gráfica e para
quando sai. Com o linger, inicia junto com o computador.

O modelo `scripts/titan-user.service.example` já limita memória (400 MB),
baixa a prioridade (`Nice=10`) e usa `NoNewPrivileges`. Ele continua
escutando apenas em `127.0.0.1` (vem do seu `.env`).

Passos (quando autorizado):

```sh
mkdir -p ~/.config/systemd/user
cp ~/Projetos/TITAN/titan/scripts/titan-user.service.example ~/.config/systemd/user/titan.service
systemctl --user daemon-reload
systemctl --user enable --now titan
systemctl --user status titan          # deve mostrar "active (running)"
journalctl --user -u titan -n 50       # logs
```

Desfazer completamente:

```sh
systemctl --user disable --now titan
rm ~/.config/systemd/user/titan.service
systemctl --user daemon-reload
sudo loginctl disable-linger $USER     # só se tiver ativado
```

## Custo

Com o TITAN sempre ligado: ~80–120 MB de RAM (medido no ambiente de
desenvolvimento; meça no notebook com `systemctl --user status titan`) e CPU
praticamente zero quando ninguém está usando.
