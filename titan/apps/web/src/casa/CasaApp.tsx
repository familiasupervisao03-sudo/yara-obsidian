// TITAN Casa: app irmão do TITAN (mesmo servidor, mesma conta, mesma voz) para o tablet.
// Abas: PAINEL (aparelhos + voz), CENAS, AJUSTES (conectar, cadastrar, renomear).
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { HttpError } from "../api";
import { ServerTts } from "../voice/browser.ts";
import { casa, ICON_LABEL, ICONS, stateWord, subtitle, type Action, type CasaEvent, type CommandResult,
         type Device, type Scene, type SceneAction, type Status } from "./api";
import { Ear, type EarState } from "./listen";
import { duckEnd, duckStart } from "../voice/duck";

type Tab = "painel" | "cenas" | "ajustes";
const EXAMPLES = ["Ei Titã, liga a luz do quarto", "desliga o ventilador", "põe o ar em 22", "luz em 30%",
                  "aumenta o volume", "liga tudo", "desliga tudo"];

export function CasaApp({ username, onExpired }: { username: string; onExpired: () => void }) {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem("titan.casa.tab") as Tab) || "painel");
  const [status, setStatus] = useState<Status | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [events, setEvents] = useState<CasaEvent[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [control, setControl] = useState<string | null>(null);
  const [voice, setVoice] = useState(false);
  const [clock, setClock] = useState(() => new Date());
  const [offline, setOffline] = useState(false);

  const fail = useCallback((e: unknown) => {
    if (e instanceof HttpError && e.status === 401) onExpired();
    else if (e instanceof HttpError && e.status === 0) setOffline(true);
    else say((e as Error).message);
  }, [onExpired]);
  const say = (t: string) => { setToast(t); window.setTimeout(() => setToast((x) => (x === t ? null : x)), 2600); };

  const load = useCallback(async () => {
    try {
      const [st, ds, sc, ev] = await Promise.all([casa.status(), casa.devices(), casa.scenes(), casa.events()]);
      setStatus(st); setDevices(ds); setScenes(sc); setEvents(ev); setOffline(false);
    } catch (e) { fail(e); }
  }, [fail]);
  useEffect(() => { void load(); const id = window.setInterval(load, 15_000); return () => window.clearInterval(id); }, [load]);
  useEffect(() => { const id = window.setInterval(() => setClock(new Date()), 1000); return () => window.clearInterval(id); }, []);
  useEffect(() => { try { localStorage.setItem("titan.casa.tab", tab); } catch { /* ignora */ } }, [tab]);

  const upsert = (d: Device) => setDevices((ds) => ds.map((x) => (x.id === d.id ? d : x)));
  const act = async (d: Device, a: Action) => {
    if (a.do === "toggle") upsert({ ...d, state: { ...d.state, on: !d.state.on } }); // resposta imediata na tela
    try { upsert(await casa.act(d.id, a)); casa.events().then(setEvents).catch(() => undefined); }
    catch (e) { upsert(d); fail(e); }
  };

  const on = devices.filter((d) => d.state.on).length;
  return (
    <div className="casa">
      <header className="casa-top">
        <a className="casa-brand" href="/" title="Abrir o TITAN">TITAN<small>CASA</small></a>
        <span className="casa-meta"><span className={`casa-dot ${offline ? "bad" : ""}`} />
          {offline ? "SEM CONEXÃO COM O NOTEBOOK" : `${(status?.home ?? "CASA").toUpperCase()} · ${devices.length} APARELHOS`}</span>
        {status?.provider === "demo" && <span className="casa-pill">DEMONSTRAÇÃO</span>}
        <span className="casa-sp" />
        <nav className="casa-nav" aria-label="Seções">
          {(["painel", "cenas", "ajustes"] as Tab[]).map((t) => (
            <button key={t} className={`casa-nb ${tab === t ? "on" : ""}`} onClick={() => setTab(t)} aria-current={tab === t ? "page" : undefined}>
              {t.toUpperCase()}{t === "ajustes" && status && status.new > 0 ? ` · ${status.new}` : ""}
            </button>
          ))}
        </nav>
        <span className="casa-meta">LIGADOS <b>{on}</b></span>
        <span className="casa-clock">{clock.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>
      </header>

      <main className="casa-main">
        {tab === "painel" && (
          <section className="casa-layout">
            <div>
              <div className="casa-lbl">aparelhos · toque para ligar/desligar · ⋯ para controles</div>
              {devices.length === 0 ? (
                <div className="casa-panel casa-empty">
                  <b>Nenhum aparelho cadastrado ainda.</b>
                  <p>Vá em <b>AJUSTES</b>, toque em <b>PROCURAR NOVOS</b> e dê um nome a cada aparelho.</p>
                  <button className="casa-b p" onClick={() => setTab("ajustes")}>IR PARA AJUSTES</button>
                </div>
              ) : (
                <div className="casa-grid">
                  {devices.map((d) => <Tile key={d.id} d={d} onTap={() => act(d, { do: "toggle" })} onMore={() => setControl(d.id)} />)}
                </div>
              )}
            </div>
            <VoicePanel events={events} onOpen={() => setVoice(true)} />
          </section>
        )}
        {tab === "cenas" && <Scenes scenes={scenes} devices={devices} onChanged={load} onError={fail} say={say} />}
        {tab === "ajustes" && <Settings status={status} onChanged={load} onError={fail} say={say} username={username} />}
      </main>

      {control && devices.find((d) => d.id === control) && (
        <Control d={devices.find((d) => d.id === control)!} act={act} onClose={() => setControl(null)} />
      )}
      {voice && <VoiceOverlay onClose={() => setVoice(false)} onResult={() => load()} onError={fail} />}
      {toast && <div className="casa-toast" role="status">{toast}</div>}
    </div>
  );
}

// --- aparelho --------------------------------------------------------------------------

function Tile({ d, onTap, onMore }: { d: Device; onTap: () => void; onMore: () => void }) {
  const timer = useRef<number | null>(null);
  const long = useRef(false);
  return (
    <div className={`casa-panel casa-tile ${d.state.on ? "on" : ""} ${d.kind === "light" ? "warm" : ""} ${d.online ? "" : "offline"}`}
         role="button" tabIndex={0} aria-pressed={Boolean(d.state.on)} aria-label={`${d.name}: ${stateWord(d).toLowerCase()}`}
         onPointerDown={(e) => { if ((e.target as HTMLElement).closest(".casa-more")) return; long.current = false;
           timer.current = window.setTimeout(() => { long.current = true; onMore(); }, 550); }}
         onPointerUp={() => timer.current && window.clearTimeout(timer.current)}
         onPointerLeave={() => timer.current && window.clearTimeout(timer.current)}
         onClick={(e) => { if ((e.target as HTMLElement).closest(".casa-more")) return; if (!long.current) onTap(); }}
         onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onTap(); } }}>
      <div className="casa-trow"><span className="casa-ic">{ICONS[d.icon] ?? "🔌"}</span>
        <button className="casa-more" onClick={onMore} aria-label={`Controles de ${d.name}`}>⋯</button></div>
      <div><div className="casa-tname">{d.name}</div><div className="casa-tsub">{subtitle(d)}</div></div>
      <div className="casa-state">{d.online ? stateWord(d) : "OFFLINE"}</div>
    </div>
  );
}

