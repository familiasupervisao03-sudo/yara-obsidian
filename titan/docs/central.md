# TITAN Central — a tela da nave na TV (app irmão em /central)

Mesmo servidor, mesmo login e mesma conta do TITAN e do TITAN Casa. Mostra o seu dia,
reage à sua voz, controla a casa e avisa quando algo grave acontece com o notebook.

## Como abrir

- **Como app no menu do Linux (recomendado)**: rode uma vez `.venv/bin/titan instalar-app`.
  Aparecem **TITAN**, **TITAN Casa** e **TITAN Central** no menu. Clicou no ícone: se o servidor
  estiver desligado, ele liga sozinho em segundo plano; o app abre numa janela própria (a Central
  em tela cheia), sem aviso de cadeado. Desligar o servidor ligado pelo ícone: `.venv/bin/titan parar`.
  Para os apps confiarem no cadeado sozinhos, o comando usa o `certutil`
  (`sudo apt install libnss3-tools`, uma vez). Opcional: a Central abrir sozinha quando o notebook
  ligar (`titan instalar-app --ao-ligar`; tirar com `--nao-ao-ligar`).
- **Notebook ligado na TV pelo HDMI** (mais fácil): com o servidor ligado (`titan ligar`),
  rode `.venv/bin/titan central`. Abre em tela cheia (Alt+F4 sai).
- **TV com Android / TV box**: na página do QR (`titan ligar`), baixe o **TITAN Central (APK)**
  e toque em **CONFIGURAR A CENTRAL SOZINHA**. Ele aparece no menu de apps da TV.
- **Qualquer navegador**: `https://ENDEREÇO-DO-NOTEBOOK:8000/central`.

Mexa o mouse (ou toque) para aparecer a barra de controles; ela some sozinha.
**Espaço** = falar. **Esc** = fechar o que estiver aberto.

## O que tem

- **Ponte de comando**: hora, clima, telemetria do notebook, núcleo do TITAN, lembretes de hoje,
  metas (anéis), aparelhos da casa (toque liga/desliga) e faixa de notícias.
- **Voz**: toque no núcleo (ou Espaço) e fale. Com **Escuta contínua** ligada, ela só obedece
  frases que começam com **"Ei, Titã"**.
  - comandos da casa: "liga a luz do quarto", "liga tudo", nome das cenas (não gastam IA);
  - "holograma" / "mostra o quarto" → quarto em holograma com os aparelhos;
  - "modo missão 30 minutos" → contagem de foco;
  - "modo noite"; "sair" fecha o que estiver aberto;
  - "mostra na tela como funciona o arco-íris" → a resposta aparece grande na TV;
  - qualquer outra pergunta vai para o TITAN (conversa "TITAN Central") e ele responde falando.
- **Bom dia**: botão, "bom dia" ou a cena "bom dia" do TITAN Casa (de qualquer aparelho) →
  inicialização da nave + clima, compromissos e metas, falados.
- **📺 Na TV**: em cada resposta do TITAN no chat (celular ou notebook) tem o botão **📺 Na TV**,
  que manda a resposta para a Central.
- **Modo noite** automático das 23h às 6h (acorda 10 min com voz, toque ou alerta).
- **Modo leve** automático: se o notebook não aguentar as animações, a Central diminui sozinha.
  Forçar: `/central?leve=1` (ou `?leve=0`).

## Palavra de ativação

- **"Ei, Titã"** na Central e no TITAN Casa (a Casa também aceita "Ei, Casa").
  Separar uma palavra para cada app fica para depois.
- Com a escuta contínua desligada (tocar no núcleo / Espaço), não precisa da palavra.

## Lembretes pela Central

"Me lembra de tirar o bolo às 2:30 da tarde", "lembrete amanhã às 7 horas levar o documento",
"me avisa daqui a 10 minutos de desligar o forno": a Central entende na hora (sem IA), cria o
lembrete (o mesmo do TITAN: aparece em HOJE, no Início do app e no celular) e **avisa na hora**
na tela e falando. Lembretes criados pelo celular também tocam na Central. Sem hora na frase,
o pedido vai para a IA do TITAN.

## Velocidade (notebook fraco)

- A resposta da IA é **falada frase a frase** enquanto ainda chega (não espera a resposta inteira).
- Com 2 núcleos ou menos, a Central já começa no **modo leve** (animação em meia resolução,
  20–30 quadros/s).
- Com a Groq ligada, o Vosk **não roda mais ao vivo** (poupa o processador); só entra se a
  Groq falhar. Para ver o texto parcial mesmo assim: `TITAN_VOICE_LOCAL_PARTIALS=true`.
- A Groq recebe uma **lista de nomes** (aparelhos, cenas, "Titã") para acertar mais; se ela só devolver a lista (áudio fraco), a fala é ignorada.
- Embaixo da resposta aparece quanto tempo levou cada etapa (**ouvir · pensar · voz**), para
  achar onde está a demora.
- **⌨ Digitar** na barra de baixo: escreve o comando em vez de falar.

## Alertas críticos (só o que é grave)

Lembrete não é alerta. Alerta é o que, se continuar, derruba o TITAN:

| Alerta | Quando | De onde vem |
|---|---|---|
| Superaquecimento | processador ≥ 85 °C em 2 leituras seguidas | sensor do processador (`/sys/class/hwmon`) |
| Sobrecarga do processador | ≥ 90% por ~1 minuto | `/proc/stat`; mostra o programa que mais usa |
| Bateria aquecendo | bateria ≥ 48 °C | só se o notebook informar a temperatura da bateria |
| Carregador puxando demais | tomada do carregador ≥ 90 W | tomada inteligente (TITAN Casa) com ícone "carregador" ou "notebook" |
| Limite de gasto da IA | ≥ 90% (laranja) / 100% (vermelho) do orçamento de hoje | o próprio controle de gasto do TITAN |

Cada alerta mostra o gráfico dos últimos minutos com a linha do limite e **o que fazer**.
A Central **não desliga nada sozinha**: quando há tomada do carregador, aparece um botão
para você desligá-la. O notebook não tem sensor de temperatura do **carregador**; por isso o
alerta do carregador usa a potência medida pela tomada inteligente.

A telemetria do notebook só aparece para o **dono do servidor** (contas de outras pessoas
veem o próprio dia e a própria casa, nunca a máquina).

## Clima

`.venv/bin/titan central-clima "Sua cidade"` — usa a Open-Meteo (grátis, sem chave). Só as
coordenadas da cidade saem do notebook, a cada 20 minutos. Se o TITAN estiver em modo só-local,
o comando pede AUTORIZO antes.
