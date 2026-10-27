# Checklist para a Clara começar a funcionar

Criado em 27/10/2026. Marque [x] conforme for fazendo. "Eu" = Claude; "Você" = Luiz.

## Parte 1 — Ficha real do consultório (você + sua mãe) · grátis · ~1 h
- [ ] Preço de cada procedimento (ou "depende da avaliação")
- [ ] Duração de: primeira consulta, retorno, manutenção de aparelho
- [ ] Nome da doutora e nome do consultório
- [ ] Endereço completo
- [ ] Número do WhatsApp do consultório e número pessoal da doutora
- [ ] O WhatsApp do consultório é o **WhatsApp Business** ou o comum?
- [ ] Horários e dias de folga / feriados do ano
- [ ] Nome da assistente (Clara?)
- [ ] Convênios (ou só particular) e formas de pagamento
- **Eu:** preencho a ficha e rodo a simulação rápida com os dados reais (3.000+ testes, grátis). Te mando o resultado.

## Parte 2 — Chave da IA para a simulação (você) · ~US$ 5 · 20 min
- [ ] Criar conta em console.anthropic.com
- [ ] Criar um espaço (workspace) "Simulação" com limite de gasto (ex.: US$ 5)
- [ ] Criar uma chave nesse espaço
- [ ] Guardar a chave nas configurações do ambiente do Claude Code (menu do ambiente no topo da sessão → Editar → segredos/variáveis), com o nome `ANTHROPIC_API_KEY_SIMULACAO`. **Nunca colar a chave no chat.**
- **Eu:** rodo as conversas com paciente simulado por IA (10 personalidades), corrijo os erros e rodo de novo até passar.

## Parte 3 — Sua mãe testa sem WhatsApp (você + sua mãe) · grátis · 1 tarde
- [ ] No seu notebook: baixar o projeto e instalar (eu passo os comandos)
- [ ] Rodar a agenda e abrir no celular dela pela Wi-Fi
- [ ] Ela usa a agenda (marcar, aprovar, desmarcar) e conversa com a Clara no terminal fingindo ser paciente
- [ ] Anotar tudo que ela estranhar ou quiser mudar
- **Eu:** ajusto textos, regras e a agenda.

## Parte 4 — WhatsApp de teste da Meta (você) · grátis · ~1 h
- [ ] Criar conta no Meta Business (business.facebook.com) com seu Facebook
- [ ] Criar um app em developers.facebook.com (tipo "Business") e adicionar o produto WhatsApp
- [ ] Usar o **número de teste** que a Meta dá de graça; cadastrar seu celular como destinatário
- [ ] Guardar o token e o ID do número nas configurações do ambiente (eu digo os nomes). Nunca no chat.
- **Eu:** escrevo a ligação Clara ↔ WhatsApp (receber, responder, áudio, foto, lembretes) e testo com mensagens de mentira.
- **Juntos:** você conversa com a Clara pelo seu WhatsApp como se fosse paciente.

## Parte 5 — Servidor 24 h (você contrata, eu configuro) · ~R$ 40–80/mês
- [ ] Contratar um servidor pequeno (VPS) — eu indico opções e o tamanho
- [ ] (Opcional, recomendado) um domínio, ~R$ 40/ano, para o endereço da agenda
- **Eu:** instalo a Clara, a agenda, os lembretes, a transcrição de áudio, cópia de segurança do banco e HTTPS.

## Parte 6 — Ligar no número do consultório (você + sua mãe)
- [ ] Aviso de privacidade (eu escrevo) na primeira mensagem da Clara
- [ ] Conectar o número do consultório (se for WhatsApp Business, dá para manter o app no celular junto — a confirmar no Brasil)
- [ ] Criar a senha da agenda da sua mãe
- [ ] Piloto de 2 semanas: a doutora aprova tudo; vocês me contam os problemas

## Parte 7 — Treino contínuo (toda semana, ~15 min)
- [ ] Rodar `colher` (conversas da semana, sem nome e telefone)
- [ ] Revisar os arquivos marcados "olhar primeiro" e marcar como revisado
- [ ] Eu rodo a simulação com as conversas reais + paciente IA e corrijo

## Sobre não ter CNPJ
- Dá para fazer o piloto sem CNPJ: conta da Meta **não verificada** consegue usar a API oficial, com limite de ~250 pessoas por dia para mensagens que a empresa inicia (lembretes). Responder quem mandou mensagem não entra nesse limite. Para um consultório, sobra.
- Incerto: a Meta pode recusar o **nome de exibição** sem empresa verificada; e a convivência app + API (coexistência) no Brasil precisa ser confirmada. Vamos descobrir na Parte 4.
- Para **vender** para outros negócios, você vai precisar de CNPJ seu (MEI ou outro). Dentista não pode ser MEI. Qual atividade de MEI serve para você: confirmar com um contador.
