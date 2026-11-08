import { useCallback, useEffect, useState } from "react";
import type { SessionInfo } from "@titan/api-contracts";
import { api, HttpError } from "./api";
import { Login } from "./components/Login";
import { Shell } from "./components/Shell";
import { BootIntro } from "./components/BootIntro";

export function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [checking, setChecking] = useState(true);
  const [fatal, setFatal] = useState<string | null>(null);
  // Abertura "IA de bordo": ao entrar na conta e ao abrir o TITAN já logado (uma vez por abertura).
  const [intro, setIntro] = useState(false);
  const [expired, setExpired] = useState(false);
  const endIntro = useCallback(() => setIntro(false), []);
  const enter = useCallback((s: SessionInfo) => { setSession(s); setExpired(false); setIntro(true); }, []);

  useEffect(() => {
    api
      .me()
      .then(enter)
      .catch((e) => {
        if (!(e instanceof HttpError && e.status === 401)) setFatal(String(e.message ?? e));
      })
      .finally(() => setChecking(false));
  }, [enter]);

  if (checking) return <div className="boot">TITAN // inicializando…</div>;
  if (fatal) return <div className="boot error">Falha ao contatar o servidor do notebook: {fatal}</div>;
  if (!session) return <Login onLogin={enter} expired={expired} />;
  return (
    <>
    <Shell
      session={session}
      onLogout={async () => {
        await api.logout().catch(() => undefined);
        setSession(null);
      }}
      onExpired={() => { setExpired(true); setSession(null); }}
    />
    {intro && <BootIntro username={session.user.username} onDone={endIntro} />}
    </>
  );
}
