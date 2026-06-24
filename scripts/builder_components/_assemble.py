#!/usr/bin/env python3
"""Compiler: amalgamate the builder_components/ package into the single, self-contained, all-in-one
tool `scripts/skill_builder.py`.

The generated `skill_builder.py` carries every component's **verbatim source** in a `_SRC` dict (one
entry per module, each under a readable `# ===MODULE <fqname>===` banner), and a small bootstrap that
registers each entry as the corresponding `builder_components.*` module — in dependency order — and
runs the CLI. Embedding the source as data (not bare top-level code) is what makes a single file able
to hold many modules: each is exec'd in its OWN namespace, so name collisions are impossible, the
`recon`/`core` engine namespaces and every relative/absolute intra-package import keep working, and
the file still parses as ordinary Python. The embedding is lossless (the exec'd text is byte-identical
to each source file), so the bundle is trivially correct — proven by diffing its CLI output against
the package's.

Usage:
  python builder_components/_assemble.py            # (re)generate scripts/skill_builder.py
  python builder_components/_assemble.py --check     # exit 1 if the committed file is stale (CI/PR guard)
  python skill_builder.py --rebuild [--check]        # the same, via the all-in-one's convenience flag

This file is the only part of the package NOT included in the bundle (it is a build-time dev tool).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent          # .../scripts/builder_components
SCRIPTS_DIR = PKG_DIR.parent                        # .../scripts
OUT = SCRIPTS_DIR / "skill_builder.py"
PACKAGES = ("builder_components", "builder_components.util")


def _fqname(path: Path) -> str:
    """Fully-qualified module name for a file under the package (``__init__.py`` -> the package name)."""
    parts = list(path.relative_to(PKG_DIR).parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
        return "builder_components" + ("." + ".".join(parts) if parts else "")
    parts[-1] = parts[-1][:-3]  # drop .py
    return "builder_components." + ".".join(parts)


def _package_of(fqname: str) -> str:
    """The package a module lives in (a package is its own package; a module's is its parent)."""
    return fqname if fqname in PACKAGES else fqname.rpartition(".")[0]


def collect_sources() -> dict[str, str]:
    """Map every component fqname -> its verbatim source (excluding this compiler). Sorted input order
    for deterministic output."""
    sources: dict[str, str] = {}
    for path in sorted(PKG_DIR.rglob("*.py")):
        if path.name == "_assemble.py":
            continue
        sources[_fqname(path)] = path.read_text(encoding="utf-8")
    return sources


def _intra_deps(fqname: str, source: str, known: set[str]) -> set[str]:
    """The intra-package modules `fqname` imports (resolving relative + absolute forms), restricted to
    names actually present in the package (stdlib imports are ignored)."""
    base = _package_of(fqname)
    deps: set[str] = set()

    def add(target: str) -> None:
        """Record `target` as a dependency if it is a known package module (and not this module)."""
        if target in known and target != fqname:
            deps.add(target)

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.level:  # relative: `from . import x` / `from .x import y` / `from .util.z import y`
                target = base + ("." + node.module if node.module else "")
                if node.module:
                    add(target)
                for alias in node.names:  # `from . import recontext_core` -> a submodule import
                    add(target + "." + alias.name)
            elif node.module and node.module.startswith("builder_components"):
                add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("builder_components"):
                    add(alias.name)
    return deps


def topo_order(sources: dict[str, str]) -> list[str]:
    """Dependency order (leaves first, `cli` last): the two packages first, then a deterministic
    topological sort of the remaining modules by their intra-package imports. Raises on a cycle."""
    known = set(sources)
    modules = [n for n in sorted(sources) if n not in PACKAGES]
    deps = {n: _intra_deps(n, sources[n], known) - set(PACKAGES) for n in modules}

    order: list[str] = [p for p in PACKAGES if p in sources]
    placed = set(order)
    remaining = list(modules)
    while remaining:
        ready = sorted(n for n in remaining if deps[n] <= placed)
        if not ready:
            raise RuntimeError(f"import cycle among: {sorted(remaining)}")
        for n in ready:
            order.append(n)
            placed.add(n)
            remaining.remove(n)
    return order


def _embed(source: str) -> str:
    """Escape a module's source for embedding inside a triple-double-quoted literal, losslessly: every
    backslash is doubled and every ``\"\"\"`` is escaped, so exec of the literal reproduces the source
    byte-for-byte. Real newlines are preserved (the embedded block stays line-readable)."""
    return source.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


_HEADER = '''#!/usr/bin/env python3
"""GENERATED — DO NOT EDIT. The all-in-one skill_builder tool.

Rebuild after editing the source components with:  python builder_components/_assemble.py
(or `python skill_builder.py --rebuild`). Every component's verbatim source is embedded in the _SRC
dict below, each under a `# ===MODULE` banner; the bootstrap registers each as a builder_components.*
module (in dependency order) and runs the CLI. The editable source of truth is the sibling
builder_components/ package; each component is also usable on its own via
`python -m builder_components.<module>`.
"""
import os as _os
import sys as _sys
import types as _types

_PACKAGES = {"builder_components", "builder_components.util"}
_ORDER = __ORDER__
# Where the editable component package lives, beside this file. Each embedded module's __file__ is set
# to its real source path so the few load-time `__file__` users (recontext's scripts/ locator, readme's
# template locator) resolve exactly as they do when run as the package. Module IMPORTS still resolve
# purely from the embedded _SRC (no disk dependency); only those data-file lookups touch disk.
_PKG = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "builder_components")


def _modfile(name):
    """Real on-disk source path for an embedded module (used as its __file__)."""
    rel = name.split(".")[1:]
    if name in _PACKAGES:
        return _os.path.join(_PKG, *rel, "__init__.py")
    return _os.path.join(_PKG, *rel) + ".py"


def _bootstrap():
    """Register every embedded component as a real module (in _ORDER) and exec its source there."""
    for name in _ORDER:
        mod = _types.ModuleType(name)
        mod.__file__ = _modfile(name)
        if name in _PACKAGES:
            mod.__path__ = []
            mod.__package__ = name
        else:
            mod.__package__ = name.rpartition(".")[0]
        _sys.modules[name] = mod
        exec(compile(_SRC[name], mod.__file__, "exec"), mod.__dict__)
        parent, _, leaf = name.rpartition(".")
        if parent and parent in _sys.modules:
            setattr(_sys.modules[parent], leaf, mod)


_SRC = {}
'''

_FOOTER = '''
_bootstrap()
from builder_components.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
'''


def render() -> str:
    """Build the full text of the self-contained `skill_builder.py` from the current components."""
    sources = collect_sources()
    order = topo_order(sources)
    order_literal = "[\n    " + ",\n    ".join(repr(n) for n in order) + ",\n]"
    out = [_HEADER.replace("__ORDER__", order_literal)]
    for name in order:
        out.append(f'\n# ===MODULE {name}===\n_SRC[{name!r}] = """\n{_embed(sources[name])}"""\n')
    out.append(_FOOTER)
    return "".join(out)


def main(argv=None) -> int:
    """Generate the bundle, or (`--check`) verify the committed bundle is in sync with the components.

    Returns 0 on success / in-sync; 1 if `--check` finds drift; 2 on a usage error. `--check` is the
    guard for public PRs: a contributor who edits a component must re-run the compiler so the committed
    `skill_builder.py` matches the source.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    check = False
    for a in args:
        if a == "--check":
            check = True
        else:
            print(f"usage: python builder_components/_assemble.py [--check]  (got {a!r})", file=sys.stderr)
            return 2
    text = render()
    if check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current == text:
            print(f"in sync: {OUT.name} matches the components")
            return 0
        print(f"DRIFT: {OUT.name} is stale — run `python builder_components/_assemble.py` to rebuild.",
              file=sys.stderr)
        return 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(text.splitlines())} lines, {text.count('# ===MODULE ')} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
