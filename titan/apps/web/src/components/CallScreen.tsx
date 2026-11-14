// "Ligar TITAN": tela de chamada no estilo do WhatsApp (ícone próprio na tela inicial do celular).
// Abre só com o botão de ligar → chama ~3 s → o TITAN atende → conversa por voz.
// No app Android: som no alto-falante de ouvido e sensor de proximidade (encostou no ouvido,
// a tela apaga e os toques travam: o rosto não desliga nem silencia sem querer).
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { androidApp } from "../notify";
import { remindersChanged } from "../reminders";
import { duckEnd, duckStart } from "../voice/duck";
import { VoiceSession } from "../voice/session";
import type { AudioFrame, Microphone } from "../voice/session";
import type { TtsEngine } from "../voice/player";
import { BrowserMicrophone, BrowserTts, ServerStt, ServerTts, StreamingChat, pickBrowserVoice } from "../voice/browser";
import { RING_MS, clock, greeting } from "../call";
import "./CallScreen.css";


type Phase = "dial" | "ringing" | "talk" | "ended";

interface CallBridge {
  callMode?(on: boolean): void;
  setSpeaker?(on: boolean): void;
  keepAwake?(on: boolean): void;
}

function bridge(): CallBridge | null {
  return androidApp() as unknown as CallBridge | null;
}

/** Microfone com "mudo": no mudo os quadros não chegam ao TITAN. */
class MutableMic implements Microphone {
  muted = false;
  private inner = new BrowserMicrophone();
  start(onFrame: (f: AudioFrame) => void): Promise<void> {
    return this.inner.start((f) => { if (!this.muted) onFrame(f); });
  }
  stop(): void { this.inner.stop(); }
}

/** Tom de chamando do Brasil (425 Hz, 1 s ligado) — leve, sem arquivo de áudio. */
function ringback(): () => void {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 425;
    gain.gain.value = 0;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    const t = ctx.currentTime;
    gain.gain.setValueAtTime(0.12, t + 0.05);
    gain.gain.setValueAtTime(0, t + 1.05);
    let done = false;
    return () => {
      if (done) return;
      done = true;
      try { osc.stop(); } catch { /* já parou */ }
      ctx.close().catch(() => undefined);
    };
  } catch {
    return () => undefined;
  }
}

