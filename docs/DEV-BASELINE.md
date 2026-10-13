# DEV-BASELINE — Bootstrap e auditoria do fork (Windows)

Data: 2026-10-12 · Branch: `chore/zcode-baseline` · Commit: `4c6467d` (`docs: add ZCode project engineering guardrails`)
Máquina: Windows 10/11 x64 · Shell: Git Bash + MSYS2 CLANG64 · Nenhuma alteração funcional de código feita nesta baseline.

Comandos e resultados abaixo são reproduzíveis a partir de um clone limpo
(`git clone --recurse-submodules https://github.com/FrosttyS18/gow3_pc`) com o ambiente descrito na seção 2.

---

## 1. Arquitetura identificada

### 1.1 Fluxo de inicialização (Windows)

```
launcher/gow3_launcher_win.py (Tkinter, ~1.7k linhas)
  └─ play() → subprocess run.py com ambiente GOW3_* derivado de settings.json + gow3.ini
       └─ run.py: mods.py → prepare.py → link_libc.py → link_modules.py → content_profile.py
            → graphics_options.py (decide patches de resolução/FPS)
            → patches.py (compila XML → out/patches.bin, formato G3PATCH2)
            → save_backup.py (backup de saves antes de cada partida)
            → out/gow3-probe.exe (jogo; runtime C + libgow3gpu estática via CMake)
```

- O launcher congelado por PyInstaller (`God of War III.exe`) também executa `run.py` (`--run`),
  os scripts (`--script`) e o jogo sem janela (`--play`); a atualização automática usa
  `--install-update` (copia a si mesmo preservando `user/`, `out/`, `gow3.ini`, mods etc.).
- Reinício in-game ("Apply and restart"): `runtime_restart()` (src/probe.c) executa
  `GOW3_RESTART_COMMAND` (linha de comando de run.py com `--after PID`); o launcher mantém o jogo
  num Job Object Windows para encerrar descendentes.

### 1.2 Persistência (contratos que qualquer UI nova deve manter)

| Arquivo | Conteúdo | Escrito por |
|---|---|---|
| `%APPDATA%/gow3-launcher/settings.json` | ~35 chaves do launcher (`game_dir`, `game_patches`, `controls`, `pad_style`, idioma UI, flags de diagnóstico…) | launcher (`collect()`) |
| `<port>/gow3.ini` | ~26 chaves de gráficos/jogo (lidas por `gpu/shim/gow3_graphics.h`; editadas também pelo menu in-game Insert/R3+L2) | launcher, menu in-game, `graphics_options.py` (rollback `restart_unconfirmed`) |
| `<port>/mods.json` / `mods_presets.json` | ordem/estado dos mods e presets | launcher |
| `<port>/patches.json` | patches externos habilitados/desabilitados | launcher |
| `<user>/savedata/<uid>/<title>/…` + `.sce_sys/` (param.bin, icon0.png) + `<title>.memory/memory.dat` | saves reais (emulação libSceSaveData em disco) | runtime C (`runtime_savedata.c`) |
| `<user>/savedata_backups/<timestamp>/` | até 10 backups automáticos | `save_backup.py` |

### 1.3 Sistema de patches e validação do executável

- Contrato **v2.1.8 (por assinatura)**: `scripts/patches.py::GAMES` registra os títulos
  `{CUSA01623, CUSA01715, CUSA01720}` (AppVer de metadados `01.02`); cada site de patch é
  localizado pelas linhas `Pattern`/`At` do XML em qualquer build cujo código corresponda —
  o SHA-256 do eboot **não** restringe mais a aplicação (o caso especial do "full 01.02 update"
  `6e72330e…` foi absorvido: seus sites têm assinaturas comprovadas,
  `tests/data/eboot_6e72_sites.json` + `tools/make_signatures.py`).
- `REFERENCE_SHA256` (`d85c8135…`) documenta o build de referência para os valores `Address`
  internos e patches de terceiros; `GOW3_FORCE_PATCHES` continua proibido usar/agregar em UI nova.
- Somente writes literais (bytes/bytes16/32/64/float/utf); patches "mask" rejeitados; endereços
  validados contra os segmentos PT_LOAD do eboot (`out/eboot.elf`); base fixa `0x400000`.
- Patches de resolução e frame-rate derivam de `gow3.ini` (`graphics_options.py`), não da lista manual;
  `GOW3_DMEM_MB`/`GOW3_VBLANK_HZ` derivam das notas dos patches selecionados.
