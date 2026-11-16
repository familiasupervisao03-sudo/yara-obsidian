# Temas visuais do TITAN

Todo o visual sai de **variáveis** (cores, fontes, brilho, formato dos cantos,
fundo). Os componentes e o `styles.css` só usam essas variáveis.

- `futurista.css` — padrão: HUD neon, vidro, cantos cortados, grade hexagonal.
- `classico.css` — o visual grafite anterior (mais sóbrio).
- `themes.ts` — lista de temas mostrada em **Sistema → Aparência**, o "modo leve"
  e a aplicação no `<html data-theme="…">`.

## Criar um tema novo

1. Copie `classico.css` (ou `futurista.css`) para `meutema.css`.
2. Troque o seletor para `:root[data-theme="meutema"]` e ajuste os valores.
   Opcional: no fim do arquivo, decorações só desse tema
   (`:root[data-theme="meutema"] .orb { … }`).
3. Importe o arquivo em `src/main.tsx` e acrescente `{ id: "meutema", nome: "Meu tema" }`
   em `THEMES` (`themes.ts`).

## Variáveis principais

| Variável | Para quê |
|---|---|
| `--bg`, `--surface`, `--surface-2`, `--surface-3` | fundo e superfícies |
| `--text`, `--muted` | texto principal e secundário |
| `--accent`, `--accent-rgb`, `--accent-strong`, `--accent-ink` | cor de destaque (e versão em números, para transparências) |
| `--user`, `--user-rgb` | cor das suas mensagens e da sua voz |
| `--ok`, `--warn`, `--bad` | estados |
| `--font-ui`, `--font-hud` | fonte do texto e dos rótulos de painel |
| `--radius`, `--radius-sm` | arredondamento |
| `--clip`, `--clip-sm` | formato dos painéis e botões (`none` = retângulo normal) |
| `--glow`, `--glow-text` | brilho em botões, abas e títulos (`none` desliga) |
| `--app-bg` | fundo da tela (degradês, grade) |
| `--scan` | intensidade das linhas de varredura (0 = sem) |
| `--panel-bg`, `--panel-stripe` | fundo dos painéis e a faixa de luz no canto |
| `--brand-spacing` | espaçamento das letras do nome TITAN |

O **modo leve** (`<html data-leve>`) desliga brilhos, fundo decorado e
animações, para aparelhos mais fracos.
