# Avaliação da voz (reproduzível)

`scripts/voice_eval/` mede a voz do TITAN com dados, para comparar cada mudança
com a anterior em vez de confiar em impressões.

- `samples/`: 22 gravações **sintéticas** (16 kHz, mono): ruídos gerados por código
  (ventilador, teclado, batidas, porta, passos, música, silêncio), outra voz ao
  fundo e falas do "dono" em várias condições (curta, uma palavra, gírias, voz
  baixa, com ventilador/teclado/música, outra pessoa ao fundo, duas vozes ao mesmo
  tempo, pausa curta e pausa longa depois de frase incompleta). As vozes são do
  Piper; `labels.json` diz o texto esperado e quando o dono está falando.
  Gerador: `make_samples.py` (semente fixa).
- `simulate.ts`: roda a **sessão de voz real** do navegador (`session.ts` e `vad.ts`)
  sobre cada arquivo, com relógio simulado, e guarda o áudio que seria enviado à
  transcrição.
- `run_eval.py`: transcreve cada trecho com o **Vosk real** (mesma classe do
  servidor) e calcula as métricas. Grava `report.md` e `report.json` com a
  configuração completa (commit, CPU, modelo, parâmetros do detector).

## Rodar no notebook

```sh
cd ~/Projetos/TITAN/titan
.venv/bin/python scripts/voice_eval/run_eval.py --label notebook
```

Nada sai do computador; o áudio temporário é apagado no fim. Precisa do Vosk e do
modelo instalados (`scripts/install_voice_local.sh`) e do Node.

## Limitações

- O áudio é usado **cru**: no navegador real, a supressão de ruído, o cancelamento
  de eco e o ganho automático agem antes. Os resultados aqui tendem a ser **piores**
  que no uso real para ruídos constantes (ventilador).
- Ruídos e vozes sintéticos não substituem gravações reais. Gravações suas só
  entram se você quiser fornecê-las.
- O tempo de transcrição na simulação é um parâmetro (`--transcribe-ms`); o tempo
  real do Vosk é medido separadamente na tabela.

## Linha de base (commit e2946ba, antes das melhorias)

Ambiente de desenvolvimento (Xeon 2,1 GHz, **com AVX**; não é o notebook),
`vosk-model-small-pt-0.3`, transcrição simulada de 300 ms.

| Métrica | Valor |
|---|---|
| Ruídos que dispararam o detector | 4/9 |
| Ruídos que viraram mensagem enviada | 2/9 (música → "o"; voz de fundo transcrita inteira) |
| Detector preso capturando até o fim (ruído / fala) | 2 / 5 |
| Falas perdidas | 2/13 ("sim"; voz baixa) |
| Falas partidas em mais de uma mensagem | 1/13 (pausa longa) |
| Primeira palavra correta | 6/13 |
| WER médio (1ª mensagem) | 56,6% |
| Detector: precisão / revocação por quadro | 50,8% / 83,2% |
| Atraso para perceber o fim da fala | 1280 ms (é o silêncio fixo de 1,3 s) |
| Vosk: carga / fim da fala → texto (média, p95) | 3,9 s / 129 ms, 250 ms |
| RAM do modelo Vosk | ~182 MB |

Com a transcrição simulada em 1000 ms (CPU lenta), a palavra "depois", dita
enquanto a parte anterior era transcrita, **se perdeu** — confirma o defeito de
áudio ignorado durante a transcrição.
