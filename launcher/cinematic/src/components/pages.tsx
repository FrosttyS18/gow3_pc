import { useEffect, useState } from "react"
import { BridgeState, bridge } from "../bridge"
import { useI18n } from "../i18n"
import { ActionButton, Dropdown, Field, PathField, Section, Slider, Toggle, pickFolderAndSet, useSaver } from "./inputs"

type P = { state: BridgeState; refresh: () => void }

/* ---------- Tela (build_display) ---------- */
export function DisplayPage({ state, refresh }: P) {
  const { t } = useI18n()
  const { run, error } = useSaver(refresh)
  const ini = state.ini
  const app = state.app
  const setIni = (k: string, v: string | boolean) => run(() => bridge.setIni({ [k]: v }))
  const setApp = (k: string, v: boolean) => run(() => bridge.setApp({ [k]: v }))
  return (
    <div className="settings">
      <h1>{t("Play") === "Jogar" ? "Tela" : "Display"}</h1>
      {error && <p className="op-error">{error}</p>}
      <Section title={t("Window")}>
        <Field label={t("Play") === "Jogar" ? "Modo de exibição" : "Display mode"} hint="Sem bordas cobre a tela sem trocar o modo do monitor.">
          <Dropdown value={ini.display_mode ?? "windowed"} choices={state.choices.display_mode}
            onChange={(v) => setIni("display_mode", v)} label={t("Play") === "Jogar" ? "Modo de exibição" : "Display mode"} />
        </Field>
        <Field label="VSync" hint="Desligado permite tearing para a menor latência.">
          <Toggle value={ini.vsync === "1"} onChange={(v) => setIni("vsync", v)} label="VSync" />
        </Field>
        <Field label={t("Play") === "Jogar" ? "Permitir saída HDR" : "Allow HDR output"} hint="Com HDR ativo no Windows e monitor compatível.">
          <Toggle value={!!app.hdr} onChange={(v) => setApp("hdr", v)} label={t("Play") === "Jogar" ? "Permitir saída HDR" : "Allow HDR output"} />
        </Field>
      </Section>
      <Section title={t("Play") === "Jogar" ? "Sobreposição" : "Overlay"}>
        <Field label={t("Play") === "Jogar" ? "Mostrar sobreposição de desempenho" : "Show performance overlay"}
               hint="Itens, tamanho e canto: menu do jogo (Insert / R3+L2) › Sobreposição.">
          <Toggle value={ini.show_fps === "1"} onChange={(v) => setIni("show_fps", v)}
            label={t("Play") === "Jogar" ? "Mostrar sobreposição de desempenho" : "Show performance overlay"} />
        </Field>
      </Section>
    </div>
  )
}

/* ---------- Gráficos experimentais (build_graphics) — upscaling temporal estacionado pela v2.2.0 do motor ---------- */
export function GraphicsPage({ state, refresh }: P) {
  const { t } = useI18n()
  const pt = t("Play") === "Jogar"
  const { run, error } = useSaver(refresh)
  const ini = state.ini
  return (
    <div className="settings">
      <h1>{pt ? "Gráficos" : "Graphics"}</h1>
      {error && <p className="op-error">{error}</p>}
      <Section title={pt ? "Filtragem anisotrópica" : "Anisotropic filtering"}>
        <Field label={pt ? "Filtragem anisotrópica" : "Anisotropic filtering"}
               hint={pt
                 ? "Nitidez das texturas vistas em ângulo (piso, paredes). 16× é a mais nítida; o padrão do jogo é desligado."
                 : "Sharpness of textures viewed at an angle (floors, walls). 16x is the sharpest; the game default is off."}>
          <Dropdown value={ini.anisotropy ?? "0"} choices={state.choices.anisotropy ?? []}
            onChange={(v) => run(() => bridge.setIni({ anisotropy: v }))}
            label={pt ? "Filtragem anisotrópica" : "Anisotropic filtering"} />
        </Field>
      </Section>
      <Section title={pt ? "Upscaling (estacionado)" : "Upscaling (parked)"}>
        <p className="page-intro">
          {pt
            ? "O upscaling temporal (FSR 3.1, TAA) foi estacionado pelo motor na versão 2.2.0: ainda não está calibrado para este jogo e permanece desligado em toda partida. Não há o que configurar aqui enquanto o recurso não voltar."
            : "Temporal upscaling (FSR 3.1, TAA) is parked by the engine as of version 2.2.0: it is not calibrated for this game yet and stays off in every session. There is nothing to configure here until the feature returns."}
        </p>
        <p className="field-hint">
          {pt
            ? `A preferência salva antes da 2.2.0 (upscaler ${state.ini.upscaler ?? "—"}) é preservada no gow3.ini e voltará a valer automaticamente se o motor reativar o recurso. Nada é regravado pelo launcher.`
            : `The preference saved before 2.2.0 (upscaler ${state.ini.upscaler ?? "—"}) is preserved in gow3.ini and takes effect again automatically if the engine re-enables the feature. Nothing is rewritten by the launcher.`}
        </p>
      </Section>
    </div>
  )
}

