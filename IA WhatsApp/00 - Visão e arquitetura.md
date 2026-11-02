# IA WhatsApp — Visão e arquitetura

Criado em 25/10/2026. Nome do produto: **provisório**.

## O que é
Produto **separado do TITAN**. O TITAN continua sendo a IA pessoal. A IA WhatsApp é um produto para vender a negócios: atende clientes no WhatsApp, passa preços e horários, encaminha pedidos de marcação para o dono aprovar, manda lembretes e resumos.

- Primeiro cliente (piloto): consultório odontológico da mãe → [[Piloto 1 - Consultório odontológico]]
- Negócio, preço e custos → [[Plano de negócio]]

## Regra principal: pensar em escala desde o dia 1
Tudo que for feito para o consultório tem que servir para o 2º, o 10º e o 1000º cliente **sem mexer no código**.

1. **Nada fixo no código.** Horários, durações, preços, regras, nome da assistente, número do dono, textos das mensagens: tudo é **configuração de cada cliente**.
2. **Vários clientes no mesmo sistema (multi-cliente).** Cada negócio é uma "conta" separada: dados, agenda, limite de gasto e números isolados. Um cliente nunca vê nada do outro.
3. **Modelos por setor.** "Dentista" é só o primeiro modelo (regras + textos prontos). Depois: salão, oficina, loja. Novo cliente = escolher modelo + preencher a ficha.
4. **A IA conversa; o programa decide.** Agenda, conflito de horário, aprovação e lembretes são código. A IA só entende e responde.
5. **Dono aprova o que importa.** Aprovação antes de agir (herdado do TITAN) é configurável por cliente: no piloto, toda marcação passa pela doutora.
6. **Testes automáticos por modelo.** A simulação (gabarito + pegadinhas) vira bateria de testes que roda antes de cada mudança. Cliente novo herda os testes do setor.
7. **Custo medido por cliente.** Limite de gasto de IA e de WhatsApp por conta; relatório de custo x mensalidade.
8. **LGPD desde o começo.** Contrato com o cliente (eu sou operador dos dados), guardar só o necessário, apagar conversas antigas, registro de quem acessou o quê.

## Peças do sistema
| Peça | Faz o quê |
|---|---|
| Recebedor do WhatsApp | Recebe mensagens da API oficial da Meta e coloca numa fila |
| Atendente (IA) | Lê a mensagem + ficha do cliente, responde ou chama o dono |
| Transcrição de áudio | Transforma áudio em texto antes da IA ler |
| Agenda | Horários, pedidos pendentes, aprovados; checa conflito |
| Aprovações | Manda pedido ao dono (botões) e aplica a resposta |
| Agendador | Lembretes (1 h e 30 min), resumo diário (19h) |
| Painel do negócio | Agenda online + ficha (preços, horários, textos) + histórico |
| Painel admin (meu) | Criar cliente, ver custos, erros, testes |
| Banco de dados | Tudo separado por conta |

## A pesquisar antes de escalar
- Como ligar **o número de vários clientes** na API da Meta (programa *Tech Provider* / cadastro embutido, ou um parceiro BSP). Conferir requisitos e custos.
- Usar o **mesmo número** que o negócio já tem no app (coexistência app + API).
- Verificação da empresa na Meta (CNPJ).
- Cobrança recorrente dos clientes (boleto/Pix/cartão).

## Ordem
1. Fechar as regras do piloto (perguntas da rodada 2).
2. Montar o mínimo **já multi-cliente**, configurado só com o consultório.
3. Rodar a bateria de testes (simulação) até passar.
4. Ligar no WhatsApp do consultório e acompanhar 30 dias.
5. Segundo cliente de outro setor para provar que escala sem mexer no código.
