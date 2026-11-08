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

import { parseReminder, whenText } from "../src/central/reminder.ts";

test("lembretes falados viram título + hora", () => {
  const now = new Date(2026, 10, 7, 10, 0, 0); // 7/nov 10:00
  const hm = (d: Date) => `${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
  const cases: [string, string, string][] = [
    ["Cria um lembrete pra me avisar de tirar o bolo às 2:30 da tarde", "Tirar o bolo", "7 14:30"],
    ["me lembra de ligar pra minha mãe às 14h30", "Ligar minha mãe", "7 14:30"],
    ["Ei Titã, me avisa às duas e meia da tarde de buscar o pão", "Buscar o pão", "7 14:30"],
    ["lembrete amanhã às 7 horas levar o documento na escola", "Levar o documento na escola", "8 7:00"],
    ["me lembra daqui a 10 minutos de desligar o forno", "Desligar o forno", "7 10:10"],
    ["me avisa em meia hora de tomar remédio", "Tomar remédio", "7 10:30"],
    ["cria um alarme pra meio dia almoçar", "Almoçar", "7 12:00"],
    ["me lembra às 8 da noite de estudar", "Estudar", "7 20:00"],
    ["me lembra às 9 de comprar o microfone", "Comprar o microfone", "7 21:00"], // 9h já passou → 21h
    ["me lembra às 7 da manhã de acordar cedo", "Acordar cedo", "8 7:00"],          // 7h já passou → amanhã
    ["Ei Titã, me lembra daqui a 2 minutos de testar o TITAN", "Testar o TITAN", "7 10:02"],
  ];
  for (const [text, title, when] of cases) {
    const r = parseReminder(text, now);
    assert.ok(r, text);
    assert.equal(hm(r.due), when, text);
    assert.equal(plainCmp(r.title), plainCmp(title), text);
  }
  assert.equal(parseReminder("liga o ventilador", now), null);
  assert.equal(parseReminder("me lembra de comprar pão", now), null); // sem hora: vai para a IA
  assert.equal(whenText(new Date(2026, 10, 8, 7, 0), now), "amanhã às 07:00");
});

function plainCmp(s: string) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

import { CASA_WAKE } from "../src/central/wake.ts";

test("Casa atende por Ei, Titã e Ei, Casa; Central só por Ei, Titã", () => {
  assert.deepEqual(stripWake("Ei, Casa, liga a luz", CASA_WAKE), ["liga a luz", true]);
  assert.deepEqual(stripWake("Ei, Titã, liga a luz", CASA_WAKE), ["liga a luz", true]);
  assert.deepEqual(stripWake("Ei, Casa, liga a luz"), ["Ei, Casa, liga a luz", false]);
  assert.deepEqual(stripWake("casamento amanhã", CASA_WAKE), ["casamento amanhã", false]);
});

import { brt } from "../src/central/brt.ts";

test("relógio no horário de Brasília (UTC−3), qualquer que seja o fuso do aparelho", () => {
  const t = brt(new Date(Date.UTC(2026, 10, 8, 17, 5, 9)));   // 17:05 UTC
  assert.deepEqual([t.h, t.m, t.s, t.day, t.month, t.year, t.dow], [14, 5, 9, 8, 10, 2026, 0]); // 14:05, domingo
  assert.equal(brt(new Date(Date.UTC(2026, 10, 9, 1, 30))).h, 22);  // virada do dia em UTC: ainda dia 8 às 22h
});
