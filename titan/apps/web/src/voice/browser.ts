// Implementações para o navegador: microfone, reconhecimento, voz e chat.
// Privacidade: cada mecanismo informa se é local (true) ou envia dados para fora.

import type { AudioFrame, ChatBackend, ChatResult, Microphone, SttEngine, SttResult } from "./session.ts";
import type { Clip, TtsEngine } from "./player.ts";
import { InterruptedError } from "./player.ts";
import { rmsOf } from "./vad.ts";

const CSRF = { "X-Titan-Request": "1" };

// ---------- microfone ----------

export class BrowserMicrophone implements Microphone {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;

  async start(onFrame: (f: AudioFrame) => void): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw Object.assign(new Error("sem getUserMedia"), { name: "InsecureContext" });
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    this.ctx = new AudioContext();
    await this.ctx.audioWorklet.addModule("/voice-worklet.js");
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "titan-capture");
    const rate = this.ctx.sampleRate;
    this.node.port.onmessage = (e: MessageEvent<Float32Array>) => {
      const f = e.data;
      onFrame({ rms: rmsOf(f), pcm16: downsampleTo16k(f, rate), durationMs: (f.length / rate) * 1000 });
    };
    src.connect(this.node);
  }

  stop(): void {
    this.node?.port.close();
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop()); // luz do microfone apaga
    void this.ctx?.close();
    this.node = null;
    this.stream = null;
    this.ctx = null;
  }
}

export function downsampleTo16k(input: Float32Array, rate: number): Int16Array {
  const ratio = rate / 16000;
  const out = new Int16Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    const v = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
    out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
  }
  return out;
}

// ---------- reconhecimento local (Vosk no notebook) ----------

interface ServerTurn {
  sid: Promise<string>;
  buffer: Int16Array[];
  buffered: number;
  sending: Promise<void>;
  onPartial: (t: string) => void;
}

export class ServerStt implements SttEngine {
  name = "vosk";
  local = true;
  /** Cada trecho tem a própria sessão no servidor: um trecho novo pode começar enquanto
   *  o anterior ainda é transcrito (a sessão emenda os dois numa mensagem só). */
  overlap = true;
  private turn: ServerTurn | null = null;

  async begin(onPartial: (t: string) => void): Promise<void> {
    const sid = fetch("/api/v1/voice/stt/sessions", { method: "POST", headers: CSRF, credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.error?.message ?? `HTTP ${r.status}`);
        return (await r.json()).session_id as string;
      });
    this.turn = { sid, buffer: [], buffered: 0, sending: Promise.resolve(), onPartial };
    await sid;
  }

  push(pcm16: Int16Array): void {
    const t = this.turn;
    if (!t) return;
    t.buffer.push(pcm16);
    t.buffered += pcm16.length;
    if (t.buffered >= 16000 * 0.4) this.flushChunk(t); // ~400 ms por envio
  }

  private flushChunk(t: ServerTurn): void {
    if (!t.buffered) return;
    const chunk = new Int16Array(t.buffered);
    let off = 0;
    for (const b of t.buffer) {
      chunk.set(b, off);
      off += b.length;
    }
    t.buffer = [];
    t.buffered = 0;
    t.sending = t.sending.then(async () => {
      const id = await t.sid;
      const r = await fetch(`/api/v1/voice/stt/sessions/${id}/audio`, {
        method: "POST", credentials: "same-origin",
        headers: { ...CSRF, "Content-Type": "application/octet-stream" }, body: chunk.buffer,
      });
      if (r.ok) t.onPartial((await r.json()).text);
    });
  }

  async end(): Promise<SttResult> {
    const t = this.turn;
    if (!t) throw new Error("sem sessão");
    this.turn = null; // um begin() seguinte já usa uma sessão nova
    this.flushChunk(t);
    await t.sending;
    const id = await t.sid;
    const r = await fetch(`/api/v1/voice/stt/sessions/${id}/finish`, {
      method: "POST", headers: CSRF, credentials: "same-origin",
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const body = await r.json();
    return { text: body.text as string, verdict: body.verdict ?? "ok", confidence: body.confidence ?? null,
             corrections: body.corrections ?? [] };
  }

  abort(): void {
    const t = this.turn;
    this.turn = null;
    void t?.sid.then((id) => fetch(`/api/v1/voice/stt/sessions/${id}`, {
      method: "DELETE", headers: CSRF, credentials: "same-origin",
    })).catch(() => undefined);
  }
}

// ---------- reconhecimento do navegador (EXTERNO: envia áudio ao fornecedor) ----------

type SR = {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void; abort(): void;
};

export function browserSttSupported(): boolean {
  const w = window as unknown as Record<string, unknown>;
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition);
}

