// Player da vídeo-aula: mostra cada cena animada e narra com a voz do TITAN.
// Tudo é texto vindo do roteiro validado pelo servidor (nada é interpretado como HTML).
import { useCallback, useEffect, useRef, useState } from "react";
import type { Lesson, LessonScene } from "@titan/api-contracts";
import { api, newRequestId } from "../api";
import { BrowserTts, pickBrowserVoice, ServerTts, StreamingChat } from "../voice/browser";
import { InterruptedError, type Clip, type TtsEngine } from "../voice/player";

const CHARS_PER_SECOND = 14; // ritmo médio de fala, para animar e para o modo sem voz

async function pickNarrator(): Promise<TtsEngine | null> {
  try {
    const st = await api.voiceStatus();
    const server = st.engines.find((e) => e.kind === "tts" && e.available);
    if (server) return new ServerTts(server.name, server.local);
  } catch {
    /* sem voz no servidor */
  }
  const local = typeof window !== "undefined" ? pickBrowserVoice(false) : null;
  return local ? new BrowserTts(local) : null; // só voz do próprio aparelho (nada sai dele)
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(t); reject(new InterruptedError()); }, { once: true });
  });
}

export function LessonPlayer({ lesson, conversationId, onClose }: {
  lesson: Lesson;
  conversationId: string;
  onClose: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [shown, setShown] = useState(0); // itens já revelados na cena
  const [voice, setVoice] = useState<TtsEngine | null | undefined>(undefined);
  const [voiceOn, setVoiceOn] = useState(true);
  const [answer, setAnswer] = useState<number | null>(null);
  const [asking, setAsking] = useState(false);
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<string | null>(null);
  const runRef = useRef<AbortController | null>(null);
  const clipRef = useRef<Clip | null>(null);
  const total = lesson.cenas.length;
  const scene = lesson.cenas[index];
  const atEnd = index >= total - 1;

  useEffect(() => { void pickNarrator().then(setVoice); }, []);

  const stopAudio = useCallback(() => {
    runRef.current?.abort();
    runRef.current = null;
    clipRef.current?.stop();
    clipRef.current = null;
  }, []);

  useEffect(() => stopAudio, [stopAudio]);

  const say = useCallback(async (text: string, signal: AbortSignal) => {
    const ms = Math.max(1800, (text.length / CHARS_PER_SECOND) * 1000);
    if (!text || !voiceOn || !voice) return wait(text ? ms : 1200, signal);
    try {
      const clip = await voice.prepare(text, signal);
      if (signal.aborted) throw new InterruptedError();
      clipRef.current = clip;
      await clip.play();
    } catch (e) {
      if (e instanceof InterruptedError || signal.aborted) throw new InterruptedError();
      await wait(ms, signal); // voz falhou: segue no tempo da leitura
    }
  }, [voice, voiceOn]);

  // Roda a cena atual: revela os itens no ritmo da fala e avança sozinha no fim.
  useEffect(() => {
    if (voice === undefined || !playing || asking) return;
    stopAudio();
    const ctrl = new AbortController();
    runRef.current = ctrl;
    const s = lesson.cenas[index];
    const count = itemCount(s);
    setShown(0);
    const step = Math.max(600, (s.narracao.length / CHARS_PER_SECOND) * 1000 / (count + 1));
    let n = 0;
    const timer = setInterval(() => { n += 1; setShown((v) => Math.max(v, n)); if (n >= count) clearInterval(timer); }, step);
    (async () => {
      try {
        const speech = s.tipo === "pergunta" && s.pergunta ? `${s.narracao} ${s.pergunta.enunciado}` : s.narracao;
        await say(speech, ctrl.signal);
        setShown(count);
        if (s.tipo === "pergunta") return; // espera a resposta
        await wait(900, ctrl.signal);
        if (index < total - 1) setIndex(index + 1);
        else setPlaying(false);
      } catch {
        /* interrompido (pausa, troca de cena ou fechar) */
      }
    })();
    return () => { clearInterval(timer); ctrl.abort(); clipRef.current?.stop(); };
  }, [index, playing, asking, voice, lesson, say, stopAudio, total]);

  function go(to: number) {
    stopAudio();
    setAnswer(null);
    setReply(null);
    setIndex(Math.max(0, Math.min(total - 1, to)));
    setPlaying(true);
  }

  function choose(i: number) {
    if (answer !== null || !scene.pergunta) return;
    setAnswer(i);
    stopAudio();
    const ok = i === scene.pergunta.correta;
    const ctrl = new AbortController();
    runRef.current = ctrl;
    void say(`${ok ? "Isso mesmo!" : "Não é essa."} ${scene.pergunta.explicacao}`, ctrl.signal).catch(() => {});
  }

  async function ask() {
    const q = question.trim();
    if (!q) return;
    setReply("…");
    const chat = new StreamingChat(async () => conversationId, voiceOn && voice ? "voice" : "text");
    const context = `[Pergunta durante a vídeo-aula "${lesson.titulo}", cena ${index + 1}: "${scene.titulo}". ` +
      `O que a cena dizia: ${scene.narracao}] ${q}`;
    let acc = "";
    const ctrl = new AbortController();
    runRef.current = ctrl;
    try {
      const res = await chat.send(context, newRequestId(), ctrl.signal, (d) => { acc += d; setReply(acc); });
      setReply(res.content);
      setQuestion("");
      await say(res.content.slice(0, 780), ctrl.signal);
    } catch (e) {
      if (!ctrl.signal.aborted) setReply(`Não consegui responder agora: ${(e as Error).message}`);
    }
  }

  return (
    <div className="lesson-overlay" role="dialog" aria-modal="true" aria-label={`Vídeo-aula: ${lesson.titulo}`}>
      <div className="lesson">
        <header className="lesson-head">
          <span className="lesson-title" title={lesson.titulo}>{lesson.titulo}</span>
          <span className="lesson-count">{index + 1}/{total}</span>
          <button className="ghost small" onClick={() => { stopAudio(); onClose(); }} aria-label="Fechar aula">Fechar</button>
        </header>
        <div className="lesson-progress" aria-hidden="true">
          {lesson.cenas.map((_, i) => <span key={i} className={i < index ? "done" : i === index ? "now" : ""} />)}
        </div>
        <section className={`lesson-stage scene-${scene.tipo}`} key={index}>
          <h2 className="scene-title">{scene.titulo}</h2>
          <SceneBody s={scene} shown={shown} answer={answer} onChoose={choose} />
          {atEnd && lesson.fontes.length > 0 && (
            <ol className="sources lesson-sources">
              {lesson.fontes.map((f) => (
                <li key={f.n}><span className="src-n">[{f.n}]</span>{" "}
                  <a href={f.url} target="_blank" rel="noopener noreferrer nofollow">{f.title}</a>
                  <span className="src-site"> · {f.site}</span></li>
              ))}
            </ol>
          )}
        </section>
        <p className="lesson-caption" aria-live="polite">{scene.narracao}</p>
        {asking && (
          <div className="lesson-ask">
            <div className="row">
              <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="O que você não entendeu?"
                     onKeyDown={(e) => { if (e.key === "Enter") void ask(); }} maxLength={1000} autoFocus />
              <button className="small" onClick={() => void ask()} disabled={!question.trim()}>Perguntar</button>
            </div>
            {reply && <p className="lesson-reply">{reply}</p>}
            <button className="ghost small" onClick={() => { stopAudio(); setAsking(false); setReply(null); setPlaying(true); }}>
              Continuar a aula
            </button>
          </div>
        )}
        <footer className="lesson-controls">
          <button className="ghost" onClick={() => go(index - 1)} disabled={index === 0} aria-label="Cena anterior">⏮</button>
          {playing && !asking ? (
            <button onClick={() => { stopAudio(); setPlaying(false); }} aria-label="Pausar">⏸ Pausar</button>
          ) : (
            <button onClick={() => { setAsking(false); setPlaying(true); }} aria-label="Continuar">▶ {atEnd && !playing ? "Repetir cena" : "Continuar"}</button>
          )}
          <button className="ghost" onClick={() => go(index + 1)} disabled={atEnd} aria-label="Próxima cena">⏭</button>
          <button className="ghost small" onClick={() => { stopAudio(); setPlaying(false); setAsking(true); }}>Perguntar</button>
          <button className="ghost small" onClick={() => { stopAudio(); setVoiceOn((v) => !v); }} aria-pressed={voiceOn}
                  disabled={!voice}
                  title={voice ? `Voz: ${voice.name}` : "Sem voz disponível: a aula avança no tempo da leitura"}>
            {!voice ? "Sem voz" : voiceOn ? "Voz: ligada" : "Voz: desligada"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function itemCount(s: LessonScene): number {
  if (s.tipo === "comparacao" && s.comparacao) return Math.max(s.comparacao.a_itens.length, s.comparacao.b_itens.length);
  if (s.tipo === "grafico" && s.grafico) return s.grafico.dados.length;
  if (s.tipo === "pergunta") return s.pergunta?.opcoes.length ?? 0;
  return s.itens.length;
}

function SceneBody({ s, shown, answer, onChoose }: {
  s: LessonScene; shown: number; answer: number | null; onChoose: (i: number) => void;
}) {
  const vis = (i: number) => (i < shown ? "in" : "out");
  switch (s.tipo) {
    case "passos":
      return (
        <ol className="lesson-steps">
          {s.itens.map((t, i) => <li key={i} className={vis(i)}><span className="step-n">{i + 1}</span>{t}</li>)}
        </ol>
      );
    case "linha_do_tempo":
      return (
        <ol className="lesson-timeline">
          {s.itens.map((t, i) => {
            const at = t.indexOf(":");
            return (
              <li key={i} className={vis(i)}>
                {at > 0 && at < 20 ? <><b>{t.slice(0, at)}</b><span>{t.slice(at + 1).trim()}</span></> : <span>{t}</span>}
              </li>
            );
          })}
        </ol>
      );
    case "formula":
      return <div className="lesson-formula">{s.itens.map((t, i) => <div key={i} className={vis(i)}>{t}</div>)}</div>;
    case "comparacao": {
      const c = s.comparacao!;
      return (
        <div className="lesson-compare">
          {[[c.a_titulo, c.a_itens], [c.b_titulo, c.b_itens]].map(([title, items], col) => (
            <div key={col} className="compare-col">
              <h3>{title as string}</h3>
              <ul>{(items as string[]).map((t, i) => <li key={i} className={vis(i)}>{t}</li>)}</ul>
            </div>
          ))}
        </div>
      );
    }
    case "grafico":
      return <Chart g={s.grafico!} shown={shown} />;
    case "diagrama":
      return <Diagram nodes={s.itens} cycle={s.diagrama_forma === "ciclo"} shown={shown} />;
    case "pergunta": {
      const q = s.pergunta!;
      return (
        <div className="lesson-quiz">
          <p className="quiz-q">{q.enunciado}</p>
          <div className="quiz-options">
            {q.opcoes.map((o, i) => {
              const state = answer === null ? "" : i === q.correta ? "right" : i === answer ? "wrong" : "dim";
              return (
                <button key={i} className={`ghost quiz-opt ${state} ${vis(i)}`} onClick={() => onChoose(i)} disabled={answer !== null}>
                  <span className="opt-letter">{String.fromCharCode(65 + i)}</span>{o}
                </button>
              );
            })}
          </div>
          {answer !== null && (
            <p className={`quiz-result ${answer === q.correta ? "ok" : "bad"}`}>
              {answer === q.correta ? "Acertou! " : `Resposta certa: ${String.fromCharCode(65 + q.correta)}. `}{q.explicacao}
            </p>
          )}
        </div>
      );
    }
    default:
      return <ul className="lesson-points">{s.itens.map((t, i) => <li key={i} className={vis(i)}>{t}</li>)}</ul>;
  }
}

const PIE_COLORS = ["#7cb0f0", "#5cc79a", "#e3b55a", "#f07a7a", "#b48ef0", "#5fc6d4", "#d49a6a", "#9aa6b2"];

function Chart({ g, shown }: { g: NonNullable<LessonScene["grafico"]>; shown: number }) {
  const max = Math.max(...g.dados.map((d) => d.valor), 0) || 1;
  const fmt = (v: number) => `${v.toLocaleString("pt-BR")}${g.unidade ? ` ${g.unidade}` : ""}`;
  if (g.forma === "pizza") {
    const sum = g.dados.reduce((a, d) => a + d.valor, 0) || 1;
    let acc = 0;
    const stops = g.dados.map((d, i) => {
      const from = (acc / sum) * 360;
      acc += d.valor;
      return `${PIE_COLORS[i % PIE_COLORS.length]} ${from}deg ${(acc / sum) * 360}deg`;
    });
    return (
      <div className="lesson-pie">
        <div className="pie" style={{ background: `conic-gradient(${stops.join(", ")})` }} role="img"
             aria-label={g.dados.map((d) => `${d.rotulo}: ${fmt(d.valor)}`).join("; ")} />
        <ul>
          {g.dados.map((d, i) => (
            <li key={i} className={i < shown ? "in" : "out"}>
              <span className="swatch" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
              {d.rotulo}: {fmt(d.valor)} ({Math.round((d.valor / sum) * 100)}%)
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <div className="lesson-bars">
      {g.dados.map((d, i) => (
        <div key={i} className="bar-row">
          <span className="bar-label">{d.rotulo}</span>
          <span className="bar-track"><span className="bar" style={{ width: i < shown ? `${(d.valor / max) * 100}%` : "0%" }} /></span>
          <span className="bar-value">{fmt(d.valor)}</span>
        </div>
      ))}
    </div>
  );
}

function Diagram({ nodes, cycle, shown }: { nodes: string[]; cycle: boolean; shown: number }) {
  if (!cycle) {
    return (
      <div className="lesson-flow">
        {nodes.map((t, i) => (
          <div key={i} className={`flow-item ${i < shown ? "in" : "out"}`}>
            <span className="flow-box">{t}</span>
            {i < nodes.length - 1 && <span className="flow-arrow" aria-hidden="true">➜</span>}
          </div>
        ))}
      </div>
    );
  }
  const n = nodes.length;
  const pos = (i: number) => {
    const a = (i / n) * 2 * Math.PI - Math.PI / 2;
    return { x: 50 + 36 * Math.cos(a), y: 50 + 36 * Math.sin(a) };
  };
  return (
    <div className="lesson-cycle">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <defs>
          <marker id="cyc-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0 0 10 5 0 10z" fill="currentColor" />
          </marker>
        </defs>
        <circle cx="50" cy="50" r="36" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeDasharray="2 2" />
        {nodes.map((_, i) => {
          const a = pos(i), b = pos((i + 1) % n);
          const mx = a.x + (b.x - a.x) * 0.3, my = a.y + (b.y - a.y) * 0.3;
          const ex = a.x + (b.x - a.x) * 0.7, ey = a.y + (b.y - a.y) * 0.7;
          return <line key={i} x1={mx} y1={my} x2={ex} y2={ey} stroke="currentColor" strokeWidth="0.8"
                       markerEnd="url(#cyc-arrow)" opacity={i < shown ? 1 : 0.15} />;
        })}
      </svg>
      {nodes.map((t, i) => {
        const p = pos(i);
        return <span key={i} className={`cycle-node ${i < shown ? "in" : "out"}`} style={{ left: `${p.x}%`, top: `${p.y}%` }}>{t}</span>;
      })}
    </div>
  );
}
