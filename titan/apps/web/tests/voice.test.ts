// Testes do modo de voz (lógica pura). Rodar: npm test --workspace apps/web
import { test } from "node:test";
import assert from "node:assert/strict";
import { Vad } from "../src/voice/vad.ts";
import { SpeechSegmenter, cleanForSpeech } from "../src/voice/segmenter.ts";
import { SpeechPlayer, InterruptedError } from "../src/voice/player.ts";
import type { Clip, TtsEngine } from "../src/voice/player.ts";
import { VoiceSession } from "../src/voice/session.ts";
import type { AudioFrame, ChatBackend, ChatResult, SttEngine, VoiceState } from "../src/voice/session.ts";

const tick = () => new Promise((r) => setTimeout(r, 0));
async function flush(n = 10) { for (let i = 0; i < n; i++) await tick(); }

// ---------- VAD ----------

function feed(vad: Vad, rms: number, fromMs: number, toMs: number, playback = false) {
  const events = [];
  for (let t = fromMs; t < toMs; t += 20) {
    const e = vad.process(rms, t, playback);
    if (e) events.push(e);
  }
  return events;
}

test("VAD: fala detectada após duração mínima e encerrada após silêncio", () => {
  const v = new Vad({ silenceEndMs: 1300 });
  feed(v, 0.003, 0, 1000);
  const start = feed(v, 0.2, 1000, 1400);
  assert.equal(start[0]?.type, "speech_start");
  const end = feed(v, 0.003, 1400, 3000);
  assert.equal(end[0]?.type, "speech_end");
  assert.ok(end[0]!.atMs >= 1400 + 1300);
});

test("VAD: pausa para pensar menor que o limite não encerra o turno", () => {
  const v = new Vad({ silenceEndMs: 1300 });
  feed(v, 0.003, 0, 500);
  feed(v, 0.2, 500, 1500);
  assert.deepEqual(feed(v, 0.003, 1500, 2600), []); // 1,1 s de pausa
  assert.deepEqual(feed(v, 0.2, 2600, 3000), []);   // volta a falar: mesmo turno
  assert.equal(feed(v, 0.003, 3000, 4500)[0]?.type, "speech_end");
});

test("VAD: estalo curto não conta como fala", () => {
  const v = new Vad();
  feed(v, 0.003, 0, 500);
  assert.deepEqual(feed(v, 0.3, 500, 560), []);
  assert.deepEqual(feed(v, 0.003, 560, 2000), []);
});

test("VAD: silêncio prolongado não gera evento", () => {
  const v = new Vad();
  assert.deepEqual(feed(v, 0.004, 0, 60_000), []);
});

test("VAD: durante a fala do TITAN exige mais energia (eco não interrompe)", () => {
  const v = new Vad();
  feed(v, 0.003, 0, 500);
  const echo = v.threshold(false) * 1.5; // eco moderado
  assert.deepEqual(feed(v, echo, 500, 2000, true), []);
  assert.equal(feed(v, 0.4, 2000, 2600, true)[0]?.type, "speech_start");
});

// ---------- Segmentação ----------

test("segmenta frases completas e não corta abreviações nem decimais", () => {
  const s = new SpeechSegmenter();
  const out = [...s.push("Olá, Sr. Luiz. O valor é 3.5 reais"), ...s.push(" hoje! Tudo"), ...s.flush()];
  assert.deepEqual(out.map((x) => x.text), ["Olá, Sr. Luiz.", "O valor é 3.5 reais hoje!", "Tudo"]);
});

test("não lê blocos de código nem marcações", () => {
  const s = new SpeechSegmenter();
  const parts = ["Veja **isto**:\n", "``", "`python\nprint('x')\n``", "`\nPronto. "];
  const out = parts.flatMap((p) => s.push(p)).concat(s.flush()).map((x) => x.text);
  assert.ok(out.every((t) => !t.includes("print") && !t.includes("*") && !t.includes("`")), out.join("|"));
  assert.ok(out.includes("O código está na tela."));
  assert.equal(out.at(-1), "Pronto.");
});

test("limpa links e listas", () => {
  assert.equal(cleanForSpeech("- veja https://exemplo.com/a?b=1 agora"), "veja link agora");
  assert.equal(cleanForSpeech("[site](https://x.y)"), "site");
});

