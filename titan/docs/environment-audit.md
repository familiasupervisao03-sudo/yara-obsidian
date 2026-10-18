# Fase Zero — auditoria do ambiente

## Importante: onde esta entrega foi construída

A implementação e os testes desta entrega rodaram em um **contêiner de
desenvolvimento na nuvem** (o ambiente do assistente), **não no seu
notebook**. Os números abaixo descrevem esse contêiner e servem só como
referência. O notebook real precisa ser auditado com:

```sh
sh scripts/audit_host.sh > auditoria.txt
```

## Repositório encontrado

- Repositório `yara-obsidian` (cofre Obsidian) com um único arquivo
  preexistente: `Zax/Apocalipse - Biblioteca de fontes.md`.
- Nenhum projeto TITAN existente. O TITAN foi criado na subpasta `titan/`
  para **não tocar** no conteúdo do cofre. Nenhum arquivo preexistente foi
  alterado.

## Contêiner de desenvolvimento (medido)

| Item | Valor |
|---|---|
| SO | Ubuntu 24.04.5 LTS, kernel 6.18 |
| Arquitetura | x86_64 (64 bits) |
| CPU | Intel Xeon @ 2,1 GHz, 4 núcleos, **sem AVX2** reportado |
| RAM | 16 GB, sem swap |
| Disco livre | ~30 GB |
| Python | 3.13.16 (também 3.10, 3.11, 3.12 disponíveis) |
| Node.js / npm | 22.22.0 / 10.9.4 |
| Git | 2.43.0 |
| SQLite (Python) | 3.45.1 |
| PostgreSQL | 16.15 instalado, cluster parado; iniciado para os testes |
| Docker | CLI 29.8 presente; **daemon inacessível** |
| Isolamento | user namespaces sem root: sim; seccomp: sim; cgroups v2: não detectado; bwrap/podman/nsjail/firejail: ausentes |
| Modelos locais | nenhum (Ollama ausente) |

## Decisões tomadas a partir da auditoria

1. **SQLite como padrão**, PostgreSQL opcional pela mesma camada
   (SQLAlchemy + Alembic). Motivo: o notebook é antigo e ainda não auditado;
   SQLite não tem custo de RAM em repouso. Ambos os bancos passaram na suíte.
2. **Execução de código desativada**: nenhum sandbox validado está disponível
   (daemon Docker inacessível aqui; notebook desconhecido).
3. **Sem modelo de IA**: nada local disponível; adaptadores externos
   bloqueados. Chat funciona com histórico persistente e informa a ausência
   de modelo.
4. **Frontend compilado e servido pelo backend**: Node só é necessário para
   compilar (pode ser feito em outra máquina).
5. **Compatibilidade**: código testado em Python 3.10 e 3.13; script de
   auditoria em `sh` POSIX (funciona em distribuições antigas e 32 bits).

## Pendências que dependem do notebook

- Arquitetura (32 vs 64 bits): define se Docker e modelos locais são viáveis.
- RAM e AVX2: define se algum modelo local é utilizável.
- Mecanismo de sandbox disponível (bwrap/podman/docker, userns, cgroups v2).
- Versão do Python (mínimo 3.10) e do Node (20.19+ só para compilar).
