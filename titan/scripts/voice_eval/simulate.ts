// Roda a sessão de voz REAL do navegador (session.ts + vad.ts) sobre arquivos WAV,
// com relógio simulado em quadros de 20 ms. Grava o áudio que a sessão enviaria
// para a transcrição em cada turno; o Python (run_eval.py) transcreve com o Vosk.
//
// Uso: node --experimental-strip-types --no-warnings simulate.ts <samples> <saida> <transcricao_ms> [vad.json]

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { VoiceSession } from "../../apps/web/src/voice/session.ts";
import type { AudioFrame, ChatResult, VoiceState } from "../../apps/web/src/voice/session.ts";
import { DEFAULT_VAD, rmsOf } from "../../apps/web/src/voice/vad.ts";

const RATE = 16000;
const FRAME = 320; // 20 ms

function readWav(path: string): Int16Array {
  const buf = readFileSync(path);
  if (buf.toString("ascii", 0, 4) !== "RIFF" || buf.toString("ascii", 8, 12) !== "WAVE") throw new Error(`${path}: não é WAV`);
  let off = 12;
  let fmtOk = false;
  while (off + 8 <= buf.length) {
    const id = buf.toString("ascii", off, off + 4);
    const size = buf.readUInt32LE(off + 4);
    if (id === "fmt ") {
      const channels = buf.readUInt16LE(off + 10), rate = buf.readUInt32LE(off + 12), bits = buf.readUInt16LE(off + 22);
      if (channels !== 1 || rate !== RATE || bits !== 16) throw new Error(`${path}: precisa ser 16 kHz mono 16 bits`);
      fmtOk = true;
    } else if (id === "data" && fmtOk) {
      const data = buf.subarray(off + 8, off + 8 + size);
      return new Int16Array(data.buffer.slice(data.byteOffset, data.byteOffset + data.length));
    }
    off += 8 + size + (size % 2);
  }
  throw new Error(`${path}: sem dados`);
}

const flush = async (n = 4) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };

interface Turn { beganMs: number; endedMs: number; samples: number; pcmFile: string; sent: boolean; stuck?: boolean }

async function simulate(name: string, pcm: Int16Array, outDir: string, transcribeMs: number, vad: object) {
  let now = 0;
  let onFrame: ((f: AudioFrame) => void) | undefined;
  let current: { beganMs: number; chunks: Int16Array[] } | null = null;
  let pendingEnd: { at: number; resolve: () => void } | null = null;
  const turns: Turn[] = [];
  const states: { atMs: number; state: VoiceState }[] = [];
  const capturing: boolean[] = []; // por quadro: a sessão está capturando fala do usuário?

  const session = new VoiceSession(
    {
      mic: { start: async (cb) => { onFrame = cb; }, stop: () => { onFrame = undefined; } },
      stt: {
        name: "sim", local: true,
        begin: async () => { current = { beganMs: now, chunks: [] }; },
        push: (p) => { current?.chunks.push(p); },
        end: () => new Promise<string>((resolve) => {
          const c = current!;
          current = null;
          const total = c.chunks.reduce((a, x) => a + x.length, 0);
          const all = new Int16Array(total);
          let o = 0;
          for (const x of c.chunks) { all.set(x, o); o += x.length; }
          const file = `${name}__${turns.length}.pcm`;
          writeFileSync(join(outDir, file), Buffer.from(all.buffer));
          turns.push({ beganMs: c.beganMs, endedMs: now, samples: total, pcmFile: file, sent: false });
          // A transcrição leva transcribeMs (tempo simulado); devolve um texto qualquer
          // para a sessão seguir o fluxo normal (o texto real vem do Vosk depois).
          pendingEnd = { at: now + transcribeMs, resolve: () => resolve("transcrito") };
        }),
        abort: () => { current = null; },
      },
      tts: null,
      chat: {
        send: async (_t: string, _id: string): Promise<ChatResult> => {
          turns[turns.length - 1].sent = true;
          return { messageId: "m", content: "" };
        },
        interrupt: async () => undefined,
      },
      now: () => now,
      newId: () => `t${turns.length}`,
      sleep: async () => undefined,
    },
    { onState: (s) => states.push({ atMs: now, state: s }) },
    { confirmBeforeSend: false, ttsEnabled: false, vad },
  );
  await session.start();
  for (let i = 0; i + FRAME <= pcm.length; i += FRAME) {
    now += 20;
    const frame = pcm.slice(i, i + FRAME);
    const f32 = Float32Array.from(frame, (v) => v / 32768);
    onFrame?.({ rms: rmsOf(f32), pcm16: frame, durationMs: 20 });
    capturing.push(session.state === "user_speaking");
    if (pendingEnd && now >= pendingEnd.at) { const p = pendingEnd; pendingEnd = null; p.resolve(); }
    await flush();
  }
  // fim do arquivo: termina transcrições pendentes
  if (pendingEnd) { (pendingEnd as { resolve: () => void }).resolve(); await flush(8); }
  // Ainda capturando no fim: o detector ficou "preso" (o ruído nunca caiu abaixo do
  // limite). Na sessão real isso só acabaria no limite de 30 s, enviando tudo.
  const open = current as { beganMs: number; chunks: Int16Array[] } | null;
  if (open) {
    const total = open.chunks.reduce((a, x) => a + x.length, 0);
    const all = new Int16Array(total);
    let o = 0;
    for (const x of open.chunks) { all.set(x, o); o += x.length; }
    const file = `${name}__${turns.length}.pcm`;
    writeFileSync(join(outDir, file), Buffer.from(all.buffer));
    turns.push({ beganMs: open.beganMs, endedMs: now, samples: total, pcmFile: file, sent: true, stuck: true });
  }
  session.stop();
  const triggers = states.filter((s) => s.state === "user_speaking").length;
  return { name, turns, triggers, states, capturing };
}

const [samplesDir, outDir, transcribeArg, vadFile] = process.argv.slice(2);
if (!samplesDir || !outDir) throw new Error("uso: simulate.ts <samples> <saida> <transcricao_ms> [vad.json]");
mkdirSync(outDir, { recursive: true });
const vad = vadFile ? JSON.parse(readFileSync(vadFile, "utf8")) : {};
const labels = JSON.parse(readFileSync(join(samplesDir, "labels.json"), "utf8"));
const results = [];
for (const s of labels.samples) {
  results.push(await simulate(s.file.replace(/\.wav$/, ""), readWav(join(samplesDir, s.file)), outDir,
    Number(transcribeArg ?? 300), vad));
}
writeFileSync(join(outDir, "simulation.json"), JSON.stringify({
  vadConfig: { ...DEFAULT_VAD, ...vad }, preRollMs: 600, transcribeMs: Number(transcribeArg ?? 300), results,
}));
console.log(`simulação: ${results.length} amostras`);
