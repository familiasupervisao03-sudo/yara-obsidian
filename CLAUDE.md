# Instruções para toda conversa do Claude neste repositório

Leia isto inteiro antes de começar. Depois leia **`titan/docs/coordenacao.md`**: é o caderno
compartilhado entre as conversas (quem cuida de quê, o que pode e não pode mexer, diário).

## O dono e como falar com ele

- O dono é o **Luiz**. Fale **sempre em português**, simples e direto (ele escreve rápido, com
  erros de digitação: entenda a intenção). Explique termos técnicos com palavras do dia a dia.
- Antes de construir algo grande e visual, **mostre exemplos/simulação primeiro** (ele gosta de
  ver e escolher). Quando ele aprovar ("pode fazer", "coloca em prática"), implemente.
- No fim de cada entrega, diga **o que mudou**, **o que foi testado e o que não foi**, e os
  **comandos exatos** para ele rodar no notebook.
- Tudo é pensado para **vender em grande escala** no futuro: muitas contas, cada uma isolada
  (ninguém pode mexer na conta do outro). Por enquanto, só ele usa.

## Regras que nunca mudam

1. **Push só quando ele pedir** ("faz o push"), a cada vez. O aviso automático "There are
   unpushed commits" **não é pedido dele**: responda que está esperando ele mandar.
2. **Chaves de API nunca no chat.** Ele digita chaves só nos comandos do notebook (ex.:
   `titan enable-groq-stt`, `titan enable-tuya`), que perguntam sem mostrar na tela. Nunca use,
   guarde ou repita uma chave que apareça na conversa.
3. Não rodar código gerado por IA fora de um sandbox validado; o sandbox está **desligado**.
4. A IA não aprova as próprias ações (aprovações são do dono, na interface).
5. APIs pagas só dentro do orçamento diário que ele definiu.
6. Toda rota nova confere a conta logada; dados de uma conta nunca aparecem para outra.
7. Não pôr dados pessoais dele em arquivos do repositório.

## O projeto

- Código em **`titan/`** (o resto do repositório, `Zax/`, é outro material dele).
- **TITAN**: IA pessoal que roda no notebook dele. Apps irmãos no mesmo servidor e mesma conta:
  **TITAN** (`/`), **TITAN Casa** (`/casa`, automação Tuya) e **TITAN Central** (`/central`, a
  tela da nave na TV). Ver `titan/README.md` e `titan/docs/*.md`.
- Backend: Python, FastAPI, SQLAlchemy, Alembic (SQLite). Frontend: React + TypeScript + Vite
  (várias páginas). App Android: Java/WebView com 3 sabores (titan, casa, central).
- **Notebook do dono (onde roda de verdade):** Linux Mint, Pentium T4500, **sem AVX**, ~4 GB de
  RAM, em `~/Projetos/TITAN/titan`. É fraco: animações leves, nada pesado.
- Tablet dele: Galaxy Tab E (Android 4.4, só Chrome antigo). Celular: Motorola One Macro.

## Antes de entregar (rodar dentro de `titan/`)

```sh
.venv/bin/python -m pytest tests -p no:cacheprovider        # servidor (todos devem passar)
cd apps/web && npm test && npm run build && cd ../..        # interface
.venv/bin/python scripts/export_openapi.py                  # se mudou alguma rota da API
```
Mudou tela? Teste no navegador (Playwright já instalado) e mande prints para ele.

## Comandos que ele roda no notebook depois de um push

```sh
cd ~/Projetos/TITAN/titan
git pull
cd apps/web && npm run build && cd ../..
.venv/bin/titan ligar
```