/* ---------- Desempenho (build_performance) ---------- */
export function PerformancePage({ state, refresh }: P) {
  const { t } = useI18n()
  const { run, error } = useSaver(refresh)
  const ini = state.ini
  const app = state.app
  const setIni = (k: string, v: string | boolean) => run(() => bridge.setIni({ [k]: v }))
  const setApp = (k: string, v: string | boolean) => run(() => bridge.setApp({ [k]: v }))
  return (
    <div className="settings">
      <h1>{t("Play") === "Jogar" ? "Desempenho" : "Performance"}</h1>
      {error && <p className="op-error">{error}</p>}
      <Section title={t("Play") === "Jogar" ? "Taxa de quadros" : "Frame rate"}>
        <Field label="Limite de quadros" hint="A taxa do motor (abaixo) é o teto.">
          <Dropdown value={ini.fps_limit ?? "0"} choices={state.choices.fps_limit}
            onChange={(v) => setIni("fps_limit", v)} label="Limite de quadros" />
        </Field>
        <Field label="Quadros enfileirados" hint="1 é a menor latência; mais pode elevar o FPS quando a placa limita.">
          <Dropdown value={ini.frames_queued ?? "1"} choices={state.choices.frames_queued}
            onChange={(v) => setIni("frames_queued", v)} label="Quadros enfileirados" />
        </Field>
        <Field label="Taxa de quadros do motor" restart hint="A taxa máxima do próprio jogo (um patch do jogo).">
          <Dropdown value={ini.engine_fps ?? "120"} choices={state.choices.engine_fps}
            onChange={(v) => setIni("engine_fps", v)} label="Taxa de quadros do motor" />
        </Field>
        <Field label="Resolução de renderização" restart
               hint="O tamanho em que o jogo desenha; maior é mais nítido e mais pesado.">
          <Dropdown value={ini.render_resolution ?? "native"} choices={state.choices.render_resolution}
            onChange={(v) => setIni("render_resolution", v)} label="Resolução de renderização" />
        </Field>
      </Section>
      <Section title={t("Play") === "Jogar" ? "Shaders" : "Shaders"}>
        <Field label="Cache de pipelines (teste A/B)" restart
               hint="Reaproveita pipelines Vulkan salvos. Desligue para comparar FPS com a compilação normal.">
          <Toggle value={app.pipeline_binary_cache !== false}
            onChange={(v) => setApp("pipeline_binary_cache", v)} label="Cache de pipelines" />
        </Field>
        <Field label="Carregar cache em segundo plano"
               hint="O jogo abre na hora e os shaders carregam durante o jogo.">
          <Toggle value={app.background_warmup !== false}
            onChange={(v) => setApp("background_warmup", v)} label="Cache em segundo plano" />
        </Field>
        <Field label="Compilar shaders novos em segundo plano"
               hint="Menos travadas em áreas novas; desligue se algo sumir da cena.">
          <Toggle value={ini.async_shaders === "1"} onChange={(v) => setIni("async_shaders", v)}
            label="Compilar shaders em segundo plano" />
        </Field>
        <Field label="Carregamento rápido do cache (paralelo)" restart
               hint="Só na tela de carregamento: monta os pipelines em várias threads da CPU.">
          <Toggle value={app.parallel_warmup !== false}
            onChange={(v) => setApp("parallel_warmup", v)} label="Carregamento paralelo" />
        </Field>
      </Section>
      <Section title={t("Play") === "Jogar" ? "Shaders" : "Shaders"}>
        <Field label="Placa de vídeo" restart
               hint="A GPU em que o jogo roda. Escolha a dedicada se o jogo usar a integrada.">
          <Dropdown value={String(app.gpu_id ?? "")} choices={state.choices.gpu_id}
            onChange={(v) => setApp("gpu_id", v)} label="Placa de vídeo" />
        </Field>
        <Field label="Memória do buffer de streaming" restart
               hint="RAM do sistema pode melhorar o FPS em notebooks NVIDIA. Vale no próximo início.">
          <Dropdown value={String(app.stream_memory ?? "cached")} choices={state.choices.stream_memory}
            onChange={(v) => setApp("stream_memory", v)} label="Memória de streaming" />
        </Field>
        <Field label="Multisampling do jogo" restart
               hint="Automático decide conforme a placa; padrão do jogo nos drivers AMD/Intel no Windows.">
          <Dropdown value={String(app.no_msaa ?? "")} choices={state.choices.no_msaa}
            onChange={(v) => setApp("no_msaa", v)} label="Multisampling" />
        </Field>
        <Field label="Pipeline de GPU em dois estágios"
               hint="20–30% mais rápido; desligue se o jogo ficar instável.">
          <Dropdown value={String(app.draw_pipe ?? "")} choices={state.choices.draw_pipe}
            onChange={(v) => setApp("draw_pipe", v)} label="Pipeline em dois estágios" />
        </Field>
        <Field label="Leituras da GPU" hint="Com que exatidão os dados escritos pela GPU voltam ao jogo.">
          <Dropdown value={String(app.readbacks ?? "")} choices={state.choices.readbacks}
            onChange={(v) => setApp("readbacks", v)} label="Leituras da GPU" />
        </Field>
        <Field label="Jogo lê a GPU sem esperar (grande ganho de FPS)" restart
               hint="De 40 a 66 FPS em cena pesada. Precisa das leituras adiadas; desligue se a luz ou objetos ficarem errados.">
          <Toggle value={ini.stale_readback === "1"} onChange={(v) => setIni("stale_readback", v)}
            label="Leitura sem esperar" />
        </Field>
        <Field label="Leituras adiadas da GPU" restart
               hint="Menos esperas pela GPU. Desligue se texturas ou sombras ficarem erradas.">
          <Toggle value={ini.deferred_readback === "1"} onChange={(v) => setIni("deferred_readback", v)}
            label="Leituras adiadas" />
        </Field>
      </Section>
    </div>
  )
}

