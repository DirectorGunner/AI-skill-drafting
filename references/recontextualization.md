# Recontextualization — turning verbatim docs into original, publishable prose

Use this when a skill's reference files were ingested **verbatim** from upstream documentation and
must become **original prose** before the skill is published, while every identifier, signature,
code span, link target, number, and table stays exact. This is the licensing gate: a published skill
must not carry copyrightable upstream prose. The work is deterministic where it can be (cleanup,
extraction, splicing, verification) and LLM-driven only for the actual rewording — and even then the
rewording is forced through a locked, self-verifying writer so a subagent cannot drift.

## The three tools

- **`scripts/builder_components/recontext_core.py`** — the stdlib-only engine. Prose-unit detection,
  the three gates, chrome/scrape cleanup, extract/splice, and triage. Path-agnostic: nothing is
  hardcoded to a skill, owner, or location. Backs both tools below (via the launcher scripts), so the
  published skill ships a self-contained engine.
- **`scripts/skill_builder.py recontext <op>`** — the command group for an operator/orchestrator:
  - primitives: `clean`, `extract`, `splice`, `gate`, `triage`
  - lifecycle: `scan` → `batch` → `drain` → `integrate` → `finish` → `reconcile` → `promote`
- **`scripts/skill_builder.py recontext-subagent`** — the **locked, gated writer** a rewriting subagent must use
  (`prepare` / `show` / `submit`). It is the rail: it derives every output path internally, refuses
  any caller-supplied path, confines all writes to one `--work-root`, and runs the gates before it
  writes anything — so a `PASS` is verified, never assumed.

## The unit of work and the gates

A file's copyrightable prose is its **prose units** = whole narrative lines **plus prose inside table
cells** (Description/Remarks columns). Headings, tables, signatures, code, and bare-token bullets are
structure, not prose, and are never reworded. Three gates decide acceptance (all run by `submit`,
`integrate`, and `finish`):

- **Gate A — identifiers.** The protected-token multiset of the source (code spans, inline code,
  URLs/link targets, CamelCase / ALL_CAPS / `Foo::Bar` identifiers) must survive into the rewrite.
  This is the catastrophic-error catch: a dropped or renamed API name fails here.
- **Gate B — verbatim residue.** No non-exempt run of **~13+ consecutive words** may match the source
  (scanned per prose unit, so a run can't bridge across units or through a preserved identifier).
  Identifier/URL/number-dominated runs are exempt. The length ratio is informational, never a target —
  fidelity beats compression.
- **Gate C — cruft.** No residual scrape chrome (PUA icon glyphs, empty `(Figure:)` stubs, nav footers).

## Modes

`triage` classifies each file by prose density:

- **extract** (sparse prose): only the listed prose units are sent to the LLM as a packet; `splice`
  reinserts the rewrites at their exact positions. Identifiers/signatures/tables never reach the LLM.
- **full** (prose-dense): the whole file is rewritten in place — prose lines and table-cell prose —
  leaving code/signatures/tables structurally intact, including wrapping any flattened-into-prose code
  back into fenced/inline code byte-for-byte.

The locked writer supports **both**: `extract` validates an item packet and splices; `full` accepts
the whole rewritten file, cleans it, and gates it.

## The locked-writer contract (what a rewriting subagent does)

A subagent NEVER writes rewrite files itself. For each file it:

1. `prepare --work-root <WR> --skill <S> --worker <wid> --source <abs> --source-root <SR> --rel <rel> --mode <mode> --tier <tier>`
2. `show --work-root <WR> --skill <S> --worker <wid>` — prints the contract and the work (extract
   packet, or the source for full mode).
3. Produces the rewrite per the contract: `extract` → exactly `{"items":[{"i","cell","text"}]}` with
   the packet's keys/order/count; `full` → the whole rewritten file as raw text.
4. Pipes it to `submit --work-root <WR> --skill <S> --worker <wid>`. `submit` runs Gate A/B/C and
   writes the canonical artifacts **only on PASS**. On `FAIL` it writes nothing and prints the failing
   gate; the subagent fixes exactly that and resubmits.

All artifacts land under `<WR>/recontext/<skill>/<worker>/` (`packet.json`, `rewrite.json`, `work.md`,
`result.json`). The `result.json` manifest carries `files[].rw` + the gate verdict + an honest
`verification` block.

## The orchestration lifecycle

Driven by `skill_builder.py recontext`, with roots from a `--config` JSON
(`source_root`/`work_root`/`store_root`/`owner`) or CLI flags — no hardcoded skill, owner, or path:

1. **scan** `--skill S` — walk `<source_root>/<S>/**/references/*.md`, classify each into
   faction/tier/mode, write the owner's queue (idempotent: re-scan preserves status).
2. **batch** — group pending queue rows into right-sized work batches.
3. **drain** — generate a Workflow script (`drain-<S>.wf.js`) whose subagent prompts call the locked
   writer (`prepare`/`show`/`submit`). Launch it with the Workflow tool. (This replaces the older
   hand-written `gen_drain.py`, which told subagents to write `_rw_`/`_pkt_` files freehand — the exact
   wrong-location/ungated risk the locked writer removes.)
4. **integrate** — copy each gated `work.md` into `<work_root>/working/<rel>` (re-gates as a backstop;
   never places a failing file).
5. **finish** — re-gate every working file for the skill; mark passes done, re-queue failures. Reports
   READY-TO-PROMOTE / NOT-READY.
6. **reconcile** — confirm every source file is queued and done.
7. **promote** — validate the finished working skill and move it into the store (writes a done marker).

## Verification / known failure modes

- **Never present ungated work as done.** `submit`/`integrate`/`finish` all run the real gates;
  `submit` writes nothing on failure. If you ever see a rewrite artifact that did not pass, treat it
  as a bug, not a pass.
- **Wrong cell index.** Table-cell units are keyed by `split('|')` index; a rewrite item with the wrong
  `cell` is rejected by the schema check (it is not silently spliced elsewhere).
- **`full` mode is not a no-op alias for `extract`.** It rewrites the whole file; do not route a
  prose-dense file through `extract` (you would leave headings/short lines unreworded).
- **Portability.** The locked writer has no hardcoded paths and confines writes to `--work-root`, so it
  is safe to run in any repo. `audit --root <tree>` recursively reports any misplaced legacy
  `_pkt_`/`_rw_`/`_result_` artifacts (case-insensitive) and reparse points.
- **Parity.** `recontext gate/extract/clean` reproduce the field-proven results of the original
  pipeline; verify with a golden-file diff if you change the engine.
