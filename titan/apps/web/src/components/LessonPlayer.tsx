// Player da vídeo-aula: mostra cada cena animada e narra com a voz do TITAN.
// Tudo é texto vindo do roteiro validado pelo servidor (nada é interpretado como HTML);
// ícones e cores vêm de listas fechadas. Perguntas, teorias e "explicar mais simples"
// viram uma continuação em vídeo, inserida logo depois da cena atual.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Lesson, LessonLevel, LessonScene } from "@titan/api-contracts";
import { api, newRequestId } from "../api";
import { BrowserTts, pickBrowserVoice, ServerTts } from "../voice/browser";
import { InterruptedError, type Clip, type TtsEngine } from "../voice/player";
import { LessonIcon, hasLessonIcon } from "./lessonIcons";

const CHARS_PER_SECOND = 14; // ritmo médio de fala, para animar e para o modo sem voz
const SUBJECT_LABEL: Record<string, string> = {
  ciencia: "Ciência", historia: "História", matematica: "Matemática", tecnologia: "Tecnologia",
  portugues: "Português", geografia: "Geografia", saude: "Saúde", dinheiro: "Dinheiro", arte: "Arte", outro: "Aula",
};
const LEVEL_LABEL: Record<string, string> = { crianca: "para criança", basico: "nível básico", avancado: "nível avançado" };
const VERDICT: Record<string, string> = {
  "correta": "Sua ideia está correta", "parcialmente correta": "Sua ideia está em parte correta",
  "incorreta": "Sua ideia não se confirma", "não dá para saber": "Ainda não dá para saber",
};

/** Uma cena na fila do player: de qual aula (parte) ela veio e o índice dentro dela. */
interface Item { scene: LessonScene; part: string; local: number; tag?: string }

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

const speechOf = (s: LessonScene) => (s.tipo === "pergunta" && s.pergunta ? `${s.narracao} ${s.pergunta.enunciado}` : s.narracao);

function itemCount(s: LessonScene): number {
  switch (s.tipo) {
    case "comparacao": return Math.max(s.comparacao?.a_itens.length ?? 0, s.comparacao?.b_itens.length ?? 0);
    case "grafico": return s.grafico?.dados.length ?? 0;
    case "pergunta": return s.pergunta?.opcoes.length ?? 0;
    case "tabela": return s.tabela?.linhas.length ?? 0;
    case "teoria": return (s.teoria?.certo.length ?? 0) + (s.teoria?.errado.length ?? 0) + 1;
    case "erro_comum": case "destaque": return 2;
    default: return s.itens.length;
  }
}

