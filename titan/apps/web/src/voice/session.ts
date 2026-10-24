// Orquestra uma conversa por voz: microfone → detecção de fala → transcrição →
// chat (streaming) → fala, com interrupção (barge-in), métricas e estados reais.
// Não depende do navegador: microfone, transcrição, chat e voz são injetados.

import { SpeechSegmenter } from "./segmenter.ts";
import { SpeechPlayer } from "./player.ts";
import type { TtsEngine } from "./player.ts";
import { Vad, VoiceBandMeter, looksIncomplete } from "./vad.ts";
import type { VadConfig } from "./vad.ts";

export interface AudioFrame {
  rms: number;
  pcm16: Int16Array; // 16 kHz mono
  durationMs: number;
}

export interface Microphone {
  start(onFrame: (f: AudioFrame) => void): Promise<void>;
  stop(): void;
}

export interface SttResult {
  text: string;
  /** ok | noise (só ruído: ignorar em silêncio) | unclear (mal entendido: pedir para repetir) */
  verdict?: "ok" | "noise" | "unclear";
  confidence?: number | null;
}

export interface SttEngine {
  name: string;
  local: boolean;
  /** true: um trecho novo pode começar enquanto o anterior ainda é transcrito. */
  overlap?: boolean;
  begin(onPartial: (text: string) => void): Promise<void>;
  push(pcm16: Int16Array): void;
  end(): Promise<SttResult | string>;
  abort(): void;
}

function asResult(r: SttResult | string): SttResult {
  return typeof r === "string" ? { text: r, verdict: "ok" } : { verdict: "ok", ...r };
}

export interface ChatResult {
  messageId: string | null;
  content: string;
}

export interface ChatBackend {
  /** Envia o turno; chama onDelta a cada pedaço. Reenvio com o mesmo requestId não duplica. */
  send(text: string, requestId: string, signal: AbortSignal,
       onDelta: (t: string) => void): Promise<ChatResult>;
  /** Registra até onde a resposta foi falada quando o usuário interrompeu. */
  interrupt(messageId: string | null, spokenChars: number, sentAt: number): Promise<void>;
}

export type VoiceState =
  | "idle"
  | "starting"
  | "listening"
  | "user_speaking"
  | "transcribing"
  | "review"
  | "thinking"
  | "speaking"
  | "error";

export interface VoiceMetrics {
  speechEndToTranscriptMs?: number;
  transcriptToFirstTextMs?: number;
  transcriptToFirstAudioMs?: number;
  bargeInStopMs?: number;
}

export interface VoiceEvents {
  onState?: (s: VoiceState) => void;
  onPartial?: (text: string) => void;
  onUserTurn?: (text: string) => void;
  onAssistantDelta?: (text: string) => void;
  onAssistantDone?: (r: ChatResult, interrupted: boolean) => void;
  onNotice?: (msg: string) => void;
  onError?: (msg: string) => void;
  onMetrics?: (m: VoiceMetrics) => void;
  onLevel?: (rms: number, threshold: number) => void;
}

export interface VoiceOptions {
  confirmBeforeSend: boolean;
  ttsEnabled: boolean;
  vad?: Partial<VadConfig>;
  preRollMs?: number;
}

export interface VoiceDeps {
  mic: Microphone;
  stt: SttEngine;
  tts: TtsEngine | null;
  chat: ChatBackend;
  now: () => number;
  newId: () => string;
  sleep?: (ms: number) => Promise<void>;
}

export class VoiceSession {
  state: VoiceState = "idle";
  pendingText = "";
  metrics: VoiceMetrics = {};
  readonly vad: Vad;
  private meter = new VoiceBandMeter();
  private deps: VoiceDeps;
  private ev: VoiceEvents;
  private opts: VoiceOptions;
  private player: SpeechPlayer | null;
  private preRoll: AudioFrame[] = [];
  private preRollMs: number;
  private sttReady: Promise<boolean> | null = null;
  /** Transcrições das partes anteriores da mesma frase (a pessoa continuou falando). */
  private heldParts: Promise<SttResult>[] = [];
  private endSeq = 0;
  /** Espera por continuação depois de uma frase que terminou incompleta (conta por quadros). */
  private holdUntil = 0;
  private holdDone: (() => void) | null = null;
  private utteranceId = "";
  private sentIds = new Set<string>();
  private turnAbort: AbortController | null = null;
  private streamDone = false;
  private ttsFailed = false;
  private messageId: string | null = null;
  private sentAt = 0;
  private transcriptAt = 0;
  private gotText = false;
  private turnSeq = 0;