- Patches externos (shadPS4/GoldHEN XML em `<data>/patches/*.xml`) filtrados por TitleID/AppVer.

### 1.4 Tela de saves (contrato PS4 → overlay)

- `src/runtime_services.c::save_open` traduz `sceSaveDataDialogOpen` (modo LIST): monta até 32 itens
  ("New save" opcional + saves com título/subtítulo/data de `param.bin` e caminho de `icon0.png`),
  título "Save game"/"Load game"/"Delete save" por `dispType`, e chama a ponte C `gow3gpu_choice_begin`.
- `gpu/shim/gow3gpu.cpp::gow3gpu_choice_begin` decoda PNGs ( Gow3Png::LoadRgba ) na thread do jogo e
  chama `Gow3Overlay::BeginChoice`; `gow3gpu_choice_poll` devolve −1 aberto / −2 cancelado / índice.
- `gpu/shim/gow3_overlay.cpp::ChoiceBox()` desenha a lista (imagens 228×128, seleção "> item" com
  contorno dourado, rodapé com dicas de tecla/controle); entrada por `HandleChoiceEvent`
  (Up/Down/W/S move; Enter/Space/Cross confirma; Esc/Backspace/Circle cancela; D-pad).
- `save_status`/`save_result` mapeiam a escolha de volta ao resultado Orbis (dirName escolhido,
  buttonId=1; cancelamento → result=1). Nomear save novo usa ImeDialog → `TextEntryBox` no overlay.
- Backend (mount/search/delete/param/memory em `runtime_savedata.c`) está fora do escopo de UI.

### 1.5 Menu in-game (overlay Dear ImGui)

`gow3_overlay.cpp::Menu()`: 4 abas (Game/Cheats+Multiplicadores+HUD, Image, Performance, Overlay),
aberto por Insert ou R3+L2, navegável por teclado/gamepad (L1/R1/Q/E trocam abas), ajuda de rodapé,
"Apply and restart" quando opções de inicialização mudam. Mesma mutex (`imgui_mutex`) protege o
contexto entre a thread de janela (input) e a de apresentação (render Vulkan).

### 1.6 Build e empacotamento Windows

- `build.sh` (caso MINGW/MSYS): `source msys2-env.sh` (PATH CLANG64) → aplica patches do submódulo
  FSR-Vulkan → `cmake -S gpu -B out/gpu -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DGOW3_PGO=off
  -DGOW3_LTO=OFF` → `ninja gow3-probe gow3-gpu-capabilities gow3-play` → copia para `out/`.
- `packaging/windows/package.sh`: venv privada + PyInstaller congela o launcher em
  `God of War III.exe` (windowed, ícone, hidden-imports dos scripts), `llvm-strip` nos .exe,
  copia DLLs do CLANG64 via `ldd`, valida proibição de arquivos do jogo/saves no pacote, gera
  `dist/gow3-windows.zip` e atualiza `dist/gow3-windows` preservando dados do jogador.
- Submódulos: fsr-vulkan, imgui, magic_enum, miniz, xbyak (gpu/third_party), LibAtrac9 (third_party).

### 1.7 Testes existentes

- **Python** (`python -m unittest discover -s tests`): 16 arquivos `.py` cobrindo patches, prepare,
  mods, saves/backup, opções gráficas, controles do launcher, conteúdo, link_libc, upscaler assets,
  runtime/sema via artefatos nativos, probe. Fixtures sintéticas (XML/temp dirs); nenhum precisa de dump real.
- **C** (CMake, `ninja <target>`): mp3, videodec, services, pad-map, audio-downmix (WIN32) —
  também construídos no Linux via `build.sh --test` junto com runtime-test, sema-test, file-mods-test,
  content-test, pad-test (Linux/POSIX).
- **C++** (CMake `EXCLUDE_FROM_ALL`, "neither launches the game nor needs a Vulkan device"):
  pipeline-binary-cache, pipeline-binary-initialization, motion-history, motion-shader, png-decode,
  aliasing, blend-rewrite, depth-stencil-state, async-compiler, warmup-inbox, async-pipeline-cache,
  async-fetch-snapshot, ui-composition, scene-resolution, taa-shader, camera-motion,
  upscaler-support, orb-multiplier, stat-multipliers, perf-overlay, cheat-hooks, readback-queue,
  wait-diagnostics, graphics-settings, actor-hook, readback-sources, page-state, cheat-hook.