test("frase muito longa é dividida em vírgula, não no meio da palavra", () => {
  const s = new SpeechSegmenter();
  const long = "Esta é uma frase bem comprida, " + "com várias partes que continuam ".repeat(8);
  const out = s.push(long);
  assert.ok(out.length >= 1);
  assert.ok(out[0].text.endsWith(","));
});

test("rawEnd acompanha a posição no texto original", () => {
  const s = new SpeechSegmenter();
  const text = "Primeira frase. Segunda frase. ";
  const out = s.push(text);
  assert.equal(text.slice(0, out[0].rawEnd).trim(), "Primeira frase.");
  assert.equal(out[1].rawEnd, "Primeira frase. Segunda frase.".length);
});

// ---------- Player ----------

class FakeClip implements Clip {
  stopped = false;
  volume = 1;
  private resolve?: () => void;
  private reject?: (e: unknown) => void;
  text: string;
  log: string[];
  constructor(text: string, log: string[]) { this.text = text; this.log = log; }
  play() {
    this.log.push(`play:${this.text}`);
    return new Promise<void>((res, rej) => { this.resolve = res; this.reject = rej; });
  }
  finish() { this.resolve?.(); }
  stop() { this.stopped = true; this.log.push(`stop:${this.text}`); this.reject?.(new InterruptedError()); }
  setVolume(v: number) { this.volume = v; }
}

class FakeTts implements TtsEngine {
  name = "fake"; local = true;
  clips: FakeClip[] = []; log: string[] = []; aborted = 0; fail = false;
  prepare(text: string, signal: AbortSignal) {
    if (this.fail) return Promise.reject(new Error("síntese falhou"));
    const c = new FakeClip(text, this.log);
    this.clips.push(c);
    signal.addEventListener("abort", () => this.aborted++);
    return Promise.resolve(c);
  }
}

test("player toca em sequência e registra até onde falou", async () => {
  const tts = new FakeTts();
  let idle = 0;
  const p = new SpeechPlayer(tts, { onIdle: () => idle++ });
  p.enqueue({ text: "um", rawEnd: 3 });
  p.enqueue({ text: "dois", rawEnd: 8 });
  await flush();
  assert.deepEqual(tts.log, ["play:um"]);
  tts.clips[0].finish(); await flush();
  assert.equal(p.spokenUntil, 3);
  tts.clips[1].finish(); await flush();
  assert.equal(p.spokenUntil, 8);
  assert.equal(idle, 1);
});

test("cancel para o áudio na hora e descarta pendentes", async () => {
  const tts = new FakeTts();
  const p = new SpeechPlayer(tts);
  ["a", "b", "c", "d"].forEach((t, i) => p.enqueue({ text: t, rawEnd: i + 1 }));
  await flush();
  tts.clips[0].finish(); await flush();
  const spoken = p.cancel();
  await flush();
  assert.equal(spoken, 1);
  assert.ok(tts.clips[1].stopped);
  assert.ok(tts.aborted > 0, "sínteses pendentes abortadas");
  assert.ok(!tts.log.includes("play:c") && !tts.log.includes("play:d"));
  assert.equal(p.active, false);
});

test("falha de síntese é reportada e para a fila", async () => {
  const tts = new FakeTts(); tts.fail = true;
  let err: unknown = null;
  const p = new SpeechPlayer(tts, { onError: (e) => { err = e; } });
  p.enqueue({ text: "x", rawEnd: 1 });
  await flush();
  assert.ok(err instanceof Error);
  assert.equal(p.active, false);
});

// ---------- Sessão ----------

class FakeMic {
  onFrame?: (f: AudioFrame) => void;
  started = false; stopped = false; deny = false;
  async start(cb: (f: AudioFrame) => void) {
    if (this.deny) throw Object.assign(new Error("negado"), { name: "NotAllowedError" });
    this.onFrame = cb; this.started = true;
  }
  stop() { this.stopped = true; this.onFrame = undefined; }
}

class FakeStt implements SttEngine {
  name = "fake"; local = true;
  pushed = 0; text = "olá titan"; fail = false; aborted = false;
  async begin(onPartial: (t: string) => void) { onPartial("olá"); }
  push(p: Int16Array) { this.pushed += p.length; }
  async end() { if (this.fail) throw new Error("x"); return this.text; }
  abort() { this.aborted = true; }
}

