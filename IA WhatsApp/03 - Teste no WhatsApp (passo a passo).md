# Teste da Clara num WhatsApp de teste — passo a passo

Criado em 02/11/2026. Nada aqui usa o número do consultório.

**Quem é quem no teste**
- Clara: número de teste grátis da Meta
- Paciente: celular de teste do Luiz, (88) 98142-2707
- "Doutora": celular do Luiz, (88) 98214-7030 (recebe pedidos e avisos)

## Parte A — Meta (no celular ou computador, ~20 min)
1. Entrar em **developers.facebook.com** com o Facebook.
2. **Meus apps → Criar app**. Caso de uso: WhatsApp / conectar com clientes. Tipo: **Empresa**. Nome: "Clara teste".
3. No app, abrir **WhatsApp → Configuração da API** (API Setup).
4. Nessa tela, anotar (NÃO mandar no chat):
   - o **número de teste** (campo "De"/From);
   - o **Phone number ID** (número grande, abaixo do número de teste) — esse pode mandar no chat, não é segredo;
   - o **token de acesso temporário** (dura 24 h) — segredo.
5. No campo **"Para"** (To): adicionar **5588981422707** e **5588982147030**. Cada um recebe um código no WhatsApp para confirmar.
6. **Configurações do app → Básico → Chave secreta do app**: anotar — segredo.

## Parte B — Notebook (o Claude guia ao vivo)
1. Baixar o projeto e instalar.
2. Guardar os segredos (token, chave secreta e uma senha inventada).
3. Ligar a Clara: `python -m atendente servidor`.
4. Abrir um "túnel" para a Meta enxergar o notebook (cloudflared), que dá um endereço https.
5. Na Meta: **WhatsApp → Configuração → Webhook**: colar o endereço + `/webhook` e a senha inventada; marcar **messages**.

## Parte C — Testar
1. Do celular "doutora" (98214-7030), mandar "oi" para o número de teste (abre a janela de 24 h para ela receber avisos).
2. Do celular "paciente" (98142-2707), conversar com a Clara: preço, endereço, marcar, foto, áudio, urgência...
3. No celular "doutora", aprovar com SIM <número>, testar DEVOLVER.
4. Anotar tudo que estranhar.

## Observações
- O token temporário vence em 24 h; para testes mais longos, criar um token permanente (o Claude explica).
- Mensagens para a doutora quando ela não fala com o número há 24 h precisam de um **modelo aprovado** na Meta. No teste, basta ela mandar "oi" antes.
