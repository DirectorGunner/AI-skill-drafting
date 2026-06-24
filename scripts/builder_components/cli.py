"""Command dispatch for the skill_builder CLI: the single entry point that fans out to every
subcommand (the build pipeline plus the folded-in validate / policy / recontext-subagent tools).

This module is the top of the dependency graph — it imports every `cmd_*`, so the bundler emits it
last. The same dispatch backs both `python skill_builder.py <cmd>` (the generated all-in-one) and
`python -m builder_components.cli <cmd>` (the source package)."""

from __future__ import annotations

import sys
from .build import cmd_build
from .finalize import cmd_finalize
from .index import cmd_index
from .ingest import cmd_ingest_html, cmd_ingest_mdbook, cmd_ingest_pdf, cmd_ingest_rustdoc
from .lint import cmd_lint
from .maintain import cmd_maintain
from .policy_cmd import cmd_policy
from .readme import cmd_readme
from .recontext import cmd_recontext
from .recontext_subagent import cmd_recontext_subagent
from .split_cmd import cmd_split
from .validate import cmd_validate


# ==============================================================================
# CLI DISPATCH
# ==============================================================================

_USAGE = """skill_builder.py — build documentation skill packages (stdlib only).

usage: python skill_builder.py <command> [options]

commands:
  ingest {html|mdbook|rustdoc|pdf}   source docs -> corpus JSONL
  build                              corpus JSONL -> a flat or router skill
  finalize                           gold-standardize SKILL.md + GOTCHA.md
  split                              split oversized references into one file per topic
  maintain                           audit / split-in-place / cross-link a built skill
  index                              cross-skill master INDEX.md (+ covers: seeding)
  lint                               link/topics health check -> AI/lint/<skill>.md
  recontext {clean|extract|splice|gate|triage}
                                     recontextualize verbatim docs into original prose + verify
  readme {scaffold|apply}            create/refresh skill README.md from the single-sourced standard
  validate [--package] <dir>         validate a skill package (leaf, or --package for a router)
  policy {audit|plan|preview|apply|restore}
                                     manage each skill's idle-listing invocation policy
  recontext-subagent {prepare|show|submit|audit}
                                     the locked, gated recontextualization artifact writer

Run `python skill_builder.py <command> --help` for that command's options."""

_INGEST_USAGE = ("usage: python skill_builder.py ingest {html|mdbook|rustdoc|pdf} [options]\n"
                 "Run `python skill_builder.py ingest <format> --help` for options.")

_INGEST = {"html": cmd_ingest_html, "mdbook": cmd_ingest_mdbook,
           "rustdoc": cmd_ingest_rustdoc, "pdf": cmd_ingest_pdf}
_COMMANDS = {"build": cmd_build, "finalize": cmd_finalize, "split": cmd_split,
             "maintain": cmd_maintain, "index": cmd_index, "lint": cmd_lint,
             "recontext": cmd_recontext, "readme": cmd_readme,
             "validate": cmd_validate, "policy": cmd_policy,
             "recontext-subagent": cmd_recontext_subagent}


def _rebuild(argv) -> int:
    """Regenerate (or --check) the all-in-one scripts/skill_builder.py from the source components.

    Convenience wrapper for `python builder_components/_assemble.py`. Works when running from the
    source package (where the `_assemble` submodule is importable from disk); when invoked on the
    GENERATED bundle the source compiler is not present, so we point the caller at the source command.
    """
    try:
        from . import _assemble  # type: ignore
    except Exception:
        print("rebuild from source: python builder_components/_assemble.py", file=sys.stderr)
        return 2
    return _assemble.main(argv)


def main(argv=None) -> int:
    """Parse argv[0] as the subcommand and dispatch to its handler (returns the process exit code).

    `ingest` takes a second positional selecting the source format; `--rebuild` regenerates the
    all-in-one file; `-h`/`--help`/empty prints the command list. Reads ``sys.argv[1:]`` when ``argv``
    is None.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "--rebuild":
        return _rebuild(rest)
    if cmd == "ingest":
        if not rest or rest[0] in ("-h", "--help"):
            print(_INGEST_USAGE)
            return 0
        fn = _INGEST.get(rest[0])
        if not fn:
            print(f"unknown ingest format: {rest[0]}\n{_INGEST_USAGE}")
            return 2
        return fn(rest[1:])
    fn = _COMMANDS.get(cmd)
    if not fn:
        print(f"unknown command: {cmd}\n{_USAGE}")
        return 2
    return fn(rest)


if __name__ == "__main__":
    raise SystemExit(main())