  constructor(deps: VoiceDeps, events: VoiceEvents, opts: VoiceOptions) {
    this.deps = deps;
    this.ev = events;
    this.opts = opts;
    this.vad = new Vad(opts.vad);
    this.preRollMs = opts.preRollMs ?? 900;
    this.player = deps.tts
      ? new SpeechPlayer(deps.tts, {
          onFirstAudio: () => {
            if (this.transcriptAt) this.metric({ transcriptToFirstAudioMs: this.deps.now() - this.transcriptAt });
            if (this.state === "thinking") this.setState("speaking");
          },
          onIdle: () => this.maybeFinishTurn(),
          onError: () => {
            this.ttsFailed = true;
            this.ev.onError?.("A voz falhou; a resposta continua em texto na tela.");
            this.maybeFinishTurn();
          },
        })
      : null;
  }

  private setState(s: VoiceState): void {
    if (this.state === s) return;
    this.state = s;
    this.ev.onState?.(s);
  }

  private metric(m: VoiceMetrics): void {
    this.metrics = { ...this.metrics, ...m };
    this.ev.onMetrics?.(this.metrics);
  }

  // --- ciclo de vida -----------------------------------------------------------

  async start(): Promise<void> {
    if (this.state !== "idle" && this.state !== "error") return;
    this.setState("starting");
    try {
      await this.deps.mic.start((f) => this.onFrame(f));
    } catch (err) {
      const name = (err as { name?: string })?.name;
      this.setState("error");
      this.ev.onError?.(
        name === "NotAllowedError"
          ? "Permissão do microfone negada. Você pode continuar digitando."
          : name === "NotFoundError"
            ? "Nenhum microfone encontrado. Você pode continuar digitando."
            : "Não foi possível abrir o microfone (no celular é preciso HTTPS). Use o texto.",
      );
      return;
    }
    this.vad.reset();
    this.setState("listening");
  }

  /** Encerra tudo: microfone desligado, fala interrompida, nada pendente. */
  stop(): void {
    this.deps.mic.stop();
    this.cancelTurn();
    if (this.sttReady) this.deps.stt.abort();
    this.sttReady = null;
    this.heldParts = [];
    this.endSeq++;
    this.releaseHold();
    this.preRoll = [];
    this.pendingText = "";
    this.setState("idle");
  }

  /** Botão "parar de falar": interrompe a resposta sem esperar a fala do usuário. */
  interruptSpeaking(): void {
    if (this.state === "speaking" || this.state === "thinking") {
      this.bargeIn(this.deps.now());
      this.setState("listening");
    }
  }

  setTtsEnabled(on: boolean): void {
    this.opts.ttsEnabled = on;
    if (!on) this.player?.cancel();
  }

  setVolume(v: number): void {
    this.player?.setVolume(v);
  }

  setMuted(m: boolean): void {
    this.player?.setMuted(m);
  }

  // --- áudio -------------------------------------------------------------------

  onFrame(f: AudioFrame): void {
    if (this.state === "idle" || this.state === "starting" || this.state === "error") return;
    const playback = this.state === "speaking";
    const energy = this.meter.rms(f.pcm16); // energia na faixa da voz (detector)
    this.ev.onLevel?.(f.rms, this.vad.threshold(playback));
    this.preRoll.push(f);
    let total = this.preRoll.reduce((a, x) => a + x.durationMs, 0);
    while (total > this.preRollMs && this.preRoll.length > 1) total -= this.preRoll.shift()!.durationMs;

    if (this.state === "user_speaking") this.deps.stt.push(f.pcm16);
    if (this.holdDone && this.deps.now() >= this.holdUntil) this.releaseHold();
    // Durante a transcrição continua ouvindo (se o reconhecedor permitir): se a pessoa
    // voltar a falar, é a continuação da mesma frase, não um áudio a descartar.
    const listensWhileTranscribing = this.state === "transcribing" && this.deps.stt.overlap === true;
    if ((this.state === "transcribing" && !listensWhileTranscribing) || this.state === "review") return;

    const event = this.vad.process(energy, this.deps.now(), playback);
    if (!event) return;
    if (event.type === "speech_start") this.onSpeechStart(event.atMs);
    else if (this.state === "user_speaking") void this.onSpeechEnd();
  }

