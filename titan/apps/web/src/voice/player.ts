// Fila de fala com interrupção imediata. Prepara (sintetiza) o próximo trecho
// enquanto o atual toca, com buffer limitado. cancel() para o áudio na hora e
// descarta tudo o que ainda não foi reproduzido.

import type { Segment } from "./segmenter.ts";

export interface Clip {
  play(): Promise<void>; // resolve quando termina; rejeita se interrompido
  stop(): void;
  setVolume(v: number): void;
}

export interface TtsEngine {
  name: string;
  /** true = roda no aparelho/notebook; false = envia texto a um serviço externo. */
  local: boolean;
  prepare(text: string, signal: AbortSignal): Promise<Clip>;
}

export interface PlayerEvents {
  onFirstAudio?: () => void;
  onSegmentDone?: (seg: Segment) => void;
  onIdle?: () => void;
  onError?: (err: unknown) => void;
}

export class InterruptedError extends Error {
  constructor() {
    super("interrompido");
    this.name = "InterruptedError";
  }
}

const PREFETCH = 2;

export class SpeechPlayer {
  engine: TtsEngine;
  events: PlayerEvents;
  volume = 1;
  muted = false;
  /** Posição no texto original até onde a fala foi concluída. */
  spokenUntil = 0;
  private queue: Segment[] = [];
  private prepared: { seg: Segment; clip: Promise<Clip> }[] = [];
  private current: Clip | null = null;
  private abort = new AbortController();
  private running = false;
  private started = false;
  private generation = 0;

  constructor(engine: TtsEngine, events: PlayerEvents = {}) {
    this.engine = engine;
    this.events = events;
  }

  get active(): boolean {
    return this.running || this.queue.length > 0 || this.prepared.length > 0;
  }

  enqueue(seg: Segment): void {
    this.queue.push(seg);
    this.fill();
    if (!this.running) void this.loop(this.generation);
  }

  setVolume(v: number): void {
    this.volume = Math.max(0, Math.min(1, v));
    this.current?.setVolume(this.muted ? 0 : this.volume);
  }

  setMuted(m: boolean): void {
    this.muted = m;
    this.current?.setVolume(m ? 0 : this.volume);
  }

  /** Para imediatamente e descarta o áudio pendente. Retorna até onde foi falado. */
  cancel(): number {
    this.generation++;
    this.abort.abort();
    this.abort = new AbortController();
    this.queue = [];
    this.prepared = [];
    const cur = this.current;
    this.current = null;
    this.running = false;
    this.started = false;
    cur?.stop();
    return this.spokenUntil;
  }

  /** Nova resposta: zera o contador de posição. */
  reset(): void {
    this.cancel();
    this.spokenUntil = 0;
  }

  private fill(): void {
    while (this.prepared.length < PREFETCH && this.queue.length) {
      const seg = this.queue.shift()!;
      const clip = this.engine.prepare(seg.text, this.abort.signal);
      clip.catch(() => undefined); // tratado no loop
      this.prepared.push({ seg, clip });
    }
  }

  private async loop(gen: number): Promise<void> {
    this.running = true;
    while (gen === this.generation && this.prepared.length) {
      const { seg, clip } = this.prepared.shift()!;
      this.fill();
      let c: Clip;
      try {
        c = await clip;
      } catch (err) {
        if (gen !== this.generation) return;
        this.running = false;
        this.queue = [];
        this.prepared = [];
        this.events.onError?.(err);
        return;
      }
      if (gen !== this.generation) {
        c.stop();
        return;
      }
      this.current = c;
      c.setVolume(this.muted ? 0 : this.volume);
      if (!this.started) {
        this.started = true;
        this.events.onFirstAudio?.();
      }
      try {
        await c.play();
      } catch (err) {
        if (gen !== this.generation || err instanceof InterruptedError) return;
        this.running = false;
        this.events.onError?.(err);
        return;
      }
      if (gen !== this.generation) return;
      this.current = null;
      this.spokenUntil = seg.rawEnd;
      this.events.onSegmentDone?.(seg);
    }
    if (gen === this.generation) {
      this.running = false;
      this.started = false;
      this.events.onIdle?.();
    }
  }
}
