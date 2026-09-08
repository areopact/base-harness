# harness/registry/

Small, versioned relationship maps consumed by bootstrap, lint, the doctors,
and the documentation generators. They contain no runtime state and no
secret values. Validate all of them with:

```text
python harness/tools/harness_registry.py
```

The command prints one line per error and exits 1 on any error. Informational
notes (a surface another package has not landed yet) never change the exit
code.

| File | Owner | What it declares | Who reads it |
|---|---|---|---|
| `structure.json` | registry | Host facts: the six memory lanes, git mode, outbound globs, brain local path and tracking, tier defaults, delegation flag, selection scope, contract mode (`rendered` or `host-owned`), and adopted-host record (`host.adopted`, `host.roots`, `host.harness_owned`) | every kernel file through `harness_registry.load_structure()` or `hook_io.load_structure()`; `init.py`, `adopt.py`, `export.py`, the doctors, `contract_files.py`, `lint.py` (L6), `deidentify_lint.py` (D3, D6) |
| `adopted-files.json` | registry (written by `adopt.py`) | Present only on an adopted host: `template_version` (from `kernel-manifest.json`) plus the sorted, repository-relative paths adopt created or wrote (copies, the `structure.json` write, every landed `.harness` sibling); a re-adoption merges (unions) rather than overwrites | `lint.py` and `deidentify_lint.py`, to scope their default scan on an adopted host to the template's own files (`--all` restores the whole tree) |
| `structure.schema.json` | registry | JSON Schema draft-07 for `structure.json`, `additionalProperties: false` at every level | CI, the doctors, `test_structure_defaults.py` |
| `selection.json` | registry (written by `selector.py`) | Selected packs plus per-skill include and exclude lists | bootstrap materialization, `build_codex_adapter.py`, `build_opencode_adapter.py`, the doctors (reconciled against materialized artifacts) |
| `runtimes.json` | registry | Runtime tiers, status, adapter and doctor paths, capability states, identity context budgets, materializations, retired destinations, hook event coverage with the degradation rung per runtime | bootstrap, `contract_files.py`, `dispatch.py`, the three doctors, `lint.py` (L2, L8) |
| `capabilities.json` | registry | Runtime-provided capabilities: kind, per-runtime state, offline probe, and the in-skill fallback sentence | skill frontmatter lint (`distribution: runtime-provided`), the doctors |
| `sources.json` | registry | Provenance and license per asset group; NOTICE and THIRD-PARTY.md are generated from it | `gen_manifest.py`, `lint.py` (asset existence, one license per pack) |
| `environment.json` | registry | Environment policy, principals, symbolic secret locations, and variable-name bindings; never a value, digest, presence result, or absolute path | `harness_registry.py` (declaration-only validation); nothing opens a secret store |
| `collaborators.yaml` | registry (operator-edited) | The named collaborators that the restricted tier may be exported to, with a tier ceiling each | `export.py --tier restricted` |
| `tests/` | registry | Regression tests for the loaders and validators | `python -m pytest harness/registry/tests -q -p no:cacheprovider` |

## Invariants

- `structure.json` is optional on disk: a missing file yields the documented
  default object verbatim, a present file merges key-by-key over it, and a
  present-but-null lane stays null. The two loaders (`harness/tools/harness_registry.py`
  and `harness/hooks/lib/hook_io.py`) must agree on that result; the tool loader raises
  `StructureError` on a malformed file, the hook loader fails open.
- Every materialization row in `runtimes.json` has a matching row in
  `harness/bootstrap/junctions.json` (same source, destination, mode) and vice
  versa. The mode vocabulary is closed: `link`, `managed-copy`, `generated`,
  `contract-render`. One rendered root contract may be listed by several
  runtimes; every other destination has exactly one owner.
- Existence checks (adapter directories, hook wrappers, materialization
  sources) apply once the owning surface under `harness/` exists. Until then
  the validator emits a note, not an error, so the registry can land before
  the packages it describes. Sources inside the bootstrap-generated selected
  skill tree are produced at materialization time and are never required to
  exist in a fresh clone.
- `environment.json` records variable names and symbolic path templates only.
  The forbidden-key walk rejects `value`, `values`, `secret_value`, `token`,
  `digest`, `sha256`, `present`, `exists`, `home`, and `absolute_path` at any
  depth outside the `policy` block, which is where the rule itself is stated.
- `kernel-manifest.json` (one level up, at `harness/kernel-manifest.json`)
  lists every kernel file with `state` in `ported | new` and a non-null
  `source` exactly when the state is `ported`. Reconciliation to the tree is a
  lint step, not a registry check. Membership rule (matches `is_kernel_file`
  in `lint.py` L6): the manifest covers `harness/`, `.githooks/`, and
  `.github/workflows/`; root metadata files and `docs/` are template-authored
  and out of scope. A `ported` file's `source` is repository-origin-prefixed
  (`upstream-harness:` for the private harness this scaffold was cut from,
  `upstream-template:` for the earlier basic-harness prototype) followed by
  that origin's own relative path; no source commit is recorded per row.

Every runtime-native configuration file that bootstrap materializes (the
`destination` column of each `materializations` row) is produced from the
adapter source named in the same row; edit the adapter source, never the
output.
