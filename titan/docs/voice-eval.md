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

## Etapa 2 — detecção e captura (sem modelos novos)

O avaliador passou a continuar 3 s além do fim de cada arquivo (repetindo o fundo),
para que "preso" signifique preso de verdade. Por isso a linha de base foi
**medida de novo** com o avaliador final, sobre uma cópia do código e2946ba.
Mesmo ambiente de desenvolvimento (Xeon, com AVX); números do notebook a medir.

| Métrica (transcrição simulada 300 ms) | Antes (e2946ba) | Depois |
|---|---|---|
| Ruídos que dispararam o detector | 4/9 | 2/9 (porta; voz de fundo) |
| Ruídos que viraram mensagem | 2/9 | 1/9 (a voz de fundo) |
| Detector preso (ruído / fala) | 2 / 4 | 0 / 1 (outra pessoa falando ao fundo) |
| Falas perdidas | 2/13 | 1/13 ("sim": o Vosk não reconhece) |
| Pediu para repetir em vez de enviar palpite | — | 1/13 (duas vozes ao mesmo tempo) |
| Frases partidas em mais de uma mensagem | 1/13 | 0/13 |
| WER médio | 65,5% | 54,4% |
| Detector: precisão / revocação por quadro | 39,7% / 83,2% | 54,1% / 91,5% |
| Atraso para perceber o fim da fala | 1446 ms | 1138 ms |
| Vosk: fim da fala → texto (média) | 119 ms | 125 ms |
| RAM do modelo | ~184 MB | ~180 MB |

Com transcrição simulada de 1000 ms (CPU lenta) os resultados "depois" são iguais;
"antes", a palavra dita durante a transcrição se perdia.

O que mudou e por quê (cada item comparado com o avaliador):

- **Energia na faixa da voz** (passa-altas 200 Hz, só para o detector): ventilador,
  zumbido, batidas e passos deixam de contar como fala.
- **Calibração de 500 ms** ao abrir o microfone, usando o percentil baixo (se a
  pessoa já estiver falando, a fala não vira "ruído").
- **Piso de ruído = máx(média no silêncio, percentil 10% dos últimos 3 s)**: um
  ruído constante que começa no meio não deixa mais o detector preso.
  *Tentativa descartada:* só o percentil fez o ventilador constante disparar.
- **Limiar 2,5× (era 3×), mínimo 0,008, fala mínima 160 ms, 900 ms guardados antes
  da detecção**: recupera voz baixa e a primeira palavra. Teclado continua sem
  disparar (estalos isolados não sustentam 160 ms).
- **Silêncio de 1,0 s** para encerrar (era 1,3 s): 0,8 s partia a pausa curta.
- **Continuação emendada**: se a pessoa volta a falar enquanto o trecho anterior
  é transcrito, as partes viram uma mensagem só (o áudio não é mais descartado).
- **Frase incompleta** ("…dentista e"): espera mais ~1 s ouvindo antes de enviar.
  *Achado no navegador real:* os textos parciais do Vosk chegam atrasados, então a
  decisão usa o texto final; a simulação, que tinha parciais imediatos, foi otimista.
- **Veredito da transcrição**: a nota de confiança do Vosk **não separa ruído**
  (música virou "o" com nota 0,99). Regras usadas: até 2 palavras, todas vazias
  ("o", "é", "hum") → ignorado em silêncio; nota média < 0,5 (visto com duas vozes
  ao mesmo tempo) → "Não entendi bem (ouvi: …). Pode repetir?" em vez de enviar.

Navegador real (Chromium, microfone simulado por WAV, Vosk e Piper reais): a frase
com pausa longa chegou inteira numa mensagem; fim da fala → texto 106–210 ms;
interrupção → áudio parado 310 ms; nenhuma requisição externa.

Limitações que continuam: outra pessoa falando ao fundo mantém a captura aberta e
entra no texto (a detecção por energia não sabe quem fala — etapa 4); o modelo
pequeno erra palavras ("abre a" → "a bia", "titan" não existe no vocabulário) e
não reconhece "sim" isolado — etapa 3. Conjunto de amostras pequeno: as regras
foram ajustadas nele e precisam ser confirmadas com gravações reais.

## Etapa 3 — reconhecimento alternativo (whisper.cpp): não integrado

whisper.cpp v1.9.5 compilado **sem AVX/AVX2/FMA/F16C/SSE4** (`-march=core2`,
`GGML_NATIVE=OFF`); o binário foi inspecionado com `objdump`: nenhuma instrução
AVX/VEX nem SSE4.1/4.2 (só SSSE3, que o Core 2/Penryn tem). Modelos quantizados
q5_1. Medido no ambiente de desenvolvimento (Xeon), **2 threads** como no T4500,
só o reconhecedor, sobre o arquivo inteiro de cada uma das 13 falas
(`scripts/voice_eval/compare_whisper.py`):

| Reconhecedor | WER | Tempo ÷ duração do áudio | RAM |
|---|---|---|---|
| Vosk small pt (atual) | 48,5% | 0,30 | ~180 MB |
| whisper tiny | 63,9% | 1,11 | ~200 MB |
| whisper base | 48,1% | 2,70 | ~200 MB |
| whisper small | 37,7% | 11,5 | ~345 MB |

O small acerta mais (nomes como "Titan" e "Paraná", e até a fala com duas vozes),
mas leva ~46 s para uma frase de 4 s **aqui**; no T4500 seria mais lento ainda —
inviável para conversa. O base empata com o Vosk e é ~9× mais lento. Decisão:
**manter o Vosk**; nenhum modelo novo no TITAN. Para repetir no notebook, compile
o whisper.cpp lá com `-DGGML_NATIVE=ON` e rode o script acima.

## Etapa 4 — verificação do dono: avaliada, não implementada

Modelo de locutor do Vosk (`vosk-model-spk-0.4`, ~15 MB, x-vector; roda dentro do
Vosk, sem AVX). Cadastro com 3 frases do "dono" (voz Piper faber); teste com 10
frases diferentes em 4 condições contra 3 outras vozes Piper e o dono com outra
pessoa ao fundo (`scripts/voice_eval/speaker_eval.py`). **Vozes sintéticas são muito
mais regulares que voz humana: estes números são otimistas.**

| Limiar de semelhança | Recusa o dono | Aceita outra pessoa | Dono + voz ao fundo aceito |
|---|---|---|---|
| 0,30 (erro igual) | 11–17% | 18,5% | 100% |
| 0,40 | 38,9% | 0% | 0% |
| 0,50 | 63,9% | 0% | 0% |

Semelhança média do dono: 0,46 normal, 0,30 com ventilador; outras vozes 0,12–0,30.
Decisão: **não usar como filtro** — mesmo no caso otimista ele ignoraria o dono com
frequência (ou deixaria outras pessoas passarem), e a regra é não descartar falas
só porque outra pessoa pode estar presente. Também não serviria como autenticação
(uma gravação da voz engana). O que mais reduz vozes de fundo é **microfone perto da
boca** (headset/lapela). Se no futuro houver gravações reais voluntárias do dono,
dá para medir de novo com o mesmo script antes de decidir.
