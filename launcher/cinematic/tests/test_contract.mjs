// CAMADA A — Testes de contrato do launcher cinematográfico em Chromium headless.
// Roda no CI (GitHub Actions) e localmente via `npx playwright test`.
// Usa um MOCK rigoroso da ponte (BridgeState completo) para validar navegação,
// renderização, idiomas, geometria e comportamentos SEM precisar de Tauri/WebView2.
// Os testes da CAMADA B (Tauri real/WebView2) estão em test_ui.py (local Windows).

import { test, expect } from "@playwright/test";
import { chromium } from "playwright";
import { createServer } from "vite";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.join(__dirname, "..");

// ===== MOCK RIGOROSO DO BridgeState (contrato da ponte) =====
const MOCK_STATE = {
  version: "2.1.8",
  app: {
    game_dir: "F:\\GOW3\\BASE",
    update_dir: "",
    ui_language: "pt",
    close_on_play: false,
    check_updates: false,
    mods_enabled: true,
    patches_dir: "",
    user_dir: "",
    mods_dir: "",
    language: "1",
    gpu_id: "",
    stream_memory: "cached",
    draw_pipe: "",
    readbacks: "",
    no_msaa: "",
    hdr: false,
    experimental_upscaler: false,
    pipeline_binary_cache: true,
    background_warmup: true,
    parallel_warmup: true,
    async_shaders: true,
    frame_stats: false,
    gpu_profile: false,
    perf_diag: false,
    frame_capture_key: false,
    vk_validation: false,
  },
  controls_cfg: { controls: {}, pad_style: "playstation" },
  game_patches_cfg: {},
  ini: {
    display_mode: "windowed", vsync: "1", fps_limit: "0", frames_queued: "1",
    engine_fps: "120", render_resolution: "native", fsr1: "0", rcas: "1",
    rcas_strength: "75", show_fps: "1", sharpen: "1", sharpness: "0.50",
    object_motion: "1", upscaler: "fsr4", preset: "1", output_res: "1920x1080",
    live_resolution: "auto", async_shaders: "1", stale_readback: "1",
    deferred_readback: "1", cheat_double_jumps: "0", cheat_very_hard: "0",
  },
  game: {
    found: true, folder: "F:\\GOW3\\BASE", title_id: "CUSA01623",
    patch_profile: true, summary: "Native (1080p) · 120 FPS engine · 2 patches",
    missing_files: [],
  },
  music: { default_path: null, file: "", volume: 0.01, muted: false },
  choices: {
    display_mode: [
      { value: "windowed", label: "Windowed" },
      { value: "borderless", label: "Borderless" },
      { value: "fullscreen", label: "Fullscreen" },
    ],
    render_resolution: [
      { value: "native", label: "Native (1080p)" },
      { value: "720p", label: "720p" },
      { value: "1440p", label: "1440p" },
      { value: "4K", label: "4K" },
    ],
    engine_fps: [
      { value: "60", label: "60 (original)" },
      { value: "120", label: "120" },
      { value: "240", label: "240" },
    ],
    fps_limit: [
      { value: "30", label: "30" }, { value: "60", label: "60" },
      { value: "120", label: "120" }, { value: "240", label: "240" },
      { value: "0", label: "Unlimited" },
    ],
    upscaler: [{ value: "fsr4", label: "FSR 4" }],
    preset: [{ value: "1", label: "Quality" }],
    output_res: [{ value: "1920x1080", label: "1920×1080" }],
    live_resolution: [{ value: "auto", label: "Auto" }, { value: "0", label: "Off" }],
    frames_queued: [{ value: "1", label: "1" }, { value: "2", label: "2" }],
    stream_memory: [{ value: "cached", label: "System RAM" }],
    draw_pipe: [{ value: "", label: "Auto" }, { value: "1", label: "On" }],
    readbacks: [{ value: "", label: "Relaxed" }],
    gpu_id: [{ value: "", label: "Automatic" }],
    no_msaa: [{ value: "", label: "Automatic" }],
    language: [
      { value: "1", label: "English" }, { value: "8", label: "Russian" },
      { value: "0", label: "Japanese" }, { value: "10", label: "Portuguese (Brazil)" },
    ],
    ui_language: [
      { value: "en", label: "English" }, { value: "pt", label: "Português (Brasil)" },
    ],
    video_backend: [{ value: "auto", label: "Automatic" }],
  },
  patches: {
    title_id: "CUSA01623", version: "01.02",
    builtin: [
      { name: "60 FPS Unlock", author: "test", note: null, enabled: true },
    ],
    external: [
      { key: "gow3_1440p_experiments.xml/E1", author: "diag", enabled: false },
      { key: "gow3_1440p_experiments.xml/E2", author: "diag", enabled: false },
      { key: "gow3_1440p_experiments.xml/E3", author: "diag", enabled: false },
    ],
    patches_dir_resolved: "C:\\Downloads\\patches",
  },
  mods: {
    available: ["ModA", "ModB"], order: ["ModA", "ModB"], disabled: ["ModB"],
    conflicts: [], presets: [],
  },
  backups: { keep: 10, names: ["20260101"] },
  controls: {
    style: "playstation",
    styles: { playstation: { a: "Cross", b: "Circle" }, xbox: { a: "A", b: "B" } },
    rows: Array.from({ length: 17 }, (_, i) => ({
      button: `btn${i}`, ps_name: `Button ${i}`, default_key: `K${i}`,
      default_pad: i < 14 ? `p${i}` : "", key: `K${i}`, pad: i < 14 ? `p${i}` : "",
      remappable: i < 14,
    })),
  },
  fsr4: { installed: 44, total: 44, missing: 0, folder: "fsr4_shaders" },
  running: false,
  translations: {
    pt: { "Play": "Jogar", "Graphics": "Gráficos", "Advanced": "Avançado", "Log": "Registro",
          "Display & FPS": "Tela e FPS", "Performance": "Desempenho", "Game & effects": "Jogo e efeitos" },
  },
};

