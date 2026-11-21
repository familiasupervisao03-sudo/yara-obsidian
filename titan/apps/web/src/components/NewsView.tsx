// Aba Notícias: notícias de sites confiáveis (sempre com link e data reais), assuntos seguidos,
// jornal do dia, dicionário e fontes. O TITAN nunca inventa: resumo/análise vêm marcados como dele.
import { useCallback, useEffect, useRef, useState } from "react";
import { HttpError } from "../api";
import { ServerTts } from "../voice/browser";
import {
  ago, brl, cached, dmy, news, shareText,
  type Cat, type Follow, type NewsList, type Source, type Story, type Term,
} from "../news";
import "./NewsView.css";

type Section = "noticias" | "assuntos" | "jornal" | "dicionario" | "fontes";
const CATS: { id: Cat; label: string }[] = [
  { id: "tudo", label: "Tudo" }, { id: "tecnologia", label: "Tecnologia" }, { id: "ia", label: "IA" },
  { id: "negocios", label: "Negócios" }, { id: "jogos", label: "Jogos" }, { id: "esportes", label: "Esportes" },
  { id: "brasil", label: "Brasil" }, { id: "ceara", label: "Ceará" }, { id: "salvas", label: "⭐ Salvas" },
];
const SECTIONS: { id: Section; label: string }[] = [
  { id: "noticias", label: "Notícias" }, { id: "assuntos", label: "Assuntos" }, { id: "jornal", label: "Jornal" },
  { id: "dicionario", label: "Dicionário" }, { id: "fontes", label: "Fontes" },
];

function openLink(url: string) {
  window.open(url, "_blank", "noopener,noreferrer");
}

export function NewsView({ onError }: { onError: (e: unknown) => void }) {
  const [section, setSection] = useState<Section>("noticias");
  return (
    <section className="news-view">
      <nav className="news-sections" aria-label="Partes das Notícias">
        {SECTIONS.map((s) => (
          <button key={s.id} className={`chip ${section === s.id ? "on" : ""}`} onClick={() => setSection(s.id)}>{s.label}</button>
        ))}
      </nav>
      {section === "noticias" && <StoriesPanel onError={onError} />}
      {section === "assuntos" && <FollowsPanel onError={onError} />}
      {section === "jornal" && <JornalPanel onError={onError} />}
      {section === "dicionario" && <TermsPanel onError={onError} />}
      {section === "fontes" && <SourcesPanel onError={onError} />}
    </section>
  );
}

function StoriesPanel({ onError }: { onError: (e: unknown) => void }) {
  const [cat, setCat] = useState<Cat>("tudo");
  const [list, setList] = useState<NewsList | null>(() => cached("tudo")?.list ?? null);
  const [offline, setOffline] = useState<number | null>(null);
  const load = useCallback((c: Cat) => {
    news.list(c).then((l) => { setList(l); setOffline(null); }).catch((e) => {
      const keep = cached(c);
      if (e instanceof HttpError && e.status === 0 && keep) { setList(keep.list); setOffline(keep.at); }
      else onError(e);
    });
  }, [onError]);
  useEffect(() => { load(cat); }, [cat, load]);

  const update = (s: Story) => setList((l) => l && { ...l, stories: l.stories.map((x) => (x.id === s.id ? s : x)) });
  return (
    <>
      <div className="news-cats">
        {CATS.map((c) => (
          <button key={c.id} className={`chip small ${cat === c.id ? "on" : ""}`} onClick={() => setCat(c.id)}>{c.label}</button>
        ))}
      </div>
      {offline && <p className="small warn">Sem conexão com o notebook: mostrando as notícias guardadas de {ago(new Date(offline).toISOString())}.</p>}
      {list && !list.enabled && (
        <p className="small muted">As Notícias estão desligadas. No notebook: <code>.venv/bin/titan enable-news</code> e depois <code>titan ligar</code>.</p>
      )}
      {list === null ? <p className="small muted">Carregando…</p> : list.stories.length === 0 ? (
        <p className="small muted">{cat === "salvas" ? "Nenhuma notícia salva ainda." : "Nenhuma notícia por aqui ainda. Elas chegam a cada 30 minutos."}</p>
      ) : (
        <div className="news-list">
          {list.stories.map((s) => <StoryCard key={s.id} s={s} onChange={update} onError={onError} offline={offline !== null} />)}
        </div>
      )}
    </>
  );
}

