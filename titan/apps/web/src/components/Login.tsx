import { useState, type FormEvent } from "react";
import type { SessionInfo } from "@titan/api-contracts";
import { api } from "../api";

export function Login({ onLogin }: { onLogin: (s: SessionInfo) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogin(await api.login(username, password));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="panel login-box" onSubmit={submit}>
        <h1 className="brand">TITAN</h1>
        <p className="muted">Centro de comando local — acesso restrito</p>
        <label>
          Operador
          <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label>
          Senha
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="alert" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? "Autenticando…" : "Entrar"}
        </button>
      </form>
    </main>
  );
}
