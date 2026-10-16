# Distribuição Windows do Cinematic Launcher — Estado e Plano NSIS

Documento próprio do fork (2026-10-15). Separa explicitamente as três versões:

| Camada                  | Versão atual | Origem                                          |
|-------------------------|--------------|-------------------------------------------------|
| Port/motor (upstream)   | windows-v2.3.0 (`f80021b0`) | FelipePrado0/gow3_pc, blob-provada            |
| Launcher cinematográfico| 2.3.0-cinematic (main `1b2379d`; vídeo/menu no PR #13) | este fork               |
| Instalador              | 0.1 (PLANEJADO — não construído) | NSIS via bundle Tauri                    |

## 1. Arquitetura de distribuição (alvo)

Instalação **por usuário, autônoma, sem Python/Rust/Node/MSYS2/Git na máquina**:

```
%LOCALAPPDATA%\gow3-cinematic\            (gravável — sem exigir admin)
├── gow3-cinematic.exe                    app Tauri (frontend embutido)
├── bridge\launcher_bridge.py             ponte (worker persistente)
├── launcher\gow3_launcher_win.py, gow3_lang.py, gow3_vulkan.py, gow3.ico, gow3.png, gowfont.ttf
├── runtime\python\                       python embeddable + Pillow (PRIVADO do launcher)
├── run.py, scripts\, patches\            preparo/execução oficiais do port (intocados)
├── bin\gow3-probe.exe, gow3-gpu-capabilities.exe, *.dll   (DLLs CLANG64 via ldd)
└── data\ …                               user/, out/, gow3.ini, mods/, caches (GRAVÁVEL)
```

A pasta do JOGO permanece externa, escolhida pelo usuário e persistida em
`settings.json` — o instalador NUNCA a toca e NUNCA inclui `eboot.bin`, `sce_module`,
`sce_sys`, dumps, saves, caches de shader ou qualquer conteúdo proprietário do jogo
(lista de proibidos idêntica à do `packaging/windows/package.sh` oficial).

## 2. Manifesto preliminar de runtime (dependências EFETIVAS verificadas)

- **App Tauri**: `gow3-cinematic.exe` (frontend embutido no binário; CSP com
  `media-src 'self' data: blob:`). Requer **WebView2 Runtime** — o bundle NSIS do Tauri
  anexa o bootstrapper oficial (baixa/instala se ausente; já configurado em
  `tauri.conf.json` → `bundle.targets: ["nsis"]`).
- **Python**: única dependência de terceiros da ponte/run.py/scripts é **Pillow**
  (`PIL` — glyphs, ícones; conferido por inspeção de imports). Runtime privado =
  "Windows embeddable Python 3.12" (~11 MB) + `pip install pillow` na imagem, com
  `python312._pth` liberando `site-packages` e apontando `..` para a árvore do launcher.
- **Binários nativos do port**: `gow3-probe.exe`, `gow3-gpu-capabilities.exe`
  (`gow3-play.exe` é do fluxo Tk, não usado pela ponte) + TODAS as DLLs que carregam da
  toolchain CLANG64 (SDL3, FFmpeg, loader Vulkan etc.) — enumerar com `ldd` exatamente
  como `packaging/windows/package.sh` faz; `llvm-strip --strip-debug` nos exes.
- **Recursos oficiais**: `run.py`, `scripts/` (inclui `discord_presence.py` e
  `guest_memory.py` — blob-idênticos; Discord permanece DESATIVADO por design),
  `patches/`, `launcher/` (módulos Python do port, fonte, ícones).
- **Arte do mantenedor** (`public/art/`: fundo/logo/mp3/videolauncher.mp4): GITIGNORED —
  incluir no instalador **exige autorização de redistribuição** (decisão pendente do
  mantenedor; sem ela, o instalador usa fallback visual embutido).

## 3. Bloqueios técnicos atuais (a resolver ANTES do instalador)

1. **`Command::new("python")` em `lib.rs`** (worker e worker morto/renascimento): assume
   Python no PATH. Resolver: variável de resolução `GOW3_CINEMATIC_PYTHON` com fallback
   `<exe_dir>\runtime\python\python.exe` → `python` (dev). Protocolo stdin/stdout
   persistente INALTERADO.
2. **`bridge_path()` caminha a árvore de código-fonte**: hoje acha
   `launcher/cinematic/bridge/launcher_bridge.py` pelos ancestrais do exe (ou
   `GOW3_CINEMATIC_BRIDGE`). Resolver: fallback adicional `<exe_dir>\bridge\launcher_bridge.py`
   antes da varredura (layout instalado) — mantém o comportamento dev.
3. **cwd do worker**: a ponte roda com cwd = raiz do port (ancestrais da bridge) — no
   layout instalado isso continua válido (bridge fica sob a raiz). `PORT_DIR`,
   `find_tool` (procura `bin/` antes de `out/`) e `run_command()` (Python em uso =
   `sys.executable` = runtime privado) já se comportam corretamente FORA do modo FROZEN —
   a ponte usa a biblioteca NÃO congelada, então **PyInstaller não é necessário** e os
   reinícios internos (`run.py --after` re-executado pelo jogo) continuam funcionando com
   o mesmo interpretador.
4. **Dados graváveis**: `DATA_DIR = env GOW3_DATA_DIR || PORT_DIR`. Com instalação em
   `%LOCALAPPDATA%` tudo é gravável e o modo portátil do port é preservado. Alternativa
   (instalação em Program Files) exigiria redirecionar `GOW3_DATA_DIR` — NÃO recomendada.
5. **Sombreamento de Python**: se o usuário tiver Python global, o runtime privado ainda
   deve vencer (ordem de resolução do item 1) para evitar mistura de versões/Pillow.

## 4. Política de preservação de dados (atualização/desinstalação)

- **Nunca apagar**: `data\` (user/saves, backups, out, gow3.ini, mods, mods.json,
  patches.json, caches), `settings.json` em `%APPDATA%\gow3-launcher`, e a pasta do jogo
  externa. NSIS: seção de dados declarada sem `/REBOOTOK`, `uninstaller` remove SOMENTE
  os arquivos instalados pelo manifesto (lista explícita — nada de `RMDir /r` na raiz de
  dados), atualização = sobreposição dos imutáveis preservando os graváveis (mesma
  semântica do refresh do `package.sh` oficial).
- **Ícone, nome exibido e versão**: `productName` "God of War III (Cinematic)",
  identificador `br.frosttys18.gow3.cinematic`; metadados de versão do instalador
  independentes (0.1.x) dos da app.
- **Permissões**: instalação per-user (`SetShellVarContext current`, sem admin) +
  bootstrapper WebView2 por usuário quando possível; fallback elevado apenas para o
  WebView2 quando o runtime pedir.

## 5. Teste futuro (máquina limpa — critérios de aceite)

VM Windows 11 NOVA, sem Python/MSYS2/Rust/Node/Git/checkout: instalar o NSIS →
(1) abre sem janela de console; (2) worker persistente sobrevive (uma alteração de
configuração = 0 processos novos); (3) JOGAR com pasta de jogo externa válida;
(4) fim da sessão volta a interface sem polling; (5) anisotropia/vibração/glyphs/F12
aplicam; (6) Discord ausente; (7) desinstalar preserva saves/settings/pasta do jogo;
(8) atualização por cima preserva dados. Sem jogo real: os itens 3-5 com processo
substituto; o jogo real é teste manual do mantenedor.
