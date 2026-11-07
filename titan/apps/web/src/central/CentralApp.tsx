// TITAN Central: a tela da nave na TV. Mostra o dia (hora, clima, lembretes, metas, casa),
// reage à voz ("Ei, Titã"), faz o briefing de bom dia, o quarto em holograma, o modo missão,
// o modo noite e os ALERTAS CRÍTICOS do notebook. Tudo com os dados reais do TITAN.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { HttpError } from "../api";
import { SpeechSegmenter } from "../voice/segmenter";
import { casa, ICONS } from "../casa/api";
import { Ear, type EarState } from "../casa/listen";
import { askTitan, askTitanStream, central, createReminder, upcomingReminders, type Alert, type Overview, type Telemetry } from "./api";
import { parseReminder, whenText } from "./reminder";
import { Speaker } from "./speaker";
import { Core, drawAlertChart, drawSpark, type CoreMode } from "./core";
import { plain, stripWake } from "./wake";

const DIAS = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];
const MES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const p2 = (n: number) => String(n).padStart(2, "0");
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const hhmm = (iso: string | null) => { if (!iso) return "—"; const d = new Date(iso); return `${p2(d.getHours())}:${p2(d.getMinutes())}`; };
const store = { get: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* sem armazenamento */ } } };
const NIGHT_FROM = 23, NIGHT_TO = 6;


let voiceEnabled = true;
const speaker = new Speaker(() => voiceEnabled);
async function say(text: string, on: boolean): Promise<void> {
  voiceEnabled = on;
  if (!on || !text) return;
  speaker.stop();
  speaker.say(text);
  await speaker.done();
}

function beep(f = 880, d = 0.18) {
  try { const a = new AudioContext(), o = a.createOscillator(), g = a.createGain(); o.type = "sawtooth"; o.frequency.value = f;
    g.gain.value = 0.03; g.gain.exponentialRampToValueAtTime(0.0001, a.currentTime + d); o.connect(g).connect(a.destination);
    o.start(); o.stop(a.currentTime + d); setTimeout(() => void a.close(), 600); } catch { /* sem som */ }
}

function useTyped(text: string, speed = 22): string {
  const [n, setN] = useState(0);
  const prev = useRef("");
  useEffect(() => {
    if (!text.startsWith(prev.current)) setN(0);   // texto novo: começa do zero; se só cresceu, continua
    prev.current = text;
    if (!text) return;
    const id = window.setInterval(() => setN((v) => { if (v >= text.length) { clearInterval(id); return v; } return v + 1; }), speed);
    return () => window.clearInterval(id);
  }, [text, speed]);
  return text.slice(0, n);
}

type Overlay = null | "brief" | "mission" | "night";

