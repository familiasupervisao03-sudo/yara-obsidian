# Fase 3 — Laboratório isolado (preparação; EXECUÇÃO DESATIVADA)

Nesta versão **nenhum código gerado é executado**. A ação `run_code` passa pelo
contrato do executor (`titan/sandbox/contract.py`), que sempre recusa com o
motivo. Não existe fallback para rodar direto no sistema.

## 1. Verificar o notebook (somente leitura)

```sh
.venv/bin/titan sandbox-probe
```

Mostra arquitetura, bubblewrap, user namespaces (e a restrição do AppArmor),
cgroups v2, systemd-run, prlimit, seccomp, Podman e Docker, com uma
recomendação. Nada é instalado nem executado além de checagens inofensivas.

## 2. Mecanismo recomendado para Linux Mint 22

**bubblewrap** (`bwrap`): isolamento por namespaces sem root e sem daemon,
leve para hardware antigo. No Ubuntu 24.04/Mint 22 os namespaces sem root são
restritos pelo AppArmor, e o pacote `bubblewrap` já traz o perfil que o permite.
Instalação (exige `sudo` e sua autorização): `sudo apt install bubblewrap`.

Perfil planejado:
- `--unshare-all` (inclui rede: sem interface de rede, só loopback isolado);
- raiz somente leitura com `/usr` e o Python do sistema; `--tmpfs /tmp`;
- workspace da tarefa montado em `/work` (único local gravável), criado em
  `var/workspaces/<tarefa>/` com permissão 700;
- sem acesso a `$HOME`, `.env`, `var/titan.db`, `var/tls`, `var/models`;
- `--die-with-parent`, `--new-session`, sem `CAP_*`, seccomp quando disponível;
- limites: tempo (timeout + `prlimit --cpu`), memória (`prlimit --as` ou
  `systemd-run --user -p MemoryMax=` se houver cgroups v2), processos
  (`--nproc`), tamanho de arquivo (`--fsize`), saída truncada;
- limpeza do workspace ao final, mantendo apenas artefatos registrados.

Alternativas: Podman rootless; Docker com `--network none --read-only
--cap-drop ALL --security-opt no-new-privileges --pids-limit --memory --cpus`
(mais pesado). Docker sozinho **não** é considerado isolamento suficiente.

## 3. Testes de fuga obrigatórios (antes de liberar)

Cada um tenta violar o isolamento; **todos** precisam falhar como esperado:

1. ler `~/.ssh`, `~/.bashrc`, o `.env` e `var/titan.db` → negado/inexistente;
2. escrever fora de `/work` (ex.: `/usr`, `/tmp` do host, `$HOME`) → negado;
3. abrir conexão de rede (DNS, TCP para 1.1.1.1, `localhost:8000` do TITAN) → falha;
4. fork bomb → limitado por `--nproc`, sem afetar o notebook;
5. alocar memória acima do limite → processo encerrado;
6. loop infinito → encerrado pelo tempo;
7. gerar arquivo gigante → limitado por `--fsize`;
8. escapar por symlink no workspace (ex.: `ln -s / root`) → não expõe o host;
9. ver processos do host (`/proc`) → só os do sandbox;
10. variáveis de ambiente do TITAN (segredos) → ausentes.

Somente com os 10 testes passando no notebook real o executor poderá ser
ligado, e mesmo assim cada execução continuará exigindo **aprovação humana**
vinculada ao código exato (scope_hash da etapa) e à versão do plano.
