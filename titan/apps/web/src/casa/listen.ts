// Ouvido do TITAN Casa: microfone + detecção de fala (VAD) + reconhecimento do servidor
// (o mesmo do TITAN: Groq/xAI com o Vosk de reserva). Cada fala vira um texto.
//   once(): ouve UMA fala (toque no núcleo)
//   continuous(): fica ouvindo; cada fala vai para onText (o servidor só age se vier "Ei, Titã")
import { BrowserMicrophone, ServerStt } from "../voice/browser.ts";
import type { AudioFrame } from "../voice/session.ts";
import { Vad } from "../voice/vad.ts";
import { duckEnd, duckStart } from "../voice/duck.ts";

export type EarState = "off" | "waiting" | "hearing" | "thinking";

const PRE_ROLL_MS = 700;

export class Ear {
  private mic: BrowserMicrophone | null = null;
  private vad = new Vad();
  private stt: ServerStt | null = null;
  private pre: AudioFrame[] = [];
  private preMs = 0;
  private busy = false;
  private stopped = true;
  private oneShot = false;
  private noSpeechTimer: number | null = null;

  constructor(private onText: (text: string) => void, private onState: (s: EarState) => void,
              private onPartial: (t: string) => void = () => undefined, private onError: (m: string) => void = () => undefined) {}

  get running(): boolean { return !this.stopped; }

  async once(): Promise<void> {
    this.oneShot = true;
    await this.start();
    // Sem fala em 8 s: desiste em silêncio.
    this.noSpeechTimer = window.setTimeout(() => { if (!this.busy) this.stop(); }, 8000);
  }

  async continuous(): Promise<void> {
    this.oneShot = false;
    await this.start();
  }

  private async start(): Promise<void> {
    this.stop();
    this.stopped = false;
    // ouvindo uma fala (toque no núcleo): a música do notebook abaixa já
    if (this.oneShot) void duckStart("ouvir");
    this.vad = new Vad({ silenceEndMs: 800, maxUtteranceMs: 12_000 });
    this.mic = new BrowserMicrophone();
    this.onState("waiting");
    try {
      await this.mic.start((f) => this.frame(f));
    } catch (e) {
      this.stop();
      const name = (e as { name?: string })?.name;
      this.onError(name === "NotAllowedError" ? "Permita o microfone para falar com o TITAN."
        : name === "InsecureContext" ? "O microfone só funciona com cadeado (https)." : "Não consegui abrir o microfone.");
    }
  }

  private frame(f: AudioFrame): void {
    if (this.stopped) return;
    const ev = this.vad.process(f.rms, performance.now());
    if (!this.stt) {
      this.pre.push(f);
      this.preMs += f.durationMs;
      while (this.preMs > PRE_ROLL_MS && this.pre.length > 1) this.preMs -= this.pre.shift()!.durationMs;
    } else {
      this.stt.push(f.pcm16);
    }
    if (ev?.type === "speech_start" && !this.stt && !this.busy) {
      if (this.noSpeechTimer) window.clearTimeout(this.noSpeechTimer);
      void duckStart("ouvir");  // escuta contínua: abaixa quando começa a fala
      const stt = new ServerStt();
      this.stt = stt;
      this.onState("hearing");
      void stt.begin(this.onPartial).catch(() => undefined);
      for (const p of this.pre) stt.push(p.pcm16);
      this.pre = [];
      this.preMs = 0;
    } else if (ev?.type === "speech_end" && this.stt) {
      const stt = this.stt;
      this.stt = null;
      this.busy = true;
      this.onState("thinking");
      void stt.end().then((r) => {
        const text = (typeof r === "string" ? r : r.verdict === "noise" ? "" : r.text).trim();
        if (text) this.onText(text);
      }).catch(() => this.onError("Não entendi o áudio. Tente de novo.")).finally(() => {
        this.busy = false;
        if (this.oneShot) this.stop();
        else if (!this.stopped) { duckEnd("ouvir"); this.onState("waiting"); }
      });
    }
  }

  stop(): void {
    duckEnd("ouvir");
    if (this.noSpeechTimer) window.clearTimeout(this.noSpeechTimer);
    this.noSpeechTimer = null;
    this.stt?.abort();
    this.stt = null;
    this.mic?.stop();
    this.mic = null;
    this.pre = [];
    this.preMs = 0;
    if (!this.stopped) this.onState("off");
    this.stopped = true;
  }
}
