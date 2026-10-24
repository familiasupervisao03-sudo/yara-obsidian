// Aprendizado explícito: quando a pessoa corrige o texto entendido (modo revisão),
// sugere guardar a troca no dicionário dela. Nada é guardado sem confirmação.

export interface CorrectionSuggestion {
  heard: string;
  meant: string;
}

const norm = (w: string) => w.toLowerCase().replace(/[^\p{L}\p{N}'-]/gu, "");

/** Compara o texto entendido com o corrigido: se houve UMA troca curta (até 4 palavras
 *  de cada lado), devolve a sugestão; senão (reescrita grande, só pontuação), nada. */
export function suggestCorrection(heardText: string, editedText: string): CorrectionSuggestion | null {
  const a = heardText.trim().split(/\s+/).filter(Boolean);
  const b = editedText.trim().split(/\s+/).filter(Boolean);
  let start = 0;
  while (start < a.length && start < b.length && norm(a[start]) === norm(b[start])) start++;
  let endA = a.length, endB = b.length;
  while (endA > start && endB > start && norm(a[endA - 1]) === norm(b[endB - 1])) { endA--; endB--; }
  const heard = a.slice(start, endA).map(norm).join(" ");
  const meant = b.slice(start, endB).join(" ").replace(/[.,!?;:]+$/, "");
  if (!heard || !meant || heard === norm(meant)) return null;
  if (endA - start > 4 || endB - start > 4) return null;
  return { heard, meant };
}
