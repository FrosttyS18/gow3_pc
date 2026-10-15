# God of War III — Cinematic Launcher (M1)

React + TypeScript + Tauri 2 sobre a lógica real do port: **nenhuma regra do port é
reimplementada em TypeScript/Rust**. A ponte `bridge/launcher_bridge.py` importa
`gow3_launcher_win.py` como biblioteca (o módulo é importável sem Tk: as classes recebem
os módulos gráficos como argumento) e responde JSON sobre stdin/stdout.

## Rodar (desenvolvimento)

```bash
cd launcher/cinematic
npm install
npm run tauri dev      # janela real (precisa de Rust/MSVC)
npm run dev            # preview no navegador com mock (não toca em configuração alguma)
```

## Build de teste

```bash
npm run tauri build -- --no-bundle   # exe em src-tauri/target/release/
```

## Arte local (NÃO versionada)

`public/art/` está no `.gitignore`: os exports do Figma do mantenedor, a faixa de música e
o vídeo de fundo (bg-launcher.png, logo-gow-3.png, intro_launcher.mp3/ambient.mp3,
videolauncher.mp4) são material licenciado ou pessoal — copie-os manualmente para
`public/art/` antes de rodar/empacotar. Sem eles o launcher usa o fundo em gradiente, a
imagem estática (fallback do vídeo) e o título tipográfico de reserva (nada de arte
aleatória). O vídeo de fundo (H.264 1920×1080) roda mudo em loop atrás da interface;
em falha ou ausência, a imagem original assume automaticamente.

## Música ambiente

O arquivo padrão é `public/art/ambient.mp3` (ou `intro_launcher.mp3`); o seletor (ícone de
pasta) permite escolher qualquer MP3 local — o caminho é persistido em
`settings.json` (`ambient_file`), o volume em `ambient_volume` e o mute em `ambient_muted`.
Ao clicar JOGAR a música faz fade-out de 2s sem bloquear a inicialização. O arquivo nunca
é enviado ao repositório nem embutido no pacote.

## Contratos preservados

- `settings.json` / `gow3.ini` / `mods.json` / `patches.json` só são escritos pelas
  próprias rotinas do launcher original (`save_ini` preserva comentários e chaves de
  terceiros; `set_ini`/`set_app` recusam chaves fora do contrato).
- JOGAR executa `run.py` exatamente como o botão PLAY do Tkinter (`game_environment`,
  `run_command`, cwd do port, processo destacado); o estado (preparando/executando/erro)
  vem do processo real (PID) e do log em `%TEMP%/gow3-cinematic-run.log`.
- Permissões Tauri mínimas (`capabilities/default.json`): janela; sem shell, sem fs,
  sem http. O diálogo de música fica no lado Rust; o áudio local é lido como data URL
  limitada a MP3 ≤ 48 MB.
- O launcher Tkinter continua presente e é o fallback oficial até a paridade M5.

## Testes da ponte

```bash
python -m unittest discover -s launcher/cinematic/tests -v   # a partir da raiz do repo
```

Fixtures 100% temporárias (`APPDATA`/`GOW3_DATA_DIR`/`GOW3_CONFIG` apontando para um
diretório descartável) — as configurações reais do mantenedor nunca são tocadas.

## Decisões do M1

- React Bits AVALIADO e não incorporado (licença MIT + Commons Clause no registry —
  ambiguidade de redistribuição no fork GPL); o comportamento visual do botão JOGAR e dos
  hovers é implementação original em CSS puro, sem dependências.
- Menu vertical fiel ao Figma (Display…Log); a página Display tem controles REAIS
  (modo de exibição, resolução de renderização, FPS do motor, limite de quadros); as
  demais páginas chegam no M2 e assim dizem na tela — nenhum controle fictício.
