// TITAN Central: palavra de ativação. Rodar: npm test --workspace apps/web
import { test } from "node:test";
import assert from "node:assert/strict";
import { plain, stripWake } from "../src/central/wake.ts";

test("tira o 'Ei, Titã' e diz se ele veio", () => {
  assert.deepEqual(stripWake("Ei, Titã, liga a luz do quarto"), ["liga a luz do quarto", true]);
  assert.deepEqual(stripWake("ei titan modo missão 30 minutos"), ["modo missão 30 minutos", true]);
  assert.deepEqual(stripWake("Titã! bom dia"), ["bom dia", true]);
  assert.deepEqual(stripWake("ok tita, holograma"), ["holograma", true]);
  assert.deepEqual(stripWake("Ei, Titã"), ["", true]);
  assert.deepEqual(stripWake("liga a luz"), ["liga a luz", false]);
  assert.deepEqual(stripWake("a titânia é um planeta"), ["a titânia é um planeta", false]);
});

test("acentos saem sem mudar o tamanho", () => {
  assert.equal(plain("Missão Ã"), "missao a");
  assert.equal(plain("Ação").length, 4);
});
