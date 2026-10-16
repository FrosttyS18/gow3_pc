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
%LOCALAPPDATA%\gow3-cinematic\            (gravável — sem exigir admin; raiz técnica do port)
├── gow3-cinematic.exe                    app Tauri (frontend embutido)
├── launcher\cinematic\bridge\launcher_bridge.py   ponte (worker persistente)
│   └── public\art\                       música/arte autorizados (NÃO embutidos no exe)
├── launcher\gow3_launcher_win.py, gow3_lang.py, gow3_vulkan.py, gow3.ico, gow3.png, gowfont.ttf
├── runtime\python\                       python embeddable + Pillow + iced_x86 (PRIVADO)
├── run.py, scripts\, patches\            preparo/execução oficiais do port (intocados)
├── bin\gow3-probe.exe, gow3-gpu-capabilities.exe, *.dll   (DLLs CLANG64 via ldd)
└── user\, out\, gow3.ini, mods\ …        dados graváveis do usuário (DENTRO da raiz)
```

A hierarquia `launcher/cinematic/bridge` é PRESERVADA intacta: os caminhos relativos
existentes continuam válidos SEM qualquer mudança no backend — o Python resolve
`Path(__file__).resolve().parents[2]` (→ `launcher/`) e o Rust `bridge.ancestors().nth(3)`
(→ raiz da instalação), ambos naturalmente neste layout. Nenhum fallback novo para a
ponte é necessário; `GOW3_CINEMATIC_BRIDGE` (env) continua disponível para casos especiais.

A pasta do JOGO permanece externa, escolhida pelo usuário e persistida em
`settings.json` — o instalador NUNCA a toca e NUNCA inclui `eboot.bin`, `sce_module`,
`sce_sys`, dumps, saves, caches de shader ou qualquer conteúdo proprietário do jogo
(lista de proibidos idêntica à do `packaging/windows/package.sh` oficial).

## 2. Manifesto preliminar de runtime (dependências EFETIVAS verificadas)

- **App Tauri**: `gow3-cinematic.exe` (frontend embutido no binário; CSP com
  `media-src 'self' data: blob:`). Requer **WebView2 Runtime** — o bundle NSIS do Tauri
  anexa o bootstrapper oficial (baixa/instala se ausente; já configurado em
  `tauri.conf.json` → `bundle.targets: ["nsis"]`).
- **Python**: dependências de terceiros verificadas = **Pillow** (`PIL` — glyphs,
  ícones, screenshots) e **iced_x86** (desmontagem — referência de compatibilidade do
  empacotamento oficial, que a inclui como hidden import). Runtime privado =
  "Windows embeddable Python 3.12" (~11 MB; distribuição SEM pip/ensurepip) + wheels
  de Pillow e iced_x86 desempacotados em `runtime\python\site-packages\`, com
  `python312._pth` importando `site-packages` e a raiz da instalação (módulos oficiais
  e ponte).
- **Binários nativos do port**: `gow3-probe.exe`, `gow3-gpu-capabilities.exe`
  (`gow3-play.exe` é do fluxo Tk, não usado pela ponte) + TODAS as DLLs que carregam da
  toolchain CLANG64 (SDL3, FFmpeg, loader Vulkan etc.) — enumerar com `ldd` exatamente
  como `packaging/windows/package.sh` faz; `llvm-strip --strip-debug` nos exes.
- **Recursos oficiais**: `run.py`, `scripts/` (inclui `discord_presence.py` e
  `guest_memory.py` — blob-idênticos; Discord permanece DESATIVADO por design),
  `patches/`, `launcher/` (módulos Python do port, fonte, ícones).
- **Mídia embutida vs. em disco**: o vídeo, a imagem de fallback e o logo são EMBUTIDOS
  no exe Tauri (frontendDist) e funcionam sempre. A MÚSICA não é embutida:
  `music_state()` procura o padrão em `<DATA_DIR>/launcher/cinematic/public/art/` (e o
  seletor persiste `ambient_file` em settings.json) — o estágio inclui o MP3 autorizado
  em `launcher/cinematic/public/art/`.
- **Arte do mantenedor** (`public/art/`: fundo/logo/mp3/videolauncher.mp4): GITIGNORED —
  incluir no instalador **exige autorização de redistribuição** (decisão pendente do
  mantenedor; sem ela, o instalador usa fallback visual embutido e vem sem música).

## 3. Bloqueios técnicos atuais (a resolver ANTES do instalador)

1. **`Command::new("python")` em `lib.rs`**: assume Python no PATH. Resolvido no PR de
   código `fix/dist-runtime`: ordem `GOW3_CINEMATIC_PYTHON` (env) →
   `runtime\python\python.exe` nos ancestrais do exe (PRIORIDADE sobre qualquer Python
   global) → `python` SOMENTE quando a ponte for encontrada em árvore de dev. Em
   distribuição sem o runtime privado: erro EXPLÍCITO, nunca o Python do usuário.
   Protocolo stdin/stdout persistente INALTERADO.
2. **`bridge_path()`**: NENHUMA mudança necessária — a varredura por ancestrais acha
   `launcher/cinematic/bridge/launcher_bridge.py` no layout instalado (hierarquia
   preservada, ver seção 1).
3. **cwd do worker**: a ponte roda com cwd = raiz do port (ancestrais da bridge) — no
   layout instalado isso continua válido (bridge fica sob a raiz). `PORT_DIR`,
   `find_tool` (procura `bin/` antes de `out/`) e `run_command()` (Python em uso =
   `sys.executable` = runtime privado) já se comportam corretamente FORA do modo FROZEN —
   a ponte usa a biblioteca NÃO congelada, então **PyInstaller não é necessário** e os
   reinícios internos (`run.py --after` re-executado pelo jogo) continuam funcionando com
   o mesmo interpretador.
4. **Dados graváveis**: `DATA_DIR = env GOW3_DATA_DIR || PORT_DIR` — nada é configurado
   automaticamente pela existência de pastas. Com instalação em `%LOCALAPPDATA%` o
   PORT_DIR É gravável e os dados (user/, out/, gow3.ini, mods/, caches, screenshots em
   user/screenshots) são escritos DENTRO da raiz da instalação — mesma semântica
   portátil da distribuição zip oficial do upstream. O desinstalador remove SOMENTE os
   imutáveis do manifesto e PRESERVA esses graváveis (política da seção 4). Instalação
   em Program Files (não recomendada) exigiria exportar GOW3_DATA_DIR no atalho.
5. **Sombreamento de Python**: o runtime privado tem PRIORIDADE absoluta (item 1); em
   distribuição, sem o runtime privado o launcher falha com erro explícito — nunca usa
   silenciosamente um Python global.

## 4. Política de preservação de dados (atualização/desinstalação)

- **Nunca apagar**: os dados graváveis DENTRO da instalação (`user/` com saves,
  screenshots e caches, `out/`, `gow3.ini`, `mods/`, `mods.json`, `patches.json`,
  backups), `settings.json` em `%APPDATA%\gow3-launcher`, e a pasta do jogo externa.
  NSIS: `uninstaller` remove SOMENTE os arquivos instalados pelo manifesto (lista
  explícita — nada de `RMDir /r` na raiz), atualização = sobreposição dos imutáveis
  preservando os graváveis (mesma semântica do refresh do `package.sh` oficial);
  nenhuma migração sobrescreve dados existentes.
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