function Control({ d, act, onClose }: { d: Device; act: (d: Device, a: Action) => void; onClose: () => void }) {
  const [bright, setBright] = useState(d.state.bright ?? 100);
  const temp = d.state.ac_temp ?? 24;
  const ac = (p: Partial<Action>) => act(d, { do: "ac", on: true, ac_temp: temp, ac_mode: d.state.ac_mode ?? "frio", ac_fan: d.state.ac_fan ?? 0, ...p });
  const key = (k: string) => act(d, { do: "key", value: k });
  const angle = ((temp - 16) / 14) * 270;
  return (
    <div className="casa-modal" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="casa-panel casa-mbox" role="dialog" aria-label={`Controles de ${d.name}`}>
        <div className="casa-mhead"><span className="casa-big-ic">{ICONS[d.icon] ?? "🔌"}</span><h3>{d.name}</h3>
          <button className="casa-b" onClick={onClose} aria-label="Fechar">✕</button></div>
        <div className="casa-lbl">{d.infrared ? "controle por infravermelho" : d.kind === "light" ? "lâmpada" : "tomada"}</div>
        {d.kind === "light" && (<>
          <p className="casa-small">Brilho: <b>{bright}%</b></p>
          <input type="range" min={1} max={100} value={bright} className="casa-slider" aria-label="Brilho"
                 onChange={(e) => setBright(+e.target.value)} onPointerUp={() => act(d, { do: "bright", value: bright })}
                 onKeyUp={() => act(d, { do: "bright", value: bright })} />
          <div className="casa-brow">{["quente", "neutro", "frio"].map((w) => (
            <button key={w} className={`casa-b ${d.state.white === w ? "a" : ""}`} onClick={() => act(d, { do: "white", value: w })}>{w.toUpperCase()}</button>))}</div>
        </>)}
        {d.kind === "ac" && (<>
          <div className="casa-dial" style={{ background: `conic-gradient(from 225deg, var(--casa-a2) 0deg, var(--casa-a) ${angle}deg, rgba(62,232,255,.12) ${angle}deg 270deg, transparent 270deg)` }}>
            <div><b>{temp}°</b><span>{(d.state.ac_mode ?? "frio").toUpperCase()} · VENT {d.state.ac_fan || "AUTO"}</span></div>
          </div>
          <div className="casa-brow"><button className="casa-b big" onClick={() => ac({ ac_temp: Math.max(16, temp - 1) })}>−</button>
            <button className="casa-b big" onClick={() => ac({ ac_temp: Math.min(30, temp + 1) })}>+</button></div>
          <div className="casa-brow">{["frio", "ventilar", "secar", "auto", "quente"].map((m) => (
            <button key={m} className={`casa-b ${d.state.ac_mode === m ? "a" : ""}`} onClick={() => ac({ ac_mode: m })}>{m.toUpperCase()}</button>))}</div>
          <div className="casa-brow">{[0, 1, 2, 3].map((f) => (
            <button key={f} className={`casa-b ${(d.state.ac_fan ?? 0) === f ? "a" : ""}`} onClick={() => ac({ ac_fan: f })}>{f ? `VENT. ${f}` : "AUTO"}</button>))}</div>
        </>)}
        {d.kind === "tv" && (<>
          <div className="casa-pad"><span /><button className="casa-b a" onClick={() => key("up")}>▲</button><span />
            <button className="casa-b a" onClick={() => key("left")}>◀</button><button className="casa-b p" onClick={() => key("ok")}>OK</button>
            <button className="casa-b a" onClick={() => key("right")}>▶</button><span /><button className="casa-b a" onClick={() => key("down")}>▼</button><span /></div>
          <div className="casa-brow"><button className="casa-b" onClick={() => key("vol_down")}>VOL −</button><button className="casa-b" onClick={() => key("vol_up")}>VOL +</button>
            <button className="casa-b" onClick={() => key("ch_down")}>CH −</button><button className="casa-b" onClick={() => key("ch_up")}>CH +</button></div>
          <div className="casa-brow"><button className="casa-b" onClick={() => key("mute")}>MUDO</button><button className="casa-b" onClick={() => key("input")}>FONTE</button>
            <button className="casa-b" onClick={() => key("back")}>VOLTAR</button><button className="casa-b" onClick={() => key("home")}>HOME</button></div>
        </>)}
        {(d.kind === "plug" || d.kind === "fan" || d.kind === "other") && (
          <p className="casa-small">Liga e desliga o que estiver plugado nesta tomada{d.state.watts !== undefined ? ` · consumo agora: ${d.state.on ? d.state.watts : 0} W` : ""}.</p>)}
        <button className={`casa-b big casa-wide ${d.state.on ? "" : "p"}`}
                onClick={() => act(d, d.kind === "ac" ? { do: "ac", on: !d.state.on } : d.kind === "tv" ? { do: "key", value: "power" } : { do: "toggle" })}>
          {d.kind === "tv" ? "⏻ LIGAR / DESLIGAR" : d.state.on ? "DESLIGAR" : "LIGAR"}
        </button>
      </div>
    </div>
  );
}