export class BrowserStt implements SttEngine {
  name = "navegador (Web Speech)";
  local = false; // Chrome/Android enviam o áudio aos servidores do Google
  private rec: SR | null = null;
  private finalText = "";
  private ended: Promise<void> = Promise.resolve();

  async begin(onPartial: (t: string) => void): Promise<void> {
    const w = window as unknown as Record<string, new () => SR>;
    const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!Ctor) throw new Error("reconhecimento do navegador indisponível");
    const rec = new Ctor();
    rec.lang = "pt-BR";
    rec.continuous = true;
    rec.interimResults = true;
    this.finalText = "";
    let done!: () => void;
    this.ended = new Promise((r) => { done = r; });
    rec.onresult = (e) => {
      let interim = "";
      let fin = "";
      for (let i = 0; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) fin += r[0].transcript;
        else interim += r[0].transcript;
      }
      this.finalText = fin;
      onPartial((fin + " " + interim).trim());
    };
    rec.onerror = () => done();
    rec.onend = () => done();
    rec.start();
    this.rec = rec;
  }

  push(): void {
    // o navegador captura o microfone por conta própria
  }

  async end(): Promise<string> {
    this.rec?.stop();
    await Promise.race([this.ended, new Promise((r) => setTimeout(r, 2500))]);
    this.rec = null;
    return this.finalText.trim();
  }

  abort(): void {
    this.rec?.abort();
    this.rec = null;
  }
}

// ---------- voz local (Piper no notebook) ----------

/** Voz gerada pelo servidor do TITAN: Piper (local) ou a voz natural on-line (externa). */
export class ServerTts implements TtsEngine {
  name: string;
  local: boolean;
  private ctx: AudioContext | null = null;
  constructor(name = "piper", local = true) {
    this.name = name;
    this.local = local;
  }

  async prepare(text: string, signal: AbortSignal): Promise<Clip> {
    const r = await fetch("/api/v1/voice/speak", {
      method: "POST", signal, credentials: "same-origin",
      headers: { ...CSRF, "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => null))?.error?.message ?? `HTTP ${r.status}`);
    const data = await r.arrayBuffer();
    this.ctx ??= new AudioContext();
    const buffer = await this.ctx.decodeAudioData(data);
    return new BufferClip(this.ctx, buffer);
  }
}

class BufferClip implements Clip {
  private src: AudioBufferSourceNode | null = null;
  private gain: GainNode;
  private reject: ((e: unknown) => void) | null = null;
  private ctx: AudioContext;
  private buffer: AudioBuffer;
  constructor(ctx: AudioContext, buffer: AudioBuffer) {
    this.ctx = ctx;
    this.buffer = buffer;
    this.gain = ctx.createGain();
    this.gain.connect(ctx.destination);
  }
  play(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.reject = reject;
      void this.ctx.resume();
      const src = this.ctx.createBufferSource();
      src.buffer = this.buffer;
      src.connect(this.gain);
      src.onended = () => resolve();
      this.src = src;
      src.start();
    });
  }
  stop(): void {
    try { this.src?.stop(); } catch { /* já parado */ }
    this.src?.disconnect();
    this.reject?.(new InterruptedError());
  }
  setVolume(v: number): void {
    this.gain.gain.value = v;
  }
}

// ---------- voz do navegador (local se a voz for do aparelho) ----------

export function pickBrowserVoice(allowNetwork: boolean): SpeechSynthesisVoice | null {
  if (!("speechSynthesis" in window)) return null;
  const voices = speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("pt"));
  const ok = voices.filter((v) => allowNetwork || v.localService);
  return ok.find((v) => v.lang === "pt-BR") ?? ok[0] ?? null;
}

