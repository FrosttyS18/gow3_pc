# CONTRATO DO LAUNCHER CINEMATOGRÁFICO — v2.0 (2026-10-14)

**Este documento é a fonte ÚNICA de verdade para a estrutura, navegação e comportamento
do launcher React+Tauri. Upstream (launcher Tkinter do Felipe) fornece FUNCIONALIDADES
e COMPATIBILIDADE — NUNCA layout, navegação ou UX. Nenhuma skill, documento ou agente
pode sobrepor este contrato sem decisão explícita do mantenedor.**

## 1. IDENTIDADE

- O launcher cinematográfico é um projeto visual PRÓPRIO derivado do Figma do mantenedor.
- Composição: Kratos à esquerda (arte 1920×1080 cover), coluna direita escurecida,
  logo topo-direita (eixo 88,8%), menu vertical, JOGAR inferior-direito, rodapé real.
- Viewport de referência: **1280×720** (escala 2/3 do Figma 1920×1080).

## 2. NAVEGAÇÃO (IDs imutáveis)

| Ordem | ID          | pt-BR       | English      | Função                          |
|-------|-------------|-------------|--------------|---------------------------------|
| 1     | display     | Tela        | Display      | Configurações de vídeo/janela   |
| 2     | graphics    | Gráficos    | Graphics     | Upscaling experimental          |
| 3     | performance | Desempenho  | Performance  | FPS, GPU, shaders               |
| 4     | game        | Jogo        | Game         | Cheats, pastas, saves, idioma   |
| 5     | patches     | Patches     | Patches      | Patches internos + externos     |
| 6     | mods        | Mods        | Mods         | Mods, ordem, presets            |
| 7     | controls    | Controles   | Controls     | Remapeamento teclado/controle   |
| 8     | advanced    | Avançado    | Advanced     | Launcher, arquivos, diagnóstico |
| 9     | log         | Registro    | Log          | Log de execução                 |
| —     | (ação)      | Música      | Music        | Toggle mute, NÃO é rota         |

**REGRAS INVARIÁVEIS:**
- Patches e Mods são PÁGINAS INDEPENDENTES (jamais juntar).
- Música é uma AÇÃO (aria-pressed), nunca recebe linha vermelha de seleção.
- IDs são estáveis; rótulos vêm do i18n por idioma.
- PROIBIDO usar chaves de gow3_lang que representam funcionalidades diferentes
  (ex.: "Mods & patches" para as duas rotas; "Gamepad names" para Controles).

## 3. TRADUÇÕES

- Mecanismo: `I18nContext` com tabelas de `gow3_lang.py` expostas pela ponte.
- Troca IMEDIATA (sem reload; página, scroll, música e estado preservados).
- Cada rótulo deve representar o SIGNIFICADO REAL do controle:
  - Restaurar ≠ Jogar; Atualizar ≠ Registro; Tela ≠ Display & FPS (são contextos diferentes).
- Nomes técnicos de patches externos ficam no idioma de origem.
- `ui_language` persiste em `settings.json`; `language` (idioma do JOGO) é separado.

## 4. GEOMETRIA (Figma 1280×720)

- Eixo central logo/menu/JOGAR: **88,8% da largura** (`--axis: 88.8%`).
- Menu: topo fixo 24%, gap 16,3px, `white-space: nowrap` (nenhum item quebra linha).
- Fonte: Segoe UI Light 300; normal 18,49px/22,67; hover/ativo 25,65px/32 (crescimento
  por font-size, SEM transform/scale — reflow dos vizinhos como o Figma).
- Hover ≠ seleção: hover = cresce + branco + brilho; seleção = cresce + branco + linha
  219×1px `linear-gradient(90deg,#000 0%,#D10000 52.4%,#000 100%)`.
- JOGAR: 186×46, r 3,3, fundo #0B0B0B, borda cinza, "Jogar" 21,6px leve, seta |→.
- Painel de vidro: 994×604, r 16, rgba(0,0,0,0.2), blur 12px.

## 5. COMPONENTES COMPARTILHADOS