export function CallScreen({ username, onClose }: { username: string; onClose: () => void }) {
  const [phase, setPhase] = useState<Phase>("dial");
  const [online, setOnline] = useState<boolean | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [muted, setMuted] = useState(false);
  const [speaker, setSpeaker] = useState(false);
  const [line, setLine] = useState<{ who: "titan" | "voce"; text: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [talking, setTalking] = useState(false);
  const sessionRef = useRef<VoiceSession | null>(null);
  const micRef = useRef<MutableMic | null>(null);
  const helloRef = useRef<{ stop(): void } | null>(null);
  const timers = useRef<number[]>([]);
  const stopRing = useRef<() => void>(() => undefined);
  const hasBridge = Boolean(bridge()?.callMode);

  // Disponível = o notebook (servidor do TITAN) responde.
  useEffect(() => {
    let alive = true;
    const check = () => fetch("/health", { credentials: "same-origin" })
      .then((r) => { if (alive) setOnline(r.ok); }).catch(() => { if (alive) setOnline(false); });
    void check();
    const id = window.setInterval(check, 10_000);
    return () => { alive = false; window.clearInterval(id); };
  }, []);

  useEffect(() => {
    if (phase !== "talk") return;
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, [phase]);

  // Sair da tela sempre desliga tudo (microfone, modo ligação, sensor).
  useEffect(() => () => hangUp(true), []); // eslint-disable-line react-hooks/exhaustive-deps

  function later(ms: number, fn: () => void) {
    timers.current.push(window.setTimeout(fn, ms));
  }

  async function buildTts(): Promise<TtsEngine | null> {
    try {
      const st = await api.voiceStatus();
      const server = st.engines.find((e) => (e.name === "piper" || e.name === "edge") && e.available);
      if (server) return new ServerTts(server.name, server.local);
    } catch { /* usa a voz do aparelho */ }
    const v = pickBrowserVoice(false) ?? pickBrowserVoice(true);
    return v ? new BrowserTts(v) : null;
  }

  function call() {
    if (phase !== "dial") return;
    setLine(null);
    setNotice(null);
    setMuted(false);
    setSpeaker(false);
    setPhase("ringing");
    const b = bridge();
    b?.callMode?.(true);   // alto-falante de ouvido + sensor de proximidade
    b?.keepAwake?.(true);
    void duckStart("ligacao");
    stopRing.current = ringback();
    later(RING_MS, () => { stopRing.current(); void answer(); });
  }

  async function answer() {
    setPhase("talk");
    setStartedAt(Date.now());
    setNow(Date.now());
    const tts = await buildTts();
    const hello = greeting(username);
    setLine({ who: "titan", text: hello });
    if (tts) {
      try {
        setTalking(true);
        const clip = await tts.prepare(hello, new AbortController().signal);
        helloRef.current = clip;
        if (phaseRef.current === "talk") await clip.play();
      } catch { /* sem voz agora: o texto já está na tela */ }
      setTalking(false);
    }
    if (!sessionRef.current && phaseRef.current === "talk") await startSession(tts);
  }

  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  async function startSession(tts: TtsEngine | null) {
    let convId: string | null = null;
    const chat = new StreamingChat(async () => {
      if (convId) return convId;
      convId = (await api.createConversation(`Ligação ${new Date().toLocaleString("pt-BR")}`)).id;
      return convId;
    }, "voice", {
      onActions: (_mid, acts) => {
        const list = acts as { type: string; title?: string }[];
        if (list.some((a) => a.type === "lembrete")) {
          remindersChanged();
          setNotice(`⏰ Anotado: ${list.filter((a) => a.type === "lembrete").map((a) => a.title).join(" · ")}`);
        }
      },
    });
    const mic = new MutableMic();
    micRef.current = mic;
    let reply = "";
    const session = new VoiceSession(
      { mic, stt: new ServerStt(), tts, chat, now: () => performance.now(),
        newId: () => crypto.randomUUID().replace(/-/g, "") },
      {
        onState: (s) => setTalking(s === "speaking"),
        onUserTurn: (t) => { reply = ""; setLine({ who: "voce", text: t }); },
        onAssistantDelta: (d) => { reply += d; setLine({ who: "titan", text: reply }); },
        onNotice: setNotice,
        onError: setNotice,
      },
      { confirmBeforeSend: false, ttsEnabled: Boolean(tts) },
    );
    sessionRef.current = session;
    await session.start();
  }

  function hangUp(silent = false) {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
    stopRing.current();
    helloRef.current?.stop();
    helloRef.current = null;
    sessionRef.current?.stop();
    sessionRef.current = null;
    micRef.current = null;
    const b = bridge();
    b?.callMode?.(false);
    b?.keepAwake?.(false);
    duckEnd("ligacao");
    setTalking(false);
    if (silent) return;
    setPhase("ended");
    later(1500, () => setPhase("dial"));
  }

  function toggleMute() {
    const m = !muted;
    setMuted(m);
    if (micRef.current) micRef.current.muted = m;
  }

  function toggleSpeaker() {
    const s = !speaker;
    setSpeaker(s);
    bridge()?.setSpeaker?.(s);
  }

  const status = phase === "ringing" ? "chamando…" : phase === "talk" ? `em ligação · ${clock(now - startedAt)}`
    : phase === "ended" ? "ligação encerrada" : "";

  return (
    <div className={`call-screen ${phase}`}>
      {phase === "dial" && (
        <button className="call-back" onClick={onClose} aria-label="Voltar ao TITAN">‹</button>
      )}
      <div className={`call-avatar ${talking ? "talking" : ""}`}>
        <img src="/icon-192.png" alt="" />
      </div>
      <div className="call-name">TITAN</div>
      {phase === "dial" ? (
        <>
          <div className="call-sub">seu assistente pessoal</div>
          <div className={`call-online ${online ? "on" : online === false ? "off" : ""}`}>
            ● {online === null ? "verificando…" : online ? "disponível" : "indisponível (notebook desligado?)"}
          </div>
        </>
      ) : (
        <>
          <div className="call-sub">📞 Chamada de voz</div>
          <div className="call-status">{status}</div>
        </>
      )}

      {phase === "talk" && line && (
        <div className="call-line"><b>{line.who === "titan" ? "TITAN" : "Você"}:</b> {line.text}</div>
      )}
      {phase === "talk" && notice && <div className="call-notice">{notice}</div>}

      <div className="call-actions">
        {phase === "dial" && (
          <div className="call-dial">
            <button className="call-btn call-green" onClick={call} disabled={online === false} aria-label="Ligar para o TITAN">
              <PhoneIcon />
            </button>
            <span>{online === false ? "o TITAN está fora do ar" : "toque para ligar"}</span>
          </div>
        )}
        {(phase === "ringing" || phase === "talk") && (
          <div className="call-row">
            <div className="call-opt">
              <button className={`call-btn call-round ${muted ? "on" : ""}`} onClick={toggleMute} disabled={phase !== "talk"}
                      aria-pressed={muted} aria-label="Mudo">{muted ? "🔇" : "🎙️"}</button>
              <span>mudo</span>
            </div>
            <div className="call-opt">
              <button className="call-btn call-red" onClick={() => hangUp()} aria-label="Desligar"><PhoneIcon /></button>
              <span>desligar</span>
            </div>
            <div className="call-opt">
              <button className={`call-btn call-round ${speaker ? "on" : ""}`} onClick={toggleSpeaker}
                      disabled={!hasBridge} aria-pressed={speaker} aria-label="Alto-falante">🔊</button>
              <span>alto-falante</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PhoneIcon() {
  return (
    <svg viewBox="0 0 24 24" width="34" height="34" aria-hidden="true">
      <path fill="currentColor" d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.6a1 1 0 0 1-.25 1z" />
    </svg>
  );
}
