# gow3-dev-guard — harness determinístico de segurança e auditoria (Fase 1)

Plugin do ZCode versionado no repositório (`zcode/gow3-dev-guard`), com marketplace local em
`zcode/marketplace.json`. Sem código do jogo, sem rede, sem LLM: toda decisão é regex,
caminho ou consulta git avaliada em código (determinismo auditável em `tests/test_guard.py`).

## Componentes

| Arquivo | Papel |
|---|---|
| `.zcode-plugin/plugin.json` | Manifest oficial (nome `gow3-dev-guard` v0.1.0; apenas hooks) |
| `hooks/hooks.json` | Registro dos eventos `SessionStart`, `PreToolUse` (matcher `Bash\|Edit\|Write\|ApplyPatch`) e `Stop`, hooks `type: process` (sem shell, portáveis no Windows) |
| `hooks/guard_common.py` | Políticas compartilhadas (tabelas de padrões, caminhos protegidos, I/O) |
| `hooks/pre_tool_use.py` | Guarda de operações (ver política abaixo) |
| `hooks/stop_guard.py` | Validação do `ZCODE FINAL REPORT CONTRACT` com proteção anti-loop |
| `hooks/session_context.py` | Contexto de sessão (repo/branch/HEAD/baseline + restrições); somente leitura |
| `tests/test_guard.py` | 53 testes determinísticos com eventos simulados |

Contrato de I/O com o host (documentado nos guias oficiais do ZCode): payload JSON no stdin;
saída por **exit codes** — `0` passa, `2` bloqueia (motivo no stderr); stdout vazio exceto no
`SessionStart`, que emite `{"additionalContext": "..."}` (chave reconhecida). JSON inválido ou
campos ausentes ⇒ **fail-open** (exit 0 + aviso no stderr): um payload ruim nunca quebra a sessão.

## Política do PreToolUse

