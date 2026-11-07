// Fala frase a frase: a 1ª frase começa a tocar enquanto a IA ainda escreve as outras,
// e a próxima já vai sendo preparada (voz do servidor) enquanto a atual toca.
import { ServerTts } from "../voice/browser";
import { duckEnd, duckStart } from "../voice/duck";

type Clip = { play: () => Promise<void>; stop: () => void };

let tts: ServerTts | null = null;

async function prepare(text: string, signal: AbortSignal): Promise<Clip> {
  try {
    tts ??= new ServerTts();
    return await tts.prepare(text, signal);
  } catch {
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

export class Speaker {
  private chain: Promise<void> = Promise.resolve();
  private ctrl = new AbortController();
  private current: Clip | null = null;
  private started = false;
  onFirstAudio: () => void = () => undefined;
  constructor(private enabled: () => boolean) {}

  /** Põe uma frase na fila (já começa a preparar a voz dela). */
  say(text: string): void {
    const t = text.trim();
    if (!t || !this.enabled()) return;
    const signal = this.ctrl.signal;
    const clip = prepare(t.slice(0, 400), signal);
    clip.catch(() => undefined);
    this.chain = this.chain.then(async () => {
      if (signal.aborted) return;
      try {
        const c = await clip;
        if (signal.aborted) return;
        this.current = c;
        if (!this.started) { this.started = true; this.onFirstAudio(); }
        await c.play();
      } catch { /* frase interrompida ou sem voz */ }
      this.current = null;
    });
  }

  /** Resolve quando tudo o que está na fila terminou de tocar. */
  async done(): Promise<void> {
    await this.chain;
  }

  stop(): void {
    this.ctrl.abort();
    this.current?.stop();
    this.ctrl = new AbortController();
    this.chain = Promise.resolve();
    this.started = false;
  }

  reset(): void { this.started = false; }
}
