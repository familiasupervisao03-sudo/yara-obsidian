# Simulação contínua

`titan simular` fica rodando simulações sem parar, uma rodada depois da outra, e
documenta tudo. Serve para achar problemas que só aparecem **com o tempo, com
volume ou com acidente** — antes de eles acontecerem no uso real.

## Começar e parar

```sh
cd ~/Projetos/TITAN/titan
.venv/bin/titan simular            # começa (deixe a janela aberta)
```

Para parar **com segurança** (a rodada em andamento termina e é salva):

- **Ctrl+C uma vez** na janela da simulação; ou
- em outro terminal: `.venv/bin/titan parar-simulacao`.

A mensagem final é *"Simulação encerrada com segurança"*. Apertar Ctrl+C de novo
não interrompe nada no meio — só lembra que está terminando. Se a energia cair
ou o processo for morto à força, a rodada incompleta é **descartada** e anotada
no diário da próxima sessão; as rodadas anteriores já estavam gravadas por
completo, e o servidor de teste morre junto (não fica processo órfão).

Opções: `--minutos 3` (duração da rodada de uso prolongado), `--pausa 10`
(segundos entre rodadas), `--tipos orcamento,uso,seguranca,falhas,voz`,
`--max-rodadas N`, `--rapido` (rodadas curtas, para testar),
`--repetir TIPO:SEMENTE` (repete exatamente uma rodada do diário).

## Seus dados ficam de fora

Tudo roda numa **cópia isolada** do TITAN: banco temporário, outra porta, pastas
temporárias, provedor de IA **falso**, e o `.env` real (com a chave da Anthropic)
**não é lido**. Nenhuma chamada paga ou externa é feita. A simulação roda com
prioridade baixa (o notebook continua usável), pausa se a memória livre ficar
abaixo de 250 MB e para sozinha se o disco ficar com menos de 500 MB.

## O que cada rodada faz

| Tipo | O que simula | O que confere |
|---|---|---|
| **Orçamento da Anthropic** | dezenas de simulações por rodada, cada uma com centenas de chamadas em 4 threads a um cliente Anthropic **falso**: respostas de tamanhos aleatórios, erros da API, quedas de conexão, respostas interrompidas | o gasto registrado nunca passa do limite diário; nunca fica abaixo do que teria sido cobrado; nenhuma reserva pendurada; chamada recusada nunca é enviada |
| **Uso prolongado** | 3 "pessoas" ao mesmo tempo: conversas (com e sem streaming, reenvio da mesma mensagem), tarefas (simples, com aprovação, canceladas), preferências, eventos ao vivo, voz (se instalada) | cada ação dá o resultado esperado; tempos de resposta; memória e arquivos abertos do servidor ao longo das horas; auditoria íntegra |
| **Segurança** | todas as rotas sem login, sem o cabeçalho anti-CSRF, com Origin de outro site, com recursos de outro usuário, e centenas de requisições aleatórias/malformadas/enormes; senhas erradas seguidas | nada aceito sem login; alterações forjadas recusadas; isolamento entre usuários; nenhum erro interno; nenhum segredo nas respostas; bloqueio após senhas erradas |
| **Falhas e recuperação** | queda abrupta do servidor (SIGKILL) num instante sorteado do uso; banco travado por outro processo; backup durante o uso, às vezes morto no meio | o servidor volta; banco íntegro; auditoria íntegra; nenhuma mensagem duplicada; nenhuma tarefa presa; tarefas interrompidas retomam; o backup seguinte passa no teste de restauração |
| **Voz (regressão)** | o avaliador de voz (docs/voice-eval.md) com as 22 gravações | os limites da etapa 2 e o mesmo resultado da rodada anterior (precisa do Vosk instalado) |

Ordem: orçamento, uso, segurança, falhas, uso, orçamento, segurança, falhas, voz — e recomeça.

## Onde fica o registro

`var/simulacao/<data-hora>/`:

- `diario.md` — cada rodada: o que foi conferido (✓/✗), medidas, problemas e
  como repetir;
- `resumo.md` — atualizado a cada rodada: placar por tipo, problemas agrupados
  (quantas vezes e em quais rodadas), memória e tempos ao longo da sessão;
