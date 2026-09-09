# Roadmap

Ordering, not dates. Nothing below is a commitment; see the no-SLA statement in `README.md`.

## v0.1.0 (ship gate)

- core and maintain packs pass the template's own doctor on Claude Code in the fresh-template CI job.
- Every adopted mechanism (bootstrap `--check` and `--copy`, regression fixtures, data-loss canary, Python execute-probe, strict runtime JSON, VERIFICATION format, degradation ladder, seatbelt list, fresh-template acceptance, doctor and verify skills, Codex stdin and trust notes, Linux-repro notes) has a test or CI assertion, a VERIFICATION row, and a stated non-coverage.
- Codex and OpenCode rows in `docs/VERIFICATION.md` populated with scope tokens: `configured` at minimum, `fired` where proven on a host.
- De-identification lint clean over the full history; permission-posture assertion green; human review of the outgoing artifact. Gate command: `python harness/tools/release_check.py --terms <private-list> --require-terms 3`; the visibility flip waits on its `PASS`.

## v0.1.1

- decks pack: deck-outline, deck-render (web output, pure-Python checks).

## v0.2

- engineering pack: debug, code-review, write-safety with the freeze hook.
- reports and youtube skills.
- connectors under a connection standard (capability rows reserved in `capabilities.json`), plus focus.
- Marketplace channel after a spike proving that a pack directory tree installs as a plugin on at least one runtime; Codex marketplace publishability still unread.
- Source updating: a per-file `ported | adopted` state with source commit, `--check` reporting only on adopted files, and a drift threshold that blocks the next release.
- Instance mode: considered only after 30 consecutive days without kernel edits and at least one external adopter; a dated decision, not a default.
- HOT digest generation for the local memory lane.

## Not planned

- Personas or identity content. The template ships neutral IDENTITY and OPERATOR shapes only.
- A security boundary. The guards stay seatbelts; real coverage is your CI's secret scanner and the runtime's own sandbox.
- Support for runtimes beyond Claude Code, Codex CLI, and OpenCode unless a contributor carries the VERIFICATION rows.
