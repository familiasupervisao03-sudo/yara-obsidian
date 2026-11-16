import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { CrashScreen, ErrorBoundary } from "./components/ErrorBoundary";
import { applyAppearance, loadAppearance } from "./theme/themes";
import "./theme/futurista.css";
import "./theme/classico.css";
import "./styles.css";

applyAppearance(loadAppearance()); // antes de desenhar, para não piscar com outro tema

const root = createRoot(document.getElementById("root")!);
root.render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);

// Erro fora das telas (ex.: navegador antigo sem algum recurso): mostra em vez de ficar preto.
window.addEventListener("error", (ev) => {
  const el = document.getElementById("root");
  if (el && el.childElementCount === 0) {
    root.render(<CrashScreen message={String(ev.message || ev.error || "erro desconhecido")}
                             stack={ev.error?.stack ?? `${ev.filename}:${ev.lineno}`} />);
  }
});

// PWA: só registra em contexto seguro (HTTPS ou localhost), exigência do navegador.
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => undefined);
}