// --- voz -----------------------------------------------------------------------------

function VoicePanel({ events, onOpen }: { events: CasaEvent[]; onOpen: () => void }) {
  return (
    <div className="casa-panel casa-side">
      <div className="casa-lbl">voz</div>
      <button className="casa-orb" onClick={onOpen} aria-label="Falar com o TITAN" />
      <div className="casa-say">“EI, TITÃ…”</div>
      <div className="casa-hint">Toque no núcleo para falar (ou digitar) um comando.</div>
      <div className="casa-log">
        {events.slice(0, 8).map((e, i) => (
          <div key={i}>&gt; <i>{e.source}</i> · {e.scene ? `cena ${e.scene}` : e.device ?? "?"} … <b className={e.ok ? "" : "bad"}>
            {e.ok ? actionLabel(e.action) : "FALHOU"}</b></div>
        ))}
      </div>
    </div>
  );
}

const KEY_LABEL: Record<string, string> = { power: "LIGA/DESLIGA", vol_up: "VOLUME +", vol_down: "VOLUME −", ch_up: "CANAL +",
  ch_down: "CANAL −", mute: "MUDO", ok: "OK", up: "▲", down: "▼", left: "◀", right: "▶", back: "VOLTAR", home: "HOME", input: "FONTE" };
function actionLabel(a: string): string {
  const [what, value] = a.split(":");
  if (what === "on") return "LIGAR";
  if (what === "off") return "DESLIGAR";
  if (what === "bright") return `BRILHO ${value}%`;
  if (what === "white") return `BRANCO ${String(value).toUpperCase()}`;
  if (what === "key") return KEY_LABEL[value] ?? "BOTÃO";
  if (what === "ac") return "AR";
  return what.toUpperCase();
}

