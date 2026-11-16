// Guarda contra a tela de erro "y is not a function": um useEffect só pode devolver uma
// função de limpeza (ou nada). Escrito como `useEffect(() => algo(), ...)` ele devolve o
// resultado de algo() — e quando o navegador muda esse resultado (o Chrome novo faz
// scrollIntoView devolver uma Promise), o React tenta chamá-lo ao sair da tela e quebra.
// Regra: o corpo do efeito vai entre chaves `{ ... }` ou devolve `() => ...`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.tsx?$/.test(f) ? [p] : [];
  });
}

test("nenhum useEffect devolve algo que não seja função de limpeza", () => {
  const bad: string[] = [];
  const src = new URL("../src", import.meta.url).pathname;
  for (const f of files(src)) {
    readFileSync(f, "utf8").split("\n").forEach((line, i) => {
      if (/use(Layout)?Effect\(\s*(async\s*)?\(\)\s*=>(?!\s*(\{|\(\)\s*=>))/.test(line) || /use(Layout)?Effect\(\s*async/.test(line)) {
        bad.push(`${f.slice(src.length + 1)}:${i + 1}: ${line.trim()}`);
      }
    });
  }
  assert.deepEqual(bad, [], "use { ... } no corpo do efeito:\n" + bad.join("\n"));
});