**Bloqueia (exit 2):**
- Destrutivos: `push --force/--force-with-lease`, `reset --hard`, `clean -f*`, `branch -D`,
  `rm -rf` sobre trabalho protegido/dados do usuário (por argumento inteiro: `src`, `gpu`,
  `scripts`, `patches`, `launcher`, `docs`, `zcode`, `tests`, `user`, `sce_module`, `sce_sys`,
  `savedata`, `eboot.bin`, configs; `~`/`$HOME`/`C:\`/`Windows`), `format`/`mkfs`/`shutdown`/
  `diskpart`/`rd /s`/`del /s`, fork bomb, `taskkill`/`Stop-Process` no jogo.
  Saídas reconstruíveis (`out/`, `dist/`, temporários) seguem liberadas.
- `main`: `checkout`/`switch main`, `push ... main`, qualquer mutação git (`commit|merge|rebase|
  reset|revert|cherry-pick|tag|push|pull`, inclusive após `&&`/`;`) e qualquer escrita dentro do
  repo enquanto HEAD estiver na `main` (verificado por `git rev-parse`).
- Motor e contratos (escrita Edit/Write): `src/`, `gpu/shadps4/`, `gpu/patches/`,
  `gpu/dlss_bridge/`, `gpu/shim/gow3gpu.cpp`, `patches/`, `scripts/`, `run.py`, `run.sh`,
  `third_party/`, `gpu/third_party/`, `.git/`.
- Proprietários (em qualquer caminho): `eboot.bin`, `sce_module/`, `sce_sys/`, `*.pkg`, `*.prx`,
  `*.sprx`, `savedata/`; e `git add` desses, `git add -f` e `GOW3_FORCE_PATCHES≠0`.

**Permite:** leituras/pesquisas (Read/Grep/Glob nem entram no matcher), `git status/log/diff`,
`checkout -b`, commit/push em branches de trabalho, build/testes (`build.sh`, `ninja`, `cmake`,
`unittest`), `rm -rf out/ dist/`, e escritas em `docs/`, `launcher/`, `tests/`, `zcode/`,
`packaging/` e `gpu/shim/gow3_overlay.cpp` (escopo aprovado da tela de saves).

## Stop (relatório final) e anti-loop

Valida no transcript (JSONL): último texto do assistente com um único bloco ```text contendo o
cabeçalho `GOW3 — ZCODE REPORT` (aceita `—` ou `-`), as seções TASK/GIT/BASELINE/CHANGES/
VALIDATION/AUDIT GATE/FINAL STATUS/NEXT e cada campo obrigatório com valor não vazio
(`[ \t]` após o dois-pontos — `\s*` engoliria a quebra de linha e aprovaria campo vazio);
`FINAL STATUS` ∈ {READY_FOR_REVIEW, BLOCKED, FAILED}. Falha ⇒ exit 2 com a lista exata dos
defeitos. A validação é **estrutural**: prova presença/completude, não a verdade dos logs
(código-review/CI continuam dons da auditoria de conteúdo).

Anti-loop triplo: `stop_hook_active` (host) ⇒ passa; contador por sessão sob
`${ZCODE_PLUGIN_DATA}` bloqueia no máximo 2× (na 3ª passa avisando); relatório válido zera o
contador. Transcript ilegível/sem mensagem do assistente ⇒ fail-open.

## Ativação no ZCode (ação única do usuário)

O plugin fica registrado no repositório; a instalação é uma ação de interface que só o usuário
pode fazer (não há CLI de instalação; modificar `~/.zcode/cli/config.json` à mão não é suportado):

1. ZCode → **Settings → Plugin Management → Discover**.
2. Botão **+** → **local directory** → selecionar `C:\gow3\gow3_pc\zcode`
   (contém o `marketplace.json` do marketplace `gow3-local`).
3. No cartão **gow3-dev-guard**, clicar **Get/Install** (plugins novos nascem habilitados).
4. Abrir o detalhe do plugin e conferir os 3 hooks listados como *runnable*.
5. Reiniciar/abrir a sessão neste workspace. Verificação: `~/.zcode/cli/config.json` passa a
   conter `gow3-dev-guard@gow3-local` em `plugins`; um comando de teste como
   `git checkout main` deve ser bloqueado com a mensagem `gow3-dev-guard: BLOCK: ...`.

Enquanto o passo 2–4 não for feito, os hooks não disparam no host — os scripts, porém, já estão
válidos e testados sob o contrato oficial (invocação, exit codes, schema do manifest/hooks).

## Testes

```
python zcode/gow3-dev-guard/tests/test_guard.py -v     # 53 testes, eventos simulados
```

Cobertura exigida pela Fase 1: bloqueio de main (checkout/switch/push/commit-while-on-main,
escrita enquanto na main, comando composto `cd && git commit`), destrutivos (force-push,
reset --hard, clean, branch -D, rm -rf protegido, format/shutdown/rd/del, fork bomb, taskkill do
jogo), críticos (runtime, shadPS4, patch XML/whitelist, scripts/, run.py, .git, proprietários,
git add -f/FORCE_PATCHES), permissões seguras (leitura, build/testes, branches de trabalho,
escritas no escopo de UI, rm -rf out/dist), Stop (relatório ausente/incompleto/campo vazio/sem
bloco ⇒ bloqueia com defeitos nomeados; válido passa; ASCII/UTF-8 no cabeçalho), anti-loop
(stop_hook_active, autolimite na 3ª parada, reset por relatório válido), robustez (JSON
inválido, `{}`, tool_input ausente/não-objeto, transcript ilegível — sempre exit 0, nunca crash)
e declaração (manifest/marketplace/hooks.json conformes ao schema oficial). Resultado real da
última execução: **53/53 PASS** (log: `python ...test_guard.py -v` — registrar no relatório).

## Fases futuras (planejadas, NÃO implementadas)

- **Skill `gow3-gamer-ui`** — conhecimento especializado em UI de jogos cinematográfica
  (direção de arte GOW III: paleta cinza-ebra/sangue, tipografia serifada, motion),
  para o launcher Tauri pt-BR e a tela de saves ImGui; guidelines anti-"dashboard genérico".
- **Skill `gow3-code-audit`** — checklist de revisão por escopo (launcher/saves), diffs
  proibidos (motor), regressões contra `docs/DEV-BASELINE.md`, formato de evidências.
- **Subagentes** — pesquisa (Explore) e auditoria de PR com veredito reproduzível; a aprovação
  final permanece com resultados determinísticos, nunca "parece correto" de LLM.
- **MCPs** — Context7 (docs de Tauri/React/ImGui) e Playwright (testes E2E do launcher),
  cada um só após verificação de compatibilidade com o host instalado.
- **Memória de projeto** — fatos não-derivable do repo (ambiente da máquina, decisões do
  mantenedor) já usada; a skill/harness complementa com estado de fase.

Extensão natural deste plugin: `PostToolUse` para invalidar cache de verificação e gates de CI
local (build/testes) antes de commit — a definir nas próximas fases.
