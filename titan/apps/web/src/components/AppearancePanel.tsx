// Sistema → Aparência: tema visual e modo leve (guardados só neste aparelho).
import { useState } from "react";
import { THEMES, loadAppearance, saveAppearance, type Appearance } from "../theme/themes";

export function AppearancePanel() {
  const [a, setA] = useState<Appearance>(loadAppearance);
  const update = (next: Appearance) => { setA(next); saveAppearance(next); };
  return (
    <div className="panel appearance">
      <h3 className="panel-title">Aparência</h3>
      <div className="theme-grid" role="radiogroup" aria-label="Tema visual">
        {THEMES.map((t) => (
          <button key={t.id} type="button" role="radio" aria-checked={a.theme === t.id}
                  className={`theme-option ghost ${a.theme === t.id ? "on" : ""}`} data-preview={t.id}
                  onClick={() => update({ ...a, theme: t.id })}>
            <span className="theme-swatch" aria-hidden="true" />
            <span className="theme-text"><strong>{t.nome}</strong><span>{t.descricao}</span></span>
          </button>
        ))}
      </div>
      <label className="check">
        <input type="checkbox" checked={a.leve} onChange={(e) => update({ ...a, leve: e.target.checked })} />
        <span><strong>Modo leve</strong> — sem brilhos, fundo decorado nem animações (para aparelhos mais fracos).</span>
      </label>
      <p className="small muted">Vale só para este aparelho: o celular e o notebook podem ter aparências diferentes.</p>
    </div>
  );
}
