---
paths:
  - "**/*.md"
---

# Access Policy

Any page may carry `access:` with one of five labels: `public`, `internal`, `confidential`, `restricted`, `secret`. The labels are strictly additive and clearance-free: they describe where a page may travel, not who a person is. Lane defaults come from `harness/registry/structure.json` under `tiers.lane_defaults`; a path in no lane takes `tiers.unlisted_path`. An explicit per-file label always overrides the default.

## Why

A repository that mixes shareable reference material with private notes needs one vocabulary for "how far may this go" that a script can act on. Without labels, every export is a hand review, and hand reviews miss. Clearance-based models (a person holds tier N and may read N and below) require a registry of people and their standing, which a template cannot ship and a solo repository does not need. Destination-based labels need only the page and the export target. When in doubt, classify one label higher than seems necessary: downgrading is easy; a leak is not.

## Application

### The five labels

| Label | Meaning |
|---|---|
| `public` | Shareable without restriction. Included in every export. |
| `internal` | Repository access is the boundary. Anyone who can clone may read. |
| `confidential` | Included only in exports run at `confidential` or above. |
| `restricted` | Requires a non-empty `allowed_collaborators` list whose ids validate against `harness/registry/collaborators.yaml`; included only in exports at `restricted` or above. |
| `secret` | Excluded from every export, at every level. On Claude Code only, an optional hook (shipped off) can deny the native read tool for a `secret` page; on every other runtime the label is documentation, and the agent respects it as if it were enforced. |

Additivity: an export at level N carries every page labelled N or below, never above. `restricted` implies `confidential` implies `internal` implies `public` for inclusion purposes; `secret` is outside the ladder and never travels.

### Defaults

Folder defaults are not a table on this page. `structure.json` names one default label per lane (identity, knowledge, journal, decisions, records, docs) and one policy for paths outside every lane: `internal` or `exclude`. A subfolder inherits its lane's default, never a same-named folder elsewhere. A page with no `access:` field takes its lane default at export time.

### What the label does not do

The label does not grant read access to anyone. It does not encrypt. It does not stop a commit. It governs `harness/tools/export.py`, which copies a history-free tree at the requested level and refuses files above it, and it informs the agent's own behavior when a page it reads says it should not be quoted onward. Files an agent must boot from or operate on cannot be `secret`, because a `secret` page is stripped from every export and, where the read-deny hook is on, from the agent's own view.

### Enforcement

- The frontmatter guard (advisory rung, see [hook-design](hook-design.md)) checks on every write that `access` is one of the five labels and that `allowed_collaborators` is present if and only if `access` is `restricted`.
- `export.py` enforces the label at export time and reports every excluded path.
- The read-deny hook for `secret` is Claude-only and off by default; enabling it is documented in `harness/hooks/README.md`.
- The frontmatter guard rejects an `allowed_collaborators` id that does not exist in the collaborator registry, and `export.py` refuses a `restricted` export whose collaborators file is missing, empty, or malformed.

### Classification guidance

Pages that mention third parties by name default to `confidential` unless the subject has consented to `public`. Identity-lane pages default to `internal` and may be raised per file. A label only ever moves down after a deliberate review, recorded where the page's lane records decisions.