  private onSpeechStart(atMs: number): void {
    const continuing = this.state === "transcribing";
    if (this.state === "speaking" || this.state === "thinking") this.bargeIn(atMs);
    if (continuing) {
      this.endSeq++; // a transcrição em andamento não envia: a próxima parte envia tudo junto
      this.releaseHold();
    } else {
      this.heldParts = [];
      this.utteranceId = this.deps.newId();
    }
    this.setState("user_speaking");
    this.sttReady = this.deps.stt.begin((t) => {
      this.vad.holdLonger = looksIncomplete(t); // "…e", "…mas": espera mais antes de encerrar
      this.ev.onPartial?.(t);
    }).then(() => true, () => false);
    // inclui o áudio de pouco antes da detecção, para não cortar o começo da frase
    for (const f of this.preRoll) this.deps.stt.push(f.pcm16);
  }

  private async onSpeechEnd(): Promise<void> {
    this.setState("transcribing");
    const endAt = this.deps.now();
    const token = ++this.endSeq;
    const ready = this.sttReady;
    this.sttReady = null;
    const part = (async () => {
      if (!ready || !(await ready)) throw new Error("transcrição indisponível");
      return asResult(await this.deps.stt.end());
    })();
    const parts = [...this.heldParts, part];
    this.heldParts = parts;
    const settled = await Promise.allSettled(parts);
    if (token !== this.endSeq) return; // continuou falando (ou encerrou): não envia esta parte sozinha
    const results = settled.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
    if (!results.length) {
      this.ev.onError?.("Falha na transcrição. Tente de novo ou digite a mensagem.");
      this.setState("listening");
      return;
    }
    this.metric({ speechEndToTranscriptMs: this.deps.now() - endAt });
    if (this.state !== "transcribing") return; // sessão encerrada no meio
    const useful = results.filter((r) => r.verdict !== "noise" && r.text.trim());
    const text = useful.map((r) => r.text.trim()).join(" ");
    if (!text) {
      // Só ruído reconhecido como "o", "é"…: ignora em silêncio. Nada reconhecido: avisa.
      if (!results.some((r) => r.text.trim())) this.ev.onNotice?.("Não entendi. Pode repetir?");
      this.setState("listening");
      return;
    }
    if (looksIncomplete(text) && this.deps.stt.overlap === true) {
      // Terminou em "e", "mas", "pra"…: provavelmente a pessoa vai continuar. Espera um pouco
      // ouvindo; se ela voltar a falar, as partes viram uma mensagem só.
      await this.waitForContinuation(this.vad.config.silenceEndMs * (this.vad.config.incompleteHoldFactor - 1));
      if (token !== this.endSeq || this.state !== "transcribing") return;
    }
    this.heldParts = []; // daqui em diante a mensagem está fechada
    if (useful.every((r) => r.verdict === "unclear") && !this.opts.confirmBeforeSend) {
      // Provavelmente mal entendido (ex.: duas pessoas falando): não envia um palpite.
      this.ev.onNotice?.(`Não entendi bem (ouvi: “${text}”). Pode repetir?`);
      this.setState("listening");
      return;
    }
    if (this.opts.confirmBeforeSend) {
      this.pendingText = text;
      this.setState("review");
      return;
    }
    void this.sendTurn(text, this.utteranceId);
  }

  private waitForContinuation(ms: number): Promise<void> {
    this.releaseHold();
    this.holdUntil = this.deps.now() + ms;
    return new Promise((resolve) => { this.holdDone = resolve; });
  }

