// Teste de fumaça da interface (desktop e celular) com navegador headless.
// Uso: [PLAYWRIGHT_MODULE=...] TITAN_URL=... TITAN_USER=... TITAN_PASSWORD=... node scripts/ui_smoke.mjs [pasta-screenshots]
// Com TITAN_EXPECT_REPLY=1 exige resposta do modelo (servidor de teste com provedor mock).
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");

const url = process.env.TITAN_URL ?? "http://127.0.0.1:8000";
const user = process.env.TITAN_USER;
const password = process.env.TITAN_PASSWORD;
const expectReply = process.env.TITAN_EXPECT_REPLY === "1";
const outDir = process.argv[2];
if (!user || !password) throw new Error("Defina TITAN_USER e TITAN_PASSWORD");

const browser = await chromium.launch();
const failures = [];
const check = (cond, msg) => { if (!cond) failures.push(msg); else console.log("ok  -", msg); };

for (const [name, viewport] of [["desktop", { width: 1366, height: 860 }], ["mobile", { width: 390, height: 844 }]]) {
  const page = await browser.newPage({ viewport });
  const consoleErrors = [];
  let loggedIn = false;
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (!loggedIn && m.text().includes("401")) return; // 401 de /auth/me antes do login é esperado
    consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  await page.goto(url);
  await page.getByLabel("Operador").fill(user);
  await page.getByLabel("Senha").fill(password);
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByPlaceholder("Mensagem para o TITAN…").waitFor({ timeout: 10000 });
  loggedIn = true;
  check(true, `${name}: login`);

  // conversa em streaming
  const msg = `teste ${name} ${Date.now()}`;
  await page.getByPlaceholder("Mensagem para o TITAN…").fill(msg);
  await page.getByRole("button", { name: "Enviar" }).click();
  await page.locator(".messages").getByText(msg, { exact: true }).first().waitFor();
  if (expectReply) {
    await page.locator(".messages .msg-assistant").getByText(`[mock] ${msg}`).waitFor({ timeout: 10000 });
    check(true, `${name}: resposta em streaming exibida`);
  } else {
    await page.getByText(/Sem resposta da IA/).waitFor({ timeout: 10000 });
    check(true, `${name}: ausência de modelo informada, sem resposta inventada`);
  }
  const box = await page.getByPlaceholder("Mensagem para o TITAN…").boundingBox();
  check(box && box.y + box.height <= viewport.height, `${name}: campo de mensagem visível na tela`);
  if (outDir) await page.screenshot({ path: `${outDir}/titan-${name}-conversa.png` });

  await page.reload();
  await page.locator(".messages").getByText(msg, { exact: true }).first().waitFor({ timeout: 10000 });
  check(true, `${name}: mensagem persiste após recarregar`);

  // tarefas: criar, executar e verificar
  await page.getByRole("button", { name: /Tarefas/ }).click();
  await page.getByRole("button", { name: "+ Nova tarefa" }).click();
  await page.getByLabel("Objetivo").fill(`Anotar ${name}`);
  await page.getByLabel("Título").fill("Guardar lembrete");
  await page.getByLabel("Texto a anotar").fill("comprar café");
  await page.getByLabel("Critério de sucesso").selectOption("contains");
  await page.getByPlaceholder("valor").fill("café");
  await page.getByRole("button", { name: "Criar tarefa" }).click();
  await page.getByRole("button", { name: "Executar" }).click();
  await page.locator(".status-COMPLETED").first().waitFor({ timeout: 10000 });
  check(true, `${name}: tarefa criada, executada e verificada (Concluída)`);
  if (outDir) await page.screenshot({ path: `${outDir}/titan-${name}-tarefa.png`, fullPage: true });

  await page.getByRole("button", { name: /Sistema/ }).click();
  await page.getByText(/APIs pagas/).waitFor();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check(!overflow, `${name}: sem rolagem horizontal`);
  const html = await page.content();
  check(!/TITAN_AUTH_SECRET|password_hash|token_hash|sk-ant-/.test(html), `${name}: nenhum segredo no DOM`);
  check(consoleErrors.length === 0, `${name}: sem erros no console (${consoleErrors.join(" | ")})`);
  if (outDir) await page.screenshot({ path: `${outDir}/titan-${name}-sistema.png` });
  await page.close();
}
await browser.close();
if (failures.length) { console.error("FALHAS:\n" + failures.join("\n")); process.exit(1); }
console.log("UI smoke: todos os checks passaram");
