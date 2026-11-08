// Tela 3 · conexão caiu com o TITAN aberto: só uma faixa em cima ("reconectando…").
// Tenta sozinha a cada 10 s; as telas continuam por baixo e o que foi escrito fica guardado
// e é enviado sozinho quando o notebook voltar.
import { useEffect, useState } from "react";

const EVERY = 10;

export function OfflineScreen({ onRetry }: { onRetry: () => void }) {
  const [left, setLeft] = useState(EVERY);
  useEffect(() => {
    const id = window.setInterval(() => {
      setLeft((v) => {
        if (v <= 1) { onRetry(); return EVERY; }
        return v - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [onRetry]);
  return (
    <div className="offline-strip" role="status" aria-live="polite">
      <i className="offline-dot" aria-hidden="true" />
      <span className="offline-text">
        <strong>RECONECTANDO AO NOTEBOOK…</strong>
        <span className="offline-count">mensagens ficam guardadas · nova tentativa em {left} s</span>
      </span>
      <button className="ghost small" onClick={() => { setLeft(EVERY); onRetry(); }}>Agora</button>
    </div>
  );
}