  private releaseHold(): void {
    const done = this.holdDone;
    this.holdDone = null;
    done?.();
  }

  /** Confirma (talvez editada) a transcrição em revisão. */
  confirm(text: string): void {
    if (this.state !== "review") return;
    const t = text.trim();
    this.pendingText = "";
    if (!t) {
      this.setState("listening");
      return;
    }
    void this.sendTurn(t, this.utteranceId);
  }

  discard(): void {
    if (this.state !== "review") return;
    this.pendingText = "";
    this.setState("listening");
  }

  // --- turno do assistente ------------------------------------------------------

  private async sendTurn(text: string, requestId: string): Promise<void> {
    if (this.sentIds.has(requestId)) return; // a mesma fala nunca é enviada duas vezes
    this.sentIds.add(requestId);
    this.ev.onUserTurn?.(text);
    const seq = ++this.turnSeq;
    this.setState("thinking");
    this.player?.reset();
    this.messageId = null;
    this.streamDone = false;
    this.ttsFailed = false;
    this.gotText = false;
    this.transcriptAt = this.deps.now();
    this.sentAt = Date.now();
    const segmenter = new SpeechSegmenter();
    let received = "";
    const abort = new AbortController();
    this.turnAbort = abort;
    const onDelta = (d: string) => {
      if (seq !== this.turnSeq) return;
      if (!this.gotText) {
        this.gotText = true;
        this.metric({ transcriptToFirstTextMs: this.deps.now() - this.transcriptAt });
      }
      received += d;
      this.ev.onAssistantDelta?.(d);
      if (this.speakable()) for (const s of segmenter.push(d)) this.player!.enqueue(s);
    };

    let result: ChatResult | null = null;
    for (let attempt = 1; attempt <= 2 && !result; attempt++) {
      try {
        result = await this.deps.chat.send(text, requestId, abort.signal, onDelta);
      } catch (err) {
        if (abort.signal.aborted || seq !== this.turnSeq) return;
        if ((err as { fatal?: boolean })?.fatal) {
          // Erro definitivo do servidor (ex.: orçamento, modelo indisponível): não repete.
          this.ev.onError?.((err as Error).message || "O servidor recusou a mensagem.");
          this.turnAbort = null;
          this.setState("listening");
          return;
        }
        if (attempt === 2) {
          this.ev.onError?.("Sem conexão com o servidor. Sua fala foi guardada; tente de novo.");
          this.turnAbort = null;
          this.setState("listening");
          return;
        }
        this.ev.onNotice?.("Conexão instável; tentando de novo…");
        await (this.deps.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms))))(800);
      }
    }
    if (seq !== this.turnSeq || !result) return;
    // Num reenvio, o servidor devolve a resposta inteira: fala só o que faltou.
    if (result.content.length > received.length && result.content.startsWith(received)) {
      onDelta(result.content.slice(received.length));
    }
    this.messageId = result.messageId;
    this.streamDone = true;
    this.turnAbort = null;
    if (this.speakable()) for (const s of segmenter.flush()) this.player!.enqueue(s);
    this.ev.onAssistantDone?.(result, false);
    this.maybeFinishTurn();
  }

  private speakable(): boolean {
    return Boolean(this.player && this.opts.ttsEnabled && !this.ttsFailed);
  }

  private maybeFinishTurn(): void {
    if (!this.streamDone) return;
    if (this.player?.active && this.speakable()) return;
    if (this.state === "thinking" || this.state === "speaking") this.setState("listening");
  }

  private bargeIn(atMs: number): void {
    const spoken = this.player ? this.player.cancel() : 0;
    this.metric({ bargeInStopMs: Math.max(0, this.deps.now() - atMs) });
    const wasStreaming = !this.streamDone;
    this.cancelTurn();
    if (this.messageId || wasStreaming) {
      void this.deps.chat.interrupt(this.messageId, spoken, this.sentAt).catch(() => undefined);
    }
    this.streamDone = true;
  }

  private cancelTurn(): void {
    this.turnSeq++;
    this.turnAbort?.abort();
    this.turnAbort = null;
    this.player?.cancel();
  }
}
