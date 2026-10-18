import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em desenvolvimento, o Vite encaminha a API para o backend local.
// Em produção, o próprio FastAPI serve os arquivos de dist/ (sem Node em execução).
const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": backend, "/health": backend, "/ready": backend },
  },
  build: {
    outDir: "dist",
    target: "es2019",
    sourcemap: false,
    // Sem chunks inline: a CSP do backend bloqueia scripts inline.
    assetsInlineLimit: 0,
  },
});
