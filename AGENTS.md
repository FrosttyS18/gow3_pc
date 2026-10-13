# AGENTS.md — FrosttyS18/gow3_pc

## Missão e responsabilidades
Este repositório é um fork do port comunitário de God of War III Remastered para Windows. O objetivo é criar uma experiência visual própria e de alta qualidade no launcher e, posteriormente, nas interfaces adicionadas ao jogo, preservando os contratos e a estabilidade do port.

O ZCode é o agente executor: inspeciona código, executa comandos, prepara dependências, implementa, testa, registra evidências e corrige falhas. O usuário faz a validação visual/funcional final; não delegue a ele comandos de desenvolvimento ou a investigação de erros que o agente pode realizar.

## Escopo definitivo da UI (decisão do mantenedor, 2026-10-12)
1. **Launcher Windows:** redesign completo, moderno, cinematográfico e exclusivo de God of War III Remastered, preservando todas as funções atuais e adotando português do Brasil. O launcher NÃO será biblioteca de jogos, loja, dashboard administrativo nem plataforma com funcionalidades fictícias.
2. **Tela de saves in-game:** personalização visual da interface de salvar/carregar em Dear ImGui, sem modificar o backend nem comprometer a compatibilidade.
3. **FORA do escopo, definitivamente:** o menu in-game aberto por Insert/R3+L2. Não redesenhar, refatorar nem modificar.
Toda implementação depende de aprovação posterior do mantenedor.

## Mapa canônico do código
- `launcher/gow3_launcher_win.py` — launcher Windows atual em Python/Tkinter: configurações, navegação, iniciar jogo, diagnóstico, mods, patches, controles, backups e atualizações.
- `launcher/gow3_lang.py` e `launcher/button_icons.py` — traduções e ícones de controle.
- `run.py` — preparo e inicialização Windows; opções por variáveis de ambiente.
- `scripts/` — preparação, link, patches, opções gráficas, mods e backup de saves.
- `gpu/shim/gow3_overlay.cpp` — interfaces in-game Dear ImGui; menu Insert, HUD e `ChoiceBox()` (lista visual de saves).
- `src/runtime_services.c` — contrato do diálogo de save do PS4, incluindo `save_open`, `save_status` e `save_result`.
- `src/runtime_savedata.c` — implementação de armazenamento e metadados de saves.
- `gpu/shadps4/` e `gpu/shim/gow3gpu.cpp` — infraestrutura gráfica/execução de alto risco; fora de escopo para trabalhos de UI, salvo autorização expressa.
- `packaging/windows/README.md`, `build.sh` e `packaging/windows/package.sh` — build e empacotamento.
- `tests/` — testes existentes; inventariar antes de adicionar ou alterar testes.
- `docs/gow3/ROADMAP.md` — documentação histórica do port upstream, não prova de validação atual do fork.

Leia os arquivos reais antes de afirmar contratos ou propor mudanças. Não trate esta descrição como substituta da inspeção.

## Regras inegociáveis de segurança do projeto
1. **Não modificar diretamente a branch `main`.** Criar branch de trabalho `feat/*`, `fix/*` ou `chore/*`; jamais fazer force-push, reset destrutivo, limpeza indiscriminada ou merge automático.
2. **Preservar o port funcional.** Alterações de UI não autorizam refatorar runtime, emulação de serviços do PS4, Vulkan, shadPS4, shaders, patches, memória, áudio, threads, save backend, compilação ou inicialização.
3. **Não relaxar controles de segurança ou compatibilidade.** Não habilitar `GOW3_FORCE_PATCHES`, ignorar comparações de bytes/hash, desativar validações ou marcar problemas como corrigidos só porque o launcher abriu.
4. **Jamais versionar ou redistribuir arquivos proprietários do jogo:** dumps, `.pkg`, `eboot.bin`, `sce_module`, `sce_sys`, saves reais, chaves, assets licenciados não permitidos. Não copiar arquivos pessoais para o repositório.
5. **Não excluir dados locais.** Preservar `user/`, `out/`, `gow3.ini`, mods, perfis, backups, shader cache, logs e `%APPDATA%/gow3-launcher/settings.json`; operações de limpeza precisam de prova de escopo, cópia segura e autorização específica quando destrutivas.
6. **Não inventar evidências nem resultados de testes.** Um teste não executado é NOT_RUN/BLOCKED, nunca PASS. Testes que já falhavam na baseline devem ser classificados separadamente de regressões.
7. **Evitar testes visuais repetitivos e loops de processo.** Nunca ficar abrindo e fechando o jogo indefinidamente. Usar testes unitários e logs primeiro; limitar tentativas reais, encerrar somente processos iniciados pelo próprio agente, verificar prontidão da janela antes de capturas e registrar o resultado.
8. **Manter alterações pequenas e reversíveis.** Sem reformatar arquivos inteiros, introduzir abstrações sem necessidade, adicionar dependências sem justificativa ou fazer migrações silenciosas.
9. **Atualizações upstream são explícitas e auditadas.** Nunca atualizar automaticamente o fork durante uma tarefa de UI. Comparar os commits/arquivos, testar em branch separada, preservar nossas modificações e só então considerar merge.
10. **Respeitar GPL-2.0 ou posterior e licenças de dependências.** Não incorporar artes proprietárias em builds redistribuídos sem autorização.

