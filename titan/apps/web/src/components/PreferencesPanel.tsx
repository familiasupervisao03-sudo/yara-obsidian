import { useEffect, useState } from "react";
import type { Preferences } from "@titan/api-contracts";
import { api } from "../api";

/** Preferências explícitas: consultar, alterar e apagar. Ficam só no notebook. */
export function PreferencesPanel() {
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.preferences().then(setPrefs).catch((e) => setError((e as Error).message));
  }, []);

  async function save(next: Preferences) {
    setPrefs(next);
    setError(null);
    try {
      setPrefs(await api.savePreferences(next));
      setSaved("Preferências salvas.");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function eraseAll() {
    if (!window.confirm("Apagar todas as preferências e correções guardadas?")) return;
    try {
      await api.deletePreferences();
      setPrefs(await api.preferences());
      setSaved("Preferências apagadas.");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!prefs) return <div className="panel"><p className="muted small">{error ?? "Carregando preferências…"}</p></div>;
  return (
    <section className="panel" aria-labelledby="prefs-title">
      <h3 id="prefs-title" className="panel-title">Preferências</h3>
      <p className="small muted">
        Mudam só o jeito de responder (nunca permissões ou aprovações). Ficam neste notebook.
      </p>
      <label>
        Tamanho das respostas
        <select value={prefs.response_length}
                onChange={(e) => void save({ ...prefs, response_length: e.target.value as Preferences["response_length"] })}>
          <option value="curta">Curtas e diretas</option>
          <option value="normal">Normal</option>
          <option value="detalhada">Mais detalhadas</option>
        </select>
      </label>
      <label>
        Tom
        <select value={prefs.formality}
                onChange={(e) => void save({ ...prefs, formality: e.target.value as Preferences["formality"] })}>
          <option value="informal">Informal</option>
          <option value="neutra">Neutro</option>
          <option value="formal">Formal</option>
        </select>
      </label>
      <label>
        Exemplos
        <select value={prefs.examples}
                onChange={(e) => void save({ ...prefs, examples: e.target.value as Preferences["examples"] })}>
          <option value="auto">Quando fizer sentido</option>
          <option value="sim">Sempre que ajudar</option>
          <option value="nao">Evitar</option>
        </select>
      </label>
      <label>
        Velocidade da voz: {prefs.voice_rate > 0 ? "+" : ""}{prefs.voice_rate}%
        <input type="range" min={-30} max={30} step={5} value={prefs.voice_rate}
               onChange={(e) => setPrefs({ ...prefs, voice_rate: Number(e.target.value) })}
               onPointerUp={() => void save(prefs)} onKeyUp={() => void save(prefs)} />
      </label>
      <h4 className="panel-title">Dicionário de correções da fala</h4>
      {prefs.corrections.length === 0 ? (
        <p className="small muted">Nenhuma. Ao corrigir um texto no modo revisão da voz, o TITAN pergunta se deve lembrar.</p>
      ) : (
        <ul className="corrections">
          {prefs.corrections.map((c) => (
            <li key={c.heard}>
              <span>“{c.heard}” → “{c.meant}”</span>
              <button className="ghost small" aria-label={`Remover correção ${c.heard}`}
                      onClick={() => void save({ ...prefs, corrections: prefs.corrections.filter((x) => x.heard !== c.heard) })}>
                Remover
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="row wrap">
        <button className="ghost danger small" onClick={() => void eraseAll()}>Apagar todas as preferências</button>
        {saved && <span className="small ok" role="status">{saved}</span>}
        {error && <span className="small bad" role="alert">{error}</span>}
      </div>
    </section>
  );
}