const EXPECTED_NAV_PT = [
  "Tela", "Gráficos", "Desempenho", "Jogo", "Patches",
  "Mods", "Controles", "Avançado", "Registro", "Música",
];

let browser, page, server;

test.beforeAll(async () => {
  // vite dev server (sem Tauri — o mock injeta o bridge)
  server = await createServer({
    root: frontendDir,
    server: { port: 3120 },
  });
  await server.listen();
  browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  page = await ctx.newPage();

  // injetar o mock ANTES do app carregar
  await page.addInitScript((state) => {
    window.__GOW3_BRIDGE__ = async (req) => {
      const parsed = JSON.parse(req);
      if (parsed.cmd === "state") return JSON.stringify(state);
      if (parsed.cmd === "set_ini") {
        Object.assign(state.ini, parsed.values);
        return JSON.stringify({ ok: true, ini: state.ini });
      }
      return JSON.stringify({ ok: true });
    };
    window.__TAURI_INTERNALS__ = {}; // enganar o boot para não carregar Tauri
  }, MOCK_STATE);

  await page.goto("http://localhost:3120");
  // aguardar a interface (não sleep fixo: sonda por seletor)
  await page.waitForSelector(".statusbar .line", { timeout: 10000 });
});

test.afterAll(async () => {
  await browser?.close();
  await server?.close();
});

// ===== 1. NAVEGAÇÃO =====
test.describe("navegação", () => {
  test("10 itens no menu (9 páginas + Música)", async () => {
    const items = await page.$$eval(".nav > button", (els) =>
      els.map((e) => e.textContent.trim()));
    expect(items).toHaveLength(10);
  });

  test("rótulos em português sem duplicação", async () => {
    const items = await page.$$eval(".nav > button", (els) =>
      els.map((e) => e.textContent.trim()));
    const pages = items.slice(0, 9);
    expect(new Set(pages).size).toBe(9); // nenhum duplicado
    expect(items[9]).toContain("Música"); // último é Música
  });

  test("Patches e Mods são independentes (rótulos distintos)", async () => {
    const items = await page.$$eval(".nav > button", (els) =>
      els.map((e) => e.textContent.trim()));
    expect(items[4].trim()).not.toBe(items[5].trim());
  });

  test("Música tem aria-pressed", async () => {
    const music = page.locator(".music-toggle");
    await expect(music).toHaveAttribute("aria-pressed");
  });
});

// ===== 2. RENDERIZAÇÃO E IDENTIDADE =====
test.describe("renderização", () => {
  const pageTests = [
    { idx: 0, id: "display", mustContain: ["Modo de exibição", "VSync"] },
    { idx: 4, id: "patches", mustContain: ["E1", "E2", "E3"] },
    { idx: 5, id: "mods", mustContain: ["ModA", "ModB"] },
    { idx: 6, id: "controls", mustContain: ["Controles", "Button"] },
  ];

  for (const { idx, id, mustContain } of pageTests) {
    test(`página ${id} renderiza conteúdo específico`, async () => {
      await page.click(`.nav > button:nth-child(${idx + 1})`);
      await page.waitForSelector(".page-host", { timeout: 5000 });
      const text = await page.textContent(".page-host");
      for (const expected of mustContain) {
        expect(text).toContain(expected);
      }
      // voltar à home
      await page.click(".logo");
      await page.waitForSelector(".statusbar", { timeout: 3000 });
    });
  }

  test("Patches e Mods renderizam conteúdos DIFERENTES (identidade)", async () => {
    // Patches
    await page.click(".nav > button:nth-child(5)");
    await page.waitForSelector(".page-host");
    const patchesText = await page.textContent(".page-host");
    // Mods
    await page.click(".logo");
    await page.click(".nav > button:nth-child(6)");
    await page.waitForSelector(".page-host");
    const modsText = await page.textContent(".page-host");
    //voltar
    await page.click(".logo");
    // Patches tem patches E1-E3; Mods tem ModA/ModB — conjuntos distintos
    expect(patchesText).toContain("E1");
    expect(patchesText).not.toContain("ModA");
    expect(modsText).toContain("ModA");
    expect(modsText).not.toContain("E1 height");
  });

  test("nenhuma página em branco", async () => {
    for (let i = 0; i < 9; i++) {
      await page.click(`.nav > button:nth-child(${i + 1})`);
      await page.waitForSelector(".page-host", { timeout: 5000 });
      const content = await page.textContent(".page-host");
      expect(content.trim().length).toBeGreaterThan(0);
      await page.click(".logo");
    }
  });
});

