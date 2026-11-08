# TITAN sócio: memória, metas, lembretes e mensagens

## O que tem
- **Início**: continuar conversa (ou "O TITAN te mandou"), **Minhas metas** (barra de
  progresso, somar, conversar sobre a meta, concluir, apagar), **Hoje** (lembretes e
  tarefas: tocar marca como feita; ⋯ = adiar, editar, apagar; "Ver todas") e o botão
  **Falar com o TITAN**.
- **Conversas**: fale normal — "me lembra amanhã às 7h…", "anota que preciso…",
  "vendi 2 por R$ 30" — e aparecem cartões (⏰ lembrete, ☐ tarefa, 🧠 memória,
  🎯 meta). Botão **📌 Importante**: resume a conversa e guarda na memória.
- **Memória**: tudo o que o TITAN lembra, com busca, categorias, de onde veio cada
  lembrança, editar/apagar, "Ensinar algo", "Apagar tudo" e **Me conta de você**
  (perguntas seguras, uma por vez).
- **Sistema → Mensagens do TITAN**: bom dia, boa noite, papo solto (1 a 3 por dia),
  acompanhamento de assuntos em aberto, conversa de sócio no domingo, horário de
  silêncio e "guardar sozinho as coisas simples".

## Como o "cérebro" funciona
1. Antes de responder, o TITAN busca na memória o que tem a ver com a mensagem (palavras
   em comum), mais as metas e os assuntos em aberto, e envia isso como DADOS junto
   com a conversa (nunca a memória inteira).
2. Depois de responder, uma chamada curta à IA lê só a última troca e devolve JSON:
   lembretes, tarefas, lembranças, assuntos resolvidos e avanço de metas.
3. Lembranças novas ficam **esperando aprovação** (a menos que "guardar sozinho"
   esteja ligado). Mudou algo? A sugestão substitui a lembrança antiga ao ser aprovada.
4. Assunto em aberto ("microfone com chiado") → o TITAN pergunta depois como ficou.
5. Lembranças que não aparecem há 120 dias vão para "Antigas" (continuam visíveis).

Use um modelo barato para o cérebro (roda depois de cada mensagem). No `.env`:
```
TITAN_BRAIN_MODEL_NAME=claude-haiku-5-5
```

## O que nunca é guardado
Documentos (CPF, RG), telefone, e-mail, endereço/CEP/bairro, nome da escola,
localização, senhas e códigos, dados de banco/cartão/Pix, chaves de API, saúde,
intimidade, brigas de família e dados de outras pessoas. Vale para o que a IA sugere,
para as respostas das perguntas e até para o que você digita em "Ensinar algo"
(`titan/brain/safety.py`).

## Onde fica
No banco do notebook, `var/titan.db` (tabelas `brain_memories`, `goals`, `todos`,
`titan_notes`). A pasta `var/` não vai para o GitHub. Os backups (`titan backup`)
incluem a memória.

## Avisos no celular
- **Lembretes com hora**: o app Android (1.1+) agenda no próprio celular — toca na hora
  mesmo com o notebook desligado, e volta a agendar depois de reiniciar o aparelho.
- **Mensagens do TITAN**: o servidor cria (agendador a cada minuto) e o app (1.7+) confere a
  cada minuto, mesmo fechado (aviso fixo "TITAN conectado"; alarme reserva a cada ~10 min).
  Precisa do notebook ligado, rede (Wi-Fi ou Tailscale) e login válido no app.
- **Login**: vence depois de `TITAN_SESSION_TTL_HOURS` (padrão 12 h) **sem uso**; cada uso renova.
  Mesmo em uso, pede a senha de novo 30 dias depois de entrar.
- **Sistema → Avisos** (app 1.8+): mostra o que está ligado/desligado, a última conferência com o
  notebook e tem o botão **Testar aviso**.