## Contratos que precisam sobreviver a qualquer redesign
- Reconhecimento de pasta com `eboot.bin`, `sce_module` e `sce_sys/param.sfo`, ID `CUSA01623`, versão `01.02`.
- Seleção segura de patches: os patches de 120/240 FPS existentes exigem o executável validado, SHA-256 `d85c8135d330c3b601bf5dc3f1dd86bd6119fb8a9fce372bed2c9785f9a79299`. Não alterar a whitelist nem forçar execução em outro binário.
- Paridade funcional do launcher: Play/Play direto, Display, Performance, Game, Patches, Mods, Controls, Advanced, Log, seleção de pastas, backups, idiomas, tratamento de erros e atualização.
- Persistência compatível com os formatos existentes: `gow3.ini`, `%APPDATA%/gow3-launcher/settings.json` e arquivos dentro de `user/`. Nada de perder configurações/saves em uma troca de UI.
- Diálogos in-game: seleção de save, "New save", imagem de cada slot, foco, cancelar/confirmar, teclado, D-pad e botões de controle, mapeamento de resultado PS4. Preservar backend; mudar o desenho somente quando esse escopo for aprovado.
- Diagnóstico: informar com precisão quando os patches não são aplicáveis; não mascarar erros, não gerar logs falsos, não travar o launcher ao fechar/reiniciar.
- Testes não podem depender de um dump real do jogo em CI. Fixtures sintéticas e mocks devem ser preferidos. A execução real é um smoke test local separado e não pode ser declarada sem ocorrer.

## Fluxo obrigatório do agente
1. **Investigar:** confirmar fork, `origin`/`upstream`, branch, HEAD, submódulos, alterações locais e arquitetura real. Identificar riscos e contratos antes de alterar.
2. **Baseline:** executar testes existentes adequados à plataforma, registrar contagens PASS/FAIL/SKIP/BLOCKED e erros já presentes. Em Windows usar a toolchain MSYS2 CLANG64 documentada; não declarar que todos os testes C/Linux executam nativamente no Windows.
3. **Especificar:** para cada mudança, escrever propósito, arquivos tocados, contratos preservados, testes de aceite, riscos e plano de reversão. Se houver troca de stack do launcher (ex.: React/Tauri), apresentar uma comparação técnica e plano de integração/empacotamento **antes** de implantar.
4. **Implementar isoladamente:** uma mudança por vez, na branch adequada, preservando APIs, dados e lógica de execução. Nunca alterar código de motor para compensar erro visual.
5. **Validar mecanicamente:** testes automatizados pertinentes, verificação de build e empacotamento quando disponíveis, diff revisado, comportamento anterior intacto; testes in-game reais somente quando o ambiente permitir.
6. **Entregar evidências:** listar arquivos alterados, testes efetivamente executados e contagens, limitações, riscos restantes, commit/branch e passos mínimos que cabem ao usuário apenas para aceite visual.

Não criar múltiplos arquivos Markdown de estado concorrentes. A referência permanente de comportamento do agente é este `AGENTS.md`. O bootstrap pode registrar uma baseline verificável em um único `docs/DEV-BASELINE.md`, com data, commit e comandos/resultados.

