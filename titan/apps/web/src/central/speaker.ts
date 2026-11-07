// Fala as respostas do TITAN frase a frase, sem picotar.
//
// - Voz on-line (Edge): a próxima frase é preparada enquanto a atual toca (mais rápido).
// - Voz gerada no notebook (Piper): NADA é gerado enquanto uma frase toca. Gerar voz ocupa o
//   processador inteiro, e num notebook fraco o som que está tocando sai picotado/travando.
//   Por isso as frases que chegam enquanto toca são juntadas num pedaço só, gerado depois.
import { ServerTts } from "../voice/browser";
import { duckEnd, duckStart } from "../voice/duck";

type Clip = { play: () => Promise<void>; stop: () => void };

let tts: ServerTts | null = null;

async function prepare(text: string, signal: AbortSignal): Promise<Clip> {
  try {
    tts ??= new ServerTts();
    return await tts.prepare(text, signal);
  } catch (e) {
    if (signal.aborted) throw e;
    // sem voz do servidor: voz do navegador
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "pt-BR"; u.pitch = 0.8;
    return {
      play: async () => {
        await duckStart("tts-nav");
        await new Promise<void>((ok) => { u.onend = () => ok(); u.onerror = () => ok(); speechSynthesis.speak(u); });
        duckEnd("tts-nav");
      },
      stop: () => { try { speechSynthesis.cancel(); } catch { /* sem voz */ } },
    };
  }
}

const MAX_CHUNK = 320;  // caracteres por pedaço de voz

export class Speaker {
  /** true = voz on-line: pode preparar a próxima enquanto toca. */
  overlap = false;
  onFirstAudio: () => void = () => undefined;
  private queue: string[] = [];
  private running = false;
  private ctrl = new AbortController();
  private current: Clip | null = null;
  private started = false;
  private waiters: (() => void)[] = [];
  constructor(private enabled: () => boolean) {}

  say(text: string): void {
    const t = text.trim();
    if (!t || !this.enabled()) return;
    this.queue.push(t);
    if (!this.running) void this.run();
  }

  /** Junta as frases da fila num pedaço (até ~320 caracteres). */
  private take(): string | null {
    if (!this.queue.length) return null;
    let out = this.queue.shift()!;
    while (this.queue.length && out.length + 1 + this.queue[0].length <= MAX_CHUNK) out += " " + this.queue.shift()!;
    return out.slice(0, 600);
  }

  private async run(): Promise<void> {
    this.running = true;
    const signal = this.ctrl.signal;
    void duckStart("fala");  // a música fica baixa a resposta inteira (não sobe entre as frases)
    let next: Promise<Clip> | null = null;
    try {
      for (;;) {
        if (signal.aborted) break;
        const pending = next ?? (() => { const t = this.take(); return t ? prepare(t, signal) : null; })();
        next = null;
        if (!pending) {
          // fila vazia: espera um instante por mais frases (a resposta ainda pode estar chegando)
          await new Promise((ok) => setTimeout(ok, 120));
          if (!this.queue.length) break;
          continue;
        }
        let clip: Clip | null = null;
        try { clip = await pending; } catch { clip = null; }
        if (signal.aborted) break;
        if (this.overlap) {  // voz on-line: já prepara a próxima enquanto esta toca
          const t = this.take();
          if (t) { next = prepare(t, signal); next.catch(() => undefined); }
        }
        if (clip) {
          this.current = clip;
          if (!this.started) { this.started = true; this.onFirstAudio(); }
          try { await clip.play(); } catch { /* interrompida */ }
          this.current = null;
        }
      }
    } finally {
      this.running = false;
      duckEnd("fala");
      const w = this.waiters; this.waiters = [];
      w.forEach((f) => f());
    }
  }

  /** Resolve quando tudo o que está na fila terminou de tocar. */
  done(): Promise<void> {
    if (!this.running && !this.queue.length) return Promise.resolve();
    return new Promise((ok) => this.waiters.push(ok));
  }

  stop(): void {
    this.ctrl.abort();
    this.queue = [];
    this.current?.stop();
    this.ctrl = new AbortController();
    this.started = false;
  }

  reset(): void { this.started = false; }
}
