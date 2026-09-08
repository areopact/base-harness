# harness/rules/

Binding behavior law: the discipline that governs how an agent works in this repository, distinct from working beliefs (memory lanes) and from invoked workflows (skills). `harness/registry/runtimes.json` declares, per runtime, whether bootstrap materializes these pages into a native rule path; where a runtime has no such path, the contract's lookup section points here and the agent reads the page on demand.

## What lives here

- **Always-on rules** load every session regardless of which file is touched.
- **Path-scoped rules** load only when a file matching their globs is touched. Runtimes that cannot auto-load by path still honor them through the explicit lookup in the contract.
- **`index.json`** is the machine-readable list: every `*.md` in this folder has exactly one entry with `kind` (`always-on` or `path-scoped`), `globs` (non-empty for path-scoped), and a one-sentence `summary`. The lint rejects an orphan page or a dangling entry. The file also carries `bootstrap_path_allowlist`, the set of documentation paths permitted to mention bootstrap-created directories.

Every page follows the rule-page model: the binding statement first, then `## Why` (the failure mode as an invariant), then `## Application` (concrete behavior and boundaries). Rules link to each other with relative Markdown links and cite repository files by `harness/`-relative path.

## What does not go here

- Working and standing beliefs that are not yet binding belong in the knowledge lane (see [memory-routing](memory-routing.md)).
- Reusable workflows with a trigger belong in `harness/skills/`.
- Host-specific layout and conventions belong in `harness/CONTRACT.host.md`; `adopt.py` merges a host's own rules into this folder by reserved-name rule and never overwrites a template page.

## Pointers

- The contract (`harness/CONTRACT.md`, rendered into the root `AGENTS.md`) carries the core operating principles with one-line summaries and names the page behind each.
- [base-routing](base-routing.md) is the authored source for the delegation policy that `harness/tools/routing_policy.py` compiles.
- [hook-design](hook-design.md) governs every file under `harness/hooks/`; [access-policy](access-policy.md) governs every Markdown page.
