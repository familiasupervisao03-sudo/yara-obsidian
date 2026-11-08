// Detecção de atividade vocal (VAD) por energia, com calibração inicial, piso de
// ruído por percentil, histerese e tolerância a pausas. Lógica pura (testável sem
// navegador). Não identifica voz humana: só decide quando há som acima do fundo.
//
// Medido com scripts/voice_eval (docs/voice-eval.md): com o piso aprendido só no
// silêncio, um ruído constante presente desde o início (ventilador forte, música)
// disparava o detector e o deixava preso capturando. O piso por percentil dos
// últimos segundos acompanha esse ruído e libera o detector.

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
  /** Ao abrir o microfone, só aprende o ruído do ambiente durante este tempo. */
  calibrationMs: number;
  /** Janela usada para estimar o ruído de fundo. */
  floorWindowMs: number;
  /** Percentil da energia na janela tomado como ruído de fundo (0..1). */
  floorPercentile: number;
  /** Adaptação do ruído aprendido no silêncio (0..1 por quadro). */
  noiseAdapt: number;
  /** Depois de uma pausa, o som precisa durar isto para voltar a contar como fala
   *  (estalos de teclado duram poucos ms e não devem manter a captura aberta). */
  resumeMs: number;
  /** Na confirmação de início, quedas de energia mais curtas que isto não zeram a contagem
   *  (sílabas de fala baixa têm intervalos curtos; cliques de teclado, longos). */
  startGapMs: number;
  /** Multiplica o silêncio de encerramento quando a frase parece incompleta. */
  incompleteHoldFactor: number;
  /** Durante a fala do TITAN, exige energia maior (evita confundir eco com o usuário). */
  playbackFactor: number;
  /** Duração mínima para interromper o TITAN (barge-in). */
  minBargeInMs: number;
}