### 1.8 Riscos e pontos de atenção

1. `patches.py` e `prepare.py` usam estilo denso; mudanças de UI **não devem** tocar neles.
2. A UI do launcher depende de detalhes do Tkinter (DPI, job objects, `os.startfile`); uma troca de
   stack reimplementa esses comportamentos de plataforma (ver proposta de arquitetura).
3. `test_probe.py` espera `out/gow3-probe` (sem `.exe`): 15 testes ficam BLOCKED no Windows.
4. Testes `test_mods::test_mod_symlinks_rejected` e `test_packaged_vulkan` exigem criação de symlink
   (precisa de Modo Desenvolvedor/privilégio no Windows) ou lógica Linux/Nix — falham por plataforma,
   não por regressão.
5. `README.md`/docs upstream descrevem o fluxo Linux; o caminho Windows autoritativo é
   `packaging/windows/README.md`.
6. O overlay renderiza na thread de apresentação; qualquer redesenho da tela de saves precisa
   respeitar `imgui_mutex` e o ciclo de texturas (RegisterUserTexture/retire).

---

## 2. Ambiente preparado

| Componente | Versão instalada/verificada | Observações |
|---|---|---|
| Windows Python | 3.12.10 (python.org) | tkinter OK, Pillow OK |
| MSYS2 | `C:\msys64` (base pré-existente) | pacman, sem elevação administrativa |
| CLANG64 toolchain | clang 22.1.7, cmake 4.3.4, ninja 1.13.2, pkgconf | instalados via pacman nesta sessão (201 pacotes, exit 0) |
| Vulkan | headers/loader 1.4.350 + VMA + glslang | via pacman (equivalente ao SDK exigido pelo projeto; camadas de validação oficiais do SDK LunarG **não** instaladas — só afetam o diagnóstico `vk_validation`) |
| SDL3 | 3.4.10 | pkg-config |
| FFmpeg | 62.28.102 (avcodec) | pkg-config |
| fmt / Boost / robin-map / xxhash / Zydis / spirv-tools+headers+cross | instalados | conforme `packaging/windows/README.md` |
| Submódulos git | 6/6 inicializados (`git submodule update --init --recursive`) | commits pinados pelo repo |

Comando de instalação usado (escopo `C:\msys64` apenas, sem mudanças globais do Windows):

```bash
pacman -S --needed git patch \
  mingw-w64-clang-x86_64-{toolchain,cmake,ninja,pkgconf,python} \
  mingw-w64-clang-x86_64-{vulkan-headers,vulkan-loader,vulkan-memory-allocator,glslang} \
  mingw-w64-clang-x86_64-{sdl3,fmt,boost,robin-map,xxhash,ffmpeg,zydis} \
  mingw-w64-clang-x86_64-{spirv-tools,spirv-headers,spirv-cross}
```

Limitações do ambiente: sem dump do jogo (CUSA01623) nesta máquina — qualquer teste que precise do
jogo real é BLOCKED por design; Vulkan SDK completo (camadas de validação) não instalado;
MSVC/DLSS bridge não configurado (opcional, `packaging/windows/build_dlss.sh`).

---

## 3. Baseline determinística

Commit: `4c6467d` · branch `chore/zcode-baseline` · submódulos nos commits pinados.
Executado em 2026-10-12, ordem: build → testes nativos → testes Python.

### 3.1 Build original (sem mudanças funcionais)

```bash
export PATH="/c/msys64/clang64/bin:/c/msys64/usr/bin:$PATH"
bash build.sh          # → BUILD_EXIT=0
```

Resultado: **PASS** — avisos apenas de política CMake (CMP0167 FindBoost removido; miniz
cmake_minimum_required<3.10; CMP0077), sem erros.

Artefatos (`out/`): `gow3-probe.exe` (136.597.504 B, PE32+ x86-64 GUI, RelWithDebInfo, LTO OFF),
`gow3-gpu-capabilities.exe` (282.624 B), `gow3-play.exe` (149.504 B).

### 3.2 Testes nativos C/C++ (alvos CMake, `ninja -C out/gpu -k 0 <targets>`)

Repositório não tem CI; estes alvos são construídos sob demanda. 33 alvos solicitados:
28 compilaram, 5 falharam a compilar (gap preexistente do upstream para Windows).

