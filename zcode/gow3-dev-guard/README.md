# gow3-dev-guard — harness determinístico de segurança e auditoria

Plugin do ZCode versionado no repositório (`zcode/gow3-dev-guard`), com marketplace local em
`zcode/marketplace.json`. Sem código do jogo, sem rede, sem LLM: toda decisão é caminho
resolvido, regex ou consulta git somente-leitura avaliada em código
(`tests/test_guard.py`, 84 testes com eventos simulados).

**v0.2.0** — endurecimento após a auditoria independente do commit `7e85be1`
(branch `fix/gow3-guard-hardening`).

## Componentes

| Arquivo | Papel |
|---|---|
| `.zcode-plugin/plugin.json` | Manifest oficial (nome, versão, descrição; sem declaração redundante de hooks — `hooks/hooks.json` no local padrão é descoberto automaticamente) |
| `hooks/hooks.json` | `SessionStart`; `PreToolUse` com matcher `Bash\|Edit\|Write\|ApplyPatch\|MultiEdit`; `Stop`. Hooks `type: process` (sem shell). Nomes verificados no host instalado: as ferramentas de escrita expostas são `Edit`, `Write` e `Bash`; `ApplyPatch` é alias de `Write\|Edit` nos matchers e `MultiEdit` não existe nesta build (coberto por defesa) |
| `hooks/guard_common.py` | Políticas compartilhadas (tabelas, resolução de caminhos, consultas git) |
| `hooks/pre_tool_use.py` | Guarda de operações (fail-closed) |
| `hooks/stop_guard.py` | Validação do `ZCODE FINAL REPORT CONTRACT` com anti-loop |
| `hooks/session_context.py` | Contexto de sessão (repo/branch/HEAD/baseline + restrições); somente leitura |
| `tests/test_guard.py` | 84 testes determinísticos (inclui a classe `AuditRegressions`: as falhas da auditoria como regressões permanentes) |

Contrato de I/O com o host: payload JSON no stdin; decisão por **exit codes** (`0` passa,
`2` bloqueia com motivo no stderr); stdout vazio exceto `SessionStart`
(`{"additionalContext": ...}`).

## Política (v0.2.0)

**Fail-closed (auditoria, item 4):** o PreToolUse só vê ferramentas capazes de escrever;
payload inválido, `tool_input` ausente/não-objeto, sem `tool_name`, alvo não identificável,
repositório/branch indeterminável ou escrita não verificável ⇒ **bloqueio com motivo
específico**. Leituras seguras nunca chegam ao hook. `SessionStart`/`Stop` permanecem
fail-open (não escrevem e não podem travar a sessão).