export function LessonPlayer({ lesson, messageId, conversationId, onClose, onChanged }: {
  lesson: Lesson;
  messageId: string;
  conversationId: string;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const [items, setItems] = useState<Item[]>(() => lesson.cenas.map((scene, local) => ({ scene, part: messageId, local })));
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [shown, setShown] = useState(0);
  const [progress, setProgress] = useState(0); // 0..1 da narração da cena (legenda karaokê)
  const [voice, setVoice] = useState<TtsEngine | null | undefined>(undefined);
  const [voiceOn, setVoiceOn] = useState(true);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [asking, setAsking] = useState(false);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  const [showResult, setShowResult] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const runRef = useRef<AbortController | null>(null);
  const clipRef = useRef<Clip | null>(null);
  const total = items.length;
  const item = items[Math.min(index, total - 1)];
  const scene = item.scene;
  const key = (it: Item) => `${it.part}:${it.local}`;
  const quizzes = useMemo(() => items.filter((it) => it.scene.tipo === "pergunta"), [items]);
  const atEnd = index >= total - 1;
  const theme = `theme-${lesson.assunto ?? "outro"}`;

  useEffect(() => { void pickNarrator().then(setVoice); }, []);

  const stopAudio = useCallback(() => {
    runRef.current?.abort();
    runRef.current = null;
    clipRef.current?.stop();
    clipRef.current = null;
  }, []);
  useEffect(() => stopAudio, [stopAudio]);

  useEffect(() => {
    const on = () => setFull(document.fullscreenElement === rootRef.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);

  /** Fala o texto (ou espera o tempo de leitura) atualizando o progresso da legenda. */
  const say = useCallback(async (text: string, signal: AbortSignal) => {
    const estimate = Math.max(1.8, text.length / CHARS_PER_SECOND);
    let seconds = estimate;
    let started = performance.now();
    const tick = setInterval(() => setProgress(Math.min(1, (performance.now() - started) / 1000 / seconds)), 120);
    try {
      if (!text || !voiceOn || !voice) {
        setProgress(0);
        await wait(seconds * 1000, signal);
        return;
      }
      try {
        const clip = await voice.prepare(text, signal);
        if (signal.aborted) throw new InterruptedError();
        clipRef.current = clip;
        seconds = clip.duration || estimate;
        started = performance.now();
        setProgress(0);
        await clip.play();
      } catch (e) {
        if (e instanceof InterruptedError || signal.aborted) throw new InterruptedError();
        started = performance.now();
        await wait(seconds * 1000, signal); // voz falhou: segue no tempo da leitura
      }
    } finally {
      clearInterval(tick);
    }
  }, [voice, voiceOn]);

  // Roda a cena atual: revela os itens no ritmo da fala e avança sozinha no fim.
  useEffect(() => {
    if (voice === undefined || !playing || asking || busy || showResult) return;
    stopAudio();
    const ctrl = new AbortController();
    runRef.current = ctrl;
    const s = items[index].scene;
    const count = itemCount(s);
    setShown(0);
    setProgress(0);
    const step = Math.max(650, (s.narracao.length / CHARS_PER_SECOND) * 1000 / (count + 1));
    let n = 0;
    const timer = setInterval(() => { n += 1; setShown((v) => Math.max(v, n)); if (n >= count) clearInterval(timer); }, step);
    (async () => {
      try {
        await say(speechOf(s), ctrl.signal);
        setShown(count);
        setProgress(1);
        if (s.tipo === "pergunta" && answers[key(items[index])] === undefined) return; // espera a resposta
        await wait(1000, ctrl.signal);
        if (index < items.length - 1) setIndex(index + 1);
        else if (quizzes.length) setShowResult(true);
        else setPlaying(false);
      } catch {
        /* interrompido (pausa, troca de cena ou fechar) */
      }
    })();
    return () => { clearInterval(timer); ctrl.abort(); clipRef.current?.stop(); };
    // answers fica de fora de propósito: responder não reinicia a cena
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, playing, asking, busy, showResult, voice, items, say, stopAudio, quizzes.length]);

  function go(to: number) {
    stopAudio();
    setShowResult(false);
    setError(null);
    setIndex(Math.max(0, Math.min(total - 1, to)));
    setPlaying(true);
  }

  function choose(i: number) {
    const q = scene.pergunta;
    if (!q || answers[key(item)] !== undefined) return;
    setAnswers((a) => ({ ...a, [key(item)]: i }));
    stopAudio();
    const ctrl = new AbortController();
    runRef.current = ctrl;
    const here = index;
    void (async () => {
      try {
        await say(`${i === q.correta ? "Isso mesmo!" : "Não é essa."} ${q.explicacao}`, ctrl.signal);
        await wait(1200, ctrl.signal);
        if (here < items.length - 1) setIndex(here + 1);
        else setShowResult(true);
      } catch {
        /* interrompido */
      }
    })();
  }

  /** Pede uma continuação em vídeo (pergunta/teoria ou "mais simples") e a insere após a cena atual. */
  async function extend(text: string, simpler: boolean) {
    stopAudio();
    setBusy(simpler ? "Preparando uma explicação mais simples…" : "Preparando a resposta em vídeo…");
    setError(null);
    try {
      const r = await api.createLesson(conversationId, text, newRequestId(), {
        continues: item.part, focus_scene: item.local, simpler, level: (lesson.nivel ?? "basico") as LessonLevel,
      });
      if (!r.lesson || !r.reply) throw new Error(r.model.detail);
      const tag = simpler ? "Mais simples" : "Sua pergunta";
      const extra = r.lesson.cenas.map((s, local) => ({ scene: s, part: r.reply!.id, local, tag }));
      setItems((list) => [...list.slice(0, index + 1), ...extra, ...list.slice(index + 1)]);
      setQuestion("");
      setAsking(false);
      setShowResult(false);
      setIndex(index + 1);
      setPlaying(true);
      onChanged?.();
    } catch (e) {
      setError(`Não consegui preparar agora: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  function toggleFull() {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    else void rootRef.current?.requestFullscreen?.().catch(() => {});
  }

  function review(target: Item) {
    const q = target.scene.pergunta;
    if (!q || q.revisar_cena === undefined || q.revisar_cena < 0) return;
    const to = items.findIndex((it) => it.part === target.part && it.local === q.revisar_cena);
    if (to >= 0) go(to);
  }

  const right = quizzes.filter((it) => answers[key(it)] === it.scene.pergunta!.correta).length;

  return (
    <div ref={rootRef} className={`lesson-overlay ${theme} ${full ? "is-full" : ""}`} role="dialog" aria-modal="true"
         aria-label={`Vídeo-aula: ${lesson.titulo}`}>
      <div className="lesson">
        <header className="lesson-head">
          <span className="lesson-tag">{SUBJECT_LABEL[lesson.assunto ?? "outro"] ?? "Aula"}</span>
          <span className="lesson-title" title={lesson.titulo}>
            {lesson.titulo}{lesson.nivel ? <span className="lesson-meta"> · {LEVEL_LABEL[lesson.nivel]}</span> : null}
          </span>
          <span className="lesson-count">{showResult ? "fim" : `${index + 1}/${total}`}</span>
          <button className="ghost small" onClick={() => { stopAudio(); if (document.fullscreenElement) void document.exitFullscreen().catch(() => {}); onClose(); }}
                  aria-label="Fechar aula">Fechar</button>
        </header>
        <div className="lesson-progress" aria-hidden="true">
          {items.map((it, i) => (
            <span key={i} className={`${i < index || showResult ? "done" : i === index ? "now" : ""} ${it.tag ? "extra" : ""}`} />
          ))}
        </div>
        <section className={`lesson-stage scene-${showResult ? "resultado" : scene.tipo}`} key={showResult ? "res" : `${key(item)}-${index}`}>
          {busy ? (
            <div className="lesson-busy"><span className="spinner" aria-hidden="true" /><p>{busy}</p></div>
          ) : showResult ? (
            <Result quizzes={quizzes} answers={answers} keyOf={key} right={right} onReview={review} />
          ) : (
            <>
              {item.tag && <span className="scene-tag">{item.tag}</span>}
              {scene.tipo !== "capa" && (
                <h2 className="scene-title">{hasLessonIcon(scene.icone) && <LessonIcon name={scene.icone} size={30} />}{scene.titulo}</h2>
              )}
              <SceneBody s={scene} shown={shown} answer={answers[key(item)] ?? null} onChoose={choose} lesson={lesson} />
              {atEnd && !quizzes.length && lesson.fontes.length > 0 && <Sources lesson={lesson} />}
            </>
          )}
        </section>
        {!busy && !showResult && <Caption text={speechOf(scene)} progress={progress} />}
        {error && <p className="lesson-error">{error}</p>}
        {asking && !busy && (
          <div className="lesson-ask">
            <div className="row">
              <input value={question} onChange={(e) => setQuestion(e.target.value)}
                     placeholder="Pergunte ou diga sua teoria (ex.: e se a planta ficar no escuro?)"
                     onKeyDown={(e) => { if (e.key === "Enter" && question.trim()) void extend(question.trim(), false); }}
                     maxLength={1000} autoFocus />
              <button className="small" onClick={() => void extend(question.trim(), false)} disabled={!question.trim()}>
                Responder em vídeo
              </button>
            </div>
            <button className="ghost small" onClick={() => { setAsking(false); setPlaying(true); }}>Voltar para a aula</button>
          </div>
        )}
        <footer className="lesson-controls">
          {showResult ? (
            <>
              <button className="ghost" onClick={() => { setAnswers({}); go(0); }}>↻ Rever aula</button>
              <button className="primary-play" onClick={() => { setShowResult(false); setAsking(true); setPlaying(false); }}>Perguntar mais</button>
            </>
          ) : (
            <>
              <button className="ghost" onClick={() => go(index - 1)} disabled={index === 0 || !!busy} aria-label="Cena anterior">⏮</button>
              {playing && !asking ? (
                <button className="primary-play" onClick={() => { stopAudio(); setPlaying(false); }} disabled={!!busy} aria-label="Pausar">⏸ Pausar</button>
              ) : (
                <button className="primary-play" onClick={() => { setAsking(false); setPlaying(true); }} disabled={!!busy} aria-label="Continuar">▶ Continuar</button>
              )}
              <button className="ghost" onClick={() => (atEnd && quizzes.length ? (stopAudio(), setShowResult(true)) : go(index + 1))}
                      disabled={(atEnd && !quizzes.length) || !!busy} aria-label="Próxima cena">⏭</button>
              <button className="ghost small" disabled={!!busy || scene.tipo === "pergunta"}
                      onClick={() => void extend(`Explica de novo, mais simples, a parte "${scene.titulo}".`, true)}>
                Explicar mais simples
              </button>
              <button className="ghost small" disabled={!!busy} onClick={() => { stopAudio(); setPlaying(false); setAsking(true); }}>
                Perguntar
              </button>
            </>
          )}
          <button className="ghost small" onClick={toggleFull} aria-pressed={full}>{full ? "Sair da tela cheia" : "⛶ Tela cheia"}</button>
          <button className="ghost small" onClick={() => { stopAudio(); setVoiceOn((v) => !v); }} aria-pressed={voiceOn}
                  disabled={!voice} title={voice ? `Voz: ${voice.name}` : "Sem voz disponível: a aula avança no tempo da leitura"}>
            {!voice ? "Sem voz" : voiceOn ? "Voz: ligada" : "Voz: desligada"}
          </button>
        </footer>
      </div>
    </div>
  );
}

/** Legenda estilo karaokê: as palavras já faladas ficam claras e o trecho atual, destacado
 *  (aproximado: a voz não informa o tempo de cada palavra). */
function Caption({ text, progress }: { text: string; progress: number }) {
  const words = text.split(/\s+/).filter(Boolean);
  const at = Math.min(words.length - 1, Math.floor(progress * words.length));
  return (
    <p className="lesson-caption" aria-live="polite" aria-label={text}>
      {words.map((w, i) => (
        <span key={i} className={i < at - 1 ? "said" : i <= at + 1 && progress > 0 ? "now" : ""}>{w} </span>
      ))}
    </p>
  );
}

function Sources({ lesson }: { lesson: Lesson }) {
  return (
    <ol className="sources lesson-sources">
      {lesson.fontes.map((f) => (
        <li key={f.n}><span className="src-n">[{f.n}]</span>{" "}
          <a href={f.url} target="_blank" rel="noopener noreferrer nofollow">{f.title}</a>
          <span className="src-site"> · {f.site}</span></li>
      ))}
    </ol>
  );
}

function Result({ quizzes, answers, keyOf, right, onReview }: {
  quizzes: Item[]; answers: Record<string, number>; keyOf: (it: Item) => string; right: number; onReview: (it: Item) => void;
}) {
  const pct = quizzes.length ? Math.round((right / quizzes.length) * 100) : 0;
  return (
    <div className="lesson-result">
      <h2 className="scene-title">{quizzes.length && right === quizzes.length ? "Você acertou tudo! 🎉" : `Você acertou ${right} de ${quizzes.length}`}</h2>
      <div className="result-grid">
        <div className="score-ring" style={{ ["--pct" as string]: `${pct}%` }}><div><CountUp value={`${pct}%`} /></div></div>
        <div className="result-list">
          {quizzes.map((it, i) => {
            const q = it.scene.pergunta!;
            const a = answers[keyOf(it)];
            const ok = a === q.correta;
            return (
              <div key={i} className={`result-row ${a === undefined ? "skip" : ok ? "ok" : "bad"}`}>
                <LessonIcon name={a === undefined ? "pergunta" : ok ? "check" : "alerta"} size={20} />
                <span className="rq">{q.enunciado}</span>
                <span className="ra">
                  {a === undefined ? "não respondida" : ok ? q.opcoes[q.correta] : <>você: {q.opcoes[a]} · certa: <b>{q.opcoes[q.correta]}</b></>}
                </span>
                {!ok && (q.revisar_cena ?? -1) >= 0 && <button className="link small" onClick={() => onReview(it)}>↻ Rever essa parte</button>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** Anima o número de um texto (ex.: "21%", "1.773.718 habitantes") de zero até o valor. */
function CountUp({ value }: { value: string }) {
  const m = /^(\D*?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(.*)$/.exec(value);
  const [shown, setShown] = useState(m ? 0 : 1);
  useEffect(() => {
    if (!m) return;
    const t0 = performance.now();
    const id = setInterval(() => {
      const k = Math.min(1, (performance.now() - t0) / 1200);
      setShown(1 - Math.pow(1 - k, 3));
      if (k >= 1) clearInterval(id);
    }, 40);
    return () => clearInterval(id);
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!m) return <>{value}</>;
  const decimals = m[3]?.length ?? 0;
  const target = Number(m[2].replace(/\./g, "") + (m[3] ? `.${m[3]}` : ""));
  const now = (target * shown).toLocaleString("pt-BR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  return <>{m[1]}{now}{m[4]}</>;
}

function SceneBody({ s, shown, answer, onChoose, lesson }: {
  s: LessonScene; shown: number; answer: number | null; onChoose: (i: number) => void; lesson: Lesson;
}) {
  const vis = (i: number) => (i < shown ? `in${i === shown - 1 ? " now" : ""}` : "out");
  const icon = (i: number) => s.icones_itens?.[i];
  switch (s.tipo) {
    case "capa":
      return (
        <div className="scene-capa">
          <div>
            <h1 className="capa-title">{s.titulo || lesson.titulo}</h1>
            {s.itens.length > 0 && <p className="capa-sub">Nesta aula você vai aprender:</p>}
            <ul className="capa-list">
              {s.itens.map((t, i) => <li key={i} className={vis(i)}><IconChip name={icon(i) ?? "check"} />{t}</li>)}
            </ul>
          </div>
          {hasLessonIcon(s.icone) && <LessonIcon name={s.icone} size={170} className="capa-icon" />}
        </div>
      );
    case "passos":
    case "exemplo":
      return (
        <ol className={`lesson-steps ${s.tipo === "exemplo" ? "is-example" : ""}`}>
          {s.tipo === "exemplo" && <li className="example-tag in"><LessonIcon name="lampada" size={18} /> Exemplo do dia a dia</li>}
          {s.itens.map((t, i) => (
            <li key={i} className={vis(i)}>
              <span className="step-n">{hasLessonIcon(icon(i)) ? <LessonIcon name={icon(i)} size={18} /> : i + 1}</span>{t}
            </li>
          ))}
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
          {([[c.a_titulo, c.a_itens], [c.b_titulo, c.b_itens]] as [string, string[]][]).map(([title, list], col) => (
            <div key={col} className={`compare-col col-${col}`}>
              <h3>{title}</h3>
              <ul>{list.map((t, i) => <li key={i} className={vis(i)}>{t}</li>)}</ul>
            </div>
          ))}
          <span className="vs" aria-hidden="true">vs</span>
        </div>
      );
    }
    case "grafico":
      return <Chart g={s.grafico!} shown={shown} />;
    case "diagrama":
      return <Diagram nodes={s.itens} icons={s.icones_itens ?? []} cycle={s.diagrama_forma === "ciclo"} shown={shown} />;
    case "mapa_mental":
      return <MindMap center={s.centro || s.titulo} branches={s.itens} icons={s.icones_itens ?? []} shown={shown} />;
    case "destaque": {
      const d = s.destaque!;
      return (
        <div className="scene-stat">
          {d.percentual >= 0 ? (
            <div className="stat-ring" style={{ ["--pct" as string]: shown > 0 ? `${d.percentual}%` : "0%" }}>
              <div><b><CountUp value={d.valor} /></b></div>
            </div>
          ) : (
            <div className="stat-num"><CountUp value={d.valor} /></div>
          )}
          <p className={`stat-label ${vis(1)}`}>{d.rotulo}</p>
        </div>
      );
    }
    case "curiosidade":
      return (
        <div className="callout tip">
          <IconChip name={s.icone && hasLessonIcon(s.icone) ? s.icone : "lampada"} big />
          <div><small>VOCÊ SABIA?</small>{s.itens.map((t, i) => <p key={i} className={vis(i)}>{t}</p>)}</div>
        </div>
      );
    case "erro_comum": {
      const e = s.erro_comum!;
      return (
        <div className="callout err">
          <small>ERRO COMUM</small>
          <p className={`wrong ${vis(0)}`}><LessonIcon name="alerta" size={20} />“{e.errado}”</p>
          <p className={`right ${vis(1)}`}><LessonIcon name="check" size={20} />{e.certo}</p>
        </div>
      );
    }
    case "tabela": {
      const t = s.tabela!;
      return (
        <div className="lesson-table-wrap">
          <table className="lesson-table">
            <thead><tr>{t.colunas.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
            <tbody>{t.linhas.map((r, i) => <tr key={i} className={vis(i)}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
          </table>
        </div>
      );
    }
    case "teoria": {
      const t = s.teoria!;
      const tone = t.veredito === "correta" ? "ok" : t.veredito === "incorreta" ? "bad" : "mid";
      return (
        <div className="scene-theory">
          <blockquote className="theory-idea">“{t.ideia}”</blockquote>
          <p className={`theory-verdict ${tone} ${vis(0)}`}>{VERDICT[t.veredito]}</p>
          <div className="theory-cols">
            {t.certo.length > 0 && (
              <ul className="theory-ok">{t.certo.map((x, i) => <li key={i} className={vis(i + 1)}><LessonIcon name="check" size={18} />{x}</li>)}</ul>
            )}
            {t.errado.length > 0 && (
              <ul className="theory-bad">{t.errado.map((x, i) => <li key={i} className={vis(i + 1 + t.certo.length)}><LessonIcon name="alerta" size={18} />{x}</li>)}</ul>
            )}
          </div>
        </div>
      );
    }
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
    default: {
      const cards = s.itens.length > 0 && s.itens.length <= 4 && (s.icones_itens ?? []).some(hasLessonIcon);
      if (cards) {
        return (
          <div className={`lesson-cards n${s.itens.length}`}>
            {s.itens.map((t, i) => {
              const [head, ...rest] = t.split(/:\s+|\s+[–—-]\s+/);
              return (
                <div key={i} className={`lcard ${vis(i)}`}>
                  <IconChip name={icon(i) ?? "check"} big />
                  <b>{head}</b>{rest.length > 0 && <span>{rest.join(" — ")}</span>}
                </div>
              );
            })}
          </div>
        );
      }
      return (
        <ul className="lesson-points">
          {s.itens.map((t, i) => <li key={i} className={vis(i)}>{hasLessonIcon(icon(i)) ? <IconChip name={icon(i)} /> : <span className="dot" />}{t}</li>)}
        </ul>
      );
    }
  }
}

function IconChip({ name, big }: { name?: string; big?: boolean }): ReactNode {
  return <span className={`ichip ${big ? "big" : ""}`}><LessonIcon name={hasLessonIcon(name) ? name : "check"} size={big ? 28 : 18} /></span>;
}

const PIE = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)", "var(--c7)", "var(--c8)"];

function Chart({ g, shown }: { g: NonNullable<LessonScene["grafico"]>; shown: number }) {
  const max = Math.max(...g.dados.map((d) => d.valor), 0) || 1;
  const fmt = (v: number) => `${v.toLocaleString("pt-BR")}${g.unidade ? ` ${g.unidade}` : ""}`;
  if (g.forma === "pizza") {
    const sum = g.dados.reduce((a, d) => a + d.valor, 0) || 1;
    let acc = 0;
    const stops = g.dados.map((d, i) => {
      const from = (acc / sum) * 360;
      acc += i < shown ? d.valor : 0;
      return `${PIE[i % PIE.length]} ${from}deg ${(acc / sum) * 360}deg`;
    });
    return (
      <div className="lesson-pie">
        <div className="pie" style={{ background: `conic-gradient(${stops.join(", ")}, rgba(255,255,255,.05) 0)` }} role="img"
             aria-label={g.dados.map((d) => `${d.rotulo}: ${fmt(d.valor)}`).join("; ")} />
        <ul>
          {g.dados.map((d, i) => (
            <li key={i} className={i < shown ? "in" : "out"}>
              <span className="swatch" style={{ background: PIE[i % PIE.length] }} />
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
        <div key={i} className={`bar-row ${i === shown - 1 ? "now" : ""}`}>
          <span className="bar-label">{d.rotulo}</span>
          <span className="bar-track"><span className="bar" style={{ width: i < shown ? `${(d.valor / max) * 100}%` : "0%" }} /></span>
          <span className="bar-value">{i < shown ? <CountUp value={fmt(d.valor)} /> : ""}</span>
        </div>
      ))}
    </div>
  );
}

function Diagram({ nodes, icons, cycle, shown }: { nodes: string[]; icons: string[]; cycle: boolean; shown: number }) {
  if (!cycle) {
    return (
      <div className="lesson-flow">
        {nodes.map((t, i) => (
          <div key={i} className={`flow-item ${i < shown ? "in" : "out"} ${i === shown - 1 ? "now" : ""}`}>
            <span className="flow-box">{hasLessonIcon(icons[i]) && <LessonIcon name={icons[i]} size={22} />}{t}</span>
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
        <circle cx="50" cy="50" r="36" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeDasharray="2 2" />
        {nodes.map((_, i) => {
          const a = pos(i), b = pos((i + 1) % n);
          return <line key={i} x1={a.x + (b.x - a.x) * 0.3} y1={a.y + (b.y - a.y) * 0.3} x2={a.x + (b.x - a.x) * 0.7}
                       y2={a.y + (b.y - a.y) * 0.7} stroke="currentColor" strokeWidth="0.9" markerEnd="url(#cyc-arrow)"
                       className={i < shown ? "draw" : "undrawn"} />;
        })}
      </svg>
      {nodes.map((t, i) => {
        const p = pos(i);
        return (
          <span key={i} className={`cycle-node ${i < shown ? "in" : "out"} ${i === shown - 1 ? "now" : ""}`} style={{ left: `${p.x}%`, top: `${p.y}%` }}>
            {hasLessonIcon(icons[i]) && <LessonIcon name={icons[i]} size={20} />}{t}
          </span>
        );
      })}
    </div>
  );
}

function MindMap({ center, branches, icons, shown }: { center: string; branches: string[]; icons: string[]; shown: number }) {
  const n = branches.length;
  const pos = (i: number) => {
    const a = (i / n) * 2 * Math.PI - Math.PI / 2 + (n % 2 === 0 ? Math.PI / n : 0);
    return { x: 50 + 38 * Math.cos(a), y: 50 + 36 * Math.sin(a) };
  };
  return (
    <div className="lesson-mind">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {branches.map((_, i) => {
          const p = pos(i);
          return <path key={i} d={`M50 50 C ${(50 + p.x) / 2} 50 ${(50 + p.x) / 2} ${p.y} ${p.x} ${p.y}`} fill="none"
                       stroke="currentColor" strokeWidth="0.6" pathLength={1} className={i < shown ? "draw" : "undrawn"} />;
        })}
      </svg>
      <span className="mind-center">{center}</span>
      {branches.map((t, i) => {
        const p = pos(i);
        return (
          <span key={i} className={`mind-branch ${i < shown ? "in" : "out"} ${i === shown - 1 ? "now" : ""}`} style={{ left: `${p.x}%`, top: `${p.y}%` }}>
            {hasLessonIcon(icons[i]) && <LessonIcon name={icons[i]} size={18} />}{t}
          </span>
        );
      })}
    </div>
  );
}