export class BrowserTts implements TtsEngine {
  name: string;
  local: boolean;
  private voice: SpeechSynthesisVoice;
  constructor(voice: SpeechSynthesisVoice) {
    this.voice = voice;
    this.local = voice.localService;
    this.name = `navegador: ${voice.name}`;
  }
  async prepare(text: string, signal: AbortSignal): Promise<Clip> {
    if (signal.aborted) throw new InterruptedError();
    const u = new SpeechSynthesisUtterance(text);
    u.voice = this.voice;
    u.lang = this.voice.lang;
    u.rate = 1.05;
    return {
      play: () => new Promise<void>((resolve, reject) => {
        u.onend = () => resolve();
        u.onerror = (e) => (e.error === "interrupted" || e.error === "canceled"
          ? reject(new InterruptedError()) : reject(new Error(e.error)));
        speechSynthesis.speak(u);
      }),
      stop: () => speechSynthesis.cancel(),
      setVolume: (v: number) => { u.volume = v; },
    };
  }
}

// ---------- chat (streaming SSE via fetch) ----------

/** Andamento da pesquisa na internet (evento "research" do servidor). */
export interface ResearchEvent {
  status: "searching" | "done" | "disabled" | "limited" | "failed";
  query?: string;
  detail?: string;
  notes?: string[];
  sources?: { n: number; title: string; url: string; site: string }[];
}

export class StreamingChat implements ChatBackend {
  conversationId: () => Promise<string>;
  /** "voice": o servidor pede ao modelo uma resposta para ser falada (curta, sem markdown). */
  mode: "text" | "voice";
  /** true: pesquisar na internet; undefined: só se o texto pedir ("pesquisa na internet ..."). */
  web?: boolean;
  onResearch?: (e: ResearchEvent) => void;
  constructor(conversationId: () => Promise<string>, mode: "text" | "voice" = "text",
              opts: { web?: boolean; onResearch?: (e: ResearchEvent) => void } = {}) {
    this.conversationId = conversationId;
    this.mode = mode;
    this.web = opts.web;
    this.onResearch = opts.onResearch;
  }

  async send(text: string, requestId: string, signal: AbortSignal,
             onDelta: (t: string) => void): Promise<ChatResult> {
    const cid = await this.conversationId();
    const r = await fetch(`/api/v1/conversations/${cid}/messages/stream`, {
      method: "POST", signal, credentials: "same-origin",
      headers: { ...CSRF, "Content-Type": "application/json" },
      body: JSON.stringify({ content: text, client_request_id: requestId, mode: this.mode,
                             ...(this.web === undefined ? {} : { web: this.web }) }),
    });
    if (!r.ok || !r.body) {
      const msg = (await r.json().catch(() => null))?.error?.message ?? `HTTP ${r.status}`;
      throw Object.assign(new Error(msg), { fatal: r.status < 500 });
    }
    const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
    let buf = "";
    let content = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += value;
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const event = /^event: (.*)$/m.exec(block)?.[1];
        const data = /^data: (.*)$/m.exec(block)?.[1];
        if (!event || !data) continue;
        const payload = JSON.parse(data);
        if (event === "delta") {
          content += payload.text;
          onDelta(payload.text);
        } else if (event === "research") {
          this.onResearch?.(payload as ResearchEvent);
        } else if (event === "done") {
          // A lista de fontes no fim da mensagem salva não é parte da fala.
          const full: string = payload.message?.content ?? content;
          const cut = Number(payload.footer_chars) || 0;
          return { messageId: payload.message?.id ?? null, content: cut ? full.slice(0, full.length - cut) : full };
        } else if (event === "error") {
          throw Object.assign(new Error(payload.detail), { fatal: true });
        } else if (event === "interrupted") {
          return { messageId: payload.message?.id ?? null, content };
        }
      }
    }
    throw new Error("conexão encerrada antes do fim da resposta");
  }

  async interrupt(messageId: string | null, spokenChars: number, sentAt: number): Promise<void> {
    const cid = await this.conversationId();
    let id = messageId;
    if (!id) {
      // A resposta foi cortada no meio: o servidor salvou o trecho; localiza-o.
      await new Promise((r) => setTimeout(r, 400));
      const conv = await fetch(`/api/v1/conversations/${cid}`, { credentials: "same-origin" })
        .then((r) => r.json());
      const last = [...(conv.messages ?? [])].reverse()
        .find((m: { role: string; created_at: string }) => m.role === "assistant"
          && Date.parse(m.created_at) >= sentAt - 5000);
      id = last?.id ?? null;
    }
    if (!id) return;
    await fetch(`/api/v1/conversations/${cid}/messages/${id}/interruption`, {
      method: "POST", credentials: "same-origin",
      headers: { ...CSRF, "Content-Type": "application/json" },
      body: JSON.stringify({ spoken_chars: spokenChars }),
    });
  }
}