**Exclusões destrutivas (item 1):** cada argumento de `rm -rf` é resolvido e normalizado
contra o diretório do evento (`payload.cwd`) e a raiz real do repo (`git rev-parse
--show-toplevel`). Bloqueia: `.`/`..`, a raiz do repo e qualquer ancestral dela, `.git`,
diretórios protegidos por caminho absoluto ou relativo (Windows `\` ou `/`), dados
pessoais/proprietários em qualquer local e o home do usuário. Libera **somente** locais
reconstruíveis autorizados (`out/`, `dist/`, `tmp/`, `__pycache__/`, `.pytest_cache/`,
`node_modules/`, `target/` — aninhados incluídos) e temporários externos (`Temp/tmp`).

**Ferramentas de escrita (item 2):** `Edit`/`Write` exigem caminho identificável (senão,
bloqueio). `ApplyPatch`/`MultiEdit` têm **todos** os arquivos analisados: `file_path`,
`path`, `files[]`, `patches[]`, `edits[]`, `operations[]` (com `new_path`/`dest_path`) e o
texto de patch (`*** Update File:`, `+++ b/`, `diff --git`).

**Bash além de blacklist (item 3):** extração determinística de alvos de escrita por
segmento de comando — redirecionamentos `>`/`>>`, `tee`, último argumento de
`cp/mv/install/rsync/shred`, `sed -i`, `truncate`, `dd of=` — cada alvo resolvido contra o
cwd do evento; PowerShell (`Set-Content`, `Out-File`, `Remove-Item`, ...) com caminho
irresolvível ⇒ bloqueio fail-closed. Git: `git add` inspeciona o **pathspec** e o
`--dry-run` (nunca escreve); `git commit` inspeciona `git diff --cached --name-only` e
bloqueia se algo protegido/proprietário estiver staged (também via `git -C`); mutações git
(`commit|merge|rebase|reset|revert|cherry-pick|tag|push|pull|stash`) em `main`/`master` ou
com branch indeterminável ⇒ bloqueio; `checkout --`/`restore`/`stash`/`git rm` protegidos.
Scripts arbitrários (`python x.py`, `bash x.sh`) seguem permitidos para build/testes; o
gate de staging no commit é o backstop determinístico contra qualquer escrita indireta.

**Motor/contratos/proprietários (como na Fase 1):** escrita bloqueada em `src/`,
`gpu/shadps4/`, `gpu/patches/`, `gpu/dlss_bridge/`, `gpu/shim/gow3gpu.cpp`, `patches/`,
`scripts/`, `run.py`, `run.sh`, `third_party/`, `.git`; e a qualquer `eboot.bin`,
`sce_module/`, `sce_sys/`, `*.pkg/*.prx/*.sprx`, `savedata/`. `git add -f` e
`GOW3_FORCE_PATCHES` bloqueados. Escopo de UI liberado: `docs/`, `launcher/`, `tests/`,
`zcode/`, `packaging/`, `tools/` e `gpu/shim/gow3_overlay.cpp` (tela de saves aprovada).

**Stop (item 5):** prioriza `last_assistant_message` do payload (campo oficial), com
fallback ao transcript JSONL; exige **um único** bloco ```text com o cabeçalho
`GOW3 — ZCODE REPORT`, as 9 seções (incluindo **RISKS**) e cada campo com valor não vazio
**dentro da própria seção** (`[ \t]` após o dois-pontos — `\s*` engoliria a quebra de
linha); `FINAL STATUS` ∈ {READY_FOR_REVIEW, BLOCKED, FAILED}. Anti-loop: `stop_hook_active`
passa; contador por sessão bloqueia no máximo 2× (o host limita continuações); relatório
válido zera o contador. Validação estrutural — não certifica veracidade dos logs citados.

## Ativação no ZCode (ação única do usuário)

1. **Settings → Plugin Management → Discover → +** → diretório local `C:\gow3\gow3_pc\zcode`.
2. Instalar **gow3-dev-guard** (novo, habilitado por padrão); conferir os 3 hooks *runnable*.
3. Nova sessão neste workspace. Teste: `git checkout main` deve ser bloqueado com
   `gow3-dev-guard: BLOCK: ...`.

Enquanto não instalado, os hooks não disparam no host (não declarar integração como PASS
sem teste com plugin realmente instalado).

## Testes

```
python zcode/gow3-dev-guard/tests/test_guard.py -v    # 84 testes
```

Red→green da correção: os 25 casos da auditoria foram escritos primeiro e falharam contra
a implementação vulnerável (28 FAIL com os ajustes de robustez/manifesto:
`guard-tests-RED.log`), depois passaram após as correções (84/84 OK:
`guard-tests-GREEN-FINAL.log`). Legítimas confirmadas: leitura/build/teste/edição do
launcher/harness, `rm -rf out|dist|__pycache__`, `git add`/`commit` de arquivos permitidos
(em repositórios temporários), PowerShell somente-leitura.

## Fases futuras (planejadas, NÃO implementadas)

Skill `gow3-gamer-ui` (UI cinematográfica GOW), skill `gow3-code-audit` (revisão/regressão),
subagentes de pesquisa/auditoria, MCPs Context7/Playwright (após verificação de
compatibilidade) e memória de projeto — a definir nas próximas fases.
