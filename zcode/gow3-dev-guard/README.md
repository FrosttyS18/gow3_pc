# gow3-dev-guard — harness determinístico de segurança e auditoria

Plugin do ZCode versionado no repositório (`zcode/gow3-dev-guard`), com marketplace local em
`zcode/marketplace.json`. Sem código do jogo, sem rede, sem LLM: toda decisão é caminho
resolvido, regex, consulta git somente-leitura ou diff real — avaliada em código.

**v0.5.0** — correção final do CI confiável (PR #1): auditoria disparada por
`workflow_run` (o workflow que audita é SEMPRE o do branch default — nenhum `pull_request`
nem `pull_request_target` no caminho crítico), superfícies de segurança por prefixo
(`.github/workflows/`, `zcode/`) com protocolo de aprovação por registro do mantenedor na
referência confiável, e 25 testes do Audit Gate.## Componentes

| Arquivo | Papel |
|---|---|
| `.zcode-plugin/plugin.json` | Manifest oficial (sem declaração redundante de hooks) |
| `hooks/hooks.json` | `SessionStart`; `PreToolUse` matcher `Bash\|Edit\|Write\|ApplyPatch\|MultiEdit`; `Stop`; hooks `type: process` |
| `hooks/guard_common.py` | Políticas compartilhadas (camada 1) |
| `hooks/{pre_tool_use,stop_guard,session_context}.py` | Hooks |
| `tools/audit_gate.py` | **Audit Gate** (camada 2) — diff real vs referência, escopo, submódulos, anti-autoenfraquecimento; exit 0/1/2 |
| `tests/test_guard.py` | 90 testes de eventos simulados (camada 1) |
| `tests/test_audit_gate.py` | 13 testes com repositórios descartáveis (camada 2) |
| `.github/workflows/guard-audit.yml` | CI: suíte do guard + audit gate em PRs contra `main` |

## CAMADA 2 — Audit Gate (v0.4.0, fonte confiável)

```
python zcode/gow3-dev-guard/tools/audit_gate.py [--repo DIR] [--ref REF] [--head COMMIT]
                                                [--upstream-exception FILE]... [--json]
```

**Fronteira de confiança:** quem aprova um PR nunca é o código do próprio PR. O CI
(`guard-audit.yml`, `pull_request_target`, `permissions: contents: read`) faz checkout da
**base protegida** (main), busca o head do PR **como dados** (objetos git, nada executado)
e roda o gate **da base** em modo commit-a-commit (`--head`); o worktree não influencia o
veredito. Os testes funcionais da branch rodam isolados no `guard-tests.yml`
(`pull_request`, somente leitura).

Verifica: escopo autorizado, caminhos protegidos, material proprietário (inclusive
untracked, modo worktree), ponteiros de submódulo (sujeira de build ignorada) e **deleção
de harness/CI** (nunca excepcionável).

**Integridade por classe** (`--head` ou worktree): *blocklists* (PROTECTED_PREFIXES,
PROPRIETARY_PATTERNS, MAIN_BRANCHES) — remover ⇒ FAIL; *allowlists* (AUTHORIZED_SCOPE,
TOP/NESTED_AUTHORIZED_RM, APPROVED_UPSTREAM) — adicionar ⇒ revisão da fonte de confiança;
qualquer outra mudança no verificador/hooks/testes do harness/workflows ⇒ **exit 3
REVIEW REQUIRED** — o gate jamais auto-aprova a si mesmo por comparação de tabelas.

**Exceção upstream (sincronizações futuras):** `--upstream-exception FILE` com
`{"tag": "windows-v2.1.7", "files": [...]}`. A tag precisa existir no registro fixado
(`APPROVED_UPSTREAM` no gate: `windows-v2.1.7` =
`b907d8a9f2324ba5f514fbfe7de803e027c6ca26` @ FelipePrado0/gow3_pc) e **cada arquivo
listado precisa ser blob-idêntico** ao commit aprovado — prova de conteúdo, não confiança
em nome de caminho. Proprietários, harness e CI nunca são excepcionáveis. Convencão CI:
declarações em `zcode/upstream-exceptions/*.json` no PR.

Exit codes: `0` PASS · `1` FAIL · `2` erro · `3` REVIEW REQUIRED (resolvido apenas por registro do mantenedor na referência confiável; nunca vira PASS sozinho). `--registry-file`
sobrescreve o registro apenas para testes/manutenção (o CI confiável nunca o passa).

## CI e proteção da main (v0.5.0)

- `guard-tests.yml` — evento `pull_request` (não privilegiado, `contents: read`):
  `test_guard.py` (90) e `test_audit_gate.py` (25) no merge ref do PR.
- `guard-audit.yml` — evento **`workflow_run`** (após `guard-tests` completar): a versão
  do workflow que executa é sempre a do **branch default** (documentação oficial: "this
  event will only trigger a workflow run if the workflow file exists on the default
  branch"). O PR não pode reescrever suas próprias instruções de auditoria — por isso não
  usamos `pull_request` (executa o workflow do PR) nem `pull_request_target` (funciona,
  mas é desencorajado pela documentação e sujeito a mudanças de política para repos
  públicos). O SHA auditado (`github.event.workflow_run.head_sha`) vem do payload do
  evento — dado, não entrada do PR — e é buscado como objetos git; a referência é
  `origin/main`. O gate roda do checkout da base (`ref: main`, `persist-credentials:
  false`), inclusive quando o `guard-tests` falha (quebrar os testes não escapa da
  auditoria). Workflows validados com actionlint 1.7.12 (zero findings).

**Limitação de bootstrap (explícita):** `workflow_run` só dispara quando o
`guard-audit.yml` já existe no branch default. O PR #1 (que traz o harness) não pode ser
auditado por ele. Procedimento do primeiro merge:

1. Mantenedor revisa o PR #1 (o check `guard-audit` não existirá para ele — isso é a
   limitação documentada; `guard-tests` deve estar verde).
2. Merge consciente para `main` (branch protection ainda desativada — ver abaixo).
3. Imediatamente após: Actions → **guard-audit → Run workflow** (self-audit
   `origin/main~1..origin/main`) e conferir verde.
4. Abrir um PR de teste trivial (ex.: comentário em docs/) e conferir nos runs que
   `guard-audit` dispara com `event=workflow_run` e audita o head do PR da base.

**Alterações futuras no próprio harness (protocolo auditável, sem auto-aprovação):**
qualquer mudança em `.github/workflows/` ou `zcode/` gera exit 3 REVIEW_REQUIRED — nunca
PASS automático. Para aprovar: o mantenedor revisa o PR e grava um registro na **main**
(`zcode/gow3-dev-guard/reviews/<data>-<slug>.json` com `{"head_sha", "pr", "approved_by",
"note"}`), commit direto do mantenedor (um único mantenedor não fica bloqueado por
exigência de segundo revisor). O gate lê os registros **da árvore da referência
confiável** — um PR jamais aprova a si mesmo. Não existe variável/global que desative a
auditoria.

**Branch protection (nomes REAIS dos checks, habilitar somente APÓS o primeiro merge):**
exigir `trusted audit gate (base ref)` e `guard + gate test suites`; **não** exigir
approving reviews (mantenedor único) — a revisão é feita pelo protocolo de registros
acima; proibir force-push em `main`.

## Ativação no ZCode (camada 1; ação única do usuário)

Settings → Plugin Management → Discover → **+** → diretório local `C:\gow3\gow3_pc\zcode` →
instalar **gow3-dev-guard** → conferir os 3 hooks *runnable* → nova sessão. A integração
real dos hooks ao host permanece **NOT_RUN** até instalado e testado no ZCode.

## CAMADA 1 — política resumida (v0.3.0)

Fail-closed em escrita; `rm -rf` com caminhos resolvidos (raiz/ancestais/`.git`/
proprietários bloqueados; só `out/ dist/ tmp/ temp/ __pycache__/ .pytest_cache/
node_modules/ target/`, aninhados incluídos); cobertura ApplyPatch (**incluindo
`*** Move to:`**)/MultiEdit de todos os arquivos; alvos de escrita bash por segmento com
**rastreamento de `cd`** (o destino resolve contra o diretório em que o shell estaria),
variáveis/substituições irresolvíveis ⇒ bloqueio, e escrita bash dentro do repo exige
branch determinável ≠ `main`; PowerShell com destino inverificável ⇒ bloqueio; git:
pathspec+`--dry-run` em `add`, staged em `commit`, **worktree em `commit -a/-am/--all
--include`**, `-C` aceito em push/checkout (push para `main`/force sempre bloqueados),
`checkout --`/`restore`/`stash`/`git rm` protegidos. Stop: `last_assistant_message`
prioritário, RISKS exigido, campos por seção, bloco ```text único, anti-loop (2×).
Mensagens de bloqueio sempre com motivo e caminho.

## Testes e evidências

```
python zcode/gow3-dev-guard/tests/test_guard.py -v        # 90 testes (camada 1)
python zcode/gow3-dev-guard/tests/test_audit_gate.py -v   # 13 testes (camada 2, fixtures)
```

Red→green da integridade: as 6 lacunas da reauditoria foram escritas primeiro e falharam
contra `20250d1` (`C:\gow3\integrity-RED.log`: 90 testes, 6 FAIL) e passaram após as
correções (`integrity-GUARD-FINAL.log`: 90/90 OK). Gate validado em fixtures positivas
(escopo autorizado, worktree não commitado, sujeira de submódulo, exceção `--allow-path`)
e negativas (protegido, proprietário commitado e untracked, fora do escopo, rename para
protegido, deleção de harness, autoenfraquecimento, ponteiro de submódulo, referência
inexistente) — `integrity-GATE-FINAL.log`: 13/13 OK. Evidência real na branch:
`audit_gate.py --ref origin/main` ⇒ PASS (11 registros, todos no escopo) e
`--ref fix/gow3-guard-hardening` ⇒ PASS (com `guard_common.py` modificado na branch —
comparação anti-enfraquecimento executada).

## Fases futuras (planejadas, NÃO implementadas)

Skill `gow3-gamer-ui`, skill `gow3-code-audit`, subagentes, MCPs Context7/Playwright e
memória de projeto — a definir nas próximas fases.

