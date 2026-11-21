// Sistema → Clima e chegada: cidade do clima, aviso de chuva, boas-vindas, pergunta ao sair e
// o que ligar ao chegar (o dono cadastra; vem vazio).
import { useEffect, useState } from "react";
import { androidApp } from "../notify";
import { DO_LABEL, jarvis, type Device, type JarvisSettings, type Place, type Step } from "../jarvis";
import "./Jarvis.css";

export function JarvisPanel({ open }: { open?: boolean }) {
  const [s, setS] = useState<JarvisSettings | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Place[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [arrive, setArrive] = useState(false);
  useEffect(() => {
    jarvis.settings().then(setS).catch(() => setS(null));
    jarvis.devices().then(setDevices).catch(() => setDevices([]));
  }, []);
  if (!s) return null;
  const flash = (t: string) => { setMsg(t); window.setTimeout(() => setMsg(null), 1800); };
  const save = (p: Partial<JarvisSettings>) => {
    setS({ ...s, ...p });
    jarvis.saveSettings(p).then((x) => { setS(x); flash("Salvo."); }).catch((e) => flash((e as Error).message));
  };
  const check = (k: "rain_alert" | "welcome" | "ask_leave", label: string, hint: string) => (
    <label className="check">
      <input type="checkbox" checked={s[k]} onChange={(e) => save({ [k]: e.target.checked })} />
      <span>{label}<span className="muted small"> — {hint}</span></span>
    </label>
  );
  const setStep = (id: string, d: Step["do"] | "") => {
    const rest = s.arrive_steps.filter((x) => x.device_id !== id);
    save({ arrive_steps: d ? [...rest, { device_id: id, do: d }] : rest });
  };
  const app = androidApp();
  return (
    <details className="panel" open={open}>
      <summary className="panel-title">Clima e chegada {msg && <span className="muted small">{msg}</span>}</summary>

      <h3 className="small">Clima</h3>
      {s.place ? (
        <p className="small">Cidade: <b>{s.place.name}</b>{s.place.admin1 && `, ${s.place.admin1}`}{" "}
          <button className="ghost small" onClick={() => jarvis.clearPlace().then(() => setS({ ...s, place: null }))}>Trocar</button></p>
      ) : (
        <form className="row" onSubmit={(e) => {
          e.preventDefault();
          setFound(null);
          jarvis.places(q).then(setFound).catch((err) => flash((err as Error).message));
        }}>
          <input placeholder="Sua cidade (ex.: Fortaleza)" value={q} onChange={(e) => setQ(e.target.value)} minLength={2} maxLength={80} aria-label="Cidade" />
          <button className="small" type="submit">Procurar</button>
        </form>
      )}
      {!s.place && found && (found.length === 0 ? <p className="muted small">Não achei essa cidade.</p> : (
        <ul className="jv-devs">
          {found.map((p) => (
            <li key={`${p.lat},${p.lon}`}>
              <span>{p.name}<span className="muted small"> · {[p.admin1, p.country].filter(Boolean).join(", ")}</span></span>
              <button className="small" onClick={() => jarvis.setPlace(p).then((x) => { setS(x); setFound(null); flash("Cidade salva."); })}>Escolher</button>
            </li>
          ))}
        </ul>
      ))}
      <p className="muted small">Previsão do Open-Meteo (grátis). Só o nome da cidade e as coordenadas saem do notebook.</p>
      {check("rain_alert", "Avisar antes da chuva", "aviso no celular ~1 h antes (respeita o horário de silêncio)")}

      <h3 className="small">Chegada e saída de casa</h3>
      <p className="muted small">
        O app do celular percebe que você chegou quando consegue falar com o notebook pela rede de casa (Wi-Fi).
        {app ? " Precisa do endereço da rede de casa salvo no app (o QR do comando titan ligar-celular salva os dois)."
             : " Funciona só no app Android do TITAN."}
        {s.presence && <> Agora: <b>{s.presence === "home" ? "em casa" : "fora de casa"}</b>.</>}
      </p>
      {check("welcome", "Boas-vindas ao chegar", "“Bem-vindo de volta, senhor” + o que aconteceu enquanto estava fora")}
      {check("ask_leave", "Perguntar ao sair", "“Ficaram ligados: … Desligo tudo?” (só desliga se você tocar)")}
      <div className="row spread">
        <span className="small">Ligar ao chegar: {s.arrive_steps.length === 0 ? <span className="muted">nada cadastrado</span>
          : s.arrive_steps.map((x) => devices.find((d) => d.id === x.device_id)?.name ?? "?").join(", ")}</span>
        <button className="ghost small" onClick={() => setArrive(!arrive)}>{arrive ? "Fechar" : s.arrive_steps.length ? "Editar" : "＋ Cadastrar"}</button>
      </div>
      {arrive && (devices.length === 0 ? <p className="muted small">Cadastre aparelhos no TITAN Casa primeiro.</p> : (
        <ul className="jv-devs">
          {devices.map((d) => (
            <li key={d.id}>
              <span>{d.name}</span>
              <select value={s.arrive_steps.find((x) => x.device_id === d.id)?.do ?? ""} aria-label={`Ao chegar: ${d.name}`}
                      onChange={(e) => setStep(d.id, e.target.value as Step["do"] | "")}>
                <option value="">não mexer</option>
                <option value="on">{DO_LABEL.on}</option>
                <option value="off">{DO_LABEL.off}</option>
                {d.kind === "light" && <option value="dim">{DO_LABEL.dim}</option>}
              </select>
            </li>
          ))}
        </ul>
      ))}
    </details>
  );
}
