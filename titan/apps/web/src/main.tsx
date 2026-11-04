import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { applyAppearance, loadAppearance } from "./theme/themes";
import "./theme/futurista.css";
import "./theme/classico.css";
import "./styles.css";

applyAppearance(loadAppearance()); // antes de desenhar, para não piscar com outro tema

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// PWA: só registra em contexto seguro (HTTPS ou localhost), exigência do navegador.
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => undefined);
}
