# TITAN Casa — central da casa (app irmão do TITAN)

Abra no tablet: **`https://ENDEREÇO-DO-NOTEBOOK:8000/casa`** (o mesmo do TITAN, com `/casa`
no fim). No Chrome do tablet: menu ⋮ → **Instalar app** → vira o ícone **TITAN Casa**,
em tela cheia e deitado. Mesmo login, mesma voz e mesmo servidor do TITAN.

- **PAINEL**: toque liga/desliga; ⋯ (ou segurar) abre os controles (brilho, ar, controle da TV).
  O núcleo de voz fica à direita: toque e fale, ou digite. **Escuta contínua** (opcional):
  o tablet fica ouvindo e só obedece quando a frase começa com "Ei, Titã".
- **CENAS**: criar, editar, apagar e rodar. Cada aparelho: ligar, desligar ou não mexer
  (luz: "baixinha"; ar: temperatura). Frases de voz e a resposta do TITAN.
- **AJUSTES**: PROCURAR NOVOS, TESTAR (a tomada pisca 2 vezes), dar nome, ícone, cômodo
  e apelidos de voz; esquecer aparelho.
- No **TITAN normal** (chat ou voz), "liga o ventilador" também funciona (sem gastar IA).

Sem a Tuya ligada, o TITAN Casa fica em **DEMONSTRAÇÃO** (aparelhos de mentira) para testar.

## Ligar os seus aparelhos (Tuya / Smart Life)

1. Os aparelhos precisam estar no app **Smart Life** (ou Tuya Smart). TV e ar: dentro do
   aparelhinho de infravermelho, adicione **TV** e **Ar-condicionado** escolhendo a marca.
2. Crie uma conta grátis em **https://platform.tuya.com** (Tuya Developer Platform).
3. **Cloud → Development → Create Cloud Project**: setor *Smart Home*, método *Smart Home*,
   **data center: Western America** (contas do Brasil; se os aparelhos não aparecerem, tente
   *Central Europe* e use `eu`).
4. Na tela de serviços, mantenha **IoT Core** e **Authorization Token Management** e adicione
   **IR Control Hub Open Service** (para TV e ar).
5. No projeto: **Devices → Link App Account → Add App Account**. Aparece um QR code: no
   Smart Life, **Eu → ícone de escanear** (canto de cima) → confirme. Os aparelhos aparecem
   na lista do projeto.
6. Em **Overview**, copie o **Access ID/Client ID** e o **Access Secret/Client Secret**.
7. No notebook:
   ```sh
   .venv/bin/titan enable-tuya     # pede o ID, o Secret (oculto), o centro de dados e AUTORIZO
   .venv/bin/titan tuya-teste      # só lista os aparelhos (não mexe em nada)
   .venv/bin/titan ligar
   ```
8. No tablet: **AJUSTES → PROCURAR NOVOS** e cadastre cada um.

O plano grátis da Tuya (IoT Core) vale por um período e precisa ser **renovado** no site
(*Cloud → Cloud Services → IoT Core → Extend Trial Period*). Se os comandos pararem de
funcionar com erro de permissão, é isso. Para vender em escala, contrata-se o plano pago.

Voltar para a demonstração: `.venv/bin/titan disable-tuya`.

## Segurança e muitas casas
- Cada usuário tem a **sua casa**; todo comando confere se o aparelho é daquela casa (o app
  nunca manda o id do aparelho na Tuya, só o nosso). Outra conta recebe "não encontrado".
- A casa fica **travada na conta Tuya** dela; se o projeto tiver mais de uma conta ligada,
  o TITAN recusa misturar.
- Limite de comandos por minuto por casa (`TITAN_CASA_MAX_COMMANDS_PER_MINUTE`, padrão 40)
  e **registro** de cada comando (quem, de onde: toque, voz, cena ou chat; deu certo?).
- O Access Secret fica só no `.env` do notebook (permissão 600).

## Limitações conhecidas
- A conexão com a Tuya foi feita seguindo a documentação oficial e testada com uma Tuya
  simulada; os comandos de **infravermelho** (TV e ar) podem precisar de ajuste ao testar
  com o seu aparelho real (os nomes de botões variam por marca).
- Por enquanto tudo vai pela nuvem da Tuya (precisa de internet no notebook). Controle
  direto pela Wi-Fi (sem nuvem) é o próximo passo.
- A escuta contínua manda cada fala detectada para o reconhecimento do TITAN (Groq/Vosk).