## Engenharia de UI
- Launcher atual: Python/Tkinter. O alvo é visual premium com navegação e UX modernas, em português do Brasil, mas **a escolha entre evoluir Tkinter e migrar para React/Tauri exige proposta arquitetural**. Se houver migração, criar uma camada de integração explícita para as funcionalidades existentes, sem depender de scraping da interface antiga.
- Tela de saves in-game: Dear ImGui/C++ em `gpu/shim/gow3_overlay.cpp` (`ChoiceBox()`/`TextEntryBox()`), personalização apenas visual; backend e entrada preservados. O menu Insert/R3+L2 (`Menu()`) está **definitivamente fora do escopo** — não modificar. Não assumir que uma UI React pode ser embutida diretamente no jogo sem nova integração.
- Manter UX de teclado/controle, acessibilidade funcional, foco e feedback de erro. Não criar controles sem ação real.
- Não remover funções pouco visíveis (logs, atualizações, opções avançadas, backups) só por simplificação estética.
- O `.gitignore` atual ignora `*.png` genericamente: qualquer novo asset necessário precisa de exceção explícita e licença verificada; nunca fazer `git add -f` indiscriminado.

## Automação e gates
- A fonte de verdade de PASS/FAIL deve ser processo determinístico (testes, análise estática, build, inspeção de artefatos), executável também fora do agente e, quando possível, em CI.
- Hooks são complementares, não substitutos de CI. No ZCode atual, hooks declarados no `<workspace>/.zcode/config.json` não são executados. Para eventos automáticos, usar configuração de usuário ou plugin com suporte documentado, validar disparos reais e evitar loops de Stop Hook.
- Subagentes podem pesquisar e revisar de forma independente; a aprovação final exige resultados reproduzíveis, nunca um simples "parece correto" de outro LLM.
- Sempre terminar cada tarefa com o **ZCODE FINAL REPORT CONTRACT** (seção abaixo). Nenhum PASS sem log ou comando correspondente.

## ZCODE FINAL REPORT CONTRACT (política obrigatória e permanente)

Toda tarefa concluída, interrompida ou bloqueada deverá terminar com um relatório técnico estruturado dentro de UM ÚNICO BLOCO DE CÓDIGO, utilizando Markdown com identificador `text`.

Não apresentar o relatório final em tabelas Markdown, parágrafos dispersos ou listas fora do bloco.

O formato obrigatório é:

```text
╔══════════════════════════════════════════╗
║           GOW3 — ZCODE REPORT            ║
╚══════════════════════════════════════════╝

TASK
  Name:        <tarefa>
  Status:      <COMPLETED | BLOCKED | FAILED>

GIT
  Branch:      <branch>
  Commit:      <hash>
  Remote:      <SYNCED | LOCAL_ONLY | ERROR>

BASELINE
  Status:      <PASS | FAIL | NOT_RUN>
  Reference:   <commit de referência>

CHANGES
  Added:       <quantidade>
  Modified:    <quantidade>
  Removed:     <quantidade>
  Files:       <arquivos alterados>

VALIDATION
  Python:      <PASS / FAIL / ERROR / SKIP>
  Native:      <PASS / FAIL / BLOCKED>
  Build:       <PASS | FAIL | NOT_RUN>
  Package:     <PASS | FAIL | NOT_RUN>
  UI:          <PASS | FAIL | NOT_RUN>
  Runtime:     <PASS | FAIL | NOT_RUN>

AUDIT GATE
  Result:      <PASS | FAIL | BLOCKED>
  Regressions: <quantidade comprovada>
  Evidence:    <logs e caminhos verificáveis>

RISKS
  <problemas pendentes ou NONE>

FINAL STATUS
  <READY_FOR_REVIEW | BLOCKED | FAILED>

NEXT
  <próxima ação objetiva>
```

Regras do relatório:
- Sempre apresentar o relatório, inclusive quando a tarefa falhar.
- Não inventar números, logs ou resultados.
- Não usar PASS para testes não executados.
- Distinguir regressões de problemas preexistentes.
- Informar explicitamente quando o build não foi executado.
- Não declarar aprovação do usuário sem confirmação.
- Exibir o bloco de código como última seção da resposta.
- Não escrever explicações extensas depois do relatório.
- Manter exatamente o mesmo padrão entre tarefas.