/* ---------- Jogo (build_game) ---------- */
export function GamePage({ state, refresh }: P) {
  const { t } = useI18n()
  const { run, error } = useSaver(refresh)
  const [backup, setBackup] = useState("")
  const [backupMsg, setBackupMsg] = useState("")
  const [busy, setBusy] = useState(false)
  const ini = state.ini
  const app = state.app
  const setIni = (k: string, v: boolean) => run(() => bridge.setIni({ [k]: v }))
  const restore = () => run(async () => {
    const selected = backup || state.backups.names[0] || ''
    if (!selected) return
    if (!window.confirm(`Substituir os saves atuais pelo backup ${selected}? Os saves atuais são copiados antes.`)) return
    setBusy(true)
    try {
      const r = await bridge.backupRestore(selected)
      setBackupMsg(`Saves restaurados de ${selected}.` + (r.safety ? ` Saves anteriores: ${r.safety}.` : ""))
    } finally { setBusy(false) }
  })
  return (
    <div className="settings">
      <h1>{t("Play") === "Jogar" ? "Jogo" : "Game"}</h1>
      {error && <p className="op-error">{error}</p>}
      <Section title={t("Play") === "Jogar" ? "Trapaças" : "Cheats"}>
        <Field label="Saltos duplos infinitos" hint="Repetir saltos no ar sem pousar. Também no menu de trapaças do jogo.">
          <Toggle value={ini.cheat_double_jumps === "1"} onChange={(v) => setIni("cheat_double_jumps", v)}
            label="Saltos duplos infinitos" />
        </Field>
        <Field label="Desbloquear Muito Difícil"
               hint="Escolher Muito Difícil sem terminar o jogo. Não altera a dificuldade de saves existentes.">
          <Toggle value={ini.cheat_very_hard === "1"} onChange={(v) => setIni("cheat_very_hard", v)}
            label="Desbloquear Muito Difícil" />
        </Field>
      </Section>
      <Section title={t("Play") === "Jogar" ? "Pastas" : "Folders"}>
        <Field label="Pasta do jogo" hint="Seu dump do jogo (eboot.bin, sce_module, sce_sys): qualquer região e versão.">
          <PathField value={String(app.game_dir ?? "")} onPick={() => pickFolderAndSet("game_dir", refresh)} />
        </Field>
        <Field label="Pasta da atualização (opcional)"
               hint="Somente se a atualização foi dumpada separada; é sobreposta à pasta do jogo sem alterar nenhuma.">
          <PathField value={String(app.update_dir ?? "")} onPick={() => pickFolderAndSet("update_dir", refresh)} />
        </Field>
        <Field label="Pasta de saves" hint="Vazio: pasta user do port (os caches de shader também ficam lá).">
          <PathField value={String(app.user_dir ?? "")} onPick={() => pickFolderAndSet("user_dir", refresh)} />
        </Field>
      </Section>
      <Section title={t("Play") === "Jogar" ? "Mods" : "Mods"}>
        <Field label={`Backups de saves (últimos ${state.backups.keep})`}
               hint="Feitos antes de cada início, do mais novo ao mais velho. Restaurar copia os saves atuais primeiro.">
          <span className="inline-row">
            <Dropdown value={backup || state.backups.names[0] || ""} choices={
              state.backups.names.map((n) => ({ value: n, label: n }))}
              onChange={setBackup} label="Backup" />
            <ActionButton onClick={restore} disabled={busy || !(backup || state.backups.names[0])}>{t("Play") === "Jogar" ? "Restaurar" : "Restore"}</ActionButton>
          </span>
        </Field>
        {backupMsg && <p className="op-ok">{backupMsg}</p>}
      </Section>
      <Section title={t("Play") === "Jogar" ? "Idioma" : "Language"}>
        <Field label="Idioma do jogo">
          <Dropdown value={String(app.language ?? "1")} choices={state.choices.language}
            onChange={(v) => run(() => bridge.setApp({ language: v }))} label="Idioma do jogo" />
        </Field>
      </Section>
    </div>
  )
}

