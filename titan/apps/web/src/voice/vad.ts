// Detecção de atividade vocal (VAD) por energia, com piso de ruído adaptativo,
// histerese e tolerância a pausas. Lógica pura (testável sem navegador).

export interface VadConfig {
  /** Fator acima do ruído de fundo para considerar fala. */
  startFactor: number;
  /** Energia mínima absoluta (RMS 0..1) para iniciar fala. */
  minStartRms: number;
  /** Fala precisa durar isto para contar (evita estalos e falsos inícios). */
  minSpeechMs: number;
  /** Silêncio contínuo que encerra o turno. Longo o bastante para pensar. */
  silenceEndMs: number;
  /** Duração máxima de um turno. */
  maxUtteranceMs: number;
  /** Velocidade de adaptação ao ruído de fundo (0..1). */
  noiseAdapt: number;
  /** Durante a fala do TITAN, exige energia maior (evita confundir eco com o usuário). */
  playbackFactor: number;
  /** Duração mínima para interromper o TITAN (barge-in). */
  minBargeInMs: number;
}

export const DEFAULT_VAD: VadConfig = {
  startFactor: 3,
  minStartRms: 0.012,
  minSpeechMs: 200,
  silenceEndMs: 1300,
  maxUtteranceMs: 30_000,
  noiseAdapt: 0.05,
  playbackFactor: 2.5,
  minBargeInMs: 300,
};

export type VadEvent =
  | { type: "speech_start"; atMs: number }
  | { type: "speech_end"; atMs: number; reason: "silence" | "max_length" }
  | null;

type State = "silence" | "maybe_speech" | "speech" | "maybe_end";

export class Vad {
  config: VadConfig;
  state: State = "silence";
  noise = 0.004;
  private candidateSince = 0;
  private utteranceSince = 0;
  private silentSince = 0;

  constructor(config: Partial<VadConfig> = {}) {
    this.config = { ...DEFAULT_VAD, ...config };
  }

  threshold(playback: boolean): number {
    const base = Math.max(this.config.minStartRms, this.noise * this.config.startFactor);
    return playback ? base * this.config.playbackFactor : base;
  }

  /** Estado "o usuário está falando agora" (inclui pausas curtas dentro da frase). */
  get speaking(): boolean {
    return this.state === "speech" || this.state === "maybe_end";
  }

  reset(): void {
    this.state = "silence";
  }

  process(rms: number, nowMs: number, playback = false): VadEvent {
    const c = this.config;
    const thr = this.threshold(playback);
    switch (this.state) {
      case "silence":
        if (rms > thr) {
          this.state = "maybe_speech";
          this.candidateSince = nowMs;
        } else if (!playback) {
          // Só aprende o ruído de fundo quando o TITAN não está falando.
          this.noise = this.noise * (1 - c.noiseAdapt) + rms * c.noiseAdapt;
        }
        return null;
      case "maybe_speech": {
        if (rms < thr * 0.7) {
          this.state = "silence"; // falso início (estalo, batida)
          return null;
        }
        const needed = playback ? c.minBargeInMs : c.minSpeechMs;
        if (nowMs - this.candidateSince >= needed) {
          this.state = "speech";
          this.utteranceSince = this.candidateSince;
          return { type: "speech_start", atMs: this.candidateSince };
        }
        return null;
      }
      case "speech":
        if (nowMs - this.utteranceSince >= c.maxUtteranceMs) {
          this.state = "silence";
          return { type: "speech_end", atMs: nowMs, reason: "max_length" };
        }
        if (rms < thr * 0.6) {
          this.state = "maybe_end";
          this.silentSince = nowMs;
        }
        return null;
      case "maybe_end":
        if (rms >= thr * 0.6) {
          this.state = "speech"; // era só uma pausa para pensar
          return null;
        }
        if (nowMs - this.silentSince >= c.silenceEndMs) {
          this.state = "silence";
          return { type: "speech_end", atMs: nowMs, reason: "silence" };
        }
        return null;
    }
  }
}

export function rmsOf(frame: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  return Math.sqrt(sum / Math.max(1, frame.length));
}
