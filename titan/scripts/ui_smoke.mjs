// Teste de fumaça da interface com navegador headless (Playwright).
// Uso: [PLAYWRIGHT_MODULE=/caminho/playwright/index.mjs] TITAN_URL=http://127.0.0.1:8000 TITAN_USER=... TITAN_PASSWORD=... node scripts/ui_smoke.mjs [pasta-screenshots]
// O Playwright não é dependência do projeto; aponte PLAYWRIGHT_MODULE para uma instalação existente.
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");

const url = process.env.TITAN_URL ?? "http://127.0.0.1:8000";
const user = process.env.TITAN_USER;
const password = process.env.TITAN_PASSWORD;
const outDir = process.argv[2];
if (!user || !password) throw new Error("Defina TITAN_USER e TITAN_PASSWORD");

const browser = await chromium.launch(
  process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
);
const failures = [];
const check = (cond, msg) => { if (!cond) failures.push(msg); else console.log("ok  -", msg); };

for (const [name, viewport] of [["desktop", { width: 1366, height: 860 }], ["mobile", { width: 390, height: 844 }]]) {
  const page = await browser.newPage({ viewport });
  const consoleErrors = [];
  let loggedIn = false;
  // Antes do login, o 401 de /api/v1/auth/me é o comportamento esperado.
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (!loggedIn && m.text().includes("401")) return;
    consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  await page.goto(url);
  await page.getByLabel("Operador").fill(user);
  await page.getByLabel("Senha").fill(password);
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByText("APIs PAGAS: BLOQUEADAS").waitFor({ timeout: 10000 });
  loggedIn = true;
  check(true, `${name}: login e indicador de APIs pagas bloqueadas`);
  await page.getByText("DESATIVADO").first().waitFor();
  check(await page.getByText("Execução de código desativada").isVisible(), `${name}: sandbox reportado como desativado`);

  const msg = `teste ${name} ${Date.now()}`;
  await page.getByPlaceholder("Digite uma mensagem…").fill(msg);
  await page.getByRole("button", { name: "Enviar" }).click();
  await page.locator(".messages").getByText(msg).waitFor();
  check(await page.getByText("Mensagem salva. Sem resposta da IA").isVisible(), `${name}: ausência de modelo informada, sem resposta inventada`);

  await page.reload();
  await page.locator(".messages").getByText(msg).waitFor({ timeout: 10000 });
  check(true, `${name}: mensagem persiste após recarregar`);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check(!overflow, `${name}: sem rolagem horizontal`);
  const html = await page.content();
  check(!/TITAN_AUTH_SECRET|password_hash|token_hash/.test(html), `${name}: nenhum segredo no DOM`);
  check(consoleErrors.length === 0, `${name}: sem erros no console (${consoleErrors.join(" | ")})`);
  if (outDir) await page.screenshot({ path: `${outDir}/titan-${name}.png`, fullPage: true });
  await page.close();
}
await browser.close();
if (failures.length) { console.error("FALHAS:\n" + failures.join("\n")); process.exit(1); }
console.log("UI smoke: todos os checks passaram");
