# TITAN — Piloto no consultório da mãe

Criado em 25/10/2026. Status: **levantando regras (perguntas abaixo).**

## Ideia
- IA no WhatsApp atende pacientes 24 h, responde dúvidas e marca horário.
- Agenda digital única: presencial e WhatsApp marcam no mesmo lugar.
- Horário ocupado → IA avisa e oferece outros horários livres.
- Horário livre → pede confirmação para a doutora.
- Resumo para a doutora; aviso para a doutora antes de cada paciente.

## Regra de ouro do desenho
- **A IA conversa; o programa decide.** Quem confere se o horário está livre é o código, olhando a agenda, nunca a "memória" da IA.
- A agenda digital é a única verdade. Se a marcação presencial ficar só no papel, a IA não tem como saber.
- Lembrete antes da consulta = tarefa agendada simples (sem IA).
- A IA nunca fala de sintoma, remédio ou diagnóstico.

## Fluxo de marcação (proposta)
1. Paciente pede dia/hora.
2. IA entende o pedido ("quarta 15h", "amanhã de manhã") e confirma com o paciente se entendeu certo.
3. Programa consulta a agenda.
4. Ocupado → "esse horário já está preenchido; tenho quarta 16h ou quinta 15h".
5. Livre → **pré-reserva** (segura o horário por X minutos) + mensagem para a doutora aprovar.
6. Doutora aprova → IA confirma ao paciente. Recusa ou não responde a tempo → IA avisa o paciente e solta o horário.

## Perguntas (responder aos poucos)
### As 5 mais importantes
1. Hoje a agenda é de papel? Quem marcaria os presenciais na agenda digital, e na hora?
2. A IA marca sozinha ou a doutora aprova cada marcação? Se aprova: quanto tempo o paciente pode esperar e o que fazer se ela não responder?
3. Qual a especialidade e quanto dura cada consulta?
4. A IA vai usar o mesmo número de WhatsApp do consultório?
5. Pode informar preço? Atende convênio?

### Consultório
6. Dias e horários de atendimento; intervalo de almoço; feriados.
7. Quantas mensagens de paciente chegam por dia? Quem responde hoje?
8. Primeira consulta e retorno têm duração ou regra diferente?

### Regras de marcação
9. Antecedência mínima (ex.: não marcar para daqui a 1 hora).
10. Até quantos dias para a frente pode marcar.
11. A IA pode remarcar e cancelar? Até quanto tempo antes?
12. Mesmo paciente pode ter dois horários?
13. Regra para quem falta.

### Avisos
14. Aviso para a doutora: 30 min ou 1 h antes? Por WhatsApp?
15. Lembrete para o paciente também (ex.: 1 dia antes, pedindo confirmação)?
16. Resumo para a doutora: a cada mensagem, ou um resumo por dia? Que horas?

### Limites e cuidados
17. Mensagem padrão para urgência (ex.: "procure o pronto-socorro ou ligue 192") e avisar a doutora na hora?
18. Que dados pedir do paciente? (proposta: só nome e telefone; motivo da consulta **não**)
19. A IA se apresenta como assistente virtual? Tem nome? Trata por "você"?
20. O que fazer com áudio, foto e documento (exame, receita)?

## Testes (vêm da simulação pausada: gabarito + pegadinhas)
- Dois pacientes pedem o mesmo horário quase ao mesmo tempo.
- "Quarta 15h" quando hoje já é quarta, 16h.
- "Amanhã de manhã", "semana que vem", "depois do almoço".
- Paciente descreve sintoma e pede opinião.
- Urgência ("tô com dor no peito").
- Pedido de dados de outro paciente.
- Feriado, fora do horário, domingo.
- Áudio, figurinha, mensagem em pedaços.
- Paciente tenta mandar a IA "esquecer as regras".