class FakeChat implements ChatBackend {
  sends: { text: string; id: string }[] = [];
  interrupts: { id: string | null; spoken: number }[] = [];
  failTimes = 0;
  reply = "Olá! Tudo bem com você? Posso ajudar.";
  holdUntil: Promise<void> | null = null;
  async send(text: string, id: string, signal: AbortSignal, onDelta: (t: string) => void): Promise<ChatResult> {
    this.sends.push({ text, id });
    if (this.failTimes-- > 0) throw new TypeError("rede caiu");
    for (const w of this.reply.split(/(?<= )/)) {
      if (signal.aborted) throw new DOMException("abortado", "AbortError");
      onDelta(w);
      if (this.holdUntil) await this.holdUntil;
    }
    return { messageId: "m1", content: this.reply };
  }
  async interrupt(id: string | null, spoken: number) { this.interrupts.push({ id, spoken }); }
}

function setup(opts: { confirm?: boolean; tts?: boolean } = {}) {
  let now = 0, n = 0;
  const mic = new FakeMic(), stt = new FakeStt(), chat = new FakeChat(), tts = new FakeTts();
  const states: VoiceState[] = [], errors: string[] = [], notices: string[] = [];
  const s = new VoiceSession(
    { mic, stt, tts: opts.tts === false ? null : tts, chat, now: () => now, newId: () => `u${++n}`,
      sleep: async () => {} },
    { onState: (x) => states.push(x), onError: (e) => errors.push(e), onNotice: (x) => notices.push(x) },
    { confirmBeforeSend: opts.confirm ?? false, ttsEnabled: true },
  );
  const frame = (rms: number) => { now += 20; mic.onFrame?.({ rms, pcm16: new Int16Array(320), durationMs: 20 }); };
  const speak = async (ms = 600) => {
    for (let t = 0; t < 400; t += 20) frame(0.003);
    for (let t = 0; t < ms; t += 20) frame(0.3);
    for (let t = 0; t < 1500; t += 20) frame(0.003);
    await flush(20);
  };
  return { s, mic, stt, chat, tts, states, errors, notices, frame, speak };
}

test("sessão: iniciar, falar, enviar, ouvir resposta, voltar a escutar, encerrar", async () => {
  const t = setup();
  await t.s.start();
  assert.equal(t.s.state, "listening");
  await t.speak();
  assert.equal(t.chat.sends.length, 1);
  assert.equal(t.chat.sends[0].text, "olá titan");
  assert.ok(t.stt.pushed > 0);
  assert.equal(t.s.state, "speaking");
  for (let round = 0; round < 10 && t.s.state === "speaking"; round++) {
    for (const c of t.tts.clips) c.finish(); // termina o trecho que estiver tocando
    await flush(20);
  }
  assert.equal(t.s.state, "listening");
  assert.equal(t.tts.clips.length, 3, "três frases faladas");
  t.s.stop();
  assert.ok(t.mic.stopped, "microfone desligado ao encerrar");
  assert.equal(t.s.state, "idle");
  assert.ok(t.s.metrics.transcriptToFirstAudioMs !== undefined);
});

test("permissão do microfone negada mostra erro e alternativa de texto", async () => {
  const t = setup();
  t.mic.deny = true;
  await t.s.start();
  assert.equal(t.s.state, "error");
  assert.match(t.errors[0], /negada.*digitando/);
});

test("falha na transcrição é explícita e nada é enviado", async () => {
  const t = setup();
  t.stt.fail = true;
  await t.s.start();
  await t.speak();
  assert.equal(t.chat.sends.length, 0);
  assert.match(t.errors[0], /transcrição/);
  assert.equal(t.s.state, "listening");
});

test("transcrição vazia não envia e pede para repetir", async () => {
  const t = setup();
  t.stt.text = "   ";
  await t.s.start();
  await t.speak();
  assert.equal(t.chat.sends.length, 0);
  assert.match(t.notices[0], /repetir/);
});