/* ---------- Patches (build_patches) ---------- */
export function PatchesPage({ state, refresh }: P) {
  const { t } = useI18n()
  const { run, error } = useSaver(refresh)
  const p = state.patches
  const toggleBuiltin = (name: string, on: boolean) => {
    const names = p.builtin.filter((b) => on ? b.enabled || b.name === name : b.enabled && b.name !== name)
      .map((b) => b.name)
    return run(() => bridge.setGamePatches(names))
  }
  const toggleExternal = (key: string, on: boolean) => {
    const enabled = p.external.filter((e) => on ? e.enabled || e.key === key : e.enabled && e.key !== key).map((e) => e.key)
    const disabled = p.external.filter((e) => !enabled.includes(e.key)).map((e) => e.key)
    return run(() => bridge.setExternalPatches(enabled, disabled))
  }
  return (
    <div className="settings">
      <h1>{t("Play") === "Jogar" ? "Patches" : "Patches"}</h1>
      {error && <p className="op-error">{error}</p>}
      <p className="page-intro">Mudanças aplicadas ao código do jogo ao iniciar.</p>
      <Section title={`Patches do jogo${p.version ? ` · ${p.title_id} · versão ${p.version}` : ""}`}>
        {p.builtin.length === 0 && <p className="field-hint">Sem patches internos para este jogo (ou pasta não configurada).</p>}
        {p.builtin.map((b) => (
          <Field key={b.name} label={b.name + (b.author ? `  (${b.author})` : "")} hint={b.note ?? undefined}>
            <Toggle value={b.enabled} onChange={(v) => toggleBuiltin(b.name, v)} label={b.name} />
          </Field>
        ))}
        <p className="field-hint">Resolução e taxa de quadros seguem a página Desempenho.</p>
      </Section>
      <Section title={t("Play") === "Jogar" ? "Mods" : "Mods"}>
        <Field label="Pasta de patches"
               hint="Arquivos XML de patch shadPS4/GoldHEN para esta versão do jogo.">
          <PathField value={String(state.app.patches_dir ?? "")} onPick={() => pickFolderAndSet("patches_dir", refresh)} />
        </Field>
        {p.external.length === 0 && <p className="field-hint">Nenhum arquivo de patch para esta versão do jogo.</p>}
        {p.external.map((e) => (
          <Field key={e.key} label={e.key + (e.author ? `  —  ${e.author}` : "")}>
            <Toggle value={e.enabled} onChange={(v) => toggleExternal(e.key, v)} label={e.key} />
          </Field>
        ))}
        <ActionButton onClick={() => refresh()}>{t("Play") === "Jogar" ? "Atualizar" : "Refresh"}</ActionButton>
      </Section>
    </div>
  )
}

