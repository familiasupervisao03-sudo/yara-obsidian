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

## Reconhecimento on-line pela Groq (opcional, externo, grátis no plano gratuito)

O Vosk pequeno erra bastante em português. O Whisper da Groq entende muito melhor.

1. Crie uma conta em <https://console.groq.com> (o plano grátis não pede cartão) e
   gere uma chave em **API Keys** (começa com `gsk_`).
2. No notebook:
   ```sh
   .venv/bin/pip install -e ".[groq]"
   .venv/bin/titan enable-groq-stt      # pede o teto diário, a chave (oculta) e AUTORIZO
   .venv/bin/titan ligar
   ```

Como funciona:
* Enquanto você fala, o **Vosk** mostra o texto parcial (nada sai do notebook).
* Ao terminar a fala, o áudio dela (WAV em memória) vai **uma vez** para a Groq; o
  texto da Groq substitui o do Vosk. Silêncio e falas curtíssimas não são enviados.
* Se a Groq falhar (sem internet, chave recusada, limite deles ou o teto diário do
  TITAN em `TITAN_VOICE_CLOUD_MAX_MINUTES_DAY`), o texto do **Vosk** é usado.
* Frases que o Whisper inventa com ruído ("Legendas pela comunidade Amara.org"…) são ignoradas.
* Custo: no plano grátis, zero (ao passar do limite deles, o Vosk assume). Com cartão
  cadastrado, ~US$ 0,04 por hora de fala, com mínimo de 10 s por fala.
* Desligar: `.venv/bin/titan disable-groq-stt` (remove a chave do `.env`).

### Alternativa: xAI (Grok Speech to Text)

Se você já tem créditos na xAI (console.x.ai), dá para usar o reconhecimento do Grok
no lugar da Groq. Funciona do mesmo jeito (Vosk de reserva, silêncio não é enviado),
mas é pago pelos créditos: ~US$ 0,10 por hora de fala (~R$ 0,01 por minuto).

```sh
.venv/bin/pip install -e ".[groq]"   # mesma biblioteca (httpx)
.venv/bin/titan enable-xai-stt       # chave começa com xai-; pede AUTORIZO
.venv/bin/titan ligar
```
Desligar: `.venv/bin/titan disable-xai-stt`.

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