| Grupo | Alvos | Resultado |
|---|---|---|
| PASS (26) | actor-hook, aliasing, async-compiler, async-fetch-snapshot, audio-downmix, blend-rewrite, cheat-hook, depth-stencil-state, graphics-settings, motion-history, mp3 (`tests/data/sine.mp3` como argv), orb-multiplier, pad-map, page-state, perf-overlay, pipeline-binary-cache, pipeline-binary-initialization, png-decode, readback-queue, readback-sources, services, stat-multipliers, ui-composition, videodec (`tests/data/tiny.h264` como argv), wait-diagnostics, warmup-inbox | EXIT=0 |
| FAIL (2, preexistente) | `async-pipeline-cache-test` — assert `vkCreateInstance` (o teste zera `VkInstanceCreateInfo`; loader/driver NVIDIA rejeita `apiVersion=0` nesta máquina; requer Vulkan com dispositivo). `cheat-hooks-test` — segfault determinístico (5/5 execuções) ao executar o stub gerado por `gow3_cheat_build_stub`; suspeita de sensibilidade à toolchain clang 22.1.7 (atributo `sysv_abi` em ponteiro de função Win64) — o alvo irmão `cheat-hook-test` passa. Nenhum código foi alterado; não é regressão deste trabalho. | EXIT≠0 |
| BLOCKED build (5, preexistente) | `motion-shader-test`, `scene-resolution-test`, `taa-shader-test`, `camera-motion-test` — compilam `tests/test_gpu_runtime_stubs.cpp` sem o shim WIN32 (`sigjmp_buf=gow3_jmp_buf` + `-include compat_win.h`) que os alvos pipeline-binary-* têm. `upscaler-support-test` — usa `setenv`/`unsetenv` (POSIX). | não compilam no Windows |

Observação: o CMake declara os alvos C++ como "neither launches the game nor needs a Vulkan
device"; `async-pipeline-cache-test` é exceção (cria instância Vulkan).

### 3.3 Testes Python

```bash
python -m unittest discover -s tests -v
# Ran 124 tests — FAILED (failures=1, errors=2, skipped=30)
```

| Resultado | Contagem | Detalhe |
|---|---|---|
| PASS | 91 | test_patches (exceto 1), test_prepare, test_mods (exceto 1), test_save_backup, test_graphics_options, test_button_icons, test_launcher_controls, test_launcher_stream_memory, test_mod_conflicts, test_upscaler_assets, test_content (3), test_link_libc, test_runtime (1, os demais SKIP), test_packaged_vulkan (parcial) |
| FAIL | 1 | `test_packaged_vulkan.test_host_driver_can_be_supplied_outside_hidden_nix_store` — lógica de Nix store (Linux) diverge no Windows |
| ERROR | 2 | `test_mods.test_mod_symlinks_rejected`, `test_packaged_vulkan.test_host_nvidia_and_compiler_are_exposed_without_host_libc` — `WinError 1314`: criação de symlink exige privilégio/Modo Desenvolvedor no Windows |
| SKIP (BLOCKED) | 30 | 15× `test_probe` ("build native probe first": espera `out/gow3-probe` sem `.exe`); 14× "run bash build.sh --test first" (`test_content` 3 + `test_runtime` 7 + `test_sema` 4 — binários de teste nativos do fluxo Linux); 1× `test_patches` ("GOW3_GAME not set" — exige dump real; por design não roda em CI) |

Auditoria da contagem (reconciliação, log `pytests-baseline.log`): o resumo do unittest
(`Ran 124 tests … failures=1, errors=2, skipped=30`) implica 91 PASS. O log contém 124 linhas de
cabeçalho `^test_`, 30 linhas `... skipped` (15+14+1 por motivo acima) e 3 testes nas seções
ERROR/FAIL. Um `grep` ancorado em `... ok$` encontra apenas 85 linhas porque 6 testes que PASSAM
(5 de `test_mods`, 1 de `test_patches.ExternalPatchTests`) escrevem stdout no meio da própria linha
de resultado (ex. `test_wrapped_layouts … … Mods: Archive: 1 files … ok`); nenhum deles aparece nas
seções de falha, logo são PASS: 85+6=91. Detalhamento anterior que somava 31 SKIPs era erro de
leitura do log (incluía um PASS cujo *nome* contém "skipped" e contava `test_sema` como 5 em vez
de 4); os números do resumo (91/1/2/30) sempre foram consistentes entre si: 91+1+2+30=124.

Classificação: os 3 FAIL/ERROR são **limitações de plataforma preexistentes**, não regressões
(o commit é o HEAD intocado de `main`); os 30 SKIP são **BLOCKED** por artefatos/plataforma, nunca PASS.

