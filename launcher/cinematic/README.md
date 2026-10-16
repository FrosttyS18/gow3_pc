# God of War III — Cinematic Launcher

Launcher próprio do fork em **React + TypeScript + Tauri 2 (Rust)** sobre a lógica real
do port: nenhuma regra do port é reimplementada em TypeScript/Rust. Nove páginas de
configuração + ação de Música, pt-BR/en, fundo cinematográfico, música ambiente e
inicialização do jogo com supervisão nativa de processos. A interface é regida por
`CONTRACT.md` (fonte única de verdade); o upstream fornece funcionalidades, nunca design.

## Arquitetura (atual)

- **Ponte Python persistente**: `src-tauri` mantém UM processo Python por launcher
  (`bridge/launcher_bridge.py` em modo worker, envelopes `{"seq","req"}` → `{"seq","resp"}`
  pela mesma conexão stdin/stdout). Zero `python.exe` por clique, escritas serializadas,
  recuperação limitada (2 renascimentos/min), prazo por chamada (`GOW3_BRIDGE_TIMEOUT_MS`,
  padrão 120 s) sem repetição automática de operações com efeito. Sem esse ambiente o
  bridge roda single-shot (um pedido por processo — modo usado pelos testes).
- **`launcher_bridge.py` importa `gow3_launcher_win.py` como biblioteca** (sem Tk): todas
  as chaves/listas/validações vêm do backend oficial do port. Comandos: state, set_ini,
  set_app, patches/mods/presets/backups/controles (com glyph_style e vibração),
  anisotropia, clear_cache, update_check, log_read, resolve_path, prepare_play, play_status.
- **Sessão do jogo por eventos**: JOGAR = `prepare_play` (a ponte devolve comando/cwd/env)
  → o Rust inicia o run.py SUSPENSO (`CreateProcessW`), associa aos Job Objects
  (principal como pai → sessão como filho, conforme Nested Jobs) e só então retoma; o fim
  real da sessão chega por porta de conclusão do kernel (ACTIVE_PROCESS_ZERO) com fallback
  `QueryInformationJobObject` — zero polling durante o jogo. Evento Tauri
  `gow3://game-end` atualiza a interface uma única vez.
- **Job Object vitalício** `KILL_ON_JOB_CLOSE`: launcher morto = árvore do jogo morta pelo
  kernel; launcher oculto (`close_on_play`) NÃO encerra o jogo; processos de terceiros
  nunca são tocados. Discord Rich Presence permanece desativado por design
  (`GOW3_DISCORD=0` em toda partida).
- **Upstream**: motor na versão windows-v2.3.0 (registro APPROVED_UPSTREAM com provas de
  blob por versão; ver `zcode/upstream-exceptions/`). FSR 4 e upscaling temporal não são
  apresentados como funcionais; anisotropia 0-16× (página Gráficos) e vibração 0-100%
  (página Controles) são reais e gravam no `gow3.ini`; screenshots F12 são do motor.

## Desenvolvimento

```bash
cd launcher/cinematic
npm install
npm run tauri dev      # janela real (precisa Rust/MSVC + Node)
npm run dev            # preview no navegador com mock (não toca em configuração alguma)
```

Requisitos: Node (npm), Rust (MSVC), Windows Python 3 no PATH para a ponte, e a árvore do
port (a ponte localiza tudo pelos ancestrais do executável — funciona no checkout e no
build de teste). Build de teste: `npm run tauri build -- --no-bundle` (exe em
`src-tauri/target/release/`). A distribuição autônoma (runtime Python próprio) está
especificada em `docs/CINEMATIC-DISTRIBUTION.md`.

## Arte local (NÃO versionada)

`public/art/` está no `.gitignore`: material licenciado ou pessoal do mantenedor —
`bg-launcher.png`, `logo-gow-3.png`, `intro_launcher.mp3`/`ambient.mp3` e (no PR do vídeo)
`videolauncher.mp4`. Copie-os manualmente para `public/art/` antes de rodar/empacotar; o
build os embute no executável (o repositório público nunca os recebe). Sem eles o launcher
usa o fundo em gradiente, a imagem estática (fallback do vídeo) e o título tipográfico de
reserva — nada de arte aleatória.

## Música ambiente

Padrão `public/art/ambient.mp3` (ou `intro_launcher.mp3`); seletor de pasta persiste o
caminho em `settings.json` (`ambient_file`, `ambient_muted`; volume fixo de contrato).
Ao clicar JOGAR a música para de forma determinística (pause imediato) antes da sessão.

## Contratos preservados

- `settings.json` / `gow3.ini` / `mods.json` / `patches.json` só são escritos pelas
  rotinas do port (`save_ini` atômico preserva comentários e chaves de terceiros; a ponte
  grava APENAS as chaves pedidas — alterações feitas dentro do jogo nunca são reescritas;
  `set_ini`/`set_app` recusam chaves fora do contrato).
- JOGAR usa exatamente `game_environment`/`run_command`/cwd do port; o estado
  (preparando/executando/erro) vem do código de saída REAL da sessão e do log em
  `%TEMP%/gow3-cinematic-run.log`.
- Permissões Tauri mínimas (`capabilities/default.json`): janela e diálogo; sem shell, sem
  fs, sem http. O áudio local é lido como data URL limitada a MP3 ≤ 48 MB.
- O launcher Tkinter do port continua no repositório (é a biblioteca que a ponte importa),
  mas a interface principal do fork é esta.

## Testes

```bash
python tests/test_bridge.py          # ponte (worker + single-shot), a partir de launcher/cinematic
python tests/test_play.py            # fluxo JOGAR com processo substituto
env USER=%USER% python tests/test_ui.py   # 48+ verificações CDP na janela real (release exe)
cd src-tauri && cargo test -- --test-threads=1   # worker/sessão/Job Objects (serializado)
```

Fixtures 100% temporárias — as configurações reais do mantenedor nunca são tocadas. O jogo
real nunca é executado pelos testes.