export function CentralApp({ onExpired }: { onExpired: () => void }) {
  const stageRef = useRef<HTMLDivElement>(null);
  const orbRef = useRef<HTMLCanvasElement>(null);
  const sparkRef = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<HTMLCanvasElement>(null);
  const core = useRef<Core | null>(null);
  const ear = useRef<Ear | null>(null);
  const [ov, setOv] = useState<Overview | null>(null);
  const [tel, setTel] = useState<Telemetry | null>(null);
  const [offline, setOffline] = useState(false);
  const [now, setNow] = useState(new Date());
  const [mode, setMode] = useState<CoreMode>("idle");
  const [holo, setHolo] = useState(false);
  const [lite, setLite] = useState(false);
  const [you, setYou] = useState("");
  const [ai, setAi] = useState("");
  const [timing, setTiming] = useState("");
  const [typing, setTyping] = useState(false);
  const [typed, setTyped] = useState("");
  const [reminders, setReminders] = useState<{ id: string; title: string; due_at: string }[]>([]);
  const [ringing, setRinging] = useState<{ id: string; title: string } | null>(null);
  const tHeard = useRef(0);     // quando terminou de ouvir (começou a transcrever)
  const tAsked = useRef(0);     // quando o texto chegou
  const tFirst = useRef(0);     // primeira palavra da resposta
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [briefStep, setBriefStep] = useState(0);
  const [mission, setMission] = useState<{ end: number; total: number; label: string } | null>(null);
  const [show, setShow] = useState<{ title: string; text: string } | null>(null);
  const [alert, setAlert] = useState<Alert | null>(null);
  const [dock, setDock] = useState(true);
  const [voiceOn, setVoiceOn] = useState(store.get("titan.central.voz") !== "0");
  const [always, setAlways] = useState(store.get("titan.central.sempre") === "1");
  const [nightAwake, setNightAwake] = useState(0);
  const lastEvent = useRef<number | null>(null);
  const lastShow = useRef<string | null>(null);
  const alertSeen = useRef<Record<string, number>>({});
  const voiceRef = useRef(voiceOn); voiceRef.current = voiceOn;
  const alwaysRef = useRef(always); alwaysRef.current = always;
  const ovRef = useRef(ov); ovRef.current = ov;
  const aiTyped = useTyped(ai);

  const fail = useCallback((e: unknown) => {
    if (e instanceof HttpError && e.status === 401) onExpired();
    else if (e instanceof HttpError && e.status === 0) setOffline(true);
  }, [onExpired]);

  // palco 1920x1080 escalado para qualquer tela
  useEffect(() => {
    const fit = () => { const s = Math.min(innerWidth / 1920, innerHeight / 1080);
      if (stageRef.current) stageRef.current.style.transform = `translate(-50%,-50%) scale(${s})`; };
    fit(); addEventListener("resize", fit); return () => removeEventListener("resize", fit);
  }, []);

  // núcleo animado
  useEffect(() => {
    const q = new URLSearchParams(location.search).get("leve");
    const c = new Core(orbRef.current!, q === "1" ? true : q === "0" ? false : null);
    c.onLite = setLite; setLite(c.lite); core.current = c;
    return () => c.stop();
  }, []);
  useEffect(() => { if (core.current) core.current.mode = mode; }, [mode]);
  useEffect(() => { if (core.current) core.current.holo = holo; }, [holo]);

  // relógio
  useEffect(() => { const id = window.setInterval(() => setNow(new Date()), 1000); return () => window.clearInterval(id); }, []);

  // lembretes com hora: a Central avisa (tela + voz) na hora certa, mesmo criados pelo celular
  const loadReminders = useCallback(() => { upcomingReminders().then(setReminders).catch(() => undefined); }, []);
  useEffect(() => { loadReminders(); const id = window.setInterval(loadReminders, 30_000); return () => window.clearInterval(id); }, [loadReminders]);
  useEffect(() => {
    let done: string[] = [];
    try { done = JSON.parse(store.get("titan.central.avisados") ?? "[]"); } catch { /* vazio */ }
    const due = reminders.find((x) => Date.parse(x.due_at) <= now.getTime() && Date.parse(x.due_at) > now.getTime() - 10 * 60_000 && !done.includes(x.id));
    if (!due) return;
    store.set("titan.central.avisados", JSON.stringify([...done, due.id].slice(-50)));
    setRinging({ id: due.id, title: due.title }); setNightAwake(Date.now());
    beep(988, 0.12); setTimeout(() => beep(1318, 0.18), 160);
    void say(`Lembrete: ${due.title}.`, voiceRef.current);
    const t = window.setTimeout(() => setRinging((v) => (v?.id === due.id ? null : v)), 60_000);
    return () => window.clearTimeout(t);
  }, [now, reminders]);

  // dados do TITAN (resumo a cada 5 s; telemetria a cada 10 s)
  const loadOverview = useCallback(async () => {
    try {
      const o = await central.overview(); setOv(o); setOffline(false);
      if (core.current) {
        const prev = new Map(core.current.devices.map((d) => [d.id, d]));
        core.current.devices = o.casa.devices.map((d) => ({ id: d.id, name: d.name, kind: d.kind, icon: d.icon, on: d.on,
          flashAt: prev.get(d.id)?.on !== undefined && prev.get(d.id)!.on !== d.on ? performance.now() : prev.get(d.id)?.flashAt }));
      }
      // algo mudou na casa (celular, tablet, cena...)
      const ev = o.casa.last_event;
      if (ev && lastEvent.current !== null && ev.id !== lastEvent.current && ev.scene && /bom dia/i.test(ev.scene)) void briefing();
      lastEvent.current = ev?.id ?? 0;
      // "mostra na tela" mandado do celular/chat
      if (o.show && o.show.id !== lastShow.current) {
        if (lastShow.current !== null || Date.now() - Date.parse(o.show.at) < 120_000) setShow({ title: o.show.title, text: o.show.text });
        lastShow.current = o.show.id;
      } else if (!o.show) lastShow.current = lastShow.current ?? "";
    } catch (e) { fail(e); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fail]);
  useEffect(() => { void loadOverview(); const id = window.setInterval(() => void loadOverview(), 5000); return () => window.clearInterval(id); }, [loadOverview]);

  const loadTelemetry = useCallback(async () => {
    try {
      const t = await central.telemetry(); setTel(t);
      for (const a of t.alerts) {
        if (a.key === "temp" || a.key === "cpu") core.current?.setLite(true);   // alivia o notebook
        if (Date.now() - (alertSeen.current[a.key] ?? 0) > 10 * 60_000) {
          alertSeen.current[a.key] = Date.now(); setAlert(a); setNightAwake(Date.now());
          for (let i = 0; i < 4; i++) setTimeout(() => beep(i % 2 ? 620 : 880), i * 450);
          void say(`${a.level === "warn" ? "Atenção" : "Alerta crítico"}. ${a.title.toLowerCase()}.`, voiceRef.current);
        }
      }
    } catch (e) { fail(e); }
  }, [fail]);
  useEffect(() => { void loadTelemetry(); const id = window.setInterval(() => void loadTelemetry(), 10_000); return () => window.clearInterval(id); }, [loadTelemetry]);

  // alerta: gráfico e some sozinho em 25 s (fica o aviso no topo enquanto durar)
  useEffect(() => {
    if (!alert) return;
    if (chartRef.current) drawAlertChart(chartRef.current, alert.history, alert.limit, alert.max, alert.unit, alert.level === "warn");
    const id = window.setTimeout(() => setAlert(null), 25_000);
    return () => window.clearTimeout(id);
  }, [alert]);
  useEffect(() => { if (sparkRef.current && tel?.history) drawSpark(sparkRef.current, tel.history.cpu.filter((v): v is number => v !== null)); }, [tel]);

  // modo noite automático (23h–6h), acorda por 10 min com voz, toque ou alerta
  const nightHour = now.getHours() >= NIGHT_FROM || now.getHours() < NIGHT_TO;
  const nightAuto = nightHour && Date.now() - nightAwake > 10 * 60_000 && overlay !== "brief" && overlay !== "mission";
  const showNight = overlay === "night" || (nightAuto && overlay === null && !alert);

  // ---------- falar e entender ----------
  const reply = useCallback(async (text: string) => {
    setAi(text); setMode("speak");
    if (!tFirst.current) tFirst.current = performance.now();
    await say(text, voiceRef.current);
    window.setTimeout(() => setMode((m) => (m === "speak" ? "idle" : m)), voiceRef.current ? 400 : 2500);
  }, []);

  // tempos de cada etapa (para achar onde está a demora): ouvir · pensar · voz
  useEffect(() => {
    speaker.onFirstAudio = () => {
      const now = performance.now(), f = (ms: number) => `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
      if (!tAsked.current || now - tAsked.current > 30_000) return;  // fala que não é resposta (ex.: lembrete tocando)
      const parts = [];
      if (tHeard.current && tAsked.current) parts.push(`ouvir ${f(tAsked.current - tHeard.current)}`);
      if (tAsked.current && tFirst.current) parts.push(`pensar ${f(tFirst.current - tAsked.current)}`);
      if (tFirst.current) parts.push(`voz ${f(now - tFirst.current)}`);
      setTiming(parts.join(" · "));
    };
  }, []);

  /** Pergunta ao TITAN e já vai falando cada frase enquanto a resposta chega. */
  const askAndSpeak = useCallback(async (text: string) => {
    voiceEnabled = voiceRef.current;
    speaker.stop();
    const seg = new SpeechSegmenter();
    let acc = "";
    const full = await askTitanStream(text, (d) => {
      if (!acc) { tFirst.current = performance.now(); setMode("speak"); }
      acc += d; setAi(acc);
      for (const sg of seg.push(d)) speaker.say(sg.text);
    });
    for (const sg of seg.flush()) speaker.say(sg.text);
    if (!acc && full) { setAi(full); speaker.say(full); }
    await speaker.done();
    window.setTimeout(() => setMode((m) => (m === "speak" ? "idle" : m)), voiceRef.current ? 300 : 2500);
  }, []);

  const startMission = useCallback((min: number, label = "FOCO") => {
    setMission({ end: Date.now() + min * 60_000, total: min * 60_000, label }); setOverlay("mission");
    void say(`Modo missão ativado. ${min} minutos de foco.`, voiceRef.current);
  }, []);

  async function briefing() {
    const o = ovRef.current ?? await central.overview().catch(() => null);
    if (!o) return;
    setOverlay("brief"); setBriefStep(0); setNightAwake(Date.now());
    for (let i = 1; i <= 8; i++) setTimeout(() => setBriefStep(i), i * 450);
    const w = o.weather, pend = o.today.filter((t) => !t.done);
    const parts = [`${o.greeting}, ${cap(o.username)}.`];
    if (w?.temp != null) parts.push(`Agora faz ${w.temp} graus em ${w.city}, ${w.text.toLowerCase()}${w.max != null ? `, máxima de ${Math.round(w.max)}` : ""}${w.rain_chance ? `, chance de chuva de ${w.rain_chance} por cento` : ""}.`);
    parts.push(pend.length ? `Você tem ${pend.length} ${pend.length === 1 ? "compromisso" : "compromissos"} hoje: ${pend.slice(0, 3).map((t) => t.title).join(", ")}.` : "Nada marcado para hoje.");
    const g = o.goals.find((x) => x.pct !== null);
    if (g) parts.push(`Sua meta ${g.title} está em ${g.pct} por cento.`);
    setTimeout(() => void say(parts.join(" "), voiceRef.current), 3800);
    setTimeout(() => setOverlay((v) => (v === "brief" ? null : v)), 22_000);
  }

  const handle = useCallback(async (raw: string, src: "voz" | "texto") => {
    const [text, woke] = stripWake(raw);
    if (src === "voz" && alwaysRef.current && !woke) return;            // escuta contínua: só com "Ei, Titã"
    setNightAwake(Date.now()); if (overlay === "night") setOverlay(null);
    if (!text) { setYou("“Ei, Titã”"); void reply("Pode falar."); return; }
    setYou(`“${text}”`); setAi(""); setMode("think"); setTiming("");
    tAsked.current = performance.now(); tFirst.current = 0;
    if (src !== "voz") tHeard.current = 0;
    const n = plain(text);
    try {
      if (/^(sair|fechar|fecha|cancela|cancelar|voltar|volta)\b/.test(n)) {
        setOverlay(null); setHolo(false); setShow(null); setMission(null); void central.clearShow().catch(() => undefined); return void reply("Ok.");
      }
      if (/holograma|mostra o quarto|planta do quarto/.test(n)) { setHolo(true); return void reply("Quarto em holograma."); }
      const ms = n.match(/modo (missao|foco)(?:\s+(?:de\s+)?(\d{1,3})\s*min)?/);
      if (ms) { setMode("idle"); return startMission(Math.max(1, Math.min(180, Number(ms[2] ?? 25)))); }
      if (/^modo noite\b/.test(n)) { setOverlay("night"); setNightAwake(0); return void reply(""); }
      const mt = text.match(/^mostr[ae]\s+(?:na|no)\s+(?:tela|tv|central)\s*(.*)$/i);
      if (mt && mt[1]) {
        const answer = await askTitan(`Explique de forma curta e clara, para mostrar numa tela grande: ${mt[1]}`);
        setShow({ title: mt[1].slice(0, 80), text: answer }); return void reply("Mostrando na tela.");
      }
      // lembrete com hora: "me lembra de tirar o bolo às 2:30 da tarde" (sem IA, na hora)
      const rem = parseReminder(text);
      if (rem) {
        await createReminder(rem.title, rem.due);
        loadReminders(); void loadOverview();
        return void reply(`Lembrete criado: ${rem.title}, ${whenText(rem.due)}. Te aviso na hora.`);
      }
      const r = await casa.command(text, src, false);
      if (r.understood) {
        if (r.device && core.current) core.current.flash(r.device.id);
        void loadOverview();
        if (r.scene && /bom dia/i.test(r.scene)) { void reply(r.reply); return void briefing(); }
        return void reply(r.reply);
      }
      if (/^bom dia\b/.test(n)) { setMode("idle"); return void briefing(); }
      await askAndSpeak(text);
    } catch (e) { fail(e); void reply("Não consegui agora."); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlay, reply, startMission, fail, loadOverview, loadReminders, askAndSpeak]);

  const earState = useCallback((s: EarState) => {
    if (s === "thinking") tHeard.current = performance.now();
    setMode((m) => (s === "hearing" ? "listen" : s === "thinking" ? "think" : m === "listen" || m === "think" ? "idle" : m));
  }, []);
  const getEar = () => (ear.current ??= new Ear((t) => void handle(t, "voz"), earState, (p) => p && setYou(`“${p}”`), (m) => void reply(m)));
  useEffect(() => { if (ear.current) (ear.current as unknown as { onText: (t: string) => void }).onText = (t: string) => void handle(t, "voz"); }, [handle]);
  useEffect(() => { if (always) void getEar().continuous(); return () => ear.current?.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [always]);
  const talk = () => { setNightAwake(Date.now()); setYou(""); setAi(""); if (!always) void getEar().once(); };

  // dock de controles: aparece ao mexer o mouse / tocar
  useEffect(() => {
    let id = window.setTimeout(() => setDock(false), 5000);
    const wake = () => { setDock(true); window.clearTimeout(id); id = window.setTimeout(() => setDock(false), 5000); };
    addEventListener("pointermove", wake); addEventListener("pointerdown", wake); addEventListener("keydown", wake);
    return () => { window.clearTimeout(id); removeEventListener("pointermove", wake); removeEventListener("pointerdown", wake); removeEventListener("keydown", wake); };
  }, []);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement | null)?.tagName === "INPUT") return;  // digitando: espaço é espaço
      if (e.key === " ") { e.preventDefault(); talk(); }
      else if (e.key === "Escape") { setOverlay(null); setHolo(false); setShow(null); setAlert(null); setMission(null); }
    };
    addEventListener("keydown", key); return () => removeEventListener("keydown", key);
  });

  // missão: contagem
  const left = mission ? Math.max(0, mission.end - now.getTime()) : 0;
  useEffect(() => { if (mission && left === 0) { setMission(null); setOverlay(null); void reply("Missão cumprida. Pode respirar."); } }, [mission, left, reply]);

  // ---------- telas ----------
  const t = tel?.now;
  const spend = t?.spend_pct;
  const tele = tel?.available ? [
    { k: "PROCESSADOR", v: t?.cpu, txt: t?.cpu != null ? `${Math.round(t.cpu)}%` : "—", bad: tel.alerts.some((a) => a.key === "cpu") },
    { k: "TEMPERATURA", v: t?.temp != null ? (t.temp - 20) / 0.85 : null, txt: t?.temp != null ? `${Math.round(t.temp)}°` : "—", bad: tel.alerts.some((a) => a.key === "temp") },
    { k: "MEMÓRIA", v: t?.mem, txt: t?.mem != null ? `${Math.round(t.mem)}%` : "—", bad: false },
    spend != null ? { k: "GASTO IA HOJE", v: spend, txt: `${Math.round(spend)}%`, bad: tel.alerts.some((a) => a.key === "spend") }
      : { k: "BATERIA", v: t?.bat_pct, txt: t?.bat_pct != null ? `${Math.round(t.bat_pct)}%${t.charging ? " ⚡" : ""}` : "—", bad: tel.alerts.some((a) => a.key === "bat") },
  ] : [];
  const devs = ov?.casa.devices ?? [];
  const pend = ov?.today ?? [];
  const goals = (ov?.goals ?? []).slice(0, 3);
  const w = ov?.weather;
  const ticker = useMemo(() => {
    if (!ov) return "";
    const items = [`◆ TITAN ${ov.today.filter((x) => !x.done).length} pendência(s) hoje`];
    ov.goals.slice(0, 2).forEach((g) => items.push(`◆ META ${g.title}${g.pct !== null ? ` · ${g.pct}%` : ""}`));
    items.push(`◆ CASA ${ov.casa.on} de ${ov.casa.devices.length} aparelho(s) ligado(s)${ov.casa.demo ? " (demonstração)" : ""}`);
    if (ov.weather?.temp != null) items.push(`◆ CLIMA ${ov.weather.city}: ${ov.weather.temp}° · ${ov.weather.text}`);
    if (tel?.available) items.push(tel.alerts.length ? `◆ SISTEMA ${tel.alerts.length} alerta(s) ativo(s)` : "◆ SISTEMA todos os módulos operando");
    return items.join("     ");
  }, [ov, tel]);
  const activeAlerts = tel?.alerts ?? [];
  const stateLabel = holo ? ["QUARTO · HOLOGRAMA", "diga “sair” para voltar"] : mode === "listen" ? ["OUVINDO", "fale normalmente"]
    : mode === "think" ? ["PROCESSANDO", "entendendo o pedido"] : mode === "speak" ? ["RESPONDENDO", "voz do TITAN"]
    : [always ? "ESCUTA CONTÍNUA" : "EM ESPERA", always ? "diga “Ei, Titã”" : "toque no núcleo ou aperte espaço"];

  return (
    <div className={`cx ${lite ? "lite" : ""}`}>
      <div className="cx-stage" ref={stageRef}>
        <div className="cx-hex" />
        <div className="cx-main">
          <div className="cx-top">
            <div className="cx-brand">TITAN<small>CENTRAL</small></div>
            <div className="cx-pills">
              {activeAlerts.map((a) => <button key={a.key} className={`cx-pill danger ${a.level}`} onClick={() => setAlert(a)}>⚠ {a.title}</button>)}
              <div className="cx-pill"><span className={`dot ${offline ? "off" : ""}`} />NÚCLEO <b>{offline ? "SEM CONEXÃO" : "ONLINE"}</b></div>
              <div className="cx-pill">CASA <b>{ov ? `${ov.casa.on}/${devs.length}` : "—"}</b></div>
              <div className="cx-pill">VOZ <b>{always ? "CONTÍNUA" : "TOQUE"}</b></div>
            </div>
          </div>

          <div className="cx-card cx-clock"><div className="cx-lbl">tempo de bordo</div>
            <div className="t">{p2(now.getHours())}:{p2(now.getMinutes())}<span>{p2(now.getSeconds())}</span></div>
            <div className="d">{DIAS[now.getDay()]} · {now.getDate()} {MES[now.getMonth()]} {now.getFullYear()}</div></div>

          <div className="cx-card cx-wx"><div className="cx-lbl">condições externas{w?.city ? ` · ${w.city}` : ""}</div>
            {w && w.temp != null ? (<><WeatherIcon icon={w.icon} /><div><div className="temp">{w.temp}°</div>
              <div className="desc">{w.text}<br />{w.max != null && <>máx {Math.round(w.max)}° · mín {Math.round(w.min ?? 0)}°</>}{w.rain_chance != null && <> · chuva {w.rain_chance}%</>}</div></div></>)
              : <div className="desc wide">Sem clima configurado. No notebook: <code>titan central-clima "Sua cidade"</code></div>}</div>

          <div className="cx-card cx-tele"><div className="cx-lbl">{tel?.available ? "telemetria do notebook" : "telemetria"}</div>
            {tel?.available ? tele.map((r) => (
              <div key={r.k} className={`cx-bar ${r.bad ? "bad" : ""}`}>{r.k}<div className="tr"><i style={{ width: `${Math.max(0, Math.min(100, r.v ?? 0))}%` }} /></div><span className="v">{r.txt}</span></div>
            )) : <div className="desc">A telemetria do notebook aparece só para o dono do servidor.</div>}
            <canvas ref={sparkRef} width={418} height={70} className="cx-spark" /></div>

          <div className="cx-core">
            <canvas ref={orbRef} width={840} height={780} onClick={talk} aria-label="Falar com o TITAN" role="button" />
            <div className={`cx-state ${mode === "think" ? "think" : ""}`}>{stateLabel[0]}<small>{stateLabel[1]}</small></div>
          </div>

          <div className="cx-card cx-today"><div className="cx-lbl">hoje</div>
            {pend.length === 0 && <div className="desc">Nada marcado para hoje.</div>}
            {pend.slice(0, 5).map((x) => {
              const late = !x.done && x.due_at && Date.parse(x.due_at) < now.getTime();
              return <div key={x.id} className={`item ${x.done ? "done" : ""} ${late ? "hot" : ""}`}><span className="h">{x.due_at ? hhmm(x.due_at) : "—"}</span>{x.title}</div>;
            })}</div>

          <div className="cx-card cx-goals"><div className="cx-lbl">metas</div>
            {goals.length === 0 ? <div className="desc">Nenhuma meta ativa. Crie no Início do TITAN.</div> : (
              <div className="rings">{goals.map((g) => (
                <div className="ring" key={g.id}><svg viewBox="0 0 112 112"><circle className="bg" cx="56" cy="56" r="48" />
                  <circle className="fg" cx="56" cy="56" r="48" strokeDasharray="301.6" strokeDashoffset={301.6 * (1 - (g.pct ?? 0) / 100)} /></svg>
                  <div className="pc">{g.pct !== null ? `${g.pct}%` : "—"}</div><div className="nm">{g.title}</div></div>))}</div>)}</div>

          <div className="cx-card cx-house"><div className="cx-lbl">casa{ov?.casa.demo ? " · demonstração" : ""}</div>
            {devs.length === 0 ? <div className="desc">Nenhum aparelho cadastrado. Cadastre no TITAN Casa.</div> : (
              <div className="devs">{devs.slice(0, 5).map((d) => (
                <button key={d.id} className={`dev ${d.on ? "on" : ""}`} onClick={() => { void casa.act(d.id, { do: "toggle" }).then(() => loadOverview()).catch(fail); }}>
                  <div className="ic">{ICONS[d.icon] ?? "🔌"}</div><div className="nm">{d.name}</div>
                  <div className="st">{d.on ? "LIGADO" : "DESLIGADO"}</div></button>))}</div>)}</div>

          <div className="cx-legend"><div className="you">{you && <><b>VOCÊ ›</b>{you}</>}</div>
            <div className="ai">{ai && <><b>TITAN ›</b>{aiTyped}{aiTyped.length < ai.length && <span className="caret" />}</>}</div>
            {timing && <div className="tm">{timing}</div>}</div>

          <div className="cx-ticker"><div key={ticker}>{ticker}</div></div>
        </div>

        {show && <div className="cx-show"><div className="cx-lbl">na tela · pedido ao TITAN</div><h3>{show.title}</h3>
          <div className="body">{show.text}</div>
          <button className="cx-close" onClick={() => { setShow(null); void central.clearShow().catch(() => undefined); }}>FECHAR ✕</button></div>}

        {overlay === "brief" && ov && <div className="cx-ov cx-brief">
          {briefStep < 6 ? <div className="boot">{["TITAN NÚCLEO", "MEMÓRIA", `CASA (${devs.length} aparelhos)`, "LINK COM A IA", "VOZ E OUVIDO"].map((l, i) =>
            <div key={l} className={`ln ${briefStep > i ? "in" : ""}`}>{l.padEnd(32, ".")} <span className="ok">OK</span></div>)}
            <div className={`ln big ${briefStep > 4 ? "in" : ""}`}>TITAN</div></div> : (<>
            <h2>BRIEFING</h2><h1>{ov.greeting}, {cap(ov.username)}.</h1>
            <div className={`bc ${briefStep > 6 ? "in" : ""}`} style={{ left: 150 }}><div className="k">CLIMA</div>
              {w?.temp != null ? <><div className="v">{w.temp}°</div><p>{w.text}{w.max != null ? `, máxima de ${Math.round(w.max)}°` : ""}{w.rain_chance ? `, chuva ${w.rain_chance}%` : ""}.</p></> : <p>Clima não configurado.</p>}</div>
            <div className={`bc ${briefStep > 6 ? "in" : ""}`} style={{ left: 760, transitionDelay: ".3s" }}><div className="k">HOJE</div>
              <ul>{pend.filter((x) => !x.done).slice(0, 4).map((x) => <li key={x.id}><span>{x.due_at ? hhmm(x.due_at) : "—"}</span>{x.title}</li>)}
                {pend.filter((x) => !x.done).length === 0 && <li>Nada marcado.</li>}</ul></div>
            <div className={`bc ${briefStep > 6 ? "in" : ""}`} style={{ left: 1370, transitionDelay: ".6s" }}><div className="k">METAS</div>
              <ul>{goals.map((g) => <li key={g.id}><span>{g.pct !== null ? `${g.pct}%` : "—"}</span>{g.title}</li>)}{goals.length === 0 && <li>Nenhuma meta ativa.</li>}</ul></div></>)}
        </div>}

        {overlay === "mission" && mission && <div className="cx-ov cx-mission" onClick={() => undefined}>
          <svg viewBox="0 0 620 620"><circle cx="310" cy="310" r="290" stroke="#1d2a18" />
            <circle cx="310" cy="310" r="290" stroke="#ffb547" strokeDasharray={2 * Math.PI * 290} strokeDashoffset={2 * Math.PI * 290 * (1 - left / mission.total)} /></svg>
          <div className="t"><div className="k">MODO MISSÃO</div><div className="n">{p2(Math.floor(left / 60000))}:{p2(Math.floor(left / 1000) % 60)}</div>
            <div className="s">{mission.label} · DIGA “SAIR” PARA ENCERRAR</div></div></div>}

        {showNight && <div className="cx-ov cx-night" onClick={() => { setNightAwake(Date.now()); setOverlay(null); }}>
          <div className="t">{p2(now.getHours())}:{p2(now.getMinutes())}</div><div className="s">MODO NOITE · DIGA “EI, TITÃ” OU TOQUE PARA ACORDAR</div></div>}

        {ringing && <div className="cx-remind" role="alert">
          <div className="k">🔔 LEMBRETE</div><div className="v">{ringing.title}</div>
          <button className="cx-remind-ok" onClick={() => setRinging(null)}>OK ✓</button></div>}

        {alert && <div className={`cx-ov cx-alert ${alert.level === "warn" ? "warn" : ""}`}><div className="band">
          <div className="k">{alert.level === "warn" ? "⚠ ATENÇÃO MÁXIMA ⚠" : "⚠ ALERTA CRÍTICO ⚠"}</div>
          <div className="row"><div><div className="tt">{alert.title}</div>
            <div className="big">{Math.round(alert.value)}<small>{alert.unit}</small></div><div className="s">{alert.text}</div>
            <div className="act"><b>O QUE FAZER</b>{alert.todo}</div>
            {alert.plug && alert.plug.on && <button className="cx-act" onClick={() => { void casa.act(alert.plug!.id, { do: "off" }).then(() => { setAlert(null); void reply(`Tomada ${alert.plug!.name} desligada.`); }).catch(fail); }}>
              DESLIGAR A TOMADA “{alert.plug.name.toUpperCase()}”</button>}</div>
            <canvas ref={chartRef} width={700} height={300} /></div>
          <button className="cx-close" onClick={() => setAlert(null)}>ENTENDI ✕</button></div></div>}

        <div className="cx-scan" />
      </div>

      {typing && <form className="cx-type" onSubmit={(e) => { e.preventDefault(); const t = typed.trim(); if (t) { void handle(t, "texto"); setTyped(""); } }}>
        <input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Digite um comando: liga o ventilador · me lembra às 14:30 de…" aria-label="Comando para o TITAN" />
        <button type="submit">ENVIAR</button>
        <button type="button" onClick={() => setTyping(false)}>✕</button>
      </form>}
      <div className={`cx-dock ${dock || typing ? "show" : ""}`}>
        <button className="main" onClick={talk}>🎙 Falar</button>
        <button onClick={() => setTyping((v) => !v)}>⌨ Digitar</button>
        <button onClick={() => void briefing()}>☀ Bom dia</button>
        <button onClick={() => setHolo((v) => !v)}>🧊 Holograma</button>
        <button onClick={() => startMission(25)}>⏱ Missão 25 min</button>
        <button onClick={() => { setOverlay("night"); setNightAwake(0); }}>🌙 Noite</button>
        <button className={always ? "on" : ""} onClick={() => { const v = !always; setAlways(v); store.set("titan.central.sempre", v ? "1" : "0"); }}>👂 Escuta contínua: {always ? "ligada" : "desligada"}</button>
        <button className={voiceOn ? "on" : ""} onClick={() => { const v = !voiceOn; setVoiceOn(v); store.set("titan.central.voz", v ? "1" : "0"); }}>{voiceOn ? "🔊 Voz" : "🔈 Sem voz"}</button>
        <button onClick={() => { (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen()).catch(() => undefined); }}>⛶ Tela cheia</button>
      </div>
    </div>
  );
}

function WeatherIcon({ icon }: { icon: string }) {
  const sun = <><circle cx="40" cy="40" r="16" fill="none" stroke="#ffb547" strokeWidth="3" />
    <g stroke="#ffb547" strokeWidth="3"><line x1="40" y1="10" x2="40" y2="17" /><line x1="40" y1="63" x2="40" y2="70" /><line x1="10" y1="40" x2="17" y2="40" />
      <line x1="63" y1="40" x2="70" y2="40" /><line x1="19" y1="19" x2="24" y2="24" /><line x1="61" y1="19" x2="56" y2="24" /></g></>;
  const cloud = <path d="M38 78h42a12 12 0 0 0-3-23.6A17 17 0 0 0 45 58a11 11 0 0 0-7 20z" fill="#061620" stroke="#3ee8ff" strokeWidth="3" />;
  const rain = <g stroke="#3ee8ff" strokeWidth="3"><line x1="48" y1="84" x2="44" y2="94" /><line x1="60" y1="84" x2="56" y2="94" /><line x1="72" y1="84" x2="68" y2="94" /></g>;
  return <svg viewBox="0 0 100 100" className="cx-wxi">{icon === "sol" ? <g transform="translate(10 10)">{sun}</g> : <>
    {icon === "nuvem-sol" && sun}{cloud}{(icon === "chuva" || icon === "tempestade") && rain}</>}</svg>;
}
