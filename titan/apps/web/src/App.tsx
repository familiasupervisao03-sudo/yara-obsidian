import { useEffect, useState } from "react";
import type { SessionInfo } from "@titan/api-contracts";
import { api, HttpError } from "./api";
import { Login } from "./components/Login";
import { Shell } from "./components/Shell";

export function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [checking, setChecking] = useState(true);
  const [fatal, setFatal] = useState<string | null>(null);

  useEffect(() => {
    api
      .me()
      .then(setSession)
      .catch((e) => {
        if (!(e instanceof HttpError && e.status === 401)) setFatal(String(e.message ?? e));
      })
      .finally(() => setChecking(false));
  }, []);

  if (checking) return <div className="boot">TITAN // inicializando…</div>;
  if (fatal) return <div className="boot error">Falha ao contatar o servidor do notebook: {fatal}</div>;
  if (!session) return <Login onLogin={setSession} />;
  return (
    <Shell
      session={session}
      onLogout={async () => {
        await api.logout().catch(() => undefined);
        setSession(null);
      }}
      onExpired={() => setSession(null)}
    />
  );
}