export const DEFAULT_VAD: VadConfig = {
  startFactor: 2.5,
  minStartRms: 0.008,
  minSpeechMs: 160,
  silenceEndMs: 1000,
  maxUtteranceMs: 30_000,
  calibrationMs: 500,
  floorWindowMs: 3000,
  floorPercentile: 0.1,
  noiseAdapt: 0.05,
  resumeMs: 60,
  startGapMs: 20,
  incompleteHoldFactor: 2,
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
  private quiet = 0.004; // ruído aprendido no silêncio (média móvel)
  private floor = 0; // percentil da energia recente (acompanha ruído constante)
  private resumeSince = -1;
  private gapSince = -1;
  /** Definido pela sessão: o texto parcial termina como frase incompleta ("e…", "mas…"). */
  holdLonger = false;
  private recent: number[] = []; // energia dos últimos quadros fora da fala do TITAN
  private frames = 0;
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

  get calibrating(): boolean {
    return this.frames * 20 < this.config.calibrationMs;
  }

  /** Recomeça do zero (ao abrir o microfone): recalibra o ruído do ambiente. */
  reset(): void {
    this.state = "silence";
    this.recent = [];
    this.frames = 0;
    this.holdLonger = false;
    this.quiet = 0.004;
    this.resumeSince = -1;
  }

  private learn(rms: number): void {
    const c = this.config;
    const max = Math.max(1, Math.round(c.floorWindowMs / 20));
    this.recent.push(rms);
    if (this.recent.length > max) this.recent.shift();
    const sorted = [...this.recent].sort((a, b) => a - b);
    this.floor = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * c.floorPercentile))];
    // Na calibração usa o percentil (se a pessoa já começar falando, a fala não vira
    // "ruído"); depois, a média só aprende fora da fala.
    if (this.calibrating) this.quiet = this.floor;
    else if (this.state === "silence") this.quiet = this.quiet * (1 - c.noiseAdapt) + rms * c.noiseAdapt;
    this.noise = Math.max(this.quiet, this.floor);
  }

  process(rms: number, nowMs: number, playback = false): VadEvent {
    const c = this.config;
    // Só aprende o ruído quando o TITAN não está falando (o eco não é ruído de fundo).
    if (!playback) this.learn(rms);
    this.frames++;
    if (this.calibrating) return null;
    const thr = this.threshold(playback);
    switch (this.state) {
      case "silence":
        if (rms > thr) {
          this.state = "maybe_speech";
          this.candidateSince = nowMs;
          this.gapSince = -1;
        }
        return null;
      case "maybe_speech": {
        if (rms < thr * 0.7) {
          if (this.gapSince < 0) this.gapSince = nowMs;
          if (nowMs - this.gapSince + 20 > c.startGapMs) this.state = "silence"; // falso início (estalo, batida)
          return null;
        }
        this.gapSince = -1;
        const needed = playback ? c.minBargeInMs : c.minSpeechMs;
        if (nowMs - this.candidateSince >= needed) {
          this.state = "speech";
          this.utteranceSince = this.candidateSince;
          this.holdLonger = false;
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
      case "maybe_end": {
        if (rms >= thr * 0.6) {
          if (this.resumeSince < 0) this.resumeSince = nowMs;
          if (nowMs - this.resumeSince + 20 >= c.resumeMs) {
            this.state = "speech"; // era só uma pausa para pensar
            this.resumeSince = -1;
          }
          return null;
        }
        this.resumeSince = -1;
        const limit = c.silenceEndMs * (this.holdLonger ? c.incompleteHoldFactor : 1);
        if (nowMs - this.silentSince >= limit) {
          this.state = "silence";
          return { type: "speech_end", atMs: nowMs, reason: "silence" };
        }
        return null;
      }
    }
  }
}

// Palavras que, no fim de um trecho, indicam frase incompleta ("liga pro dentista e…").
const CONTINUES = new Set([
  "e", "mas", "ou", "que", "porque", "porquê", "pra", "para", "pro", "de", "do", "da", "dos", "das",
  "com", "sem", "tipo", "então", "aí", "quando", "se", "o", "a", "os", "as", "um", "uma", "no", "na",
  "em", "mais", "também", "como", "onde", "qual", "quem", "até", "sobre", "pelo", "pela", "meu", "minha",
]);

export function looksIncomplete(text: string): boolean {
  const last = text.trim().toLowerCase().split(/\s+/).pop() ?? "";
  return CONTINUES.has(last.replace(/[^\p{L}]/gu, ""));
}

/** Energia só na faixa da voz: passa-altas de 2ª ordem em 200 Hz (16 kHz) antes do RMS.
 *  Ventilador, zumbido, batidas e passos ficam quase todos abaixo de 200 Hz. Usado só
 *  pelo detector: o áudio enviado à transcrição não é filtrado. */
export class VoiceBandMeter {
  private x1 = 0; private x2 = 0; private y1 = 0; private y2 = 0;
  private b0: number; private b1: number; private b2: number; private a1: number; private a2: number;

  constructor(cutoffHz = 200, rate = 16000) {
    const w = (2 * Math.PI * cutoffHz) / rate, alpha = Math.sin(w) / (2 * Math.SQRT1_2), cos = Math.cos(w);
    const a0 = 1 + alpha;
    this.b0 = (1 + cos) / 2 / a0; this.b1 = -(1 + cos) / a0; this.b2 = (1 + cos) / 2 / a0;
    this.a1 = (-2 * cos) / a0; this.a2 = (1 - alpha) / a0;
  }

  rms(pcm16: Int16Array): number {
    let sum = 0;
    for (let i = 0; i < pcm16.length; i++) {
      const x = pcm16[i] / 32768;
      const y = this.b0 * x + this.b1 * this.x1 + this.b2 * this.x2 - this.a1 * this.y1 - this.a2 * this.y2;
      this.x2 = this.x1; this.x1 = x; this.y2 = this.y1; this.y1 = y;
      sum += y * y;
    }
    return Math.sqrt(sum / Math.max(1, pcm16.length));
  }
}

export function rmsOf(frame: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  return Math.sqrt(sum / Math.max(1, frame.length));
}
