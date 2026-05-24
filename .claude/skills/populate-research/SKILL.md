---
name: populate-research
description: Scan this repository with 3 parallel agents and append grep-friendly facts to RESEARCH.md. Use when RESEARCH.md is empty or stale, when the user asks to "refresh research" or "populate research," or when starting work on an unfamiliar area of the repo.
---

# /populate-research

Populate or refresh `RESEARCH.md` at the repository root by dispatching three parallel research agents and merging their findings into the existing file.

## Output format

Every entry in RESEARCH.md is a single grep-friendly line. Format:

```
<topic>: <fact> [— <file>:<line>]
```

- Lead with a lowercase keyword/topic so `grep '^build:'` works.
- Keep each line under ~160 characters. If you need more, split into multiple lines, each with the same topic prefix.
- Cite source location (`path/to/file.ext:line`) when the fact comes from a specific file.
- No prose paragraphs. No bullet trees. One fact per line.

Examples:
```
build: pnpm workspaces, turbo for orchestration — turbo.json:1
routing: Express app mounts /api/* under authMiddleware — src/server.ts:42
db: Postgres 14, pool size 20 — src/db/pool.ts:8
deploy: Fly.io, config in fly.toml; secrets via `fly secrets set`
domain: "tenant" = top-level customer org; "workspace" = sub-unit per tenant
```

## Procedure

1. **Read existing RESEARCH.md.** If it does not exist, stop and tell the user — do not create it from scratch unless they confirm. The template ships with an empty RESEARCH.md, so absence usually means the user is in the wrong directory.

2. **Dispatch 3 agents in parallel** (single message, three Agent tool calls). Use `subagent_type: Explore` so they're read-only. Split by topic, not by directory — directory splits cause overlap and miss cross-cutting facts:

   - **Agent A — Structure & architecture.** Entry points, module/package layout, key abstractions, how data flows end-to-end, public vs internal boundaries. Read README, top-level config, main source dirs.
   - **Agent B — Tooling & ops.** Build/test/lint/format commands, package manager, CI config, deploy targets, runtime dependencies of note, version pins that matter. Read package manifests, CI files, Makefile/justfile, Dockerfiles.
   - **Agent C — Domain & external context.** Business/domain vocabulary, external APIs called, third-party services, links to upstream docs already mentioned in the repo. Read docs/, comments in core modules, any `.md` other than CLAUDE/BEHAVIOR/RESEARCH.

   Each agent must return only grep-friendly lines in the format above. Tell them explicitly: no prose, no markdown headers, no bullet trees.

3. **Merge into RESEARCH.md.**
   - Read the current contents.
   - For each new line, check if an equivalent fact already exists (same topic + same subject). If yes, skip or update in place. If no, append under the matching topic section, or add a new topic section if none exists.
   - Preserve any existing user-written entries. Do not delete or reorder them.
   - Sort within each topic alphabetically by subject for stable diffs.

4. **Record conflicts durably.** If two agents returned contradictory facts for the same subject, append a section to RESEARCH.md titled `## Conflicts surfaced by /populate-research` (create it if missing) and add one line per conflict in this format:

   ```
   <topic>: <subject> — source A says X (path:line); source B says Y (path:line). <one-line note on how to resolve>
   ```

   Do not silently pick a winner. Conflicts belong in the file so they remain visible across sessions, not only in chat.

5. **Report back to the user** with: total lines added, total skipped as duplicates, and a count of conflicts written to the conflicts section. Point the user at the conflicts section if any were recorded.

## Constraints

- Append-only with respect to existing entries. Never wholesale-overwrite RESEARCH.md.
- Do not invent facts. If an agent can't find a fact, it omits the line — empty is better than wrong.
- Skip generated/vendored directories (`node_modules`, `dist`, `build`, `.venv`, `target`, `vendor`).
- If the repo is tiny (≤10 source files), one agent is enough — do not over-deploy. Use judgment.
- Web lookups are allowed only when the repo explicitly references an external doc URL. Do not search the web for general background.

## When NOT to run

- If RESEARCH.md was updated in the last hour and no major changes have landed since, ask the user before re-running. The point is durable knowledge, not constant churn.
- If the user asked a narrow question, answer it directly — do not detour through this skill.