### 3.4 Empacotamento Windows (`packaging/windows/package.sh`)

```bash
export PATH="/c/msys64/clang64/bin:/c/msys64/usr/bin:$PATH"
env USER="$USER" bash packaging/windows/package.sh   # Git Bash: USER precisa estar no ambiente
```

Resultado: **PASS** — venv privada `out/pyenv` + PyInstaller congelou o launcher em
`God of War III.exe`; `dist/gow3-windows.zip` (66 MB) e `dist/gow3-windows/` (180 MB) com
`Play God of War III.exe`, `bin/gow3-probe.exe` + DLLs CLANG64 (SDL3, FFmpeg, …), `scripts/`,
`run.py`, `patches/`; a checagem de arquivos proibidos (eboot/sce_/saves/logs) passou.

Nota de ambiente (não é bug do projeto): o script usa `set -u` e espera o shell MSYS2 CLANG64,
onde `USER` existe; em Git Bash puro é preciso `env USER=<nome>` antes de invocá-lo.

### 3.5 Resumo consolidado da baseline

| Suíte | PASS | FAIL | SKIP/BLOCKED | Observação |
|---|---|---|---|---|
| Python (`unittest discover`) | 91 | 1 | 30 (BLOCKED: 30) | 2 ERROR contam como FAIL; falhas de plataforma Windows (symlink/Nix), preexistentes |
| Nativas C/C++ (CMake) | 26 | 2 | 5 (BLOCKED build) | ver §3.2; falhas preexistentes, determinísticas |
| build.sh | PASS | — | — | 3 executáveis em `out/` |
| package.sh | PASS | — | — | `dist/gow3-windows.zip` |

Nenhum teste foi marcado PASS sem execução; logs completos em `/c/gow3/*.log` desta máquina
(`pytests-baseline.log`, `native-tests-final.log`, `testlogs/`, `build-baseline.log`,
`package-baseline.log`).

### 3.6 Erros preexistentes e não resolvidos nesta baseline

- Falhas/erros de plataforma descritos em §3.3 (reproduzíveis em qualquer Windows sem Modo
  Desenvolvedor; esperado PASS no CI Linux do upstream).
- `cheat-hooks-test` segfault determinístico e `async-pipeline-cache-test` assert Vulkan (§3.2) —
  requerem investigação em trabalho futuro; NÃO são regressões deste bootstrap.
- 5 alvos de teste C++ não compilam no Windows (shim `sigjmp_buf`/`setenv` ausente nos alvos, §3.2).
- Avisos CMake (§3.1) — inofensivos, sem tratamento na baseline.

---

## 4. Escopo do redesign de UI (decisão do mantenedor, 2026-10-12)

**Definitivamente FORA do escopo:** o menu in-game aberto por Insert/R3+L2
(`Menu()` em `gpu/shim/gow3_overlay.cpp`). Não redesenhar, refatorar nem modificar.

O projeto de UI tem **exatamente dois objetivos**:

1. **Launcher Windows** — redesign completo, moderno, cinematográfico e exclusivo de God of War
   III Remastered, preservando **todas** as funções atuais (paridade funcional: Play/Display/
   Performance/Game/Patches/Mods/Controls/Advanced/Log, backups, idiomas, atualização) e adotando
   **português do Brasil** como idioma. Direção técnica proposta (aprovação pendente): React +
   Tauri 2 híbrido com sidecar Python congelado para toda a orquestração do jogo (`run.py` +
   `scripts/` intocados); Tkinter permanece fallback até paridade comprovada por testes de
   saída dourada. O launcher NÃO será biblioteca de jogos, loja, dashboard administrativo nem
   plataforma com funcionalidades fictícias.
2. **Tela de saves in-game** — personalização **visual** da interface de salvar/carregar em Dear
   ImGui (`ChoiceBox()`/`TextEntryBox()` em `gpu/shim/gow3_overlay.cpp`), sem modificar o backend
   (`save_open/status/result`, `runtime_savedata.c`, ponte `gow3gpu_choice_begin`, decodificação
   PNG) nem comprometer a compatibilidade; entrada por teclado/controle preservada.

Implementação continua **dependendo de aprovação posterior**. Esta branch contém apenas
documentação; nenhum código funcional foi alterado.



---

## 5. Re-baseline pós-upstream windows-v2.1.8 (2026-10-13)

