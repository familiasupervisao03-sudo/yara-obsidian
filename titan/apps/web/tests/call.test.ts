import { test } from "node:test";
import assert from "node:assert/strict";
import { RING_MS, clock, greeting } from "../src/call.ts";

test("Ligar TITAN: cumprimento com o nome, relógio da ligação e ~3 s chamando", () => {
  assert.equal(greeting("luiz"), "Oi, Luiz! Pode falar.");
  assert.equal(greeting("maria.souza"), "Oi, Maria! Pode falar.");
  assert.equal(greeting(""), "Oi! Pode falar.");
  assert.equal(clock(0), "00:00");
  assert.equal(clock(65_400), "01:05");
  assert.equal(RING_MS, 3000);
});