/* ---------- Mods (build_mods) ---------- */
export function ModsPage({ state, refresh }: P) {
  const { t } = useI18n()
  const { run, error } = useSaver(refresh)
  const m = state.mods
  const [preset, setPreset] = useState("")
  const move = (index: number, step: number) => {
    const order = [...m.order]
    const other = index + step
    if (other < 0 || other >= order.length) return
    ;[order[index], order[other]] = [order[other], order[index]]
    run(() => bridge.modsSet(order, m.disabled))
  }
  const toggle = (name: string, on: boolean) => run(() =>
    bridge.modsSet(m.order, on ? m.disabled.filter((n) => n !== name)
                               : [...new Set([...m.disabled, name])]))
  return (
    <div className="settings">
      <h1>{t("Play") === "Jogar" ? "Mods" : "Mods"}</h1>
      {error && <p className="op-error">{error}</p>}
      <p className="page-intro">Arquivos sobrepostos ao jogo ao iniciar; os arquivos do jogo nunca mudam.</p>
      <Section title={t("Play") === "Jogar" ? "Mods" : "Mods"}>
        <Field label="Carregar mods" hint="Mods de arquivos soltos, cada um em sua pasta com dvdroot_ps4.">
          <Toggle value={state.app.mods_enabled !== false}
            onChange={(v) => run(() => bridge.setApp({ mods_enabled: v }))} label="Carregar mods" />
        </Field>
        <Field label="Pasta de mods">
          <PathField value={String(state.app.mods_dir ?? "")} onPick={() => pickFolderAndSet("mods_dir", refresh)} />
        </Field>
        {m.available.length === 0 && <p className="field-hint">Nenhum mod na pasta ainda.</p>}
        {m.order.map((name, index) => (
          <div className="mod-row" key={name}>
            <span className="mod-index">{index + 1}.</span>
            <button className="mod-move" aria-label="Subir" onClick={() => move(index, -1)}>▲</button>
            <button className="mod-move" aria-label="Descer" onClick={() => move(index, 1)}>▼</button>
            <span className="mod-name">{name}</span>
            <Toggle value={!m.disabled.includes(name)} onChange={(v) => toggle(name, v)} label={name} />
          </div>
        ))}
        {m.order.length > 1 && <p className="field-hint">Mais abaixo na lista carrega depois e vence conflitos.</p>}
        {m.conflicts.length > 0 && (
          <p className="op-error">{m.conflicts.length} arquivo(s) substituído(s) por mais de um mod (o último vence):
            {" " + m.conflicts.slice(0, 4).map(([path]) => path).join(", ")}</p>
        )}
        {m.available.length > 0 && (
          <div className="inline-row presets">
            <Dropdown value={preset} choices={m.presets.map((n) => ({ value: n, label: n }))}
              onChange={setPreset} label="Preset" />
            <ActionButton onClick={() => preset && run(() => bridge.preset(preset, "load"))} disabled={!preset}>Carregar</ActionButton>
            <ActionButton onClick={() => preset && run(() => bridge.preset(preset, "save"))} disabled={!preset}>Salvar</ActionButton>
            <ActionButton danger onClick={() => preset && run(() => bridge.preset(preset, "delete"))} disabled={!preset}>Excluir</ActionButton>
            <input className="text" placeholder="nome do preset" value={preset} onChange={(e) => setPreset(e.target.value)} />
          </div>
        )}
        <ActionButton onClick={() => refresh()}>{t("Play") === "Jogar" ? "Atualizar" : "Refresh"}</ActionButton>
      </Section>
    </div>
  )
}

