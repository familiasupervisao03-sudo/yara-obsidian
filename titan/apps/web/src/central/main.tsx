// Entrada do TITAN Central (/central): a tela da nave na TV. Mesmo login e servidor do TITAN.
import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { SessionInfo } from "@titan/api-contracts";
import { api, HttpError } from "../api";
import { Login } from "../components/Login";
import { BootIntro } from "../components/BootIntro";
import { CrashScreen, ErrorBoundary } from "../components/ErrorBoundary";
import { applyAppearance, loadAppearance } from "../theme/themes";
import { CentralApp } from "./CentralApp";
import "../theme/futurista.css";
import "../theme/classico.css";
import "../styles.css";
import "./central.css";

applyAppearance(loadAppearance());

function CentralRoot() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [checking, setChecking] = useState(true);
  const [fatal, setFatal] = useState<string | null>(null);
  const [intro, setIntro] = useState(false);
  const [expired, setExpired] = useState(false);
  const enter = useCallback((s: SessionInfo) => { setSession(s); setExpired(false); setIntro(true); }, []);
  const endIntro = useCallback(() => setIntro(false), []);
  // A TV pode ligar antes do notebook: sem resposta, tenta de novo sozinha a cada 5 s.
  const [tries, setTries] = useState(0);
  useEffect(() => {
    let alive = true, timer = 0;
    api.me().then((s) => { if (alive) { setFatal(null); enter(s); } }).catch((e) => {
      if (!alive) return;
      if (e instanceof HttpError && e.status === 401) { setFatal(null); return; }
      setFatal(String(e.message ?? e));
      timer = window.setTimeout(() => setTries((n) => n + 1), 5000);
    }).finally(() => { if (alive) setChecking(false); });
    return () => { alive = false; window.clearTimeout(timer); };
  }, [enter, tries]);
  if (checking) return <div className="boot">TITAN CENTRAL // inicializando…</div>;
  if (fatal) return (
    <div className="boot error">
      <p>TITAN CENTRAL // procurando o notebook… (tentativa {tries + 1})</p>
      <p>Falha ao contatar o servidor do notebook: {fatal}</p>
      <p className="muted">Ligue o servidor no notebook (.venv/bin/titan ligar). Esta tela tenta de novo sozinha a cada 5 segundos.
        Se o navegador nunca abriu o TITAN, abra primeiro https://ENDEREÇO:8000 e aceite o cadeado.</p>
    </div>
  );
  if (!session) return <Login onLogin={enter} expired={expired} />;
  return (
    <>
      <CentralApp onExpired={() => { setExpired(true); setSession(null); }} />
      {intro && <BootIntro username={session.user.username} onDone={endIntro} />}
    </>
  );
}

const root = createRoot(document.getElementById("root")!);
root.render(<StrictMode><ErrorBoundary><CentralRoot /></ErrorBoundary></StrictMode>);
window.addEventListener("error", (ev) => {
  const el = document.getElementById("root");
  if (el && el.childElementCount === 0) root.render(<CrashScreen message={String(ev.message || ev.error)} />);
});
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => undefined);
}
