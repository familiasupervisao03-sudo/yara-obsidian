# App Android do TITAN

Uma "janela" para o TITAN do notebook: **o servidor continua sendo um só, o do
notebook**. O app não guarda conversas nem chaves; ele abre a interface do servidor.

## Instalar no celular

1. No notebook: `.venv/bin/titan ligar-celular` e siga a página de instalação pelo
   QR code (instale o **cadeado**).
2. Na mesma página, toque em **BAIXAR O APP (APK)** e instale. O Android pede para
   permitir instalar apps "desta origem": permita para esta instalação.
3. Abra o app e digite o endereço mostrado (ex.: `https://192.168.0.10:8000`).
   Para trocar depois: segure o ícone → **Servidor**.

O APK também fica em `apps/web/public/titan.apk` (e o TITAN o serve em `/titan.apk`).

## O que o app faz

- Só abre `https://`; certificado inválido **não abre** (nunca "continuar mesmo assim").
  Confia no sistema e no cadeado do TITAN instalado em Configurações.
- Microfone e câmera só para o próprio servidor (o Android pergunta na 1ª vez).
- Links de fora (fontes, aulas) abrem no navegador.
- Compartilhar → TITAN, atalhos no ícone (Falar, Nova conversa, Nova aula, Servidor).
- Tela acesa durante a voz e avisos do sistema, pela ponte `TitanAndroid`
  (`apps/web/src/notify.ts`).

## Gerar o APK de novo (só quando o app mudar)

A interface vem do servidor, então mudanças na tela **não** exigem APK novo.

Precisa do Android SDK (platforms;android-34, build-tools;34.0.0), Java 17+ e Gradle 8.9+:

```sh
cd apps/android
echo "sdk.dir=/caminho/do/android-sdk" > local.properties
TITAN_KEYSTORE=/caminho/titan-release.jks TITAN_KEYSTORE_PASS=... gradle assembleRelease
cp app/build/outputs/apk/release/app-release.apk ../web/public/titan.apk
```

**Chave de assinatura:** fica fora do repositório (`*.jks` está no `.gitignore`).
Guarde o arquivo e a senha: um APK novo só instala por cima do antigo se for
assinado com a mesma chave. Sem ela, desinstale o app antigo antes (o app só
guarda o endereço do servidor).