/* ---------- Controles (build_controls) ---------- */
export function ControlsPage({ state, refresh }: P) {
  const { t } = useI18n()
  const { run, error } = useSaver(refresh)
  const c = state.controls
  const [rows, setRows] = useState(c.rows)
  const [style, setStyle] = useState(c.style)
  useEffect(() => { setRows(c.rows); setStyle(c.style) }, [c])
  const save = (nextRows = rows, nextStyle = style) => {
    setRows(nextRows); setStyle(nextStyle)
    const key: Record<string, string> = {}
    const pad: Record<string, string> = {}
    for (const r of nextRows) { key[r.button] = r.key; if (r.remappable) pad[r.button] = r.pad }
    run(() => bridge.controlsSet(key, pad, nextStyle))
  }
  const labels = c.styles[style] ?? {}
  const reset = () => save(c.rows.map((r) => ({ ...r, key: r.default_key, pad: r.default_pad })), style)
  return (
    <div className="settings">
      <h1>{t("Play") === "Jogar" ? "Controles" : "Controls"}</h1>
      {error && <p className="op-error">{error}</p>}
      <p className="page-intro">Qual tecla ou botão do controle aperta cada botão do jogo.</p>
      <Section title={t("Play") === "Jogar" ? "Nomes dos botões" : "Button names"}>
        <span className="inline-row">
          {(["playstation", "xbox"] as const).map((s) => (
            <label key={s} className={"radio" + (style === s ? " on" : "")}>
              <input type="radio" name="pad_style" checked={style === s}
                onChange={() => save(rows, s)} /> {s === "playstation" ? "PlayStation" : "Xbox"}
            </label>
          ))}
        </span>
        <Field label={t("Play") === "Jogar" ? "Ícones de botões no jogo" : "In-game button icons"}
               hint={t("Play") === "Jogar"
                 ? "Substitui os ícones de botão de PlayStation dentro do jogo pelos do seu controle. Funciona numa cópia de dois arquivos do jogo (cerca de 70 MB) na pasta de dados do port — a pasta do jogo nunca é alterada. Aplicado ao iniciar o jogo."
                 : "Replaces the PlayStation button icons inside the game with your controller's. Works on a copy of two game files (about 70 MB) in the port's data folder — your game folder is never changed. Applied when the game starts."}>
          <Dropdown value={String(state.app.glyph_style ?? "off")} choices={state.choices.glyph_style ?? []}
            onChange={(v) => run(() => bridge.setApp({ glyph_style: v }))}
            label={t("Play") === "Jogar" ? "Ícones de botões no jogo" : "In-game button icons"} />
        </Field>
        <Field label={t("Play") === "Jogar" ? "Vibração do controle" : "Gamepad vibration"}
               hint={t("Play") === "Jogar"
                 ? "Intensidade da vibração do controle; 0% desliga."
                 : "Strength of the gamepad's vibration; 0% turns it off."}>
          <Slider value={Number(state.ini.vibration ?? "100")} min={0} max={100} step={1}
            label={t("Play") === "Jogar" ? "Vibração do controle" : "Gamepad vibration"}
            format={(v) => `${v}%`}
            onCommit={(v) => run(() => bridge.setIni({ vibration: String(v) }))} />
        </Field>
      </Section>
      <Section title={t("Play") === "Jogar" ? "Mapeamento" : "Mapping"}>
        <div className="controls-table">
          <span className="th">BOTÃO DO JOGO</span><span className="th">TECLADO</span><span className="th">CONTROLE</span>
          {rows.map((r) => (
            <div className="controls-row" key={r.button}>
              <span className="ps-name">{r.ps_name}</span>
              <input className="text key" value={r.key} aria-label={`Tecla de ${r.ps_name}`}
                onChange={(e) => save(rows.map((row) => row.button === r.button ? { ...row, key: e.target.value } : row))} />
              {r.remappable ? (
                <Dropdown width={240} value={r.pad}
                  choices={Object.entries(labels).map(([value, label]) => ({ value, label }))}
                  onChange={(v) => save(rows.map((row) => row.button === r.button ? { ...row, pad: v } : row))}
                  label={`Botão do controle para ${r.ps_name}`} />
              ) : (
                <span className="fixed">{r.button === "touchpad_left" ? "L1 + Touchpad direito"
                  : `${r.ps_name} (gatilho)`}</span>
              )}
            </div>
          ))}
        </div>
        <p className="field-hint">
          Teclas usam nomes SDL: letras, dígitos, Space, Return, Tab, Left Shift, F1 a F12… Um nome que o jogo
          não conhece mantém o padrão (o log diz qual). L2/R2 ficam nos gatilhos. Aplicado ao iniciar o jogo.
        </p>
        <ActionButton onClick={reset}>Restaurar padrões</ActionButton>
      </Section>
    </div>
  )
}

