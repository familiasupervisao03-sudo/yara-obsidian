import { useEffect, useMemo, useRef, useState } from "react";
import type { VoiceStatus } from "@titan/api-contracts";
import { api } from "../api";
import { VoiceSession } from "../voice/session";
import type { VoiceMetrics, VoiceState } from "../voice/session";
import type { TtsEngine } from "../voice/player";
import { Icon } from "./icons";
import {
  BrowserMicrophone,
  BrowserStt,
  BrowserTts,
  ServerStt,
  ServerTts,
  StreamingChat,
  browserSttSupported,
  pickBrowserVoice,
} from "../voice/browser";

type SttChoice = "vosk" | "browser";
type TtsChoice = "piper" | "browser-local" | "browser-network" | "none";

interface Prefs {
  stt: SttChoice;
  tts: TtsChoice;
  allowExternalStt: boolean;
  confirm: boolean;
  silenceMs: number;
  volume: number;
}

const DEFAULT_PREFS: Prefs = {
  stt: "vosk", tts: "piper", allowExternalStt: false, confirm: false, silenceMs: 1300, volume: 1,
};

function loadPrefs(): Prefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem("titan.voice") ?? "{}") };
  } catch {
    return DEFAULT_PREFS;
  }
}

const STATE_LABEL: Record<VoiceState, string> = {
  idle: "Desligado",
  starting: "Abrindo o microfone…",
  listening: "Ouvindo",
  user_speaking: "Você está falando",
  transcribing: "Entendendo o que você disse…",
  review: "Confira o texto antes de enviar",
  thinking: "TITAN está pensando…",
  speaking: "TITAN está falando",
  error: "Erro",
};

