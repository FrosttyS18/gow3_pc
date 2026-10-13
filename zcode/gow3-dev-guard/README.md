# gow3-dev-guard — harness determinístico de segurança e auditoria

Plugin do ZCode versionado no repositório (`zcode/gow3-dev-guard`), com marketplace local em
`zcode/marketplace.json`. Sem código do jogo, sem rede, sem LLM: toda decisão é caminho
resolvido, regex, consulta git somente-leitura ou diff real — avaliada em código.

**v0.3.0** — integridade em duas camadas após a reauditoria do `20250d1`
(branch `fix/gow3-guard-integrity`):

- **CAMADA 1 — PreToolUse (pré-execução):** bloqueia operações perigosas identificáveis.
- **CAMADA 2 — Audit Gate (pós-fato, independente):** verifica as alterações REAIS do
  repositório contra uma referência confiável — não depende da interpretação do LLM nem do
  texto dos comandos. CLI e CI: `zcode/gow3-dev-guard/tools/audit_gate.py`.

## Componentes

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

## CAMADA 2 — Audit Gate

```
python zcode/gow3-dev-guard/tools/audit_gate.py [--repo DIR] [--ref REF]
                                                [--allow-path PATH]... [--json]
```

- Referência explícita (padrão `origin/main`, senão `main`); diff `--name-status` cobre
  commits + staged + worktree de uma vez; renames inspecionam os dois lados.
- Verifica: caminhos protegidos, material proprietário (inclusive **untracked**, via
  `git status`), mudanças funcionais fora do escopo autorizado (`docs/ launcher/ tests/
  zcode/ packaging/ tools/ .github/ gpu/shim/gow3_overlay.cpp` + meta), **ponteiros de
  submódulo** (sujeira de conteúdo do build é ignorada; mover o ponteiro falha), exclusão
  de arquivos do harness.
- **Anti-autoenfraquecimento:** se o próprio `guard_common.py` ou `audit_gate.py` mudar na
  branch analisada, as tabelas de política (PROTECTED_PREFIXES, PROPRIETARY_PATTERNS,
  AUTHORIZED_SCOPE, ...) são extraídas por AST da referência e comparadas — remover
  entradas ⇒ FAIL; arquivo ilegível/inparseável ⇒ FAIL; harness novo na referência ⇒ nada
  a comparar (regras passam a valer a partir do merge).
- Saída `PASS`/`FAIL` com status, caminho e evidência (`ref..worktree`); exit `0/1/2`.
- **Exceção de escopo para integrações upstream:** `--allow-path PATH` explícito por
  invocação, declarado no PR e restrito ao commit/tag aprovado — nunca liberação geral nem
  variável de ambiente que desative o gate.

## CI e proteção da main

`.github/workflows/guard-audit.yml` (sintaxe validada) roda em `pull_request → main` e
`workflow_dispatch`: suíte do guard (90 testes) + audit gate vs `origin/main`.
**Proteção da `main` proposta, ainda NÃO confirmada como ativa** (exige configuração do
mantenedor no GitHub): exigir o check `guard-audit`, exigir revisão de PR, proibir
force-push/exclusão. Após habilitar, confirmar em Settings → Branches.

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