test("barge-in: usuário fala por cima, áudio para e fala nova é ouvida", async () => {
  const t = setup();
  await t.s.start();
  await t.speak();
  assert.equal(t.s.state, "speaking");
  const playing = t.tts.clips[0];
  for (let i = 0; i < 25; i++) t.frame(0.5); // fala forte por cima da voz
  await flush();
  assert.ok(playing.stopped, "áudio interrompido");
  assert.equal(t.s.state, "user_speaking");
  assert.deepEqual(t.chat.interrupts, [{ id: "m1", spoken: 0 }]);
  assert.ok((t.s.metrics.bargeInStopMs ?? 999) <= 500);
  for (let i = 0; i < 80; i++) t.frame(0.003);
  await flush(20);
  assert.equal(t.chat.sends.length, 2, "novo turno enviado");
  assert.notEqual(t.chat.sends[0].id, t.chat.sends[1].id);
});

test("barge-in durante a geração cancela a resposta em andamento", async () => {
  const t = setup();
  let release!: () => void;
  t.chat.holdUntil = new Promise((r) => { release = r; });
  await t.s.start();
  await t.speak();
  for (let i = 0; i < 25; i++) t.frame(0.5);
  release();
  await flush(20);
  assert.equal(t.chat.interrupts.length, 1);
  assert.equal(t.chat.interrupts[0].id, null); // resposta ainda não tinha id
  assert.equal(t.s.state, "user_speaking");
});

test("botão de interromper funciona sem detecção de fala", async () => {
  const t = setup();
  await t.s.start();
  await t.speak();
  t.s.interruptSpeaking();
  await flush();
  assert.ok(t.tts.clips[0].stopped);
  assert.equal(t.s.state, "listening");
});

test("queda de rede: reenvia com o MESMO id (servidor não duplica)", async () => {
  const t = setup();
  t.chat.failTimes = 1;
  await t.s.start();
  await t.speak();
  assert.equal(t.chat.sends.length, 2);
  assert.equal(t.chat.sends[0].id, t.chat.sends[1].id);
  assert.ok(t.notices.some((n) => /tentando de novo/.test(n)));
});

test("rede fora: erro claro depois de uma nova tentativa", async () => {
  const t = setup();
  t.chat.failTimes = 5;
  await t.s.start();
  await t.speak();
  assert.equal(t.chat.sends.length, 2);
  assert.match(t.errors.at(-1)!, /Sem conexão/);
  assert.equal(t.s.state, "listening");
});

test("modo revisão: transcrição editável antes de enviar", async () => {
  const t = setup({ confirm: true });
  await t.s.start();
  await t.speak();
  assert.equal(t.s.state, "review");
  assert.equal(t.s.pendingText, "olá titan");
  t.s.confirm("olá TITAN, corrigido");
  await flush(20);
  assert.equal(t.chat.sends[0].text, "olá TITAN, corrigido");
  t.s.confirm("de novo");
  await flush();
  assert.equal(t.chat.sends.length, 1, "não envia duas vezes");
});

test("falha da voz: resposta continua em texto e sessão volta a escutar", async () => {
  const t = setup();
  t.tts.fail = true;
  await t.s.start();
  await t.speak();
  await flush(20);
  assert.ok(t.errors.some((e) => /voz falhou/.test(e)));
  assert.equal(t.s.state, "listening");
});

test("sem mecanismo de voz: só texto, sem erro", async () => {
  const t = setup({ tts: false });
  await t.s.start();
  await t.speak();
  assert.equal(t.s.state, "listening");
  assert.deepEqual(t.errors, []);
});

test("encerrar a sessão no meio desliga tudo e ignora áudio posterior", async () => {
  const t = setup();
  await t.s.start();
  for (let i = 0; i < 30; i++) t.frame(0.3);
  t.s.stop();
  const pushed = t.stt.pushed;
  t.frame(0.3);
  assert.equal(t.stt.pushed, pushed);
  assert.ok(t.stt.aborted);
  assert.equal(t.chat.sends.length, 0);
});

test("erro definitivo do servidor (ex.: orçamento) não é repetido", async () => {
  const t = setup();
  t.chat.send = async (text, id) => {
    t.chat.sends.push({ text, id });
    throw Object.assign(new Error("Orçamento diário atingido"), { fatal: true });
  };
  await t.s.start();
  await t.speak();
  assert.equal(t.chat.sends.length, 1);
  assert.match(t.errors.at(-1)!, /Orçamento/);
  assert.equal(t.s.state, "listening");
});