/* ---------- Avançado (build_advanced) ---------- */
export function AdvancedPage({ state, refresh }: P) {
  const { t } = useI18n()
  const { run, error } = useSaver(refresh)
  const app = state.app
  const [updateMsg, setUpdateMsg] = useState("")
  const [cacheMsg, setCacheMsg] = useState("")
  const setApp = (k: string, v: string | boolean) => run(() => bridge.setApp({ [k]: v }))
  const checkUpdate = () => run(async () => {
    const r = await bridge.updateCheck()
    setUpdateMsg(r.newer ? `Versão ${r.latest} disponível.` : `Você tem a versão mais recente (${r.current}).`)
  })
  const clearCache = () => run(async () => {
    if (!window.confirm("Limpar o cache de shaders? O próximo início trava alguns minutos enquanto o cache é refeito.")) return
    await bridge.clearCache()
    setCacheMsg("Cache de shaders limpo.")
  })
  return (
    <div className="settings">
      <h1>{t("Play") === "Jogar" ? "Avançado" : "Advanced"}</h1>
      {error && <p className="op-error">{error}</p>}
      <Section title={t("Advanced")}>
        <Field label={t("Language")} hint="Aplica-se quando o launcher abrir de novo.">
          <Dropdown value={String(app.ui_language ?? "en")} choices={state.choices.ui_language}
            onChange={(v) => setApp("ui_language", v)} label="Idioma do launcher" />
        </Field>
        <Field label={t("Stop")}>
          <Toggle value={!!app.close_on_play} onChange={(v) => setApp("close_on_play", v)}
            label="Fechar ao iniciar" />
        </Field>
        <Field label={t("Stop")}>
          <Toggle value={!!app.check_updates} onChange={(v) => setApp("check_updates", v)}
            label="Verificar atualizações" />
        </Field>
        <div className="inline-row">
          <ActionButton onClick={checkUpdate}>Verificar atualizações</ActionButton>
          <span className="version">v{state.version}</span>
        </div>
        {updateMsg && <p className="op-ok">{updateMsg}</p>}
      </Section>
      <Section title={t("Log")}>
        <div className="inline-row">
          <ActionButton onClick={() => bridge.openInExplorer(state.app.user_dir ? String(state.app.user_dir) : "user")}>Pasta de saves</ActionButton>
          <ActionButton onClick={() => bridge.openInExplorer("gow3.ini")}>gow3.ini</ActionButton>
        </div>
        <div className="inline-row">
          <ActionButton danger onClick={clearCache}>Limpar cache de shaders</ActionButton>
          <span className="version">Se o jogo só mostrar uma tela preta, isto costuma resolver.</span>
        </div>
        {cacheMsg && <p className="op-ok">{cacheMsg}</p>}
      </Section>
      <Section title={t("Log")}>
        <Field label="Estatísticas de quadros no log (a cada 5 s)">
          <Toggle value={!!app.frame_stats} onChange={(v) => setApp("frame_stats", v)} label="Estatísticas" />
        </Field>
        <Field label="Tempo de GPU por passo no log">
          <Toggle value={!!app.gpu_profile} onChange={(v) => setApp("gpu_profile", v)} label="Perfil de GPU" />
        </Field>
        <Field label="Relatório de esperas e leituras da GPU no log"
               hint="Mostra onde o quadro espera a GPU; para testes de desempenho.">
          <Toggle value={!!app.perf_diag} onChange={(v) => setApp("perf_diag", v)} label="Relatório de GPU" />
        </Field>
        <Field label="F11 captura um quadro para análise"
               hint="Grava como o próximo quadro é desenhado na pasta de capturas.">
          <Toggle value={!!app.frame_capture_key} onChange={(v) => setApp("frame_capture_key", v)}
            label="Captura de quadro" />
        </Field>
        <Field label="Camadas de validação Vulkan (precisa do SDK; muito mais lento)">
          <Toggle value={!!app.vk_validation} onChange={(v) => setApp("vk_validation", v)}
            label="Validação Vulkan" />
        </Field>
      </Section>
    </div>
  )
}

