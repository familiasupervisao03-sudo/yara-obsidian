// Divide o texto que chega em streaming em frases faláveis, sem ler código,
// marcações de formatação ou links, e sem cortar frases no meio.

export interface Segment {
  text: string;
  /** Posição (em caracteres do texto original) onde este trecho termina. */
  rawEnd: number;
}

const ABBREVIATIONS = ["sr.", "sra.", "dr.", "dra.", "ex.", "p.ex.", "etc.", "obs.", "nº.", "vs."];
const SOFT_LIMIT = 180;
const HARD_LIMIT = 300;

export function cleanForSpeech(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "link")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/\*\*|__|~~/g, "")
    .replace(/(^|\s)[*_](\S)/g, "$1$2")
    .replace(/(\S)[*_](\s|$)/g, "$1$2")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+•]\s+/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/[ \t]+/g, " ")
    .trim();
}

export class SpeechSegmenter {
  private raw = ""; // texto recebido ainda não emitido (sem blocos de código)
  private consumed = 0; // caracteres do original já emitidos/descartados
  private inCode = false;
  private codeAnnounced = false;
  private pending = ""; // possível início de ``` dividido entre pedaços

  push(delta: string): Segment[] {
    let text = this.pending + delta;
    this.pending = "";
    // Uma ou duas crases no fim podem ser o começo de ``` dividido entre pedaços.
    const tail = /`{1,2}$/.exec(text);
    if (tail) {
      this.pending = tail[0];
      text = text.slice(0, tail.index);
    }
    const out: Segment[] = [];
    while (text.length) {
      const fence = text.indexOf("```");
      if (this.inCode) {
        if (fence < 0) {
          this.consumed += text.length;
          return out;
        }
        this.consumed += fence + 3;
        text = text.slice(fence + 3);
        this.inCode = false;
        continue;
      }
      const chunk = fence < 0 ? text : text.slice(0, fence);
      this.raw += chunk;
      out.push(...this.drain(false));
      if (fence < 0) break;
      // início de bloco de código: o que veio antes vira frase; o código não é lido
      out.push(...this.drain(true));
      this.consumed += 3;
      text = text.slice(fence + 3);
      this.inCode = true;
      if (!this.codeAnnounced) {
        this.codeAnnounced = true;
        out.push({ text: "O código está na tela.", rawEnd: this.consumed });
      }
    }
    return out;
  }

  flush(): Segment[] {
    this.raw += this.inCode ? "" : this.pending;
    this.pending = "";
    return this.drain(true);
  }

  private drain(force: boolean): Segment[] {
    const out: Segment[] = [];
    for (;;) {
      const cut = this.findCut();
      if (cut < 0) break;
      out.push(...this.emit(cut));
    }
    if (force && this.raw.trim()) out.push(...this.emit(this.raw.length));
    else if (force) {
      this.consumed += this.raw.length;
      this.raw = "";
    }
    return out;
  }

  private emit(cut: number): Segment[] {
    const piece = this.raw.slice(0, cut);
    this.raw = this.raw.slice(cut);
    this.consumed += piece.length;
    const text = cleanForSpeech(piece);
    return /[\p{L}\p{N}]/u.test(text) ? [{ text, rawEnd: this.consumed }] : [];
  }

  /** Índice (exclusivo) onde cortar a próxima frase, ou -1 se ainda não há frase completa. */
  private findCut(): number {
    const s = this.raw;
    const re = /[.!?…]+["')\]]*(?=\s)|\n\s*\n|:\s*\n/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(s))) {
      const end = m.index + m[0].length;
      const before = s.slice(0, end).toLowerCase();
      const word = before.slice(before.lastIndexOf(" ") + 1);
      if (ABBREVIATIONS.includes(word.trim())) continue;
      if (cleanForSpeech(s.slice(0, end)).length < 2) continue;
      return end;
    }
    if (s.length > SOFT_LIMIT) {
      const soft = Math.max(s.lastIndexOf(", ", HARD_LIMIT), s.lastIndexOf("; ", HARD_LIMIT));
      if (soft > 20) return soft + 1;
      if (s.length > HARD_LIMIT) {
        const space = s.lastIndexOf(" ", HARD_LIMIT);
        return space > 40 ? space : HARD_LIMIT;
      }
    }
    return -1;
  }
}
