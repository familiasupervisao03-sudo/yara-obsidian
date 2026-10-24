# Modo de voz

## Como funciona

```
microfone (navegador, com cancelamento de eco e redução de ruído)
  → detecção de fala (VAD, no navegador)
  → reconhecimento: Vosk no notebook (áudio enviado em pedaços enquanto você fala)
  → chat em streaming (o mesmo histórico do chat de texto)
  → frases faláveis (sem código/links/markdown)
  → voz: Piper no notebook (frase por frase, a 1ª começa logo)
  → reprodução, interrompível a qualquer momento
```

- **Fale naturalmente.** Pausas de até ~1,3 s (ajustável de 0,8 a 3 s em
  Configurações) não encerram a sua vez.
- **Interromper:** fale por cima do TITAN. O áudio para na hora, o que não foi
  falado é descartado e o próximo turno informa à IA até onde a resposta foi
  ouvida. Também há o botão **Interromper**.
- **Revisar antes de enviar** (opcional): mostra o texto entendido para editar.
- Se a voz falhar, a resposta continua em texto; o botão **Usar texto** leva
  ao chat.

## Privacidade

| Mecanismo | Onde roda | O que sai do notebook |
|---|---|---|
| Vosk (reconhecimento) | notebook | nada |
| Piper (voz) | notebook | nada |
| Reconhecimento do navegador (Web Speech) | servidores do fornecedor (ex.: Google) | **o áudio da sua fala** — só com o seu consentimento explícito na tela |
| Voz "do aparelho" (local) | celular/notebook | nada |
| Voz on-line do navegador | fornecedor | o texto da resposta — opcional |
| Voz natural on-line (Microsoft, `edge`) | servidores da Microsoft | o texto da resposta — só depois de `enable-online-voice` com AUTORIZO |
| Modelo de IA (Anthropic, se ligado) | Anthropic | o texto da conversa (já era assim no chat) |

Áudio não é gravado: é processado em memória e descartado. O microfone é
desligado ao encerrar a sessão ou sair da tela. Uma transcrição é só texto:
**não aprova nenhuma ação** (aprovações exigem o botão na tela de Tarefas).

## Instalar a voz local (opcional)

```sh
cd ~/Projetos/TITAN/titan
git pull
sh scripts/install_voice_local.sh     # mostra tamanhos e pede "sim"
```

Baixa ~230 MB de bibliotecas (onnxruntime é a maior), ~32 MB do modelo Vosk
pt e ~63 MB da voz pt_BR "faber". Depois reinicie o servidor e recompile a
interface (`npm run build`).

**Processadores sem AVX** (ex.: Pentium Dual-Core T4500): o `onnxruntime`,
usado pelo Piper, encerra o processo com "instrução ilegal". O instalador
detecta isso e instala só o Vosk. Mesmo que o Piper esteja instalado, o TITAN
testa cada biblioteca de voz num processo separado antes de usá-la: se ela
for incompatível, a voz fica indisponível com o motivo, e o servidor continua
funcionando (`test_library_that_crashes_is_probed_in_a_separate_process`).

## Voz natural on-line (opcional, gratuita, externa)

Para uma voz parecida com a de uma pessoa (Antônio, Francisca ou Thalita), o
TITAN pode usar as vozes neurais da Microsoft pelo `edge-tts`:

```sh
sh scripts/enable_online_voice.sh        # instala edge-tts (~5 MB), pede a voz e AUTORIZO
.venv/bin/titan disable-online-voice     # volta para a voz local
```

- O **texto** de cada resposta falada vai para a Microsoft; o áudio da sua fala
  continua local (Vosk).
- É um serviço gratuito sem garantia: pode mudar ou parar sem aviso. Se falhar,
  a resposta continua por escrito e o erro aparece na tela.
- Conexão por IPv4 (como a Anthropic) e limite de 30 s por trecho.

## Medições reais (ambiente de desenvolvimento, Xeon 2,1 GHz, 4 núcleos)

| Medida | Valor |
|---|---|
| Piper: carga / memória | 2,0 s / ~196 MB |
| Piper: frase curta | 0,07 s (fator 0,09× o tempo do áudio) |
| Vosk: carga / memória adicional | 1,1 s / ~110 MB |
| Os dois carregados | ~370 MB |
| Navegador real (Chromium, microfone simulado): fim da fala → texto | 111–179 ms |
| Texto → 1º áudio (Piper) | 123–148 ms |
| Interrupção: início da fala → áudio parado | 301 ms (300 ms são a confirmação de que é fala, contra estalos) |

No notebook (3,8 GB de RAM, CPU mais lenta) os tempos serão maiores; meça na
tela "Medições desta sessão". O tempo da IA (Anthropic) se soma a isso.

## Limitações conhecidas

- O modelo **pequeno** do Vosk às vezes perde palavras, principalmente a
  primeira da frase (visto nos testes com voz sintética). Use "Revisar antes
  de enviar" quando a precisão importar. Modelos maiores (~1,6 GB) não cabem
  bem no notebook.
- A detecção de fala é por energia: ambientes muito barulhentos podem
  disparar falsos inícios. Fones de ouvido melhoram muito a interrupção.
- No celular, o microfone exige HTTPS (ver `docs/mobile.md`).
- Não testado em Android físico.