export function VoiceView({ conversationId, onConversation, onTurn, onUseText, onError }: {
  conversationId: string | null;
  onConversation: (id: string) => void;
  onTurn: () => void;
  onUseText: () => void;
  onError: (e: unknown) => void;
}) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [state, setState] = useState<VoiceState>("idle");
  const [partial, setPartial] = useState("");
  const [userText, setUserText] = useState("");
  const [assistant, setAssistant] = useState("");
  const [review, setReview] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<VoiceMetrics>({});
  const [muted, setMuted] = useState(false);
  const [ttsOn, setTtsOn] = useState(true);
  const sessionRef = useRef<VoiceSession | null>(null);
  const levelRef = useRef<HTMLDivElement>(null);
  const convRef = useRef<string | null>(conversationId);
  convRef.current = conversationId;

  useEffect(() => {
    api.voiceStatus().then(setStatus).catch(onError);
    // vozes do navegador carregam de forma assíncrona
    if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => setStatus((s) => (s ? { ...s } : s));
    return () => sessionRef.current?.stop(); // sair da tela desliga o microfone
  }, [onError]);

  useEffect(() => {
    try {
      localStorage.setItem("titan.voice", JSON.stringify(prefs));
    } catch {
      /* ignora */
    }
  }, [prefs]);

  const engines = useMemo(() => {
    const by = Object.fromEntries((status?.engines ?? []).map((e) => [e.name, e]));
    return { vosk: by.vosk, piper: by.piper };
  }, [status]);
  const localVoice = typeof window !== "undefined" ? pickBrowserVoice(false) : null;
  const anyVoice = typeof window !== "undefined" ? pickBrowserVoice(true) : null;
  const secure = typeof window !== "undefined" && window.isSecureContext;

  function buildTts(): TtsEngine | null {
    switch (prefs.tts) {
      case "piper": return engines.piper?.available ? new ServerTts() : null;
      case "browser-local": return localVoice ? new BrowserTts(localVoice) : null;
      case "browser-network": return anyVoice ? new BrowserTts(anyVoice) : null;
      default: return null;
    }
  }

  const sttOk = prefs.stt === "vosk" ? Boolean(engines.vosk?.available)
    : browserSttSupported() && prefs.allowExternalStt;

  async function start() {
    setErrorMsg(null);
    setNotice(null);
    const stt = prefs.stt === "vosk" ? new ServerStt() : new BrowserStt();
    const chat = new StreamingChat(async () => {
      if (convRef.current) return convRef.current;
      const c = await api.createConversation(`Voz ${new Date().toLocaleString("pt-BR")}`);
      onConversation(c.id);
      convRef.current = c.id;
      return c.id;
    });
    let lastPaint = 0;
    const session = new VoiceSession(
      { mic: new BrowserMicrophone(), stt, tts: buildTts(), chat, now: () => performance.now(),
        newId: () => crypto.randomUUID().replace(/-/g, "") },
      {
        onState: (s) => {
          setState(s);
          if (s === "review") setReview(sessionRef.current?.pendingText ?? "");
        },
        onPartial: setPartial,
        onUserTurn: (t) => { setUserText(t); setPartial(""); setAssistant(""); },
        onAssistantDelta: (d) => setAssistant((a) => a + d),
        onAssistantDone: () => onTurn(),
        onNotice: setNotice,
        onError: setErrorMsg,
        onMetrics: (m) => setMetrics({ ...m }),
        onLevel: (rms) => {
          const now = performance.now();
          if (now - lastPaint < 66 || !levelRef.current) return; // ~15 quadros/s
          lastPaint = now;
          const scale = 1 + Math.min(0.6, rms * 6);
          levelRef.current.style.setProperty("--level", scale.toFixed(3));
        },
      },
      { confirmBeforeSend: prefs.confirm, ttsEnabled: ttsOn, vad: { silenceEndMs: prefs.silenceMs } },
    );
    session.setVolume(prefs.volume);
    session.setMuted(muted);
    sessionRef.current = session;
    await session.start();
  }

  function stop() {
    sessionRef.current?.stop();
    sessionRef.current = null;
    setState("idle");
    setPartial("");
  }

  const active = state !== "idle" && state !== "error";
  const ttsEngineLabel = prefs.tts === "piper" ? "Piper (local)" : prefs.tts === "browser-local"
    ? `Navegador local${localVoice ? `: ${localVoice.name}` : " (indisponível)"}`
    : prefs.tts === "browser-network" ? "Navegador (pode enviar texto para fora)" : "Sem voz";

  return (
    <section className="voice-view">
      {!secure && (
        <p className="banner banner-warn">
          O navegador só libera o microfone em conexão segura (HTTPS) ou em
          http://127.0.0.1. No celular, a voz exige configurar HTTPS (ver docs/mobile.md).
        </p>
      )}

      <div className={`orb-wrap state-${state}`}>
        <div className="orb" ref={levelRef} aria-hidden />
        <p className="orb-label" role="status" aria-live="polite">{STATE_LABEL[state]}</p>
        {state === "listening" && <p className="muted small">Fale normalmente. Pode pausar para pensar.</p>}
        {active && <p className="mic-on small">● microfone ligado</p>}
      </div>

      <div className="voice-controls">
        {!active ? (
          <button onClick={start} disabled={!sttOk}><Icon name="mic" size={18} /> Iniciar conversa por voz</button>
        ) : (
          <button className="danger" onClick={stop}>Encerrar</button>
        )}
        {(state === "speaking" || state === "thinking") && (
          <button className="ghost" onClick={() => sessionRef.current?.interruptSpeaking()}>
            Interromper
          </button>
        )}
      </div>
      {!sttOk && (
        <p className="notice">
          {prefs.stt === "vosk"
            ? `Reconhecimento local indisponível: ${engines.vosk?.detail ?? "carregando…"}`
            : "Ative o consentimento para o reconhecimento do navegador abaixo, ou instale a voz local."}
        </p>
      )}

      {errorMsg && (
        <div className="banner banner-error" role="alert">
          {errorMsg} <button className="small" onClick={onUseText}>Usar texto</button>
        </div>
      )}
      {notice && <p className="notice">{notice}</p>}

      {state === "review" && (
        <div className="panel review">
          <label>
            Texto entendido (edite se precisar)
            <textarea value={review} onChange={(e) => setReview(e.target.value)} rows={3} />
          </label>
          <div className="row">
            <button onClick={() => sessionRef.current?.confirm(review)}>Enviar</button>
            <button className="ghost" onClick={() => sessionRef.current?.discard()}>Descartar</button>
          </div>
        </div>
      )}

      <div className="voice-transcript">
        {partial && <p className="partial"><span className="tag">parcial</span> {partial}</p>}
        {userText && <p className="msg msg-user"><span className="msg-meta">VOCÊ (texto final)</span>{userText}</p>}
        {assistant && <p className="msg msg-assistant"><span className="msg-meta">TITAN</span>{assistant}</p>}
      </div>

      <div className="voice-row">
        <button className="ghost small" onClick={() => { const m = !muted; setMuted(m); sessionRef.current?.setMuted(m); }}>
          {muted ? "🔇 Som desligado" : "🔊 Silenciar"}
        </button>
        <button className="ghost small" onClick={() => { const on = !ttsOn; setTtsOn(on); sessionRef.current?.setTtsEnabled(on); }}>
          {ttsOn ? "Voz: ligada" : "Voz: desligada (só texto)"}
        </button>
        <label className="volume">
          Volume
          <input type="range" min={0} max={1} step={0.05} value={prefs.volume}
                 onChange={(e) => { const v = Number(e.target.value); setPrefs({ ...prefs, volume: v }); sessionRef.current?.setVolume(v); }} />
        </label>
      </div>

      <details className="panel">
        <summary>Configurações e privacidade</summary>
        <fieldset disabled={active}>
          <legend className="small muted">Altere com a voz desligada</legend>
          <label>
            Reconhecimento de fala
            <select value={prefs.stt} onChange={(e) => setPrefs({ ...prefs, stt: e.target.value as SttChoice })}>
              <option value="vosk">Vosk no notebook — local {engines.vosk?.available ? "" : "(não instalado)"}</option>
              <option value="browser" disabled={!browserSttSupported()}>Navegador — EXTERNO (envia áudio ao fornecedor)</option>
            </select>
          </label>
          {prefs.stt === "browser" && (
            <label className="check">
              <input type="checkbox" checked={prefs.allowExternalStt}
                     onChange={(e) => setPrefs({ ...prefs, allowExternalStt: e.target.checked })} />
              Entendo que o áudio da minha fala será enviado ao fornecedor do navegador (ex.: Google).
            </label>
          )}
          <label>
            Voz do TITAN
            <select value={prefs.tts} onChange={(e) => setPrefs({ ...prefs, tts: e.target.value as TtsChoice })}>
              <option value="piper">Piper no notebook — local {engines.piper?.available ? "" : "(não instalado)"}</option>
              <option value="browser-local" disabled={!localVoice}>Voz do aparelho — local {localVoice ? "" : "(nenhuma pt-BR local)"}</option>
              <option value="browser-network" disabled={!anyVoice}>Voz do navegador on-line — pode enviar texto para fora</option>
              <option value="none">Sem voz (só texto)</option>
            </select>
          </label>
          <label>
            Silêncio para encerrar a sua fala: {(prefs.silenceMs / 1000).toFixed(1)} s
            <input type="range" min={800} max={3000} step={100} value={prefs.silenceMs}
                   onChange={(e) => setPrefs({ ...prefs, silenceMs: Number(e.target.value) })} />
          </label>
          <label className="check">
            <input type="checkbox" checked={prefs.confirm}
                   onChange={(e) => setPrefs({ ...prefs, confirm: e.target.checked })} />
            Revisar o texto antes de enviar
          </label>
        </fieldset>
        <p className="small muted">Voz em uso: {ttsEngineLabel}. Áudio não é gravado; é processado e descartado.</p>
        <ul className="small muted">{status?.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      </details>

      <details className="panel">
        <summary>Medições desta sessão</summary>
        <dl className="kv">
          <dt>Fim da fala → texto</dt><dd>{fmt(metrics.speechEndToTranscriptMs)}</dd>
          <dt>Texto → 1º trecho da resposta</dt><dd>{fmt(metrics.transcriptToFirstTextMs)}</dd>
          <dt>Texto → 1º áudio</dt><dd>{fmt(metrics.transcriptToFirstAudioMs)}</dd>
          <dt>Interrupção → áudio parado</dt><dd>{fmt(metrics.bargeInStopMs)}</dd>
        </dl>
      </details>
    </section>
  );
}

function fmt(ms?: number): string {
  return ms === undefined ? "—" : `${Math.round(ms)} ms`;
}
