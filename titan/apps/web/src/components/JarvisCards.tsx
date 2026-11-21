// Início: cartão do clima, protocolos (com confirmação antes) e a tela "O senhor saiu de casa".
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { deg, DO_LABEL, jarvis, type Device, type Protocol, type Result, type Step, type Weather } from "../jarvis";
import { createPortal } from "react-dom";
import "./Jarvis.css";

// --- clima -----------------------------------------------------------------------------------

export function WeatherCard({ onSetup }: { onSetup: () => void }) {
  const [w, setW] = useState<Weather | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => jarvis.weather().then((x) => alive && setW(x)).catch(() => alive && setW(null));
    load();
    const id = window.setInterval(load, 15 * 60_000);
    return () => { alive = false; window.clearInterval(id); };
  }, []);
  if (!w) return null;
  if (!w.place) {
    return (
      <div className="card jv-weather-empty">
        <span>🌦️ Quer que eu avise antes da chuva?</span>
        <button className="small" onClick={onSetup}>Escolher cidade</button>
      </div>
    );
  }
  return (
    <section className="card jv-weather" aria-labelledby="jv-weather-title">
      <header className="card-head">
        <h2 id="jv-weather-title" className="card-title">Clima · {w.place.name}</h2>
        {w.source_url && <a className="muted small" href={w.source_url} target="_blank" rel="noreferrer">fonte: {w.source}</a>}
      </header>
      {w.now ? (
        <>
          <div className="jv-now">
            <span className="jv-temp">{deg(w.now.temp)}</span>
            <span className="jv-sky">{w.now.emoji} {w.now.text}
              {w.today && <span className="muted small">mín {deg(w.today.min)} · máx {deg(w.today.max)}</span>}
            </span>
          </div>
          {w.hours && w.hours.length > 0 && (
            <>
              <p className="muted small jv-label">Chance de chuva</p>
              <div className="jv-hours">
                {w.hours.map((h) => (
                  <div key={h.time} className={(h.rain ?? 0) >= 60 ? "wet" : ""}>
                    <span>{h.time}</span><b>{h.rain ?? "–"}%</b>
                    <i style={{ height: `${Math.max(4, h.rain ?? 0) * 0.3}px` }} aria-hidden="true" />
                  </div>
                ))}
              </div>
            </>
          )}
          {w.tip && <p className="small jv-tip">{w.tip}</p>}
          {w.days && w.days.length > 1 && (
            <details className="jv-days">
              <summary className="small">Próximos dias</summary>
              <ul>
                {w.days.slice(1).map((d) => (
                  <li key={d.date}><span>{d.weekday} {d.date.slice(8, 10)}/{d.date.slice(5, 7)}</span>
                    <span>{d.emoji} {deg(d.min)}–{deg(d.max)}</span><span className="muted">{d.rain ?? "–"}% chuva</span></li>
                ))}
              </ul>
              <p className="muted small">Previsão para mais de 3 dias pode mudar.</p>
            </details>
          )}
        </>
      ) : <p className="muted small">{w.error ?? "Previsão ainda não chegou."}</p>}
      {w.now && w.error && <p className="muted small">Última atualização falhou: {w.error}</p>}
    </section>
  );
}

// --- protocolos ------------------------------------------------------------------------------