function StoryCard({ s, onChange, onError, offline }: {
  s: Story; onChange: (s: Story) => void; onError: (e: unknown) => void; offline: boolean;
}) {
  const [explain, setExplain] = useState<{ mode: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [timeline, setTimeline] = useState(false);
  const a = s.analysis;
  const names = [...new Set(s.sources.map((x) => x.name))];
  const set = (st: { read?: boolean; saved?: boolean; vote?: number }) =>
    news.state(s.id, st).then(onChange).catch(onError);
  const ask = (mode: "melhor" | "facil") => {
    setBusy(true);
    news.explain(s.id, mode).then((r) => setExplain({ mode, text: r.text })).catch(onError).finally(() => setBusy(false));
    if (!s.read) void set({ read: true });
  };
  const share = () => {
    const text = shareText(s);
    const nav = navigator as Navigator & { share?: (d: { title?: string; text?: string }) => Promise<void> };
    if (nav.share) nav.share({ title: s.title, text }).catch(() => undefined);
    else openLink(`https://wa.me/?text=${encodeURIComponent(text)}`);
  };
  const readOn = (url: string) => { openLink(url); if (!s.read) void set({ read: true }); };
  return (
    <article className={`news-card ${s.read ? "read" : ""}`}>
      <div className="news-src">{names.join(" · ")} · {ago(s.last_at)}</div>
      <h3 className="news-title">{s.title}</h3>
      <div className="news-badges">
        {s.n_sources >= 2 ? <span className="nb ok">✅ confirmada por {s.n_sources} sites</span>
          : <span className="nb warn">⚠ só 1 site falou até agora</span>}
        {a?.discordam && <span className="nb warn">⚠ os sites discordam</span>}
        {s.affects && <span className="nb titan">⚙ assunto dos seus projetos</span>}
        {a?.oportunidade && <span className="nb opp">💡 oportunidade</span>}
      </div>
      {a && (a.resumo || a.por_que_importa) && (
        <div className="news-ai">
          <span className="tag">Resumo do TITAN (feito só com o texto dos sites)</span>
          {a.resumo && <p>{a.resumo}</p>}
          {a.por_que_importa && <p className="why">👉 {a.por_que_importa}</p>}
        </div>
      )}
      {a?.discordam && a.discordancia && <div className="news-box warn">⚠ <b>Os sites discordam:</b> {a.discordancia} Leia cada um antes de confiar.</div>}
      {a?.afeta_titan && <div className="news-box titan"><b>⚙ Isso afeta o TITAN:</b> {a.afeta_titan}</div>}
      {a?.oportunidade && <div className="news-box opp"><b>💡 Oportunidade:</b> {a.oportunidade}</div>}
      {s.checks.length > 0 && (
        <div className="news-box check">🔎 <b>Checagem:</b> {s.checks.map((c, i) => (
          <a key={i} href={c.url} target="_blank" rel="noopener noreferrer">{c.name}: {c.title}</a>))}
        </div>
      )}
      <div className="news-actions">
        {s.sources.length === 1 || !a?.discordam
          ? <button className="small" onClick={() => readOn(s.sources[s.sources.length - 1].url)}>Ler no site ↗</button>
          : names.map((n) => {
            const it = s.sources.filter((x) => x.name === n).pop()!;
            return <button key={n} className="small" onClick={() => readOn(it.url)}>Ler no {n} ↗</button>;
          })}
        <button className="small ghost" disabled={busy || offline} onClick={() => ask("melhor")}>Explica melhor</button>
        <button className="small ghost" disabled={busy || offline} onClick={() => ask("facil")}>Me explica fácil</button>
        {s.sources.length > 1 && <button className="small ghost" onClick={() => setTimeline(!timeline)}>Linha do tempo</button>}
      </div>
      <div className="news-actions">
        <button className={`small ghost ${s.vote === 1 ? "on" : ""}`} disabled={offline} aria-pressed={s.vote === 1}
                onClick={() => set({ vote: s.vote === 1 ? 0 : 1 })} title="Quero mais assim">👍</button>
        <button className={`small ghost ${s.vote === -1 ? "on" : ""}`} disabled={offline} aria-pressed={s.vote === -1}
                onClick={() => set({ vote: s.vote === -1 ? 0 : -1 })} title="Menos disso">👎</button>
        <button className={`small ghost ${s.saved ? "on" : ""}`} disabled={offline} onClick={() => set({ saved: !s.saved })}>⭐ {s.saved ? "Salva" : "Salvar"}</button>
        <button className="small ghost" disabled={offline} onClick={() => set({ read: !s.read })}>{s.read ? "Marcar não lida" : "✓ Lida"}</button>
        <button className="small ghost" onClick={share}>Compartilhar</button>
      </div>
      {timeline && (
        <ol className="news-timeline">
          {s.sources.map((x, i) => (
            <li key={i}><b>{dmy(x.published_at)}</b> · {x.name}: <a href={x.url} target="_blank" rel="noopener noreferrer">{x.title}</a></li>
          ))}
        </ol>
      )}
      {(busy || explain) && (
        <div className="news-ai">
          <span className="tag">{explain?.mode === "facil" ? "Explicado fácil" : "Explicação"} do TITAN (só com o texto dos sites)</span>
          <p>{busy ? "Lendo os sites…" : explain?.text}</p>
        </div>
      )}
    </article>
  );
}

function FollowsPanel({ onError }: { onError: (e: unknown) => void }) {
  const [list, setList] = useState<Follow[] | null>(null);
  const [text, setText] = useState("");
  const [form, setForm] = useState({ topic: "", prices: false, past_weeks: 2, future_weeks: 2, store_url: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => { news.follows().then(setList).catch(onError); }, [onError]);
  useEffect(load, [load]);
  const fromText = () => {
    setMsg(null);
    news.followFromText(text).then((f) => { setText(""); setMsg(`Pronto: seguindo “${f.topic}”.`); load(); })
      .catch((e) => setMsg((e as Error).message));
  };
  const add = () => {
    setMsg(null);
    news.addFollow(form).then((f) => { setForm({ ...form, topic: "", store_url: "" }); setMsg(`Pronto: seguindo “${f.topic}”.`); load(); })
      .catch((e) => setMsg((e as Error).message));
  };
  return (
    <>
      <div className="panel">
        <h3 className="panel-title">Seguir um assunto</h3>
        <p className="small muted">Fale do seu jeito, por exemplo: <i>analisa os preços da ESP32 nas próximas 3 semanas e nas semanas passadas</i>.
          Ele só mostra o que achar de verdade, com data e link.</p>
        <div className="row">
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="segue as notícias sobre…" aria-label="Pedido" />
          <button disabled={text.trim().length < 3} onClick={fromText}>Seguir</button>
        </div>
        <details>
          <summary className="small">Ou preencha os campos</summary>
          <div className="follow-form">
            <label>Assunto <input value={form.topic} onChange={(e) => setForm({ ...form, topic: e.target.value })} /></label>
            <label className="check"><input type="checkbox" checked={form.prices} onChange={(e) => setForm({ ...form, prices: e.target.checked })} /> acompanhar preço</label>
            <label>Semanas para trás <input type="number" min={0} max={52} value={form.past_weeks} onChange={(e) => setForm({ ...form, past_weeks: Number(e.target.value) })} /></label>
            <label>Semanas para frente <input type="number" min={0} max={52} value={form.future_weeks} onChange={(e) => setForm({ ...form, future_weeks: Number(e.target.value) })} /></label>
            <label>Link de uma loja (opcional) <input value={form.store_url} placeholder="https://…" onChange={(e) => setForm({ ...form, store_url: e.target.value })} /></label>
            <button disabled={form.topic.trim().length < 2} onClick={add}>Seguir</button>
          </div>
        </details>
        {msg && <p className="small" role="status">{msg}</p>}
      </div>
      {list?.map((f) => (
        <div key={f.id} className="panel follow">
          <div className="row spread">
            <h3 className="panel-title">{f.prices ? "💲" : "🔎"} {f.topic}</h3>
            <button className="small ghost" onClick={() => news.removeFollow(f.id).then(load).catch(onError)}>Parar de seguir</button>
          </div>
          <p className="small muted">De {dmy(f.since)} até {dmy(f.until)}{f.last_checked_at ? ` · conferido ${ago(f.last_checked_at)}` : " · ainda não conferido"}</p>
          {f.trend && <p className="trend">{f.trend}</p>}
          {f.hits.length === 0 ? <p className="small muted">Nada encontrado ainda.</p> : (
            <ol className="news-timeline">
              {f.hits.map((h, i) => (
                <li key={i}>
                  <b>{dmy(h.published_at)}</b> · {h.source}: <a href={h.url} target="_blank" rel="noopener noreferrer">{h.title}</a>
                  {h.price !== null && <div className="price">{brl(h.price)} <span className="muted small">— “{h.quote}”</span></div>}
                </li>
              ))}
            </ol>
          )}
        </div>
      ))}
    </>
  );
}

function JornalPanel({ onError }: { onError: (e: unknown) => void }) {
  const [j, setJ] = useState<{ title: string; body: string } | null>(null);
  const [playing, setPlaying] = useState(false);
  const clip = useRef<{ stop(): void } | null>(null);
  useEffect(() => { news.jornal().then(setJ).catch(onError); }, [onError]);
  useEffect(() => () => clip.current?.stop(), []);
  const listen = async () => {
    if (!j) return;
    if (playing) { clip.current?.stop(); setPlaying(false); return; }
    setPlaying(true);
    try {
      const c = await new ServerTts().prepare(j.body.replace(/•/g, ""), new AbortController().signal);
      clip.current = c;
      await c.play();
    } catch { /* sem voz agora */ }
    setPlaying(false);
  };
  return (
    <div className="panel">
      <h3 className="panel-title">{j?.title ?? "Jornal do TITAN"}</h3>
      <p className="small muted">Todo dia às 19h ele manda os destaques no celular; no domingo, o resumo da semana.</p>
      <pre className="jornal">{j?.body ?? "Carregando…"}</pre>
      <button disabled={!j} onClick={() => void listen()}>{playing ? "■ Parar" : "▶ Ouvir"}</button>
    </div>
  );
}

function TermsPanel({ onError }: { onError: (e: unknown) => void }) {
  const [terms, setTerms] = useState<Term[] | null>(null);
  useEffect(() => { news.terms().then(setTerms).catch(onError); }, [onError]);
  return (
    <div className="panel">
      <h3 className="panel-title">Dicionário do Luiz</h3>
      <p className="small muted">Palavras difíceis que apareceram nas notícias, explicadas de um jeito simples.</p>
      {terms === null ? <p className="small muted">Carregando…</p> : terms.length === 0 ? <p className="small muted">Ainda vazio.</p> : (
        <dl className="terms">{terms.map((t) => <div key={t.term}><dt>{t.term}</dt><dd>{t.explanation}</dd></div>)}</dl>
      )}
    </div>
  );
}

function SourcesPanel({ onError }: { onError: (e: unknown) => void }) {
  const [list, setList] = useState<Source[] | null>(null);
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { news.sources().then(setList).catch(onError); }, [onError]);
  const add = () => {
    setMsg(null);
    news.setSource(url.trim(), true).then((l) => { setList(l); setUrl(""); setMsg("Site adicionado."); })
      .catch((e) => setMsg((e as Error).message));
  };
  return (
    <div className="panel">
      <h3 className="panel-title">Fontes</h3>
      <p className="small muted">Toque no nome para abrir o site. Ligue ou desligue cada um.</p>
      <ul className="sources">
        {list?.map((s) => (
          <li key={s.url}>
            <a href={s.site} target="_blank" rel="noopener noreferrer">{s.name} ↗</a>
            <span className="muted small">{s.category}</span>
            <label className="check"><input type="checkbox" checked={s.enabled}
              onChange={(e) => news.setSource(s.url, e.target.checked).then(setList).catch(onError)} /> {s.enabled ? "ligado" : "desligado"}</label>
            {s.custom && <button className="small ghost" onClick={() => news.removeSource(s.url).then(setList).catch(onError)}>Remover</button>}
          </li>
        ))}
      </ul>
      <div className="row">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://site.com/feed" aria-label="Endereço do feed" />
        <button disabled={!url.startsWith("https://")} onClick={add}>+ Adicionar site</button>
      </div>
      {msg && <p className="small" role="status">{msg}</p>}
    </div>
  );
}
