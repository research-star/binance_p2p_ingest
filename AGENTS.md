# Codex instructions — FinanzasBo

Before doing any analysis or work in this repository, read completely:

1. `HANDOFF.md` — canonical repository contract and source of truth for the current architecture and operational state.
2. `CLAUDE.md` — shared repository conventions and engineering etiquette.
3. `CLAUDE.local.md` — local and personal workflow rules, only if the file exists.

For project facts and repository rules, use this precedence:
`HANDOFF.md` > `CLAUDE.md` > `AGENTS.md` / `CLAUDE.local.md`.

The current task brief defines the authorized perimeter for that task, including filesystem writes, network access, Git operations, VPS access and API usage. Never exceed that perimeter.

If the documents contradict each other, or repository/runtime evidence suggests that a document is stale:

- Do not resolve the discrepancy silently.
- Report it before implementation.
- Treat the repository and runtime code as falsifiable evidence.
- Do not rewrite canonical documentation unless the task explicitly authorizes it.

Product decisions, visual decisions, merges, production actions and irreversible operations always require Diego’s explicit authorization.

## Reglas duras

- Jerarquía normativa: `HANDOFF.md` > `CLAUDE.md` > `AGENTS.md`.
- Nunca usar `git add -A` ni `git add .`; agregar archivos por nombre.
- Nunca commitear `index.html`; es un artefacto generado por el publish.
- Los merges usan merge commit, nunca squash; borrar la branch después.
- Prohibido gastar APIs Anthropic/externas sin autorización explícita en el brief.
- Nunca tocar VPS/SSH salvo que el perímetro diga explícitamente `VPS-*`.