- `Toggle`: 66×33, knob 26px com ARO escuro 1,5px; OFF = #000/#9F0000/seta→; ON = #9F0000/borda preta/seta←.
- `Dropdown`: 251×33, #000/#9F0000, lista estilizada (sem popup nativo), teclado completo.
- `Tooltip`: fundo #050404, borda #9F0000, r 5, 12px leve — NUNCA `title` nativo.
- `ActionButton`, `PathField`, `Field`, `Section`: tokens de `:root` (--field-*, --toggle-*).
- Sliders: trilha vermelha, thumb #9F0000 com aro branco.

## 6. COMPORTAMENTOS

### Música
- Volume FIXO 0.01; persiste SOMENTE `ambient_muted`.
- Ao clicar JOGAR: `gow3:stop-music` (pause DETERMINÍSTICO) ANTES de `bridge.play()`.
- Fade é cosmético; o silêncio é garantido por `pause()`.
- `mayPlay()`: só toca se !muted && fase !== preparing/running && janela visível.
- Nenhum callback tardio (pointerdown, restore, load) reinicia durante o jogo.

### JOGAR
- Validações do Tkinter (arquivos, atualização, Sc0, probe) com mensagens pt-BR.
- Monitor com exit code REAL; spawn falho = 127.
- Estados: disponível/preparando/executando/erro (com código + última linha do log).
- Supervisão: Windows Job Object KILL_ON_JOB_CLOSE (launcher morto = árvore morta).

### Home
- LIMPA: só arte, logo, menu, JOGAR, rodapé, controles de janela e Música no menu.
- NENHUM formulário, painel, seletor ou atalho na Home.
- Atalhos da Home do Tkinter: PROIBIDO migrar (decisão definitiva do mantenedor).

## 7. COMPATIBILIDADE COM O BACKEND

- A ponte Python importa `gow3_launcher_win` como BIBLIOTECA (sem Tk).
- Chaves/listas/valores vêm SEMPRE do backend (nada inventado no frontend).
- Patches: `_resolve_patches_dir` com fallback para o pacote em Downloads.
- Persistência: settings.json / gow3.ini / mods.json / patches.json / mods_presets.json.

## 8. SUPERVISÃO DE PROCESSOS

- Job Object KILL_ON_JOB_CLOSE vitalício do processo Tauri.
- Cada ponte Python associada ao Job ANTES do pedido chegar ao stdin.
- Monitor → run.py → gow3-probe → TODOS os filhos herdam o Job.
- Launcher morto (X, Alt+F4, taskkill, crash) = árvore morta pelo kernel.
- `close_on_play`: OCULTA a janela (não fecha — Job mataria o jogo); sai ao fim.

## 9. REGRA DE UPSTREAM (PERMANENTE — decisão do mantenedor 2026-10-14)

**ATUALIZAÇÃO DO MOTOR NÃO É REDESIGN DO LAUNCHER.**

O projeto acompanha as atualizações técnicas estáveis de FelipePrado0/gow3_pc.

**Upstream FORNECE:** motor, runtime, scripts, patches, correções, compatibilidade e novas funcionalidades.
**Upstream NUNCA FORNECE:** layout, navegação, organização de páginas ou componentes visuais do launcher.

- Ao integrar: preservar integralmente o design e a navegação; adaptar somente as integrações.
- Não copiar o layout do Tkinter nem manter controles para funções que o upstream desativou.
- Validações automatizadas priorizam comportamento técnico e integridade dos dados.
- O mantenedor faz o aceite visual e os testes de interação manual.
- Integração em branch isolada com o protocolo de auditoria existente (exceção blob-provada + APPROVED_UPSTREAM na main).
- PRs de upstream que tocarem `launcher/cinematic/**` devem ser BLOQUEADOS e exigir
  justificativa + aprovação visual específica do mantenedor.
- Nenhuma substituição de UI, nenhum bypass, nenhum merge automático.

**Próxima versão técnica:** windows-v2.2.0, commit af5930a0e3bb6bd257563d0bfd6fa09210a78310.
**Prioridades:** compatibilidade, novas funcionalidades, gravação segura de configurações, patches obrigatórios, inicialização do jogo e gerenciamento de processos.

## 10. TESTES ANTIRREGRESSÃO

Ver `launcher/cinematic/tests/test_ui.py` — CDP na janela real Tauri com fixtures.
Um build TypeScript verde NÃO substitui estes testes.
