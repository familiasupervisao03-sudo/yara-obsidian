# TITAN — Plano: atendente de WhatsApp para pequenos negócios

Criado em 25/10/2026. Status: **antes de programar — fase de entrevistas.**

## Decisões
- Evitar: IA geral (concorrer com ChatGPT/Gemini) e áreas reguladas (saúde, jurídico, finanças). **Clínica sai da lista** (dado de saúde = LGPD sensível).
- Nicho: **a escolher** (ver critérios abaixo).
- Critério para construir: **3 ou mais donos aceitam um piloto pago** (pagar o 1º mês adiantado ou deixar um sinal). Dizer só "eu pagaria" não conta.

## Critérios para escolher o nicho (nota de 1 a 5 em cada)
1. Recebe muita pergunta repetida (preço, horário, endereço)?
2. O dono está de mão ocupada quando a mensagem chega?
3. Perder 1 cliente custa caro (ticket alto)?
4. As respostas cabem numa ficha (preço fixo)? Orçamento "depende de ver" = ruim para robô.
5. Já existe app dominante no setor? (salão/barbearia: Trinks, Booksy, AppBarber e vários robôs a R$ 90–190; pizzaria: iFood)
6. Eu conheço donos desse setor pessoalmente?

## Roteiro de entrevista (15 min, sem vender nada)
Perguntar sobre o que **já aconteceu**, não sobre o que fariam:
1. Me conta como funciona o atendimento no WhatsApp hoje. Quem responde?
2. Pode abrir o WhatsApp e ver quantas conversas de cliente teve ontem? (contar junto)
3. Quais são as 3 perguntas que mais chegam?
4. Qual o horário mais difícil para responder? O que acontece com as mensagens nessa hora?
5. Lembra da última vez que perdeu um cliente por demora? O que aconteceu? Quanto valia esse cliente?
6. Já tentou resolver isso? (resposta automática, funcionário, app, robô) Quanto pagou? Por que parou?
7. Quanto vale um cliente novo para você, em média?
8. **No final:** "Estou montando isso. O piloto custa R$ X no primeiro mês e eu configuro tudo com você. Quer ser um dos 3 primeiros?" — anotar a reação exata.

Anotar por entrevista: setor, conversas/dia, perguntas mais comuns, perdeu cliente? (sim/não, quanto), já paga ferramenta? (quanto), aceitou piloto? (sim/não/talvez).

## Custos estimados por negócio (outubro/2026 — conferir antes de cobrar)
Cenário: ~600 conversas/mês (20/dia), ~8 respostas por conversa. Dólar ~R$ 5,50 (aproximado).

| Item | Estimativa/mês | Observação |
|---|---|---|
| IA — Claude Haiku 5.5 (US$ 0,10 / 0,50 por milhão de tokens) | ~R$ 10–15 | Se usar Haiku 4.5 (US$ 1 / 5) fica ~10x mais: ~R$ 130. **Conferir qual Haiku o TITAN usa.** |
| WhatsApp — responder cliente que escreveu primeiro | R$ 0 (a confirmar) | Fontes divergem sobre cobrança de mensagens de serviço a partir de 1/10/2026. Conferir na tabela oficial da Meta. |
| WhatsApp — lembretes de horário (utilidade) | ~R$ 0,035–0,05 cada → ~R$ 10–15 para 300 lembretes | |
| WhatsApp — marketing/promoção | ~R$ 0,32 cada | Evitar no começo. |
| Servidor (VPS) | R$ 40–80 no total | Dividido entre clientes; no começo pago sozinho. |
| Chip/número (se o negócio quiser número separado) | ~R$ 20 | |
| MEI/CNPJ (DAS) | ~R$ 80 no total | Ajuda na verificação da Meta e para emitir nota. |
| **Custo direto por negócio** | **~R$ 30–50** | O custo maior é o **meu tempo** de configuração e suporte. |

## Concorrência (preços anunciados, 2026)
RobotiZap R$ 89,90 · WSeller a partir de R$ 97 · Atenndo.IA Beauty R$ 89,90–190 + instalação · Zaia a partir de R$ 150 · GPT Zendra a partir de R$ 387 · Assis a partir de R$ 600.

**Diferencial possível:** não é a tecnologia, é o **atendimento próximo** — eu vou até o negócio, configuro, ajusto e respondo no WhatsApp quando algo der errado.

## Preço sugerido para testar
- Instalação: R$ 300–500 (inclui montar a ficha do negócio junto com o dono).
- Mensalidade: R$ 150–250.
- Piloto: 1º mês com desconto, **pago adiantado**.

## O que o TITAN precisa ganhar para virar produto
**Reaproveita:** conversa com Claude, limite de gasto (agora por cliente), aprovação antes de agir, auditoria, painel web.
**Fica de fora no produto:** voz (Vosk), pesquisa na internet (o robô só responde com a ficha do negócio).

1. Rodar num servidor 24h (o notebook não aguenta nem fica ligado sempre).
2. Ligar com a API oficial do WhatsApp (Cloud API da Meta: webhook para receber, envio para responder).
3. **Ficha do negócio** que o dono edita no painel: serviços, preços, horários, endereço, regras.
4. **Nunca inventar preço:** se não está na ficha, responde "vou confirmar com o responsável" e avisa o dono.
5. **Passar para humano:** botão/comando para o dono assumir a conversa.
6. Agenda: marcar, remarcar e cancelar (começar simples; Google Agenda depois).
7. Vários negócios no mesmo sistema, cada um separado (dados, limite de gasto, número).
8. LGPD: aviso de privacidade, guardar só o necessário, apagar conversas antigas.
9. Relatório simples para o dono: quantas conversas, quantos horários marcados, perguntas sem resposta.

## Ordem
1. Escolher nicho (esta semana).
2. 5–10 entrevistas (2 semanas).
3. Se 3+ aceitarem piloto pago: montar o mínimo (itens 1–5) para 1 negócio.
4. Rodar 30 dias com 1–3 pilotos, medir, ajustar.
5. Só então agenda, relatórios e mais clientes.

## Fontes
- Preços WhatsApp Brasil: https://www.flowcall.co/blog/whatsapp-business-api-pricing · https://help.manychat.com/hc/en-us/articles/14281380243740-WhatsApp-pricing-guide · https://whautomate.com/whatsapp-business-api-pricing-brazil · https://blueticks.co/blog/whatsapp-business-api-pricing-2026
- Concorrentes: https://www.robotizap.com/sistema-de-agendamento-salao-de-beleza-whatsapp/ · https://wseller.co/vendedor-ia-whatsapp-salao-beleza/ · https://www.zaia.app/casos/saloes-de-beleza/ · https://atenndoia.com.br/beauty.html · https://gptzendra.com/ · https://assis.co/blog/ia-para-salao-de-beleza