/* ---------- Registro (build_log) ---------- */
export function LogPage(_props: P) {
  const { t } = useI18n()
  const [text, setText] = useState("")
  const [source, setSource] = useState("")
  const load = () => bridge.logRead().then((r) => {
    const s = r.sources[0]
    setText(s ? s.text : "")
    setSource(s ? s.path : "")
  }).catch(() => setText(""))
  useEffect(() => { void load() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="settings log-page">
      <h1>{t("Play") === "Jogar" ? "Registro" : "Log"}</h1>
      <div className="inline-row">
        <ActionButton onClick={load}>{t("Play") === "Jogar" ? "Atualizar" : "Refresh"}</ActionButton>
        <ActionButton onClick={() => navigator.clipboard?.writeText(text)}>Copiar</ActionButton>
      </div>
      <pre className="log" aria-label="Log de execução">{text || "Sem registros ainda — o log da execução aparece aqui durante e após iniciar o jogo."}</pre>
      {source && <p className="field-hint">Fonte: {source}</p>}
    </div>
  )
}

export const PAGES: { id: string; label: string; component: (p: P) => React.ReactElement | null }[] = [
  { id: "display", label: "Display", component: DisplayPage },
  { id: "graphics", label: "Gráficos", component: GraphicsPage },
  { id: "performance", label: "Performance", component: PerformancePage },
  { id: "game", label: "Game", component: GamePage },
  { id: "patches", label: "Patches", component: PatchesPage },
  { id: "mods", label: "Mods", component: ModsPage },
  { id: "controls", label: "Controls", component: ControlsPage },
  { id: "advanced", label: "Advanced", component: AdvancedPage },
  { id: "log", label: "Log", component: LogPage },
]