- `falhas/` — detalhes de cada rodada com problema (requisição, resposta, semente);
- `rodadas.jsonl` — os mesmos dados em formato para programas;
- `registros-tecnicos.log` — avisos técnicos.

Um problema no próprio simulador aparece como "o simulador executou a rodada sem
erro ✗" com o erro anotado — nada é escondido, e isso não é confundido com
defeito do TITAN.

## O que a simulação já encontrou (ambiente de desenvolvimento, 25/10/2026)

Em 4 rodadas seguidas de uso prolongado (3 "pessoas" ao mesmo tempo, ~9 min):

1. **Erros 500 e tarefas interrompidas sob uso simultâneo** (`database is locked`):
   12 tarefas simples e 10 com aprovação terminaram como INTERRUPTED; também
   houve 500 em listar conversas, enviar mensagem, streaming e estado do sistema;
   o streaming chegou a 14,8 s (p95). Causas confirmadas no log do servidor:
   - **ordem invertida das travas**: `audit.record` pega a trava da auditoria
     (Python) e depois precisa da trava de escrita do SQLite, enquanto outra
     requisição tem a do SQLite e espera a da auditoria — as duas esperam até o
     limite de 15 s (`titan/audit/log.py:79`, executor de tarefas);
   - **toda requisição grava** `last_seen_at` da sessão (`titan/auth/service.py:143`),
     então até leituras viram escritas e disputam a trava (`GET /tasks/{id}`
     falhou 12× em `titan/tasks/service.py:73`).
2. **Memória do servidor subindo**: 233 → 587 → 639 → 706 → 744 MB em ~9 min, sem
   estabilizar. Suspeita principal (não confirmada): `/system/status` reverifica
   a cadeia de auditoria INTEIRA a cada chamada (`apps/api/titan_api/routers/system.py:76`)
   e a interface consulta essa rota a cada 30 s — o custo cresce com o histórico.
3. **Orçamento conservador** (não é defeito): quedas e respostas interrompidas
   mantêm a reserva do pior caso; o registrado fica acima do cobrado e o limite
   diário chega antes. Em 120 simulações o limite nunca foi ultrapassado.

Passaram em todas as rodadas: segurança (34 rotas, centenas de requisições
malformadas, isolamento entre usuários, bloqueio por senha errada), falhas e
recuperação (queda abrupta, banco travado, backup morto no meio) e voz.

### Correções aplicadas (25/10/2026) e nova medição

1. `audit.record` pega a trava de escrita do SQLite **antes** da trava da cadeia
   (sempre a mesma ordem) — `test_audit_lock_order_does_not_deadlock` reproduzia o
   travamento de 15 s antes e passa em 0,7 s depois.
2. `last_seen_at` é gravado no máximo **uma vez por minuto** (leituras deixam de
   ser escritas) — `test_last_seen_is_written_at_most_once_per_minute`.
3. A tela de estado confere a auditoria de forma **incremental** (só eventos novos,
   mais o último já conferido; a cadeia inteira a cada 10 min) e a verificação
   completa lê só as colunas, em blocos — `test_chain_monitor_checks_only_new_events_and_still_catches_tampering`.
   `titan audit-verify` continua conferindo tudo.

Mesmas 4 rodadas seguidas de uso prolongado, com voz em uso nos dois casos:

| | Antes | Depois |
|---|---|---|
| Ações que falharam | 6–9 por rodada | 0 |
| Erros no log do servidor | dezenas (`database is locked`) | 0 |
| Streaming p95 | até 14.785 ms | 62–73 ms |
| Memória do servidor (~9 min) | 233 → 587 → 639 → 706 → 744 MB | 242 → 442 → 504 → 525 → 531 MB |

Com voz, a memória agora estabiliza (+200, +54, +10, +3,5 MB por rodada); os
~180 MB iniciais são o modelo Vosk. **Sem voz, ainda sobe devagar** (102 → 170 MB em
8 min, ~20 MB por rodada) — pode ser só o crescimento dos dados (conversas mais
longas), não confirmado. Uma sessão longa no notebook mostra a tendência no resumo.
