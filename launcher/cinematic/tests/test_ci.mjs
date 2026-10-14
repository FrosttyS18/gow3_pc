// CI Layer A — testes FUNDAMENTAIS de interface (não visuais; o mantenedor avalia
// aparência, hover, fontes, cores, animações manualmente).
// Valida: abertura das páginas, ausência de crashes/exceções React, rotas distintas.

import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3120";

test.beforeEach(async ({ page }) => {
  // mock do bridge ANTES do app carregar
  await page.addInitScript(() => {
    const state = {
      version: "2.1.8",
      app: { game_dir: "", ui_language: "pt", close_on_play: false, mods_enabled: true },
      controls_cfg: { controls: {}, pad_style: "playstation" },
      game_patches_cfg: {},
      ini: { display_mode: "windowed", vsync: "1", engine_fps: "120", render_resolution: "native" },
      game: { found: false, folder: "", title_id: null, patch_profile: false,
              summary: "Pasta do jogo não configurada", missing_files: [] },
      music: { default_path: null, file: "", volume: 0.01, muted: true },
      choices: {
        display_mode: [{ value: "windowed", label: "Windowed" }],
        render_resolution: [{ value: "native", label: "Native" }],
        engine_fps: [{ value: "120", label: "120" }],
        fps_limit: [{ value: "0", label: "Unlimited" }],
      },
      patches: { title_id: null, version: null, builtin: [], external: [],
                 patches_dir_resolved: null },
      mods: { available: [], order: [], disabled: [], conflicts: [], presets: [] },
      backups: { keep: 10, names: [] },
      controls: { style: "playstation", styles: { playstation: {} }, rows: [] },
      fsr4: { installed: 0, total: 44, missing: 44, folder: "fsr4_shaders" },
      running: false,
      translations: { pt: { Play: "Jogar" } },
    };
    window.__GOW3_BRIDGE__ = async (req) => {
      const p = JSON.parse(req);
      if (p.cmd === "state") return JSON.stringify(state);
      return JSON.stringify({ ok: true });
    };
    window.__TAURI_INTERNALS__ = {};
  });
  await page.goto(BASE);
  await page.waitForSelector(".statusbar, .nav", { timeout: 15000 });
});

test("app carrega sem crash", async ({ page }) => {
  const nav = await page.$$(".nav > button");
  expect(nav.length).toBeGreaterThanOrEqual(10);
});

test("zero erros de console/React ao navegar por todas as páginas", async ({ page }) => {
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  for (let i = 0; i < 9; i++) {
    await page.click(`.nav > button:nth-child(${i + 1})`);
    await page.waitForTimeout(400);
    await page.click(".logo");
    await page.waitForTimeout(200);
  }
  expect(errors.filter((e) => !e.includes("favicon"))).toHaveLength(0);
});

test("páginas abrem e renderizam conteúdo", async ({ page }) => {
  for (let i = 0; i < 9; i++) {
    await page.click(`.nav > button:nth-child(${i + 1})`);
    await page.waitForSelector(".page-host", { timeout: 5000 });
    const text = await page.textContent(".page-host");
    expect(text.trim().length).toBeGreaterThan(5);
    await page.click(".logo");
    await page.waitForTimeout(200);
  }
});

test("Patches e Mods são rotas distintas (conteúdo diferente)", async ({ page }) => {
  await page.click(".nav > button:nth-child(5)");
  await page.waitForSelector(".page-host");
  const patches = await page.textContent(".page-host");
  await page.click(".logo");
  await page.click(".nav > button:nth-child(6)");
  await page.waitForSelector(".page-host");
  const mods = await page.textContent(".page-host");
  await page.click(".logo");
  expect(patches).not.toBe(mods);
});

test("Música é uma ação (aria-pressed), não rota", async ({ page }) => {
  const music = page.locator(".music-toggle");
  await expect(music).toHaveAttribute("aria-pressed");
  const navCount = await page.$$eval(".nav > button", (els) => els.length);
  expect(navCount).toBe(10);
});
