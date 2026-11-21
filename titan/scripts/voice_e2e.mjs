// Teste ponta a ponta do modo de voz num Chromium real, com microfone simulado
// a partir de um arquivo WAV. Mede latências reais do pipeline.
// Uso: PLAYWRIGHT_MODULE=... TITAN_URL=... TITAN_USER=... TITAN_PASSWORD=... \
//      node scripts/voice_e2e.mjs caminho/fala.wav [pasta-screenshots]
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const url = process.env.TITAN_URL ?? "http://127.0.0.1:8000";
const [wav, outDir] = process.argv.slice(2);
const browser = await chromium.launch({
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
         `--use-file-for-fake-audio-capture=${wav}`, "--autoplay-policy=no-user-gesture-required"],
});
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, permissions: ["microphone"] });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
const requests = [];
page.on("request", (r) => { if (!r.url().startsWith(url)) requests.push(r.url()); });

await page.goto(url);
await page.getByLabel("Operador").fill(process.env.TITAN_USER);
await page.getByLabel("Senha").fill(process.env.TITAN_PASSWORD);
await page.getByRole("button", { name: "Entrar" }).click();
await page.getByRole("button", { name: /Voz/ }).click();
await page.getByRole("button", { name: "Iniciar conversa por voz" }).click();
const t0 = Date.now();
await page.getByText("VOCÊ (texto final)").waitFor({ timeout: 30000 });
const userText = await page.locator(".voice-transcript .msg-user").innerText();
await page.locator(".voice-transcript .msg-assistant").waitFor({ timeout: 30000 });
await page.getByText("TITAN está falando").waitFor({ timeout: 30000 }).catch(() => null);
if (outDir) await page.screenshot({ path: `${outDir}/voz-celular.png`, fullPage: true });
// o WAV se repete: a nova fala chega por cima da resposta (barge-in)
await page.waitForTimeout(9000);
await page.getByText("Medições desta sessão").click();
const metrics = await page.locator(".voice-view dl.kv").innerText();
const assistant = await page.locator(".voice-transcript .msg-assistant").innerText();
await page.getByRole("button", { name: "Encerrar" }).click();
await page.getByText("Desligado").waitFor();
console.log(JSON.stringify({ userText, assistant, metrics, seconds: (Date.now() - t0) / 1000,
  externalRequests: requests, pageErrors: errors }, null, 2));
await browser.close();