export function ProtocolsCard() {
  const [items, setItems] = useState<Protocol[] | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [asking, setAsking] = useState<Protocol | null>(null);
  const [editing, setEditing] = useState<Protocol | "new" | null>(null);
  const [done, setDone] = useState<{ p: Protocol; text: string; results: Result[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    jarvis.protocols().then(setItems).catch(() => setItems(null));
    jarvis.devices().then(setDevices).catch(() => setDevices([]));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (!items) return null;

  const run = (p: Protocol) => {
    setBusy(true);
    jarvis.run(p.id).then((r) => { setDone({ p, ...r }); setAsking(null); load(); })
      .catch((e) => setError((e as Error).message)).finally(() => setBusy(false));
  };

  return (
    <section className="card jv-protos" aria-labelledby="jv-protos-title">
      <header className="card-head">
        <h2 id="jv-protos-title" className="card-title">Protocolos</h2>
        <button className="ghost small" onClick={() => setEditing("new")}>＋ Criar</button>
      </header>
      {devices.length === 0 && (
        <p className="muted small">Nenhum aparelho cadastrado no TITAN Casa ainda. Os protocolos usam os aparelhos de lá.</p>
      )}
      <div className="jv-grid">
        {items.map((p) => (
          <div key={p.id} className={`jv-proto ${p.special === "all_off" ? "red" : ""}`}>
            <button className="jv-proto-main" onClick={() => { setError(null); setAsking(p); }}
                    disabled={p.lines.length === 0} title={p.lines.length ? "Executar" : "Escolha os aparelhos primeiro"}>
              <span className="jv-emoji" aria-hidden="true">{p.emoji}</span>
              <b>{p.name}</b>
              <small>{p.summary}</small>
            </button>
            {p.special !== "all_off" && (
              <button className="ghost small jv-edit" onClick={() => setEditing(p)} aria-label={`Editar ${p.name}`}>Editar</button>
            )}
          </div>
        ))}
      </div>
      <p className="muted small">Também dá para falar: “Titã, protocolo dormir”. Ele mostra o que vai fazer e espera o “sim”.</p>

      {asking && (
        <Sheet onClose={() => setAsking(null)} danger={asking.special === "all_off"}>
          <h3>{asking.emoji} {asking.special === "all_off" ? "Lousa Limpa" : `Protocolo ${asking.name}`}</h3>
          {asking.special === "all_off" && <p>Vai desligar <b>todos os {asking.lines.length} aparelhos</b> da casa agora.</p>}
          <ul>{asking.lines.map((l) => <li key={l}>{l}</li>)}</ul>
          {error && <p className="warn small">{error}</p>}
          <div className="jv-go">
            <button className="ghost" onClick={() => setAsking(null)}>Cancelar</button>
            {asking.special === "all_off"
              ? <HoldButton label="Segure para desligar" busy={busy} onDone={() => run(asking)} />
              : <button onClick={() => run(asking)} disabled={busy}>{busy ? "Executando…" : "Executar"}</button>}
          </div>
        </Sheet>
      )}
      {done && (
        <Sheet onClose={() => setDone(null)}>
          <h3>{done.p.emoji} {done.text}</h3>
          <Results items={done.results} />
          <div className="jv-go"><button onClick={() => setDone(null)}>Ok</button></div>
        </Sheet>
      )}
      {editing && (
        <ProtocolEditor p={editing === "new" ? null : editing} devices={devices}
                        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />
      )}
    </section>
  );
}

export function Results({ items }: { items: Result[] }) {
  return (
    <ul className="jv-results">
      {items.map((r, i) => (
        <li key={i}><span>{r.name}</span><span className={r.ok ? "ok" : "warn"}>{r.ok ? "✓" : "⚠"} {r.detail}</span></li>
      ))}
    </ul>
  );
}

/** Botão que só age segurando ~1,2 s (evita desligar a casa toda num toque sem querer). */
export function HoldButton({ label, onDone, busy }: { label: string; onDone: () => void; busy?: boolean }) {
  const [p, setP] = useState(0);
  const timer = useRef<number | null>(null);
  const start = () => {
    if (busy || timer.current) return;
    const t0 = Date.now();
    timer.current = window.setInterval(() => {
      const v = Math.min(1, (Date.now() - t0) / 1200);
      setP(v);
      if (v >= 1) { stop(); onDone(); }
    }, 50);
  };
  const stop = () => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
    setP(0);
  };
  useEffect(() => () => stop(), []);
  return (
    <button className="jv-hold" onPointerDown={start} onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop}
            onContextMenu={(e) => e.preventDefault()} disabled={busy}
            style={{ backgroundImage: `linear-gradient(90deg, rgba(255,255,255,.35) ${p * 100}%, transparent ${p * 100}%)` }}>
      {busy ? "Desligando…" : label}
    </button>
  );
}

function Sheet({ children, onClose, danger }: { children: ReactNode; onClose: () => void; danger?: boolean }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  // no <body>: o cartão tem recorte/efeitos que prenderiam a janela dentro dele
  return createPortal(
    <div className="jv-dim" onClick={onClose}>
      <div className={`jv-sheet ${danger ? "danger" : ""}`} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>,
    document.body,
  );
}

const EMOJIS = ["⚡", "🌙", "🎉", "🎬", "☀️", "📚", "🍽️", "🎮", "🏠", "🚿", "💼", "🛋️"];

