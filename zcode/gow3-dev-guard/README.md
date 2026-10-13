# gow3-dev-guard — harness determinístico de segurança e auditoria

Plugin do ZCode versionado no repositório (`zcode/gow3-dev-guard`), com marketplace local em
`zcode/marketplace.json`. Sem código do jogo, sem rede, sem LLM: toda decisão é caminho
resolvido, regex, consulta git somente-leitura ou diff real — avaliada em código.

**v0.6.0** — bootstrap desbloqueado (PR #1): auditoria via **`pull_request_target`
endurecido** (elegível como required status check; `workflow_run` foi descartado porque
seus checks reportam no SHA do branch default e não podem ser exigidos na proteção de
branches), material proprietário **incondicional** em qualquer superfície, e procedimento
de bootstrap corrigido. 30 testes do Audit Gate.## Componentes

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

## CI e proteção da main (v0.6.0)

- `guard-tests.yml` — evento `pull_request` (não privilegiado, `contents: read`):
  `test_guard.py` (90) e `test_audit_gate.py` (30) no merge ref do PR.
- `guard-audit.yml` — evento **`pull_request_target`** (branches: main): a versão do
  workflow executada é a do **branch base** (documento oficial), e o check anexa-se ao
  PR — **elegível como required status check** (motivo da troca: checks de `workflow_run`
  reportam no SHA do branch default e não podem ser exigidos na proteção). Endurecimento
  conforme a página oficial "Securely using pull_request_target": único checkout é a base
  (`ref: main`, `persist-credentials: false`, `contents: read`); o head do PR **nunca** é
  feito checkout — seus objetos chegam por `git fetch` e são inspecionados **como dados**
  (diff/ls-tree/show: "the checked-out code is only ever inspected as data and never
  executed"); sem secrets, sem cache; forks e cenários não suportados **falham o check
  explicitamente** (nunca ficam em estado ignorado que possa ler-se como aprovação);
  referência confiável = `origin/main`; SHA auditado = `github.event.pull_request.head.sha`
  (payload do evento).

**Política oficial (pré-condição do mantenedor):** a documentação informa que repos
públicos recebem uma política padrão que **bloqueia workflows `pull_request_target`**,
hoje em modo *evaluate* (as execuções seguem), com **aplicação em 2 de novembro de
2026**. Para manter este workflow após essa data, o mantenedor deve criar/atualizar a
**Actions event policy** do repositório autorizando explicitamente
`pull_request_target` (Settings → Actions). Até lá, o modo evaluate permite a execução.

**Material proprietário é incondicional:** `eboot.bin`, `*.pkg`, `*.prx`, `*.sprx`,
`sce_module/`, `sce_sys/`, `savedata/` em **qualquer** caminho — inclusive dentro de
`zcode/gow3-dev-guard/reviews/`, `zcode/upstream-exceptions/`, `.github/workflows/` e do
próprio harness — resultam em FAIL, nunca PASS nem REVIEW_REQUIRED.

**Procedimento de bootstrap (corrigido — o primeiro merge instala o verificador):**
1. Revisão consciente do PR #1 pelo mantenedor (o check `guard-audit` não existe para
   ele: `pull_request_target` só executa workflows já presentes na base — limitação
   documentada; `guard-tests` deve estar verde).
2. Merge inicial autorizado pelo mantenedor (branch protection ainda desativada).
3. PR descartável de teste com alteração permitida (ex.: nota em docs/): confirmar que o
   check `trusted audit gate (base ref)` aparece no PR, dispara como
   `event=pull_request_target`, executa o gate da base contra o head do PR e fica verde.
4. PR descartável separado com alteração proibida (ex.: tocar `src/`): confirmar que o
   mesmo check fica vermelho com o motivo — o bloqueio funciona de ponta a ponta.
5. Somente então habilitar a proteção da `main` exigindo os checks reais
   **`trusted audit gate (base ref)`** e **`guard + gate test suites`** (sem exigir
   segundo revisor — mantenedor único; proibir force-push). Nota: o self-audit manual
   (dispatch) após um merge que carrega mudanças de segurança retorna REVIEW_REQUIRED
   por design — grave o registro de aprovação na main ou confirme conscientemente.

**Alterações futuras no próprio harness:** mudanças em `.github/workflows/` ou `zcode/` ⇒
exit 3 REVIEW_REQUIRED (nunca PASS automático). O mantenedor aprova gravando
`zcode/gow3-dev-guard/reviews/<data>-<slug>.json` (`{"head_sha", "pr", "approved_by",
"note"}` — SHA exato, rastreável) **na main**; o gate lê os registros da árvore da
referência confiável, então um PR jamais aprova a si mesmo (testado). A manutenção do
harness nunca exige desligar a branch protection: cada mudança tem registro próprio.

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
prioritário, RISKS exigido, campos por seção, bloco ```text único **e exclusivo** (nada
além de espaços fora do bloco — introduções/sínteses/listas/conclusões externas
invalidam; ajuste permanente do contrato), anti-loop (2×).
Mensagens de bloqueio sempre com motivo e caminho.

## Testes e evidências

```
python zcode/gow3-dev-guard/tests/test_guard.py -v        # 90 testes (camada 1)
python zcode/gow3-dev-guard/tests/test_audit_gate.py -v   # 30 testes (camada 2, fixtures)
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

