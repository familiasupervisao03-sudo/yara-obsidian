# TITAN Central — plano guardado (ainda não implementado)

App irmão do TITAN e do TITAN Casa ("mesma mãe"): a **tela da nave** na TV do quarto.
Mesmo servidor, mesmo login, tudo interligado. Simulação aprovada: `simulacao.html`
(abra no navegador; botões 1–7 ou teclas). Só demonstração, com dados de mentira.

## O que foi aprovado
- **Ponte de Comando** (tela principal): hora, clima, telemetria, núcleo do TITAN no meio,
  lembretes, metas, aparelhos da casa, faixa de notícias.
- **Reage à voz**: "Ei, Titã" → núcleo cresce, onda de voz, legenda do que você disse,
  resposta digitando; aparelhos mudam no painel.
- **Briefing de bom dia**: inicialização da nave + clima, compromissos e cena "bom dia".
- **Quarto em holograma**: planta 3D neon do quarto com os aparelhos acendendo.
- **Mostra na tela**: gráficos/explicações pedidos por voz aparecem na TV.
- **Modo missão** (foco com contagem) e **modo noite** (estrelas, hora fraquinha).
- **Alertas só para coisa grave** (o que pode derrubar o TITAN), com gráfico dos últimos
  10 min, linha de limite, valor ao vivo e "o que o TITAN já fez":
  - superaquecimento do notebook (temperatura do processador);
  - bateria/carregador aquecendo (carregador: pela potência da tomada Tuya, o notebook
    não tem sensor do carregador; bateria: só se o notebook expuser a temperatura);
  - sobrecarga do processador;
  - limite de gasto da IA (laranja = atenção máxima).
  Lembretes comuns NÃO são alerta.

## Quando for implementar
- App próprio "TITAN Central" (como o Casa: rota no servidor + APK/PWA), ligado ao TITAN.
- Animações leves (o notebook é fraco: Pentium T4500, 4 GB, sem AVX).
- Perguntar ao dono: a TV é smart ou só HDMI.
