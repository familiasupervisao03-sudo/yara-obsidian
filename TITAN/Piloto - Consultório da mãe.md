# TITAN — Piloto no consultório da mãe

Criado em 25/10/2026. Status: **regras principais decididas em 25/10; faltam detalhes (ver "Perguntas da rodada 2").**

## Ideia
- IA no WhatsApp atende pacientes 24 h, responde dúvidas e marca horário.
- Agenda digital única: presencial e WhatsApp marcam no mesmo lugar.
- Horário ocupado → IA avisa e oferece outros horários livres.
- Horário livre → pede confirmação para a doutora.
- Resumo para a doutora; aviso para a doutora antes de cada paciente.

## Decidido (25/10/2026)
- **Dentista.** Agenda hoje é de papel → vamos criar uma **agenda online**.
- **A IA nunca marca sozinha.** Todo pedido de marcação vira um pedido para a doutora aprovar.
- **Dois WhatsApp:** o número atual do consultório é o que a IA usa para atender; o outro número (pessoal da doutora) recebe os avisos, pedidos de aprovação e o resumo.
- **Duração:** primeira consulta e retorno são diferentes; média de 1 hora por enquanto.
- **Remarcar, cancelar e marcar retorno: só a doutora.** A IA só avisa a doutora.
- **Pode informar preço** de cada procedimento.
- **Horário:** segunda a sexta, 8h–12h e 14h–17h; fim de semana 8h–12h.
- **Avisos para a doutora:** 1 h e 30 min antes de cada paciente.
- **Aviso para o paciente:** 1 h antes (não um dia antes).
- **Resumo do dia para a doutora:** todo dia às 19h.
- **Assistente virtual com nome** — ela se apresenta assim logo na primeira mensagem.
- **Áudio:** a IA transcreve e lê. Se for marcar, pagar ou algo da doutora → avisa o paciente que vai chamar a doutora e avisa a doutora. Se for dúvida simples → responde normal.
- **Foto/exame:** exame → chama a doutora. Foto comum → a IA responde.

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

## Perguntas da rodada 2
1. Fim de semana: sábado **e** domingo, 8h–12h? Feriado atende?
2. Duração exata: primeira consulta = ? Retorno = ?
3. Como a doutora aprova? (proposta: mensagem no WhatsApp pessoal com botões Aprovar / Recusar / Outro horário)
4. Enquanto espera a doutora, o horário fica segurado para esse paciente? Se outro pedir o mesmo horário, a IA diz que está ocupado?
5. Se a doutora não responder em X horas, o que a IA diz ao paciente?
6. Tabela de preços: lista com valores. Procedimentos que dependem de avaliação: mostrar "a partir de R$ X, valor final depois da avaliação"?
7. Pagamento: a IA pode mandar chave Pix? (recomendação: não — sempre a doutora)
8. Fotos: considerar **toda** foto de boca/dente/rosto como clínica e chamar a doutora? (recomendação: sim)
9. Urgência odontológica (dor forte, inchaço, dente quebrado, sangramento): avisar a doutora na hora + mensagem padrão?
10. O WhatsApp do consultório é o WhatsApp Business ou o normal? O consultório tem CNPJ?
11. Tem secretária ou só a doutora mexe na agenda?
12. Nome da doutora e do consultório (para a apresentação).
13. Nome da assistente.
14. Resumo das 19h também no fim de semana?

## Sugestões de nome da assistente
Clara · Sofia · Lia · Bia · Luna

## Modelos de mensagem (rascunho)
- **Primeira mensagem:** "Olá! Eu sou a Clara, assistente virtual do consultório da Dra. [Nome]. Posso te passar valores, horários e endereço, e encaminhar seu pedido de consulta para a doutora. Como posso te ajudar?"
- **Pedido de marcação (horário livre):** "Anotei seu pedido para quarta, 15h. Vou enviar para a Dra. [Nome] confirmar e te aviso aqui assim que ela responder."
- **Horário ocupado:** "Esse horário já está preenchido. Tenho livre quarta às 16h ou quinta às 15h. Algum desses serve?"
- **Chamar a doutora:** "Esse assunto a própria doutora resolve com você. Já avisei a Dra. [Nome] e ela vai te responder por aqui."
- **Lembrete ao paciente (1 h antes):** "Oi, [Nome]! Lembrando da sua consulta hoje às 15h com a Dra. [Nome]. Até já!"
- **Pedido para a doutora:** "Novo pedido: [Paciente], [telefone], primeira consulta, quarta 15h. Aprovar / Recusar / Outro horário"

## Perguntas da rodada 1 (respondidas em 25/10)
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