let tts: ServerTts | null = null;
async function speak(text: string) {
  if (!text) return;
  try {
    tts ??= new ServerTts();
    const clip = await tts.prepare(text, new AbortController().signal);
    await clip.play();
  } catch {
    try {
      const u = new SpeechSynthesisUtterance(text); u.lang = "pt-BR";
      await duckStart("tts-nav");
      u.onend = u.onerror = () => duckEnd("tts-nav");
      speechSynthesis.speak(u);
    } catch { duckEnd("tts-nav"); /* sem voz */ }
  }
}

function VoiceOverlay({ onClose, onResult, onError }: { onClose: () => void; onResult: () => void; onError: (e: unknown) => void }) {
  const [state, setState] = useState<EarState>("off");
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState("Toque em FALAR, ou digite um comando.");
  const [result, setResult] = useState<CommandResult | null>(null);
  const [text, setText] = useState("");
  const [always, setAlways] = useState(() => localStorage.getItem("titan.casa.sempre") === "1");
  const ear = useRef<Ear | null>(null);
  const alwaysRef = useRef(always);
  alwaysRef.current = always;

  const run = useCallback(async (t: string, src: "voz" | "texto") => {
    setHeard(`“${t}”`); setReply("…"); setResult(null);
    try {
      const r = await casa.command(t, src, src === "voz" && alwaysRef.current);
      if (r.kind === "ignored") { setReply("(sem “Ei, Titã”: ignorei)"); return; }
      setResult(r); setReply(r.reply); onResult(); void speak(r.reply);
    } catch (e) { onError(e); setReply("Não consegui agora."); }
  }, [onError, onResult]);

  useEffect(() => {
    ear.current = new Ear((t) => void run(t, "voz"), setState, (p) => p && setHeard(`“${p}”`), (m) => setReply(m));
    if (always) void ear.current.continuous(); else void ear.current.once();
    return () => ear.current?.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const toggleAlways = () => {
    const v = !always;
    setAlways(v);
    try { localStorage.setItem("titan.casa.sempre", v ? "1" : "0"); } catch { /* ignora */ }
    if (v) void ear.current?.continuous(); else ear.current?.stop();
  };
  const undo = async () => {
    if (!result?.undo.length) return;
    try { for (const u of result.undo) await casa.act(u.device_id, u.action as Action); setReply("Desfeito."); setResult(null); onResult(); void speak("Desfeito."); }
    catch (e) { onError(e); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); if (text.trim()) { void run(text.trim(), "texto"); setText(""); } };
  const listening = state === "waiting" || state === "hearing";
  return (
    <div className={`casa-ov ${state === "hearing" ? "hearing" : ""}`} role="dialog" aria-label="Comando de voz">
      <div className="casa-orb big" aria-hidden="true" />
      <div className="casa-wave" aria-hidden="true">{Array.from({ length: 28 }, (_, i) => <i key={i} style={{ animationDelay: `${(i % 7) * 0.09}s` }} />)}</div>
      <p className="casa-state-line">{state === "hearing" ? "OUVINDO…" : state === "thinking" ? "ENTENDENDO…"
        : state === "waiting" ? (always ? "ESCUTA CONTÍNUA · diga “Ei, Titã…”" : "PODE FALAR") : "MICROFONE DESLIGADO"}</p>
      <div className="casa-you">{heard}</div>
      <div className="casa-reply" aria-live="polite">{reply}</div>
      {result && (
        <div className="casa-done">
          {result.device && <span className="casa-chip a">{ICONS[result.device.icon] ?? "🔌"} {result.device.name.toUpperCase()} · <b>{stateWord(result.device)}</b></span>}
          {result.scene && <span className="casa-chip a">▶ CENA {result.scene.toUpperCase()}</span>}
          {result.undo.length > 0 && <button className="casa-chip" onClick={undo}>↺ DESFAZER</button>}
        </div>
      )}
      <form className="casa-vin" onSubmit={submit}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Digite: liga a luz do quarto" aria-label="Comando" />
        <button className="casa-b p" type="submit">ENVIAR</button>
        <button className="casa-b u" type="button" onClick={() => (listening ? ear.current?.stop() : void ear.current?.once())}>
          {listening ? "■ PARAR" : "🎙 FALAR"}</button>
      </form>
      <div className="casa-chips">{EXAMPLES.map((c) => <button key={c} className="casa-chip" onClick={() => void run(c, "texto")}>{c}</button>)}</div>
      <label className="casa-check"><input type="checkbox" checked={always} onChange={toggleAlways} />
        Escuta contínua: fica ouvindo e só obedece quando você diz “Ei, Titã”</label>
      <button className="casa-b" onClick={onClose}>FECHAR</button>
    </div>
  );
}

// --- cenas ---------------------------------------------------------------------------

function Scenes({ scenes, devices, onChanged, onError, say }: {
  scenes: Scene[]; devices: Device[]; onChanged: () => void; onError: (e: unknown) => void; say: (t: string) => void;
}) {
  const [editing, setEditing] = useState<Scene | "new" | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const name = (id: string) => devices.find((d) => d.id === id)?.name;
  const runIt = async (s: Scene) => {
    setRunning(s.id);
    try { const r = await casa.runScene(s.id); say(r.reply); void speak(r.reply); onChanged(); } catch (e) { onError(e); }
    finally { window.setTimeout(() => setRunning(null), 700); }
  };
  return (
    <section>
      <div className="casa-lbl">cenas · um comando liga e desliga vários aparelhos de uma vez</div>
      <div className="casa-scenes">
        {scenes.map((s) => (
          <div key={s.id} className={`casa-panel casa-scene ${running === s.id ? "run" : ""}`}>
            <div><b>{s.name}</b>
              <div className="casa-sdesc">🎙 “{s.phrases.split(",")[0]?.trim() || s.name}”
                {s.actions.map((a) => name(a.device_id) && (
                  <div key={a.device_id}><span className={a.action === "off" ? "off" : "on"}>{a.action === "off" ? "✕" : "●"}</span> {name(a.device_id)}
                    {a.action === "dim" ? " (baixinha)" : a.ac_temp ? ` (${a.ac_temp}°)` : ""}</div>))}
              </div></div>
            <div className="casa-sbtns">
              <button className="casa-b p" onClick={() => void runIt(s)}>▶ RODAR</button>
              <button className="casa-b a" onClick={() => setEditing(s)}>✎ EDITAR</button>
              <button className="casa-b bad" aria-label={`Apagar ${s.name}`} onClick={async () => {
                if (!confirm(`Apagar a cena "${s.name}"?`)) return;
                try { await casa.deleteScene(s.id); say("Cena apagada"); onChanged(); } catch (e) { onError(e); }
              }}>✕</button>
            </div>
          </div>
        ))}
        <button className="casa-panel casa-scene casa-newsc" onClick={() => setEditing("new")} disabled={devices.length === 0}
                title={devices.length ? undefined : "Cadastre aparelhos primeiro (Ajustes)"}>
          <div><div className="casa-plus">+</div><div className="casa-tsub">nova cena</div></div></button>
      </div>
      {editing && <SceneForm scene={editing === "new" ? null : editing} devices={devices} onError={onError} say={say}
                             onDone={() => { setEditing(null); onChanged(); }} />}
    </section>
  );
}

function SceneForm({ scene, devices, onDone, onError, say }: {
  scene: Scene | null; devices: Device[]; onDone: () => void; onError: (e: unknown) => void; say: (t: string) => void;
}) {
  const [name, setName] = useState(scene?.name ?? "");
  const [phrases, setPhrases] = useState(scene?.phrases ?? "");
  const [reply, setReply] = useState(scene?.reply ?? "");
  const [acts, setActs] = useState<Record<string, SceneAction>>(() => Object.fromEntries((scene?.actions ?? []).map((a) => [a.device_id, a])));
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, []);
  const save = async () => {
    if (!name.trim()) { say("Dê um nome para a cena"); return; }
    const actions = Object.values(acts);
    if (!actions.length) { say("Escolha pelo menos um aparelho"); return; }
    const body = { name: name.trim(), phrases: phrases.trim() || name.trim().toLowerCase(), reply: reply.trim(), actions };
    try { if (scene) await casa.updateScene(scene.id, body); else await casa.createScene(body); say(scene ? "Cena salva" : "Cena criada"); onDone(); }
    catch (e) { onError(e); }
  };
  return (
    <div className="casa-panel casa-card" ref={ref}>
      <div className="casa-lbl">{scene ? "editar cena" : "nova cena"}</div>
      <label className="casa-srow"><span>Nome</span><input className="casa-inp" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Estudar" maxLength={60} /></label>
      <label className="casa-srow"><span>Frases de voz <small>separe por vírgula</small></span>
        <input className="casa-inp" value={phrases} onChange={(e) => setPhrases(e.target.value)} placeholder="Ex.: modo estudo, vou estudar" maxLength={300} /></label>
      <label className="casa-srow"><span>O TITAN responde</span>
        <input className="casa-inp" value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Ex.: Modo estudo ligado. Bons estudos!" maxLength={300} /></label>
      <div className="casa-lbl" style={{ marginTop: 16 }}>o que cada aparelho faz</div>
      {devices.map((d) => {
        const a = acts[d.id];
        const set = (v: string) => setActs((x) => { const n = { ...x }; if (!v) delete n[d.id]; else n[d.id] = { device_id: d.id, action: v as SceneAction["action"], ac_temp: d.kind === "ac" ? (x[d.id]?.ac_temp ?? 24) : null }; return n; });
        return (
          <div key={d.id} className="casa-srow"><span>{ICONS[d.icon] ?? "🔌"} {d.name}</span>
            <span className="casa-row">
              <select className="casa-inp" value={a?.action ?? ""} onChange={(e) => set(e.target.value)} aria-label={`O que ${d.name} faz`}>
                <option value="">não mexe</option><option value="on">ligar</option><option value="off">desligar</option>
                {d.kind === "light" && <option value="dim">luz baixinha</option>}
              </select>
              {d.kind === "ac" && a?.action === "on" && (
                <select className="casa-inp casa-temp" value={a.ac_temp ?? 24} aria-label="Temperatura"
                        onChange={(e) => setActs((x) => ({ ...x, [d.id]: { ...x[d.id], ac_temp: +e.target.value } }))}>
                  {Array.from({ length: 15 }, (_, i) => 16 + i).map((t) => <option key={t} value={t}>{t}°</option>)}
                </select>)}
            </span>
          </div>
        );
      })}
      <div className="casa-brow left"><button className="casa-b p" onClick={() => void save()}>SALVAR</button>
        <button className="casa-b" onClick={onDone}>CANCELAR</button></div>
    </div>
  );
}

// --- ajustes: conectar, procurar, cadastrar -------------------------------------------

function Settings({ status, onChanged, onError, say, username }: {
  status: Status | null; onChanged: () => void; onError: (e: unknown) => void; say: (t: string) => void; username: string;
}) {
  const [all, setAll] = useState<Device[]>([]);
  const [busy, setBusy] = useState(false);
  const reload = useCallback(() => { casa.devices(true).then(setAll).catch(onError); }, [onError]);
  useEffect(reload, [reload]);
  const discover = async () => {
    setBusy(true);
    try { const r = await casa.discover(); say(r.new ? `${r.new} aparelho(s) novo(s): dê um nome a cada um` : `Nenhum novo (${r.found} na conta)`); reload(); onChanged(); }
    catch (e) { onError(e); } finally { setBusy(false); }
  };
  const fresh = all.filter((d) => !d.configured);
  const done = all.filter((d) => d.configured);
  return (
    <section>
      <div className="casa-panel casa-card">
        <div className="casa-lbl">conexão</div>
        {status?.provider === "demo" ? (
          <p className="casa-small"><b className="warn">MODO DEMONSTRAÇÃO</b> · aparelhos de mentira para você testar tudo. Para usar os seus aparelhos de verdade,
            no notebook rode <code>.venv/bin/titan enable-tuya</code> (passo a passo em docs/casa.md) e depois toque em PROCURAR NOVOS.</p>
        ) : (
          <p className="casa-small"><b className="ok">TUYA / SMART LIFE</b> · {status?.linked ? "conta ligada" : "procure os aparelhos para ligar a sua conta"} · operador {username}</p>
        )}
        <div className="casa-brow left"><button className="casa-b a" onClick={() => void discover()} disabled={busy}>{busy ? "PROCURANDO…" : "↻ PROCURAR NOVOS"}</button></div>
      </div>
      {fresh.length > 0 && (
        <div className="casa-panel casa-card casa-pending">
          <div className="casa-lbl">novos · dê um nome para cada um</div>
          <p className="casa-small">Não sabe qual tomada é qual? Toque em <b>TESTAR</b>: ela liga e desliga 2 vezes.</p>
          {fresh.map((d) => <DeviceEditor key={d.id} d={d} isNew onSaved={() => { reload(); onChanged(); }} onError={onError} say={say} />)}
        </div>
      )}
      <div className="casa-panel casa-card">
        <div className="casa-lbl">aparelhos cadastrados</div>
        {done.length === 0 ? <p className="casa-small">Nenhum ainda.</p>
          : done.map((d) => <DeviceEditor key={d.id} d={d} onSaved={() => { reload(); onChanged(); }} onError={onError} say={say} />)}
      </div>
    </section>
  );
}

function DeviceEditor({ d, isNew = false, onSaved, onError, say }: {
  d: Device; isNew?: boolean; onSaved: () => void; onError: (e: unknown) => void; say: (t: string) => void;
}) {
  const [name, setName] = useState(isNew ? "" : d.name);
  const [icon, setIcon] = useState(d.icon);
  const [room, setRoom] = useState(d.room);
  const [aliases, setAliases] = useState(d.aliases);
  const [testing, setTesting] = useState(false);
  const isPlug = d.kind === "plug" || d.kind === "fan";
  const save = async () => {
    const n = name.trim() || (isNew ? "" : d.name);
    if (!n) { say("Dê um nome (ex.: Ventilador)"); return; }
    const al = aliases.trim() || n.toLowerCase();
    try {
      await casa.patch(d.id, { name: n, icon, room: room.trim() || "Quarto", aliases: al, configured: true,
                               ...(isPlug ? { kind: icon === "fan" ? "fan" : "plug" } : {}) });
      say(isNew ? `${n} cadastrado` : "Salvo"); onSaved();
    } catch (e) { onError(e); }
  };
  return (
    <div className="casa-drow">
      <span className="casa-ic small">{ICONS[icon] ?? "🔌"}</span>
      <div className="casa-dcol">
        <span className="casa-small">{d.provider_name}{d.infrared ? " · infravermelho" : ""}{d.online ? "" : " · OFFLINE"}</span>
        <input className="casa-inp" value={name} onChange={(e) => setName(e.target.value)} placeholder={isNew ? "Nome (ex.: Ventilador)" : "Nome"} aria-label="Nome" maxLength={60} />
      </div>
      <select className="casa-inp" value={icon} onChange={(e) => setIcon(e.target.value)} aria-label="O que é">
        {Object.keys(ICONS).filter((k) => isPlug ? !["tv", "ac"].includes(k) : true).map((k) => <option key={k} value={k}>{ICONS[k]} {ICON_LABEL[k]}</option>)}
      </select>
      <input className="casa-inp" value={room} onChange={(e) => setRoom(e.target.value)} placeholder="Cômodo" aria-label="Cômodo" maxLength={40} />
      <input className="casa-inp" value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="Apelidos de voz (vírgula)" aria-label="Apelidos de voz" maxLength={300} />
      <span className="casa-row">
        {!d.infrared && <button className="casa-b" disabled={testing} onClick={async () => {
          setTesting(true); try { await casa.identify(d.id); } catch (e) { onError(e); } finally { setTesting(false); } }}>{testing ? "…" : "TESTAR"}</button>}
        <button className="casa-b p" onClick={() => void save()}>{isNew ? "CADASTRAR" : "SALVAR"}</button>
        {!isNew && <button className="casa-b bad" aria-label={`Esquecer ${d.name}`} onClick={async () => {
          if (!confirm(`Esquecer "${d.name}" no TITAN? (Na Tuya ele continua; volta como NOVO se procurar de novo.)`)) return;
          try { await casa.forget(d.id); onSaved(); } catch (e) { onError(e); } }}>✕</button>}
      </span>
    </div>
  );
}