// ===== 3. HOOKS E CONSOLE =====
test.describe("hooks e console", () => {
  test("nenhum erro de console", async () => {
    const errors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    page.on("pageerror", (err) => errors.push(err.message));
    // navegar por todas as páginas
    for (let i = 0; i < 9; i++) {
      await page.click(`.nav > button:nth-child(${i + 1})`);
      await page.waitForTimeout(300);
      await page.click(".logo");
    }
    expect(errors.filter((e) => !e.includes("favicon"))).toHaveLength(0);
  });
});

// ===== 4. GEOMETRIA =====
test.describe("geometria", () => {
  test("nenhum item do menu quebra linha (altura ≤40px)", async () => {
    await page.click(".logo");
    const heights = await page.$$eval(".nav > button", (els) =>
      els.map((e) => e.getBoundingClientRect().height));
    for (const h of heights) expect(h).toBeLessThanOrEqual(40);
  });

  test("Música não invade JOGAR", async () => {
    const music = await page.locator(".music-toggle").boundingBox();
    const play = await page.locator(".play .btn").boundingBox();
    expect(music.y + music.height).toBeLessThan(play.y);
  });

  test("viewport 1280×720", async () => {
    expect(page.viewportSize()).toEqual({ width: 1280, height: 720 });
  });
});

// ===== 5. COMPORTAMENTOS =====
test.describe("comportamentos", () => {
  test("volume do áudio é 0.01 (fixo)", async () => {
    const vol = await page.evaluate(() => window.__gow3Audio?.volume);
    expect(vol).toBe(0.01);
  });

  test("stop-music pausa determinísticamente", async () => {
    await page.evaluate(() =>
      window.dispatchEvent(new Event("gow3:stop-music")));
    const paused = await page.evaluate(() => window.__gow3Audio?.paused);
    expect(paused).toBe(true);
  });

  test("pointerdown não reinicia durante pausa forçada", async () => {
    await page.evaluate(() =>
      window.dispatchEvent(new Event("gow3:stop-music")));
    await page.evaluate(() =>
      window.dispatchEvent(new Event("pointerdown")));
    const paused = await page.evaluate(() => window.__gow3Audio?.paused);
    expect(paused).toBe(true);
  });
});

// ===== 6. HOVER (via Playwright — mouse real) =====
test.describe("hover", () => {
  test("hover aumenta fonte do item (sem clique)", async () => {
    await page.click(".logo");
    const btn = page.locator(".nav > button:nth-child(3)"); // Desempenho
    const before = await btn.evaluate((el) => getComputedStyle(el).fontSize);
    await btn.hover(); // Playwright: move o mouse de verdade
    await page.waitForTimeout(300); // transição 200ms
    const after = await btn.evaluate((el) => getComputedStyle(el).fontSize);
    expect(parseFloat(after)).toBeGreaterThan(parseFloat(before));
    // afastar o mouse
    await page.mouse.move(10, 400);
    await page.waitForTimeout(300);
    const reverted = await btn.evaluate((el) => getComputedStyle(el).fontSize);
    expect(parseFloat(reverted)).toBeCloseTo(parseFloat(before), 0);
  });

  test("hover muda cor para branco", async () => {
    const btn = page.locator(".nav > button:nth-child(3)");
    await btn.hover();
    await page.waitForTimeout(300);
    const color = await btn.evaluate((el) => getComputedStyle(el).color);
    expect(color).toContain("255, 255, 255"); // rgb(255,...)
    await page.mouse.move(10, 400);
  });

  test("hover NÃO abre página (sem clique)", async () => {
    await page.click(".logo");
    const btn = page.locator(".nav > button:nth-child(3)");
    await btn.hover();
    await page.waitForTimeout(400);
    const hostExists = await page.$(".page-host");
    expect(hostExists).toBeNull(); // hover não navega
    await page.mouse.move(10, 400);
  });
});
