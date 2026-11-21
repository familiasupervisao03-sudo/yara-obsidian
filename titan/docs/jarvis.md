# Funções do Jarvis (mundo real)

Três funções inspiradas no J.A.R.V.I.S., feitas com o que o TITAN já tem (casa Tuya, celular, notebook).

## 1. Clima ("Senhor, vai chover")

- **Onde:** cartão no Início; cidade em Sistema → Clima e chegada.
- **Fonte:** [Open-Meteo](https://open-meteo.com/) (grátis, sem chave). Só o nome da cidade e as
  coordenadas saem do notebook. Atualiza a cada 30 min, só para quem escolheu a cidade.
- **Aviso de chuva:** chance ≥ 60% na próxima 1h30 → mensagem no celular (uma vez por chuva;
  respeita o horário de silêncio das Mensagens do TITAN).
- **Conversa:** "vai chover amanhã?" → a IA recebe a previsão real e responde só com ela, citando a fonte.

## 2. Chegada e saída de casa

- O **app Android** percebe que você está em casa quando está no Wi-Fi **e** alcança o notebook pelo
  endereço da rede de casa (192.168…/10…). Não pede localização. Precisa dos dois endereços no app
  (QR do `titan ligar-celular --tailscale`).
- Saída só conta depois de 3 checagens seguidas sem o notebook (~3 min), para o Wi-Fi que pisca não
  virar "saiu".
- **Chegou:** "Bem-vindo de volta, senhor." + o que aconteceu enquanto estava fora (notícias novas,
  próximos lembretes de hoje). **Não liga nada** a não ser o que o dono cadastrar em "Ligar ao chegar".
- **Saiu:** "Ficaram ligados: … Desligo tudo?" → o aviso abre a tela com "Desligar tudo / Deixar".
  Só desliga se o dono tocar.

## 3. Protocolos

- Início → Protocolos: Dormir, Festa, Filme, Acordar e Lousa Limpa (+ os que o dono criar).
- Cada protocolo: aparelhos do TITAN Casa (ligar, desligar, luz baixa) e, se quiser, "silenciar avisos
  de notícias até HH:MM" (o Dormir vem com 07:00).
- **Sempre pergunta antes:** mostra a lista e espera "Executar". Lousa Limpa (desliga tudo) precisa
  **segurar** o botão.
- Falando: "Titã, protocolo dormir" → ele lista e pergunta → "sim" (até 3 min) executa, "não" cancela.
- Resultado verdadeiro: aparelho que falhar aparece como "não respondeu".

## Técnico

- Código: `titan/jarvis/` (estado, clima, serviço), rotas `/api/v1/jarvis/*`, tela
  `apps/web/src/components/JarvisCards.tsx` e `JarvisPanel.tsx`, app `NotesJob.presence`.
- Estado de cada conta numa linha própria (`memory_items`, tipo `jarvis` e `protocolos`). Aparelhos são
  conferidos pelo TITAN Casa a cada comando: aparelho de outra conta nunca é acionado.
- Migração 0010: tipos de mensagem `clima` e `casa`.