function ProtocolEditor({ p, devices, onClose, onSaved }: {
  p: Protocol | null; devices: Device[]; onClose: () => void; onSaved: () => void;
}) {
  const [name, setName] = useState(p?.name ?? "");
  const [emoji, setEmoji] = useState(p?.emoji ?? "⚡");
  const [steps, setSteps] = useState<Step[]>(p?.steps ?? []);
  const [quiet, setQuiet] = useState(p?.quiet_until ?? "");
  const [error, setError] = useState<string | null>(null);
  const isDefault = p !== null && !p.custom;
  const setDo = (id: string, d: Step["do"] | "") =>
    setSteps((s) => d ? [...s.filter((x) => x.device_id !== id), { device_id: id, do: d }] : s.filter((x) => x.device_id !== id));
  const save = () => jarvis.saveProtocol(p?.id ?? null, { name, emoji, steps, quiet_until: quiet })
    .then(onSaved).catch((e) => setError((e as Error).message));
  return (
    <Sheet onClose={onClose}>
      <h3>{p ? `Editar ${p.name}` : "Novo protocolo"}</h3>
      <div className="jv-form">
        <label>Nome
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={30} disabled={isDefault} />
        </label>
        <div className="jv-emojis" role="group" aria-label="Ícone">
          {EMOJIS.map((e) => <button key={e} type="button" className={`ghost small ${e === emoji ? "on" : ""}`} onClick={() => setEmoji(e)}>{e}</button>)}
        </div>
        <p className="muted small">O que cada aparelho faz:</p>
        {devices.length === 0 && <p className="muted small">Cadastre aparelhos no TITAN Casa primeiro.</p>}
        <ul className="jv-devs">
          {devices.map((d) => {
            const cur = steps.find((s) => s.device_id === d.id)?.do ?? "";
            return (
              <li key={d.id}>
                <span>{d.name}{!d.online && <span className="muted small"> (offline)</span>}</span>
                <select value={cur} onChange={(e) => setDo(d.id, e.target.value as Step["do"] | "")} aria-label={`Ação para ${d.name}`}>
                  <option value="">não mexer</option>
                  <option value="on">{DO_LABEL.on}</option>
                  <option value="off">{DO_LABEL.off}</option>
                  {d.kind === "light" && <option value="dim">{DO_LABEL.dim}</option>}
                </select>
              </li>
            );
          })}
        </ul>
        <label className="check">
          <input type="checkbox" checked={Boolean(quiet)} onChange={(e) => setQuiet(e.target.checked ? "07:00" : "")} />
          <span>Silenciar avisos de notícias até</span>
          {quiet && <input type="time" value={quiet} onChange={(e) => e.target.value && setQuiet(e.target.value)} aria-label="Até que horas" />}
        </label>
      </div>
      {error && <p className="warn small">{error}</p>}
      <div className="jv-go">
        {p?.custom && <button className="ghost danger" onClick={() => {
          if (confirm(`Apagar o protocolo ${p.name}?`)) jarvis.deleteProtocol(p.id).then(onSaved).catch((e) => setError((e as Error).message));
        }}>Apagar</button>}
        <button className="ghost" onClick={onClose}>Cancelar</button>
        <button onClick={save}>Salvar</button>
      </div>
    </Sheet>
  );
}

// --- saiu de casa ----------------------------------------------------------------------------

/** Aberta pelo aviso "O senhor saiu de casa" (?acao=saida): o dono escolhe se desliga. */
export function LeaveSheet({ onClose }: { onClose: () => void }) {
  const [on, setOn] = useState<Device[] | null>(null);
  const [results, setResults] = useState<Result[] | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { jarvis.leave().then(setOn).catch(() => setOn([])); }, []);
  if (on === null) return null;
  return (
    <Sheet onClose={onClose}>
      <h3>🏠 O senhor saiu de casa</h3>
      {results ? <Results items={results} />
        : on.length === 0 ? <p>Nada ficou ligado. Tudo certo, senhor.</p>
        : <><p>Ficaram ligados:</p><ul>{on.map((d) => <li key={d.id}>{d.name}</li>)}</ul></>}
      <div className="jv-go">
        {!results && on.length > 0 && <>
          <button className="ghost" onClick={onClose}>Deixar</button>
          <button disabled={busy} onClick={() => {
            setBusy(true);
            jarvis.turnOff(on.map((d) => d.id)).then(setResults).catch(() => setResults([]))
              .finally(() => setBusy(false));
          }}>{busy ? "Desligando…" : "Desligar tudo"}</button>
        </>}
        {(results || on.length === 0) && <button onClick={onClose}>Ok</button>}
      </div>
    </Sheet>
  );
}