Branch `chore/upstream-windows-v2.1.8` (merge de `bb74e41c` sobre `main@997dab2`, árvore
upstream blob-idêntica; exceção `zcode/upstream-exceptions/windows-v2.1.8.json` com 65 arquivos
comprovados contra o commit oficial). Mesma máquina/ambiente da seção 2. Logs: `/c/gow3/*.log`
(`build-v218.log`, `native-build-v218.log`, `native-runs-v218.log`, `pytests-v218.log`,
`pytests-v218-verbose.log`, `package-v218.log`).

### 5.1 Build e artefatos

`bash build.sh` → **PASS** (exit 0). `out/gow3-probe.exe` 137.794.048 B (+1,2 MB vs baseline:
ISA rewrite/CPU check/MSAA/GPU paths), `gow3-gpu-capabilities.exe` 285.696 B, `gow3-play.exe`
149.504 B. Avisos CMake idênticos aos preexistentes.

### 5.2 Testes nativos (43 alvos; 10 novos da v2.1.8)

- **37 PASS** — inclui os 10 novos (`amd-paths`, `cpu-check`, `isa-emulate`, `isa-stub`
  (argv `tests/data/isa_fixture.bin`), `lighting-test-knob`, `no-msaa`, `pass-census`,
  `signatures`, `tsc-clock`, `wave-stats`) e **`cheat-hooks-test` agora PASSA** (segfault
  determinístico da baseline §3.2 corrigido pelo upstream).
- **1 FAIL preexistente**: `async-pipeline-cache-test` (assert `vkCreateInstance`; exige
  dispositivo Vulkan — idêntico à baseline).
- **5 BUILD-BLOCKED preexistentes**: `motion-shader`, `scene-resolution`, `taa-shader`,
  `camera-motion`, `upscaler-support` (shim WIN32 `sigjmp_buf`/`setenv` ausente — gap upstream).
- Nota de método: `timeout 60 ./x.exe` no Git Bash retornou 127 espúrio para 3 exes que passam
  ao rodar diretamente (`orb-multiplier`, `pipeline-binary-cache`, `async-pipeline-cache` tem
  FAIL real com assert impresso); rodar direto é o método válido.

### 5.3 Testes Python (`python -m unittest discover -s tests`)

`Ran 211 tests — FAILED (failures=2, errors=3, skipped=50)` → **156 PASS** (87 testes novos
vs baseline de 124). Módulos novos 100% OK: `test_launcher_desktop` (5), `test_launcher_font`
(9), `test_launcher_game_files`/Sc0 (2), `test_launcher_no_msaa` (8), `test_launcher_run_log`
(6), `test_launcher_stdio` (2), `test_steam_shortcut` (12), `test_run_isa` (4), `test_link_modules`
(1); `test_isa_rewrite` 21/21 OK com `pip install iced-x86` (17 skips sem o pacote).
Falhas classificadas: 3 preexistentes (§3.3: symlink `test_mods`/`test_packaged_vulkan`, Nix)
+ **2 novas de plataforma do upstream** (`test_game_update`: fusão de pastas via junction e
  `WinError 145` no `remove_view` — sem privilégio de symlink no Windows; código
  blob-idêntico ao oficial, reproduziria igual na árvore upstream nesta máquina) — não são
  regressões da integração. Skips: 15 probe-.exe, 14 artefatos `--test` Linux, 2 `GOW3_GAME`,
  17 iced-x86 (convertidos em PASS acima), 2 demais.

### 5.4 Empacotamento

`env USER=adcka bash packaging/windows/package.sh` → **PASS** (exit 0);
`dist/gow3-windows.zip` 76.996.051 B (74 MB, vs 66 MB da baseline; `God of War III.exe`
launcher v2.1.8 via PyInstaller 6.22.3; checagem de arquivos proibidos OK).

### 5.5 Cobertura das novidades v2.1.8

CPU/ISA (`cpu-check`, `isa-emulate`, `isa-stub`, `test_isa_rewrite`, `test_run_isa`) ·
multisampling automático (`no-msaa`, `test_launcher_no_msaa`) · seleção de GPU
(`amd-paths`, `vk_amd_paths.h`) · Sc0 (`test_launcher_game_files`) · logs de execução
(`test_launcher_run_log`) · Steam (`test_steam_shortcut`) · patches por assinatura
(`signatures`, `test_patches` 13 OK; `REFERENCE_SHA256` apenas de referência).
