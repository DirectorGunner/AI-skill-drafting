#!/usr/bin/env python3
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
_ORDER = [
    'builder_components',
    'builder_components.util',
    'builder_components.htmlmd',
    'builder_components.index',
    'builder_components.readme',
    'builder_components.recontext_core',
    'builder_components.util.config',
    'builder_components.util.frontmatter',
    'builder_components.util.repo_paths',
    'builder_components.util.text_io',
    'builder_components.finalize',
    'builder_components.ingest',
    'builder_components.policy_engine',
    'builder_components.recontext',
    'builder_components.recontext_subagent',
    'builder_components.validate',
    'builder_components.corpus',
    'builder_components.policy_cmd',
    'builder_components.packing',
    'builder_components.build',
    'builder_components.maintain',
    'builder_components.split_engine',
    'builder_components.lint',
    'builder_components.split_cmd',
    'builder_components.cli',
]
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

# ===MODULE builder_components===
_SRC['builder_components'] = """
\"\"\"builder_components — the skill-drafting tooling package.

One importable home for the skill build/maintain pipeline (`skill_builder`), the package
validator, the skill-invocation-policy manager, and the recontextualization engine + locked
writer. The loose scripts in `scripts/` are thin launchers that delegate here so every
documented invocation path (and the VALIDATOR path baked into built skills' SKILL.md) keeps
working. Shared, single-concern helpers live under `builder_components.util`.

Stdlib only; no third-party dependencies.
\"\"\"
"""

# ===MODULE builder_components.util===
_SRC['builder_components.util'] = """
\"\"\"builder_components.util — single-concern helpers shared across the tooling modules.

Each module here holds one canonical copy of a helper that was previously duplicated across the
standalone scripts (frontmatter parsing, project-root resolution, the LF-forced file writer).
Splitting the monoliths into submodules turns these former in-file helpers into genuinely shared
utilities, so they live here once and every consumer imports them.
\"\"\"
"""

# ===MODULE builder_components.htmlmd===
_SRC['builder_components.htmlmd'] = """
\"\"\"HTML -> Markdown conversion (was the htmlmd.py section of skill_builder.py).\"\"\"

from __future__ import annotations

import html
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin


# ==============================================================================
# SHARED — HTML -> Markdown (was htmlmd.py)
# ==============================================================================

_SKIP = {"script", "style", "head", "nav", "header", "footer", "aside", "noscript", "svg", "button", "form"}
_BLOCK = {"p", "div", "section", "article", "ul", "ol", "li", "pre", "blockquote", "table",
          "tr", "thead", "tbody", "h1", "h2", "h3", "h4", "h5", "h6", "hr"}


class _MD(HTMLParser):
    \"\"\"Streaming HTML parser that emits Markdown, collecting headings and tables as it goes.\"\"\"

    def __init__(self, base_url: str = ""):
        \"\"\"Initialize parser state; base_url resolves relative link/image hrefs.\"\"\"
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.out: list[str] = []
        self.skip_depth = 0
        self.pre_depth = 0          # inside <pre> (code block)
        self.code_inline = 0        # inside inline <code> (not in pre)
        self.pre_lang = ""
        self.list_stack: list[str] = []   # 'ul'/'ol' with counters
        self.ol_counters: list[int] = []
        self.href: str | None = None
        self.link_text: list[str] = []
        self.in_table = False
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.table_rows: list[list[str]] = []
        self.table_header_done = False
        self.headings: list[tuple[int, str, str]] = []   # (level, text, id) for callers
        self._cur_id = ""
        self._cur_h: list | None = None
        self._a_class = ""          # class of the anchor currently open (to drop ¶ headerlinks)

    # ---- helpers ----
    def _emit(self, s: str):
        \"\"\"Append text to the current sink: open table cell, open link text, or main output.\"\"\"
        if self.cell is not None:
            self.cell.append(s)
        elif self.link_text and self.href is not None:
            self.link_text.append(s)
        else:
            self.out.append(s)

    def _nl(self, n=1):
        \"\"\"Emit n newlines to the main output, but only when not inside a cell or link text.\"\"\"
        if self.cell is None and not (self.link_text and self.href is not None):
            self.out.append("\\n" * n)

    # ---- tags ----
    def handle_starttag(self, tag, attrs):
        \"\"\"Translate an opening HTML tag into its Markdown prefix and update parser state.\"\"\"
        a = dict(attrs)
        if self.skip_depth or tag in _SKIP:
            if tag in _SKIP:
                self.skip_depth += 1
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            lvl = int(tag[1])
            self._nl(2)
            self._emit("#" * lvl + " ")
            self._cur_h = [lvl, [], a.get("id", "")]
            self._cur_id = a.get("id", "")
        elif tag == "p":
            self._nl(2)
        elif tag == "br":
            self._emit("  \\n")
        elif tag == "hr":
            self._nl(2); self._emit("---"); self._nl(2)
        elif tag == "pre":
            if not self.pre_lang and "rust" in a.get("class", ""):
                self.pre_lang = "rust"   # rustdoc: <pre class="rust item-decl">
            self.pre_depth += 1
            self._nl(2); self._emit("```" + self.pre_lang); self._nl(1)
        elif tag == "code":
            cls = a.get("class", "")
            m = re.search(r"language-([\\w+-]+)", cls) or re.search(r"\\b(rust|python|bash|sh|json|toml|c|cpp|js|ts|html)\\b", cls)
            if self.pre_depth:
                pass  # text captured verbatim
            else:
                self.code_inline += 1
                self._emit("`")
            if m and self.pre_depth:
                self.pre_lang = m.group(1)
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "a":
            if not self.pre_depth:   # inside a code fence, anchors emit their text only (clean signatures)
                self.href = a.get("href", "")
                self._a_class = a.get("class", "") or ""
                self.link_text = [""]
        elif tag == "dt":          # definition-list term (Sphinx API signature) -> own line
            self._nl(2)
        elif tag == "dd":          # definition body (the description) -> indented new line
            self._nl(1)
        elif tag == "div":         # Sphinx code wrapper carries the language: highlight-<lang>
            cls = a.get("class", "")
            m = re.search(r"highlight-(\\w+)", cls)
            if m:
                lang = m.group(1).lower()
                self.pre_lang = {"default": "python", "python3": "python", "ipython3": "python",
                                 "pycon": "pycon", "pycon3": "pycon", "py": "python"}.get(lang, lang)
        elif tag == "ul":
            self.list_stack.append("ul"); self.ol_counters.append(0)
        elif tag == "ol":
            self.list_stack.append("ol"); self.ol_counters.append(0)
        elif tag == "li":
            self._nl(1)
            indent = "  " * (len(self.list_stack) - 1)
            if self.list_stack and self.list_stack[-1] == "ol":
                self.ol_counters[-1] += 1
                self._emit(f"{indent}{self.ol_counters[-1]}. ")
            else:
                self._emit(f"{indent}- ")
        elif tag == "blockquote":
            self._nl(2); self._emit("> ")
        elif tag == "table":
            self.in_table = True; self.table_rows = []; self.table_header_done = False
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
        elif tag == "img":
            alt = a.get("alt", "").strip()
            src = a.get("src", "")
            cap = alt or re.sub(r"[-_]+", " ", re.sub(r"\\.[a-z0-9]+$", "", src.rsplit("/", 1)[-1], flags=re.I))
            self._emit(f"(Figure: {cap})")

    def handle_endtag(self, tag):
        \"\"\"Translate a closing HTML tag into its Markdown suffix and finalize state (links, tables).\"\"\"
        if tag in _SKIP and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if self._cur_h:
                txt = "".join(self._cur_h[1]).replace("​", "").strip()
                self.headings.append((self._cur_h[0], txt, self._cur_h[2]))
                self._cur_h = None
            self._nl(2)
        elif tag == "pre":
            if self.pre_depth:
                self.pre_depth -= 1
                self._nl(1); self._emit("```"); self._nl(2); self.pre_lang = ""
        elif tag == "code" and not self.pre_depth and self.code_inline:
            self.code_inline -= 1; self._emit("`")
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "a":
            if self.href is None:   # no open link (e.g. an anchor inside <pre>): text already emitted verbatim
                self._a_class = ""; self.link_text = []
            else:
                text = "".join(self.link_text).strip()
                href = self.href; acls = self._a_class
                self.href = None; self.link_text = []; self._a_class = ""
                if "headerlink" in acls or text in ("¶", "#"):
                    pass  # Sphinx permalink pilcrow (¶) — drop it
                elif href and not href.startswith("#") and text:
                    url = urljoin(self.base, href) if self.base else href
                    self._emit(f"[{text}]({url})")
                else:
                    self._emit(text)
        elif tag in ("dt", "dd"):
            self._nl(1)
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop(); self.ol_counters.pop()
            self._nl(1)
        elif tag in ("p", "blockquote"):
            self._nl(2)
        elif tag in ("td", "th"):
            if self.row is not None and self.cell is not None:
                self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr":
            if self.row is not None:
                self.table_rows.append(self.row); self.row = None
        elif tag == "table":
            self._flush_table(); self.in_table = False

    def handle_data(self, data):
        \"\"\"Emit text content; verbatim inside <pre>, whitespace-collapsed elsewhere.\"\"\"
        if self.skip_depth:
            return
        if self.pre_depth:
            self._emit(data)
            return
        text = data
        if self._cur_h is not None:
            self._cur_h[1].append(text)
        # collapse whitespace outside code/pre
        collapsed = re.sub(r"\\s+", " ", text)
        if collapsed:
            self._emit(collapsed)

    def _flush_table(self):
        \"\"\"Render the collected table rows as a padded GFM Markdown table into the output.\"\"\"
        rows = [r for r in self.table_rows if r]
        if not rows:
            return
        self.out.append("\\n")
        ncols = max(len(r) for r in rows)
        head = rows[0] + [""] * (ncols - len(rows[0]))
        self.out.append("| " + " | ".join(head) + " |\\n")
        self.out.append("| " + " | ".join(["---"] * ncols) + " |\\n")
        for r in rows[1:]:
            r = r + [""] * (ncols - len(r))
            self.out.append("| " + " | ".join(r) + " |\\n")
        self.out.append("\\n")


def _balanced_div_inner(html: str, open_match: "re.Match") -> str:
    \"\"\"Given a match for an opening <div ...>, return its inner HTML up to the matching </div>
    (depth-balanced — handles the nested divs that a non-greedy regex would stop short on).\"\"\"
    start = open_match.end()
    depth = 1
    for m in re.finditer(r"<div\\b|</div\\s*>", html[start:], re.IGNORECASE):
        if m.group(0)[1] == "/":
            depth -= 1
            if depth == 0:
                return html[start:start + m.start()]
        else:
            depth += 1
    return html[start:]


def split_main(html: str) -> str:
    \"\"\"Return the inner HTML of the doc body. Tries, in order: a div with role="main" (Sphinx),
    <main>, <div id="content">, <body>, else the whole document.\"\"\"
    m = re.search(r'<div\\b[^>]*\\brole=["\\']main["\\'][^>]*>', html, re.IGNORECASE)
    if m:
        return _balanced_div_inner(html, m)
    for pat in (r"<main\\b[^>]*>(.*?)</main>", r'<div[^>]*id="content"[^>]*>(.*?)</div>\\s*</div>'):
        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1)
    m = re.search(r"<body\\b[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else html


def html_to_md(html: str, base_url: str = "") -> tuple[str, list]:
    \"\"\"Convert HTML to Markdown. Returns (markdown, headings) where headings is a list of
    (level, text, id). Pass the doc body (use split_main first for full pages).\"\"\"
    p = _MD(base_url)
    p.feed(html)
    md = "".join(p.out)
    md = unescape(md)
    md = md.replace("​", "")                  # strip zero-width-space anchor artifacts
    md = re.sub(r"(?m)^[ \\t]*#{1,6}[ \\t]*$", "", md)  # drop headings left empty after that
    md = re.sub(r"[ \\t]+\\n", "\\n", md)
    md = re.sub(r"\\n{3,}", "\\n\\n", md)
    return md.strip() + "\\n", p.headings
"""

# ===MODULE builder_components.index===
_SRC['builder_components.index'] = """
\"\"\"Build the cross-skill master index (was the index section of skill_builder.py).\"\"\"

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path


# ==============================================================================
# INDEX — cross-skill master index (was build_master_index.py)
# ==============================================================================

_STOP = {"and", "the", "for", "with", "use", "using", "a", "an", "to", "of", "in", "on", "or"}


def parse_frontmatter(text: str) -> dict:
    \"\"\"Line-based YAML-lite parse of the SKILL.md frontmatter: handles inline scalars, folded/literal
    block scalars (`>-`, `>`, `|`), inline lists (`[a, b]`), and block lists (`- a`).\"\"\"
    m = re.match(r"^---\\n(.*?)\\n---", text, re.DOTALL)
    if not m:
        return {}
    lines = m.group(1).split("\\n")
    fm, i = {}, 0
    while i < len(lines):
        km = re.match(r"^(\\w+):\\s?(.*)$", lines[i])
        if not km:
            i += 1
            continue
        key, val = km.group(1), km.group(2).strip()
        if val in (">-", ">", ">+", "|", "|-", "|+"):                 # block scalar
            buf, i = [], i + 1
            while i < len(lines) and (lines[i].startswith((" ", "\\t")) or not lines[i].strip()):
                buf.append(lines[i].strip()); i += 1
            fm[key] = " ".join(x for x in buf if x)
            continue
        if val.startswith("[") and val.endswith("]"):                # inline list
            fm[key] = [x.strip().strip("'\\"") for x in val[1:-1].split(",") if x.strip()]
        elif val == "":                                              # maybe a block list follows
            buf, j = [], i + 1
            while j < len(lines) and re.match(r"^\\s+-\\s", lines[j]):
                buf.append(re.match(r"^\\s+-\\s*(.+)", lines[j]).group(1).strip().strip("'\\"")); j += 1
            fm[key] = buf if buf else ""
            i = j if buf else i + 1
            continue
        else:
            fm[key] = val.strip("'\\"")
        i += 1
    return fm


def derive_covers(skill: Path) -> list:
    \"\"\"Entities a skill covers. Router → its sub-skill area names (clean). Flat → distinctive
    topics.json keywords filtered to clean single-concept terms (drops concatenated slugs).\"\"\"
    subs = [d.name for d in sorted(skill.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]
    if subs:
        return subs
    terms = collections.Counter()
    tj = skill / "references" / "topics.json"
    if tj.is_file():
        try:
            d = json.loads(tj.read_text(encoding="utf-8"))
        except Exception:
            d = {"topics": []}
        for t in d.get("topics", []):
            for kw in t.get("keywords", []):
                k = str(kw).replace("_", "-").strip().lower()
                if k and k not in _STOP and 3 <= len(k) <= 30 and k.count("-") <= 3 and not k.isdigit():
                    terms[k] += 1
    return [t for t, _ in terms.most_common()]


def seed_covers_in_skill(skill: Path, covers: list) -> bool:
    \"\"\"Insert/replace a `covers:` block list in a SKILL.md frontmatter, preserving the bespoke body
    byte-for-byte. Idempotent: an existing covers: block (inline or list) is stripped and rewritten.\"\"\"
    p = skill / "SKILL.md"
    text = p.read_text(encoding="utf-8")
    m = re.match(r"^(---\\n)(.*?)(\\n---\\n)", text, re.DOTALL)
    if not m:
        return False
    lines = m.group(2).split("\\n")
    out, i = [], 0
    while i < len(lines):
        cm = re.match(r"^covers:\\s*(\\S.*)?$", lines[i])
        if cm:
            i += 1
            if not cm.group(1):                       # block list follows — drop its items too
                while i < len(lines) and re.match(r"^\\s+-\\s", lines[i]):
                    i += 1
            continue
        out.append(lines[i]); i += 1
    body = "\\n".join(out).rstrip("\\n")
    block = "covers:\\n" + "\\n".join(f"  - {c}" for c in covers)
    p.write_text(m.group(1) + body + "\\n" + block + m.group(3) + text[m.end():],
                 encoding="utf-8", newline="\\n")
    return True


def skill_info(skill: Path) -> dict:
    \"\"\"Return a skill's {name, trigger, covers} summary, deriving covers when not in frontmatter and
    using the description's first sentence (capped at 200 chars) as the trigger.\"\"\"
    fm = parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8")) if (skill / "SKILL.md").is_file() else {}
    covers = fm.get("covers") or derive_covers(skill)
    desc = fm.get("description", "")
    trigger = re.split(r"(?<=[.])\\s", desc, 1)[0] if desc else ""
    return {"name": fm.get("name", skill.name), "trigger": trigger[:200], "covers": covers}


def build_master_text(root: Path) -> str:
    \"\"\"Build the master INDEX.md Markdown for a skills root: a skills catalog table, a related-skills
    list, and an entity->skill map for entities shared by more than one skill.\"\"\"
    skills = [d for d in sorted(root.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]
    infos = {d.name: skill_info(d) for d in skills}

    # Catalog column shows the curated `covers:` (capped); the overlap map/related-skills use the
    # fuller derived entity set, so genuine cross-references aren't hidden by the display cap.
    ent2skill = collections.defaultdict(set)
    for d in skills:
        for e in derive_covers(d):
            ent2skill[e].add(d.name)

    related = collections.defaultdict(collections.Counter)
    for e, owners in ent2skill.items():
        if len(owners) > 1:
            for a in owners:
                for b in owners:
                    if a != b:
                        related[a][b] += 1

    out = ["# Skills — Master Index", "",
           "Catalog of every skill in this folder, with the entities/domains each covers and which "
           "skills are related. A discovery / audit entry point — agents still route via each skill's "
           "`description`. Generated by `skill-drafting/scripts/skill_builder.py index`.", "",
           "## Skills", "", "| Skill | Covers (top) | Trigger |", "| --- | --- | --- |"]
    for name in sorted(infos):
        info = infos[name]
        cov = ", ".join(info["covers"][:8]) + (" …" if len(info["covers"]) > 8 else "")
        out.append(f"| [{name}]({name}/SKILL.md) | {cov} | {info['trigger']} |")

    out += ["", "## Related skills", "", "Skills that share covered entities:", ""]
    for name in sorted(related):
        rel = ", ".join(f"{b} ({n})" for b, n in related[name].most_common(6))
        out.append(f"- **{name}** ↔ {rel}")
    if not related:
        out.append("- (no shared entities across skills)")

    shared = {e: sorted(s) for e, s in ent2skill.items() if len(s) > 1}
    out += ["", "## Entity → skill map (shared)", "",
            "Entities documented by more than one skill (where to look, and overlaps):", "",
            "| Entity | Skills |", "| --- | --- |"]
    for e in sorted(shared):
        out.append(f"| {e} | {', '.join(shared[e])} |")
    if not shared:
        out.append("| (none) | |")
    return "\\n".join(out).rstrip() + "\\n"


def cmd_index(argv=None) -> int:
    \"\"\"Run the `index` subcommand: optionally seed each SKILL.md `covers:` frontmatter, then write the
    master INDEX.md to the root (and any --mirror root). Returns an exit code.\"\"\"
    ap = argparse.ArgumentParser(prog="skill_builder.py index")
    ap.add_argument("root", help="a skills root, e.g. .agents/skills")
    ap.add_argument("--mirror", help="also write the identical index to this skills root")
    ap.add_argument("--seed-covers", action="store_true",
                    help="seed/refresh each SKILL.md `covers:` frontmatter from derived entities "
                         "(routers: all area names; flat: top 12). Also seeds --mirror for parity.")
    ap.add_argument("--flat-cap", type=int, default=12, help="max covers entries for a flat skill")
    args = ap.parse_args(argv)
    root = Path(args.root)

    if args.seed_covers:
        roots = [root] + ([Path(args.mirror)] if args.mirror else [])
        for d in sorted(root.iterdir()):
            if not (d.is_dir() and (d / "SKILL.md").is_file()):
                continue
            is_router = any(c.is_dir() and (c / "SKILL.md").is_file() for c in d.iterdir())
            covers = derive_covers(d)
            if not is_router:
                covers = covers[:args.flat_cap]
            for r in roots:
                if (r / d.name / "SKILL.md").is_file() and seed_covers_in_skill(r / d.name, covers):
                    print(f"seeded covers ({len(covers)}) -> {(r / d.name).as_posix()}/SKILL.md")

    text = build_master_text(root)
    (root / "INDEX.md").write_text(text, encoding="utf-8", newline="\\n")
    print(f"wrote {root}/INDEX.md ({text.count(chr(10))} lines)")
    if args.mirror:
        mroot = Path(args.mirror)
        (mroot / "INDEX.md").write_text(text, encoding="utf-8", newline="\\n")
        print(f"wrote {mroot}/INDEX.md (mirror)")
    return 0

def main(argv=None) -> int:
    \"\"\"Standalone entry point for `python -m builder_components.index`; delegates to cmd_index.\"\"\"
    return cmd_index(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.readme===
_SRC['builder_components.readme'] = """
\"\"\"Skill README scaffold/apply against the single-sourced standard (was the readme section).\"\"\"

from __future__ import annotations

import argparse
import re
from pathlib import Path


# ==============================================================================
# README STANDARD — scaffold + managed-region apply (single-sourced template)
# ==============================================================================
# A skill's public README.md is part constant boilerplate and part per-skill prose. The constant
# blocks — the "Part of Agent Kaizen" intro paragraph, the full %DEVROOT% "Use it" section, the
# idle-context policy section, and the License — are single-sourced in references/readme-standard.md
# and re-applied in place. Regions are located by MARKDOWN STRUCTURE, never by HTML-comment markers:
# the intro by its leading "Part of **[Agent Kaizen](" text, the others as whole `## ` sections (the
# heading through the line before the next `## `). Shippable READMEs therefore carry NO tool markers;
# everything outside the managed regions is author-owned and never rewritten. No README prose lives here.

def _readme_store_root() -> Path:
    \"\"\"The skills store this package ships inside
    (skills/skill-drafting/scripts/builder_components -> skills).\"\"\"
    return Path(__file__).resolve().parents[3]


def _readme_default_template() -> Path:
    \"\"\"Path to the single-sourced README standard (skill-drafting/references/readme-standard.md).\"\"\"
    # this module lives in skills/skill-drafting/scripts/builder_components/; the standard is two
    # levels up under skill-drafting/references/.
    return Path(__file__).resolve().parents[2] / "references" / "readme-standard.md"


def _readme_skill_dirs(store: Path):
    \"\"\"Return the skill directories (those containing a SKILL.md) directly under `store`, sorted.\"\"\"
    return [d for d in sorted(store.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]


def _readme_fill(text: str, *, skill=None, title=None, tagline=None, article=None) -> str:
    \"\"\"Substitute the {{skill}}/{{title}}/{{tagline}}/{{article}} placeholders present in `text`.\"\"\"
    for token, val in (("{{skill}}", skill), ("{{title}}", title),
                       ("{{tagline}}", tagline), ("{{article}}", article)):
        if val is not None:
            text = text.replace(token, val)
    return text


def _readme_strip(block):
    \"\"\"Drop leading/trailing blank lines from a list of lines.\"\"\"
    s, e = 0, len(block)
    while s < e and block[s].strip() == "":
        s += 1
    while e > s and block[e - 1].strip() == "":
        e -= 1
    return block[s:e]


#: Managed regions, in document order. Each is located by markdown structure (see _readme_region_locate);
#: their canonical content is single-sourced from the template skeletons. `intro` and `license` are
#: Pattern A only; `use-it` and `idle-context` appear in every skill (presence-driven, so absent regions
#: are simply skipped).
_README_REGIONS = ("intro", "use-it", "idle-context", "license")

#: Heading prefix that locates each `## ` section region (intro is located separately, by leading text).
_README_HEADINGS = {
    "use-it": "## Use it",
    "idle-context": "## Reducing idle context cost",
    "license": "## License",
}


def _readme_region_locate(lines, name):
    \"\"\"Span (lo, hi) of a managed region located by markdown structure, or None if absent. `intro` is the
    single 'Part of **[Agent Kaizen](' paragraph; the rest are whole `## ` sections (heading through the
    line before the next `## `).\"\"\"
    if name == "intro":
        return _readme_anchor_intro(lines)
    prefix = _README_HEADINGS.get(name)
    return _readme_anchor_section(lines, prefix) if prefix else None


def _readme_strip_markers(lines):
    \"\"\"Remove any leftover '<!-- ak:readme:* -->' marker lines and collapse the resulting blank runs to a
    single blank, outside fenced code blocks. Idempotent; un-migrates READMEs that still carry markers.\"\"\"
    marker = re.compile(r"<!-- ak:readme:.*(START|END) -->$")
    kept, in_fence = [], False
    for ln in lines:
        s = ln.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            kept.append(ln)
            continue
        if not in_fence and marker.match(s):
            continue
        kept.append(ln)
    out, in_fence = [], False
    for ln in kept:
        s = ln.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            out.append(ln)
            continue
        if not in_fence and s == "" and out and out[-1].strip() == "":
            continue
        out.append(ln)
    return out


def _readme_parse_template(path: Path):
    \"\"\"Return (regions, skeletons). The template holds the markerless Pattern A/B exemplar READMEs in its
    >=4-backtick fenced blocks; regions[name] = canonical content lines, extracted from the Pattern A
    skeleton by the SAME markdown anchors the tool uses on real READMEs (so the standard and the detection
    can never drift apart).\"\"\"
    lines = path.read_text(encoding="utf-8").split("\\n")
    skel = []
    i = 0
    while i < len(lines):
        f = re.match(r"(`{4,})", lines[i])
        if f and "markdown" in lines[i]:
            fence = f.group(1)
            for j in range(i + 1, len(lines)):
                s = lines[j].strip()
                if s and set(s) == {"`"} and len(s) >= len(fence):
                    skel.append(lines[i + 1:j])
                    i = j
                    break
        i += 1
    skeletons = {}
    if skel:
        skeletons["a"] = "\\n".join(skel[0])
    if len(skel) >= 2:
        skeletons["b"] = "\\n".join(skel[1])
    regions = {}
    if skel:
        a = skel[0]
        for name in _README_REGIONS:
            span = _readme_region_locate(a, name)
            if span:
                lo, hi = span
                regions[name] = _readme_strip(a[lo:hi])
    return regions, skeletons


def _readme_refresh(lines, regions, skill):
    \"\"\"Replace each managed region (located by markdown structure) with the canonical content from the
    template, where the region is present. Presence-driven. Returns (new_lines, changed_region_names).\"\"\"
    changed = []
    for name in _README_REGIONS:
        if name not in regions:
            continue
        span = _readme_region_locate(lines, name)
        if not span:
            continue
        lo, hi = span
        canonical = [_readme_fill(ln, skill=skill) for ln in regions[name]]
        if lines[lo:hi] != canonical:
            lines = lines[:lo] + canonical + lines[hi:]
            changed.append(name)
    return lines, changed


def _readme_anchor_intro(lines):
    \"\"\"Span (lo, hi) of the single 'Part of **[Agent Kaizen]' intro paragraph, or None if absent.\"\"\"
    for i, ln in enumerate(lines):
        if ln.startswith("Part of **[Agent Kaizen]"):
            return (i, i + 1)
    return None


def _readme_anchor_section(lines, prefix):
    \"\"\"Span (lo, hi) of the `## ` section whose heading starts with `prefix` — heading line through
    the last non-blank line before the next `## ` heading — or None if absent.\"\"\"
    for i, ln in enumerate(lines):
        if ln.startswith(prefix):
            last, j = i, i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                if lines[j].strip():
                    last = j
                j += 1
            return (i, last + 1)
    return None


def _readme_ensure_full_use_it(lines, content_lines):
    \"\"\"Ensure a '## Use it' section exists (`content_lines` = the canonical use-it section, heading
    included). If the heading is already present, leave it for refresh; otherwise insert the canonical
    section right after the '## What's inside' section. Returns (new_lines, acted).\"\"\"
    if any(l.strip() == "## Use it" for l in lines):
        return lines, False
    wi = next((i for i, l in enumerate(lines) if l.strip() == "## What's inside"), None)
    if wi is None:
        return lines, False
    last, j = wi, wi + 1
    while j < len(lines) and not lines[j].startswith("## "):
        if lines[j].strip():
            last = j
        j += 1
    return lines[:last + 1] + [""] + content_lines + lines[last + 1:], True


def _readme_targets(args, store):
    \"\"\"Resolve which skill dirs to act on: all of them (`--all`), the named ones, or None if neither
    was given (the caller treats None as a usage error). Unknown names are warned and skipped.\"\"\"
    dirs = _readme_skill_dirs(store)
    if args.all:
        return dirs
    if args.skills:
        by_name = {d.name: d for d in dirs}
        out = []
        for s in args.skills:
            if s in by_name:
                out.append(by_name[s])
            else:
                print(f"  ! unknown skill: {s}")
        return out
    return None


def _readme_scaffold(args, store, tmpl) -> int:
    \"\"\"Write a brand-new README.md for one skill from the Pattern A/B skeleton, placeholders filled.

    Refuses to overwrite an existing README without --force. Returns 0 on write, 1 if it would
    overwrite, 2 if the requested pattern has no skeleton in the template.
    \"\"\"
    regions, skeletons = _readme_parse_template(tmpl)
    if args.pattern not in skeletons:
        print(f"template has no Pattern {args.pattern.upper()} skeleton")
        return 2
    skill = args.skill
    out_dir = Path(args.dir).resolve() if args.dir else (store / skill)
    readme = out_dir / "README.md"
    if readme.exists() and not args.force:
        print(f"refusing to overwrite {readme} (use --force)")
        return 1
    title = args.title if args.title is not None else skill
    tagline = args.tagline if args.tagline is not None else f"_TODO: one-line summary of the {skill} skill._"
    body = _readme_fill(skeletons[args.pattern], skill=skill, title=title,
                        tagline=tagline, article=args.article)
    if not body.endswith("\\n"):
        body += "\\n"
    out_dir.mkdir(parents=True, exist_ok=True)
    readme.write_text(body, encoding="utf-8", newline="\\n")
    print(f"WROTE {readme} (Pattern {args.pattern.upper()})")
    return 0


def _readme_apply(args, store, tmpl) -> int:
    \"\"\"Refresh the managed regions of existing skill READMEs from the single-sourced standard.

    For each target: strip any legacy markers, optionally ensure a full "Use it" section
    (--ensure-use-it), then replace each present managed region with the template's canonical content.
    Honors --dry-run (no writes) and --check (exit 1 on any drift). Returns the process exit code.
    \"\"\"
    regions, _ = _readme_parse_template(tmpl)
    targets = _readme_targets(args, store)
    if targets is None:
        print("specify skill name(s) or --all")
        return 2
    rc, drift = 0, False
    for d in targets:
        readme = d / "README.md"
        if not readme.is_file():
            print(f"  ! {d.name}: no README.md")
            rc = max(rc, 1)
            continue
        text = readme.read_text(encoding="utf-8")
        new_lines = _readme_strip_markers(text.split("\\n"))
        acted = []
        if args.ensure_use_it and "use-it" in regions:
            canonical = [_readme_fill(ln, skill=d.name) for ln in regions["use-it"]]
            new_lines, did = _readme_ensure_full_use_it(new_lines, canonical)
            if did:
                acted.append("insert use-it")
        new_lines, changed = _readme_refresh(new_lines, regions, d.name)
        acted += changed
        new_text = "\\n".join(new_lines)
        if new_text == text:
            print(f"  unchanged {d.name}")
            continue
        if not acted:
            acted = ["stripped markers"]
        if args.check:
            print(f"  DRIFT {d.name}: would update ({', '.join(acted)})")
            drift = True
            continue
        if args.dry_run:
            print(f"  [dry-run] {d.name}: would update ({', '.join(acted)})")
            continue
        readme.write_text(new_text, encoding="utf-8", newline="\\n")
        print(f"  WROTE {d.name}: {', '.join(acted)}")
    return 1 if (args.check and drift) else rc


def cmd_readme(argv=None) -> int:
    \"\"\"Parse the `readme` CLI (`scaffold` | `apply`) and dispatch to the matching handler.

    Resolves the store root and the README standard template, then scaffolds a new README or applies
    the standard to existing ones. Returns the process exit code.
    \"\"\"
    ap = argparse.ArgumentParser(
        prog="skill_builder.py readme",
        description="Scaffold and maintain skill README.md files from the single-sourced standard "
                    "(references/readme-standard.md).")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", help="skills store root (default: the store this script lives in)")
    common.add_argument("--template", help="standard/template file (default: references/readme-standard.md)")
    sub = ap.add_subparsers(dest="op", required=True)

    sp = sub.add_parser("scaffold", parents=[common], help="write a brand-new README.md from the standard")
    sp.add_argument("skill")
    sp.add_argument("--pattern", choices=["a", "b"], default="a",
                    help="a = full domain/reference skill; b = lighter/status-driven (default a)")
    sp.add_argument("--article", choices=["a", "the"], default="the")
    sp.add_argument("--title", default=None)
    sp.add_argument("--tagline", default=None)
    sp.add_argument("--dir", default=None, help="output directory (default: <store>/<skill>)")
    sp.add_argument("--force", action="store_true", help="overwrite an existing README.md")

    sp = sub.add_parser("apply", parents=[common],
                        help="refresh managed regions of existing READMEs (presence-driven)")
    sp.add_argument("skills", nargs="*", help="skill names (or use --all)")
    sp.add_argument("--all", action="store_true", help="every skill in the store")
    sp.add_argument("--ensure-use-it", action="store_true",
                    help="normalize: give every target skill the full 'Use it' section — insert it after "
                         "'What's inside' where absent — then refresh")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="print what would change; write nothing")
    g.add_argument("--check", action="store_true", help="exit 1 if any README is out of date; write nothing")

    args = ap.parse_args(argv)
    store = Path(args.store).resolve() if args.store else _readme_store_root()
    tmpl = Path(args.template).resolve() if args.template else _readme_default_template()
    if not tmpl.is_file():
        print(f"template not found: {tmpl}")
        return 2
    if args.op == "scaffold":
        return _readme_scaffold(args, store, tmpl)
    if args.op == "apply":
        return _readme_apply(args, store, tmpl)
    return 2

def main(argv=None) -> int:
    \"\"\"Standalone entry point for `python -m builder_components.readme`; delegates to cmd_readme.\"\"\"
    return cmd_readme(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.recontext_core===
_SRC['builder_components.recontext_core'] = """
#!/usr/bin/env python3
\"\"\"recontext_core.py — generalized, stdlib-only recontextualization primitives.

The portable core shared by `skill_builder.py` (its `recontext` command group) and
`recontext_subagent.py` (the locked artifact writer). It carries the proven, deterministic
algorithms for turning a *verbatim* documentation reference file into *original prose* while
preserving every identifier — and for verifying that it did:

  fence/code      is_fence, iter_lines, strip_code, code_blocks
  prose units     prose_units, prose_lines, prose_ratio, prose_text, is_prose_line
  cleanup         clean_text (chrome/scrape-artifact removal + marker normalize + blank collapse)
  extract/splice  extract (prose packet), load_rewrites, splice (tamper-proof re-insertion)
  triage          score_file, classify (faction/tier/mode by prose density)
  Gate A          extract_protected, gate_a  (protected-identifier multiset preserved)
  Gate B          gate_b                       (no >=13-word verbatim prose run shared w/ source)
  Gate C          gate_c                       (no residual scrape cruft)
  run_gates       all three gates over a (source, working) pair

NOTHING here is hardcoded to a skill, owner, repo, or absolute path: every location is supplied
by the caller. That is what makes the toolset broadly useful and lets the published skill ship a
self-contained engine with no gitignored dependency. Derived from the field-hardened recon-staged
pipeline (lib_recon/cleanup/extract/splice/gates/triage), kept algorithm-for-algorithm faithful so
verdicts match the originals.
\"\"\"
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

try:  # ensure tool stdout/stderr can emit any source glyph on a cp1252 Windows console
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# --------------------------------------------------------------------------- #
# Fence detection and code/prose separation.
# --------------------------------------------------------------------------- #
_FENCE = re.compile(r"^(?:`{3,}|~{3,})[\\w+.\\-]*$")


def is_fence(stripped: str) -> bool:
    \"\"\"True only for a clean opening/closing code-fence delimiter line.\"\"\"
    return bool(_FENCE.match(stripped))


def iter_lines(text):
    \"\"\"Yield (line, in_fence) for each line. The fence delimiter itself is in_fence=True.\"\"\"
    in_fence = False
    for ln in text.split("\\n"):
        if is_fence(ln.strip()):
            in_fence = not in_fence
            yield ln, True
            continue
        yield ln, in_fence


def strip_code(text: str) -> str:
    \"\"\"Return prose-only text (fenced code blocks removed, delimiters dropped).\"\"\"
    out = []
    for ln, in_fence in iter_lines(text):
        if in_fence:
            continue
        out.append(ln)
    return "\\n".join(out)


def code_blocks(text: str):
    \"\"\"Return the list of fenced code-block bodies (verbatim, joined by \\\\n).\"\"\"
    blocks, cur, in_fence = [], [], False
    for ln in text.split("\\n"):
        if is_fence(ln.strip()):
            if in_fence:
                blocks.append("\\n".join(cur))
                cur = []
            in_fence = not in_fence
            continue
        if in_fence:
            cur.append(ln)
    if cur:
        blocks.append("\\n".join(cur))
    return blocks


# --------------------------------------------------------------------------- #
# Word / n-gram originality (locked 13-word gate).
# --------------------------------------------------------------------------- #
def words(t: str):
    \"\"\"Return the lowercased word tokens of t.\"\"\"
    return re.findall(r"\\w+", t.lower())


def maxruns(a, b, n):
    \"\"\"Maximal runs of >= n consecutive words in a that also appear in b.\"\"\"
    if len(a) < n or len(b) < n:
        return []
    bset = {tuple(b[i:i + n]) for i in range(len(b) - n + 1)}
    runs, i = [], 0
    while i <= len(a) - n:
        if tuple(a[i:i + n]) in bset:
            j = i + n
            while j < len(a) and tuple(a[j - n + 1:j + 1]) in bset:
                j += 1
            runs.append(" ".join(a[i:j]))
            i = j
        else:
            i += 1
    return runs


# Exempt benign shared runs: a run that is really a functional identifier / URL / path /
# numeric table is allowed to stay. Match WHOLE words, never substrings.
_EXEMPT_EXTS = {
    "png", "gif", "jpg", "jpeg", "svg", "webp", "pdf", "html", "htm", "json", "yaml",
    "yml", "toml", "csv", "xml", "css", "scss", "sass", "md", "rst", "cpp", "hpp",
    "obj", "dll", "exe", "so", "py", "rs", "js", "ts", "jsx", "tsx", "mjs", "sh",
    "ps1", "bat", "cmd", "ini", "cfg", "lock", "sql", "wgsl", "glsl", "hlsl",
}


def _idish(tok: str) -> bool:
    \"\"\"A token that is functional, not prose: snake_case, has a digit, file ext, URL.\"\"\"
    return ("_" in tok) or any(c.isdigit() for c in tok) or tok in _EXEMPT_EXTS \\
        or tok in ("http", "https", "www")


def looks_exempt(run: str):
    \"\"\"Exempt a shared run ONLY if it is genuinely identifier-dominated — never just because
    a long prose run happens to contain one underscore.\"\"\"
    w = run.split()
    n = len(w)
    if not n:
        return "EMPTY"
    frac = sum(1 for x in w if _idish(x)) / n
    if frac >= 0.5:                                  # tables / signatures / enum / path lists
        return "IDENT_DOMINATED"
    if n <= 14 and frac > 0 and (
        any(x in ("http", "https", "www") for x in w) or any("_" in x for x in w)):
        return "SHORT_IDENT"                          # short preserved label/command run
    if sum(c.isdigit() for c in run) >= 8 and frac >= 0.3:
        return "ENUM/NUM"
    return None                                       # genuine prose -> must be broken


# --------------------------------------------------------------------------- #
# Marker blockquote.
# --------------------------------------------------------------------------- #
MARKER_RE = re.compile(
    r"^> .+ reference\\. (Original prose|Verbatim docs); identifiers preserved verbatim\\.\\s*$"
)


def marker_line(skill_title: str) -> str:
    \"\"\"Return the normalized marker blockquote line for the given skill title.\"\"\"
    return f"> {skill_title} reference. Original prose; identifiers preserved verbatim."


# --------------------------------------------------------------------------- #
# Chrome / scrape-artifact patterns. Line-anchored and conservative.
# --------------------------------------------------------------------------- #
SECTION_TITLED_SUB = re.compile(r'Section titled\\s+[“"][^”"]*[”"]\\s*')

CHROME_PATTERNS = [
    re.compile(r'^\\s*Section titled\\s+[“"].*[”"]\\s*$'),
    re.compile(r'^\\s*Was this page helpful\\??\\s*$', re.I),
    re.compile(r'^\\s*On this page\\s*$', re.I),
    re.compile(r'^\\s*Edit this page.*$', re.I),
    re.compile(r'^\\s*Table of contents\\s*$', re.I),
    re.compile(r'^\\s*Back to top\\s*$', re.I),
    re.compile(r'^\\s*Print this page\\s*$', re.I),
    re.compile(r'^\\s*(?:Support|Sponsor)\\s+(?:us\\s+)?on\\s+Open\\s+Collective.*$', re.I),
    re.compile(r'^\\s*\\[(?:Support on Open Collective|Sponsor on GitHub)\\]\\(.*$', re.I),
    re.compile(r'^\\s*©.*(?:contributor|reserved|license|\\d{4}).*$', re.I),
    re.compile(r'^\\s*\\(c\\)\\s+\\d{4}.*$', re.I),
    re.compile(r'^\\s*All rights reserved\\.?\\s*$', re.I),
    re.compile(r'^\\s*Licensed under\\s+.*$', re.I),
    re.compile(r'^\\s*\\[[^\\]]*Previous\\]\\([^)]*\\)\\s*\\[[^\\]]*Next\\]\\(.*$', re.I),
]

_UNICODE_SPACE = re.compile("[\\u00A0\\u2002\\u2003\\u2007\\u2008\\u2009\\u200A\\u202F\\uFEFF]")
_PUA = re.compile("[\\uE000-\\uF8FF]")                          # icon-font glyphs (Font Awesome)
_FIGURE_EMPTY = re.compile(r"\\(Figure:\\s*\\)")                 # empty image-placeholder stub
_FIGURE_ANY = re.compile(r"\\(Figure:[^)]*\\)")                 # any figure caption (image alt-text)
_RUSTDOC_NAV = re.compile(r"\\[(?:Read more|Source)\\]\\([^)]*\\)")  # rustdoc nav labels
_SECTION_SIGN = re.compile(r"\\s*§")                           # rustdoc trailing section sign
_MIDDOT = re.compile(r"\\s+·(?=\\s)")                           # rustdoc version separator


def scrape_cruft_subs(line: str) -> str:
    \"\"\"Remove substring scrape cruft from one (non-fence) line.\"\"\"
    line = _UNICODE_SPACE.sub(" ", line)
    line = _PUA.sub("", line)
    line = _FIGURE_EMPTY.sub("", line)
    line = _RUSTDOC_NAV.sub("", line)
    line = _SECTION_SIGN.sub("", line)
    line = _MIDDOT.sub("", line)
    return line


def chrome_hits(text: str):
    \"\"\"Return [(lineno, line)] matching chrome patterns OR carrying residual scrape glyphs
    (PUA icon fonts, empty figure stubs), outside fences.\"\"\"
    hits = []
    for i, (ln, in_fence) in enumerate(iter_lines(text)):
        if in_fence:
            continue
        if any(pat.match(ln) for pat in CHROME_PATTERNS) \\
                or _PUA.search(ln) or _FIGURE_EMPTY.search(ln):
            hits.append((i, ln))
    return hits


# --------------------------------------------------------------------------- #
# Prose-line identification — the extraction predicate AND the mode decision.
# --------------------------------------------------------------------------- #
STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "is", "are", "and", "or", "for", "with", "that",
    "this", "you", "can", "will", "it", "as", "on", "by", "be", "from", "at", "if", "when",
    "your", "not", "but", "which", "these", "those", "into", "its", "their", "them", "then",
    "than", "so", "such", "each", "all", "may", "must", "should", "we", "they", "do", "does",
    "use", "used", "using", "there", "here", "how", "what", "where", "while", "after", "before",
    "any", "no", "only", "also", "more", "most", "some", "other", "between", "per", "via",
}
EXTRACT_THRESHOLD = 0.35   # prose fraction below this -> extraction mode; at/above -> full-file

_TABLE_RE = re.compile(r"^\\|")
_TABLE_SEP_RE = re.compile(r"^\\|?\\s*[-:]+\\s*\\|")
_BARE_BULLET_RE = re.compile(r"^[-*+]\\s+`?\\[?[\\w./:-]+`?\\]?\\s*$")


def is_prose_line(stripped: str) -> bool:
    \"\"\"True if a stripped line is copyrightable narrative prose to rewrite.
    Generous capture (>=6 words, >=1 stopword); Gate B (13-word) is the residue backstop.\"\"\"
    s = stripped
    if not s or MARKER_RE.match(s):
        return False
    if s.startswith("#") or s.startswith(">"):
        return False
    if _TABLE_RE.match(s) or _TABLE_SEP_RE.match(s):
        return False
    if _BARE_BULLET_RE.match(s):
        return False
    wl = re.findall(r"[A-Za-z]+", s.lower())
    if len(wl) < 6:
        return False
    return any(w in STOPWORDS for w in wl)


def prose_lines(text: str):
    \"\"\"Yield (line_index, raw_line) for each prose line (fence-aware).\"\"\"
    for i, (ln, in_fence) in enumerate(iter_lines(text)):
        if in_fence:
            continue
        if is_prose_line(ln.strip()):
            yield i, ln


_URL_STRIP = re.compile(r"https?://\\S+")
_LINK_FULL_STRIP = re.compile(r"\\[[^\\]]*\\]\\([^)]*\\)")  # whole [label](url) — label is nav/UI, preserved
_LINKTARGET_STRIP = re.compile(r"\\]\\(\\s*[^)]*\\)")      # any remaining ](url)
_INLINE_STRIP = re.compile(r"`[^`]*`")


def _strip_preserved(s: str) -> str:
    \"\"\"Remove the things we keep verbatim before the n-gram: inline code, FULL markdown links
    (the [label] display text is a navigational/UI label, not copyrightable prose), and URLs.\"\"\"
    s = _INLINE_STRIP.sub(" ", s)
    s = _LINK_FULL_STRIP.sub(" ", s)
    s = _LINKTARGET_STRIP.sub("] ", s)
    s = _URL_STRIP.sub(" ", s)
    s = _FIGURE_ANY.sub(" ", s)        # figure captions are image alt-text, not residue
    return s


def _looks_like_signature(cell: str) -> bool:
    \"\"\"A code signature masquerading as prose (e.g. `bool operator== (const T& O) const`).
    Such cells must NOT be reworded — some signature tokens aren't in Gate A's protected set.\"\"\"
    if re.search(r"\\boperator\\b", cell):
        return True
    if re.search(r"\\)\\s*const\\b", cell):              # trailing ) const
        return True
    if "(" in cell and ")" in cell and re.search(r"[A-Z]\\w*\\s*[&*]\\s*\\w", cell):
        return True                                   # Type& / Type* param inside a call
    return False


def _is_cell_prose(cell: str) -> bool:
    \"\"\"True if a table cell holds copyrightable narrative (>=6 words, >=1 stopword, after
    removing preserved identifiers/links). Identifier-only and signature cells excluded.\"\"\"
    if _looks_like_signature(cell):
        return False
    wl = re.findall(r"[A-Za-z]+", _strip_preserved(cell).lower())
    return len(wl) >= 6 and any(w in STOPWORDS for w in wl)


def prose_units(text: str):
    \"\"\"Yield each PROSE UNIT — a whole prose line OR a prose-bearing table cell:
       whole line:  {'i': idx, 'cell': None, 'indent': ws, 'text': stripped_line}
       table cell:  {'i': idx, 'cell': seg_index, 'text': stripped_cell}
    `cell` is the index into line.split('|') (so splice can rejoin exactly).\"\"\"
    for i, (ln, in_fence) in enumerate(iter_lines(text)):
        if in_fence:
            continue
        s = ln.strip()
        if not s or MARKER_RE.match(s) or s.startswith("#"):
            continue
        if s.startswith("|") and not _TABLE_SEP_RE.match(s):
            for ci, seg in enumerate(ln.split("|")):
                cell = seg.strip()
                if cell and _is_cell_prose(cell):
                    yield {"i": i, "cell": ci, "text": cell}
        elif is_prose_line(s):
            indent = ln[:len(ln) - len(ln.lstrip())]
            yield {"i": i, "cell": None, "indent": indent, "text": s}


def prose_ratio(text: str):
    \"\"\"Return (ratio, prose_word_count, total_word_count, prose_unit_count).\"\"\"
    total = len(re.findall(r"[A-Za-z0-9_]+", text))
    pwc = puc = 0
    for u in prose_units(text):
        pwc += len(u["text"].split())
        puc += 1
    return (pwc / total if total else 0.0), pwc, total, puc


def prose_text(text: str) -> str:
    \"\"\"All prose-unit text (whole lines + prose table cells) — the surface Gate B checks.\"\"\"
    return "\\n".join(u["text"] for u in prose_units(text))


def prose_for_ngram(text: str) -> str:
    \"\"\"Prose-unit text with preserved identifiers/links/URLs removed before the n-gram.\"\"\"
    return _strip_preserved(prose_text(text))


# --------------------------------------------------------------------------- #
# Gate A: protected-identifier multisets (source vs working).
# --------------------------------------------------------------------------- #
_INLINE = re.compile(r"`([^`\\n]+)`")
_URL = re.compile(r"https?://[^\\s)>\\]}\\"']+")
_LINK_TARGET = re.compile(r"\\]\\(\\s*([^)\\s]+)")
_UNESCAPE = re.compile(r"\\\\([_()\\[\\]*~#.`])")
_CAMEL = re.compile(r"\\b[A-Za-z][a-z0-9]+(?:[A-Z][a-z0-9]+)+[A-Za-z0-9]*\\b")
_ALLCAPS = re.compile(r"\\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\\b")
_QUALIFIED = re.compile(r"\\b[A-Za-z_]\\w*(?:::[A-Za-z_0-9]+)+\\b")
_NUM = re.compile(
    r"(?<![\\w.])\\d[\\d,]*(?:\\.\\d+)?"
    r"(?:\\s?(?:%|px|fps|Hz|kHz|MHz|GHz|ms|ns|µs|us|s|KB|MB|GB|TB|kB|dBFS|dB|"
    r"bits?|bytes?|mm|cm|m|x)\\b)?"
)


def extract_protected(text: str) -> dict:
    \"\"\"Return {category: Counter} of protected tokens. 'code'/'inline'/'url'/'ident' are
    hard-preserve; 'num' is reported as a softer signal.\"\"\"
    prose = _UNESCAPE.sub(r"\\1", strip_code(text))   # normalize prettier escapes
    cats = {
        "code": Counter(b.strip() for b in code_blocks(text) if b.strip()),
        "inline": Counter(m.group(1).strip() for m in _INLINE.finditer(prose)),
        "url": Counter(u.strip("<>") for u in _URL.findall(prose)) + Counter(
            t.strip("<>") for t in _LINK_TARGET.findall(prose) if not t.lstrip("<").startswith("#")
        ),
        "ident": (Counter(_CAMEL.findall(prose)) + Counter(_ALLCAPS.findall(prose))
                  + Counter(_QUALIFIED.findall(prose))),
        "num": Counter(m.group(0).strip() for m in _NUM.finditer(prose)),
    }
    return cats


def gate_a(source_text: str, working_text: str, chrome_stripped_source: str = None):
    \"\"\"Identifier-preservation. Baseline = chrome-stripped source. PASS when no hard-category
    token is lost. Returns (passed, detail).\"\"\"
    base = chrome_stripped_source if chrome_stripped_source is not None else source_text
    src = extract_protected(base)
    wrk = extract_protected(working_text)
    # A flattened source identifier the rewrite WRAPPED in backticks/code moves out of the
    # ident/num category into a working inline/code span. It is preserved, not lost — forgive it.
    wrapped = " ".join(list(wrk["inline"]) + list(wrk["code"]))
    lost, added = {}, {}
    for cat in src:
        lost_c = src[cat] - wrk[cat]
        if cat in ("ident", "num"):
            for tok in [t for t in lost_c if t in wrapped]:
                del lost_c[tok]
        added_c = wrk[cat] - src[cat]
        if lost_c:
            lost[cat] = dict(lost_c)
        if added_c:
            added[cat] = dict(added_c)
    hard = [c for c in ("code", "inline", "url", "ident") if c in lost]
    passed = len(hard) == 0
    return passed, {"lost": lost, "added": added, "hard_fail_categories": hard}


# --------------------------------------------------------------------------- #
# Gate B: verbatim-residue n-gram (prose-only, 13 words, exempt-classified).
# --------------------------------------------------------------------------- #
def _maxruns_set(a, bset, n):
    \"\"\"Maximal runs of >= n words in `a` whose every n-gram is in the precomputed bset.\"\"\"
    runs, i = [], 0
    while i <= len(a) - n:
        if tuple(a[i:i + n]) in bset:
            j = i + n
            while j < len(a) and tuple(a[j - n + 1:j + 1]) in bset:
                j += 1
            runs.append(" ".join(a[i:j]))
            i = j
        else:
            i += 1
    return runs


def gate_b(source_text: str, working_text: str, min_run: int = 13):
    \"\"\"PASS when no non-exempt >= min_run-word run is shared with the source. Scans working
    prose PER UNIT against the full source prose n-gram set. Returns (passed, detail).\"\"\"
    sw = words(prose_for_ngram(source_text))
    s_all, w_all = words(source_text), words(working_text)
    ratio = (len(w_all) / len(s_all)) if s_all else 0.0
    if len(sw) < min_run:
        return True, {"ratio": round(ratio, 3), "runs_remaining": 0, "runs": []}
    sset = {tuple(sw[i:i + min_run]) for i in range(len(sw) - min_run + 1)}
    flagged = []
    for u in prose_units(working_text):
        uw = words(_strip_preserved(u["text"]))
        for run in _maxruns_set(uw, sset, min_run):
            if looks_exempt(run) is None:
                flagged.append({"unit": u["i"], "cell": u["cell"], "run": run})
    return (len(flagged) == 0), {
        "ratio": round(ratio, 3),
        "runs_remaining": len(flagged),
        "runs": [f["run"] for f in flagged[:25]],
        "flagged": flagged[:25],
    }


# --------------------------------------------------------------------------- #
# Gate C: residual cruft.
# --------------------------------------------------------------------------- #
def gate_c(working_text: str):
    \"\"\"PASS when the working text carries no residual scrape cruft. Returns (passed, detail).\"\"\"
    hits = chrome_hits(working_text)
    return (len(hits) == 0), {"cruft_lines": [ln for _, ln in hits][:25], "count": len(hits)}


def run_gates(source_text: str, working_text: str, faction: int = 2, min_run: int = 13) -> dict:
    \"\"\"Run gates A/B/C on a (source, working) pair. PASS = A and C pass; B is required for
    Faction-2 (recontextualized) files and reported (ratio) for F1.\"\"\"
    chrome_stripped_source, _ = clean_text(source_text)
    a_ok, a_detail = gate_a(source_text, working_text, chrome_stripped_source)
    b_ok, b_detail = gate_b(source_text, working_text, min_run)
    c_ok, c_detail = gate_c(working_text)
    b_required = faction == 2
    passed = a_ok and c_ok and (b_ok or not b_required)
    return {
        "passed": passed,
        "faction": faction,
        "gate_a": {"passed": a_ok, **a_detail},
        "gate_b": {"passed": b_ok, "required": b_required, **b_detail},
        "gate_c": {"passed": c_ok, **c_detail},
    }


# --------------------------------------------------------------------------- #
# Cleanup (Faction-1 deterministic cleaner; no LLM).
# --------------------------------------------------------------------------- #
def clean_text(text: str, skill_title: str = None):
    \"\"\"Conservative cleanup outside fenced code: strip scrape chrome, normalize the marker
    blockquote to 'Original prose', collapse blank runs. Returns (new_text, actions).\"\"\"
    actions = []

    # 1a. remove inline "Section titled ..." chrome + source-specific scrape cruft (substrings).
    sub_lines, in_fence, subs, cruft = [], False, 0, 0
    for ln in text.split("\\n"):
        if is_fence(ln.strip()):
            in_fence = not in_fence
            sub_lines.append(ln)
            continue
        if not in_fence:
            new = SECTION_TITLED_SUB.sub("", ln)
            if new != ln:
                subs += 1
            new2 = scrape_cruft_subs(new)
            if new2 != new:
                cruft += 1
            ln = new2
        sub_lines.append(ln)
    if subs:
        actions.append(f"strip_section_titled:{subs}")
    if cruft:
        actions.append(f"strip_scrape_cruft:{cruft}")
    text = "\\n".join(sub_lines)

    # 1b. strip whole chrome lines (outside fences)
    keep, in_fence, stripped = [], False, 0
    for ln in text.split("\\n"):
        if is_fence(ln.strip()):
            in_fence = not in_fence
            keep.append(ln)
            continue
        if not in_fence and any(p.match(ln) for p in CHROME_PATTERNS):
            stripped += 1
            continue
        keep.append(ln)
    if stripped:
        actions.append(f"strip_chrome:{stripped}")
    text = "\\n".join(keep)

    # 2. normalize the marker blockquote to "Original prose"
    out, fixed = [], 0
    for ln in text.split("\\n"):
        s = ln.strip()
        if MARKER_RE.match(s) and "Verbatim docs" in s:
            ln = ln.replace("Verbatim docs", "Original prose")
            fixed += 1
        out.append(ln)
    if fixed:
        actions.append("fix_marker")
    text = "\\n".join(out)

    # 3. normalize whitespace: strip trailing ws; collapse 3+ blank lines to 1
    lines = [l.rstrip() for l in text.split("\\n")]
    collapsed, blanks, changed = [], 0, False
    for l in lines:
        if l == "":
            blanks += 1
            if blanks <= 1:
                collapsed.append(l)
            else:
                changed = True
        else:
            blanks = 0
            collapsed.append(l)
    text = "\\n".join(collapsed).rstrip() + "\\n"
    if changed:
        actions.append("normalize_blanks")

    return text, actions


# --------------------------------------------------------------------------- #
# Extract (prose packet) and splice (tamper-proof re-insertion).
# --------------------------------------------------------------------------- #
def extract(text: str) -> dict:
    \"\"\"Extract the prose units of a file into a rewrite packet. For extraction-mode files only
    the prose units are sent to the LLM; identifiers/signatures/tables/code never leave the file.

    Packet schema: {"total_lines": N, "items": [{"i","cell","heading","text"}]}.
    The caller adds the "file" key (the source path) if it wants one.
    \"\"\"
    lines = text.split("\\n")
    headings, last, in_fence = {}, "", False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if is_fence(s):
            in_fence = not in_fence
        elif not in_fence and s.startswith("#"):
            last = s
        headings[i] = last
    items = []
    for u in prose_units(text):
        items.append({"i": u["i"], "cell": u["cell"],
                      "heading": headings.get(u["i"], ""), "text": u["text"]})
    return {"total_lines": len(lines), "items": items}


def load_rewrites(obj):
    \"\"\"Return a list of {'i','cell','text'} items. Accepts {'items':[...]}, a list, or a legacy
    whole-line map {idx: text}.\"\"\"
    if isinstance(obj, dict) and "items" in obj:
        return obj["items"]
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        return [{"i": int(k), "cell": None, "text": v} for k, v in obj.items()]
    raise ValueError("rewrites must be {'items':[...]}, a list, or {idx: text}")


def splice(source_text: str, rewrites: list):
    \"\"\"Re-derive the allowed prose-unit (i,cell) keys from the SOURCE, then replace ONLY those
    units with their rewrites. Any rewrite aimed at a non-prose index is ignored, so identifiers /
    signatures / code can never be altered by a stray index. Returns (out_text, stats).\"\"\"
    allowed = {(u["i"], u["cell"]) for u in prose_units(source_text)}
    lines = source_text.split("\\n")
    whole, cellrw = {}, {}
    replaced = skipped = 0
    applied = set()
    for r in rewrites:
        key = (r["i"], r.get("cell"))
        if key not in allowed:
            skipped += 1
            continue
        if r.get("cell") is None:
            whole[r["i"]] = r["text"]
        else:
            cellrw.setdefault(r["i"], {})[r["cell"]] = r["text"]
        applied.add(key)
        replaced += 1
    for i, nt in whole.items():
        orig = lines[i]
        indent = orig[:len(orig) - len(orig.lstrip())]
        lines[i] = indent + " ".join(str(nt).splitlines()).strip()
    for i, cmap in cellrw.items():
        segs = lines[i].split("|")
        for ci, nt in cmap.items():
            seg = segs[ci]
            lead = seg[:len(seg) - len(seg.lstrip())] or " "
            trail = seg[len(seg.rstrip()):] or " "
            segs[ci] = lead + " ".join(str(nt).splitlines()).strip() + trail
        lines[i] = "|".join(segs)
    left = sorted(allowed - applied, key=lambda k: (k[0], -1 if k[1] is None else k[1]))
    return "\\n".join(lines), {
        "replaced": replaced,
        "skipped_non_prose": skipped,
        "left_verbatim": len(left),
        "left_verbatim_keys": [[k[0], k[1]] for k in left[:50]],
    }


# --------------------------------------------------------------------------- #
# Triage: classify a file into a faction / tier / mode by prose density.
# --------------------------------------------------------------------------- #
def score_file(text: str):
    \"\"\"Return (prose_ratio, prose_words, prose_unit_count, chrome_count, marker_ok).\"\"\"
    ratio, pwc, _total, plc = prose_ratio(text)
    marker_ok = False
    for ln, in_fence in iter_lines(text):
        if in_fence:
            continue
        s = ln.strip()
        if MARKER_RE.match(s):
            marker_ok = s.endswith("Original prose; identifiers preserved verbatim.")
            break
    chrome = len(chrome_hits(text))
    return round(ratio, 3), pwc, plc, chrome, marker_ok


def classify(ratio, prose_words, prose_lc, chrome, marker_ok):
    \"\"\"Return (faction, tier, mode, needs_cleanup, review).

    Bias toward Faction-2: mis-routing prose to F1 leaves copyrighted text verbatim (the costly
    error); mis-routing an identifier file to F2 only wastes some tokens. mode = 'extract' (send
    only prose lines) when the prose fraction is below EXTRACT_THRESHOLD, else 'full' (whole-file).
    tier (light/medium/heavy) = the rewrite workload = number of prose units.\"\"\"
    needs_cleanup = (chrome > 0) or (not marker_ok)
    if prose_lc == 0 or prose_words < 25:           # negligible prose -> cleanup only
        return 1, "none", "none", needs_cleanup, False
    mode = "extract" if ratio < EXTRACT_THRESHOLD else "full"
    review = prose_lc <= 3
    if prose_lc <= 8:
        tier = "light"
    elif prose_lc <= 25:
        tier = "medium"
    else:
        tier = "heavy"
    return 2, tier, mode, needs_cleanup, review


# --------------------------------------------------------------------------- #
# Corpus walking and I/O (path-agnostic; caller supplies all roots).
# --------------------------------------------------------------------------- #
def content_files(skill_dir: Path):
    \"\"\"All marker-bearing reference content files under a skill dir: **/references/*.md minus
    INDEX.md. The caller supplies skill_dir; nothing is hardcoded.\"\"\"
    out = []
    for p in Path(skill_dir).rglob("*.md"):
        parts = [x.lower() for x in p.parts]
        if "references" in parts and p.name.lower() != "index.md":
            out.append(p)
    return sorted(out)


def read(path) -> str:
    \"\"\"Read and return the UTF-8 text of path.\"\"\"
    return Path(path).read_text(encoding="utf-8")


def write(path, text: str):
    \"\"\"Write text to path as UTF-8, creating parent directories as needed.\"\"\"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def append_jsonl(path, record: dict):
    \"\"\"Append record as one JSON line to path, creating parent directories as needed.\"\"\"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\\n")


def skill_title(skill: str) -> str:
    \"\"\"Return a human-readable title from a hyphenated skill slug.\"\"\"
    return skill.replace("-", " ").title()
"""

# ===MODULE builder_components.util.config===
_SRC['builder_components.util.config'] = """
\"\"\"Shared constants for the build pipeline.\"\"\"

from __future__ import annotations

#: Path to the all-in-one tool, used as the validator in the SKILL.md Verification command that
#: `finalize` generates and the default the `recontext` promote step runs. Callers append the
#: ``validate`` subcommand token (e.g. ``python {VALIDATOR} validate <dir>``). Repo-relative default;
#: override per-run with ``finalize --validator``.
VALIDATOR = ".agents/skills/skill-drafting/scripts/skill_builder.py"
"""

# ===MODULE builder_components.util.frontmatter===
_SRC['builder_components.util.frontmatter'] = """
\"\"\"Minimal YAML-frontmatter reader shared by the validator and the policy manager.

This is the scalar reader: folded multi-line values are space-joined and every value is a string.
It was duplicated byte-for-byte in ``validate_skill_package.py`` and ``skill_policy.py``; this is the
single canonical copy.

NOTE: the build pipeline's ``index`` module keeps its own *richer* ``parse_frontmatter`` (block
scalars + inline/block lists, so values may be lists). That parser has a single caller and is a
genuinely different function, so it is not consolidated here.
\"\"\"

from __future__ import annotations

import re

#: Frontmatter delimiter (tolerates CRLF).
FRONTMATTER_RE = re.compile(r"\\A---\\r?\\n(?P<body>.*?)\\r?\\n---\\r?\\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, str]:
    \"\"\"Read scalar frontmatter values; fold multi-line values with a single space.\"\"\"
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    values: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in match.group("body").splitlines():
        if not raw_line.strip():
            continue
        if raw_line.startswith((" ", "\\t")) and current_key:
            values[current_key] = values[current_key] + " " + raw_line.strip().strip("'\\"")
            continue
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        current_key = key.strip()
        values[current_key] = value.strip().strip("'\\"")
    return values
"""

# ===MODULE builder_components.util.repo_paths===
_SRC['builder_components.util.repo_paths'] = """
\"\"\"Project-root resolution for default scratch paths.

``_find_repo_root`` resolves the VS Code *project* that owns a path — deliberately climbing past
per-skill repos so default ``AI/work`` / ``AI/lint`` scratch never lands inside a skill package.
Was duplicated byte-for-byte (modulo docstring) in ``skill_builder.py`` and ``skill_policy.py``.
\"\"\"

from __future__ import annotations

import os
from pathlib import Path


def _find_repo_root(start) -> Path:
    \"\"\"The VS Code project root that owns `start`: the immediate child of $DEVROOT containing it
    (%DEVROOT%\\\\<project>), else the nearest enclosing repo/workspace that is NOT a per-skill package.
    Every skills/<name>/ is its own git repo (its root has SKILL.md), so resolving to the nearest .git
    would wrongly land inside a skill; this climbs past skills to the owning project. Keeps default
    AI/lint and AI/work scratch at the project root, never inside a skill, regardless of CWD.\"\"\"
    current = Path(start).resolve()
    devroot = os.environ.get("DEVROOT")
    if devroot:
        dr = Path(devroot).resolve()
        for path in (current, *current.parents):
            if path.parent == dr:
                if not (path / "SKILL.md").is_file():
                    return path
                break  # a skill sits directly under DEVROOT; fall through to the climb
    for path in (current, *current.parents):
        if (path / "SKILL.md").is_file():
            continue  # never resolve to a per-skill package
        if (path / ".git").exists() or (path / "AGENTS.md").is_file():
            return path
    return current


def _project_ai_dir(start, *parts) -> Path:
    \"\"\"Default AI/ scratch path under the owning project root; refuses to land inside a skill package.\"\"\"
    root = _find_repo_root(start)
    if (root / "SKILL.md").is_file():  # guard: fail loudly rather than pollute a skill
        raise SystemExit(f"refusing to write {'/'.join(parts)} inside a skill package: {root}")
    return root.joinpath(*parts)
"""

# ===MODULE builder_components.util.text_io===
_SRC['builder_components.util.text_io'] = """
\"\"\"Shared file-writing helper for the build pipeline.

``write_text`` forces ``\\\\n`` line endings and creates parent directories — the writer used across
the build/finalize/index/maintain/readme stages. Relocated verbatim from ``skill_builder.py``.

NOTE: the other ``write``/``read`` helpers in the codebase are intentionally NOT consolidated here.
``finalize`` keeps its rstrip-then-newline ``write``; the recontext engine keeps its own
platform-newline ``read``/``write``/``append_jsonl``; the locked recontext writer keeps its
confinement-aware ``_atomic_write_*``. Those differ in newline handling or safety contracts, so
merging them would change behavior.
\"\"\"

from __future__ import annotations

from pathlib import Path


def write_text(path: Path, text: str) -> None:
    \"\"\"Write `text` to `path` as UTF-8 with forced ``\\\\n`` line endings, creating parent dirs.\"\"\"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\\n")
"""

# ===MODULE builder_components.finalize===
_SRC['builder_components.finalize'] = """
\"\"\"Finalize a gold SKILL.md + GOTCHA.md (was the finalize section of skill_builder.py).\"\"\"

from __future__ import annotations

import argparse
import json
from pathlib import Path
from builder_components.util.config import VALIDATOR


# ==============================================================================
# FINALIZE — gold SKILL.md + GOTCHA.md (was finalize_gold.py)
# ==============================================================================

REF = "Recurring failure modes and what to do instead live in the sibling [GOTCHA.md](GOTCHA.md)."

DEFAULT_GOTCHAS = [
    "These reference files are reproduced verbatim from the upstream documentation and split into "
    "focused topics; a file may cover several adjacent subjects — use `references/INDEX.md` or "
    "`rg -n \\"PATTERN\\" references/*.md` to locate the exact one.",
    "The docs track a specific version; verify version-sensitive APIs, flags, and defaults against the "
    "actual toolchain/build in use before relying on them.",
    "Treat every identifier (API/type/function name, flag, path, enum value, number) as an exact "
    "reference fact — do not invent or paraphrase.",
]


def write(path: Path, text: str) -> None:
    \"\"\"Write text to path with a single trailing newline and LF line endings.\"\"\"
    path.write_text(text.rstrip() + "\\n", encoding="utf-8", newline="\\n")


def ref_count(skill_dir: Path) -> int:
    \"\"\"Count the subject reference *.md files under skill_dir/references (excluding INDEX.md).\"\"\"
    refs = skill_dir / "references"
    return len([p for p in refs.glob("*.md") if p.name != "INDEX.md"]) if refs.is_dir() else 0


def gotcha_md(title: str, gotchas: list) -> str:
    \"\"\"Render GOTCHA.md content for title from the given gotchas (or DEFAULT_GOTCHAS if empty).\"\"\"
    lead = (f"Recurring failure modes when relying on the {title} reference, and what to do instead. "
            f"Read alongside `SKILL.md`.")
    body = "\\n".join(f"- {g}" for g in (gotchas or DEFAULT_GOTCHAS))
    return f"# {title} — Gotchas\\n\\n{lead}\\n\\n{body}\\n"


def source_note(meta: dict) -> str:
    \"\"\"Render the SKILL.md Source section from meta, or "" when no source_url is present.\"\"\"
    if not meta.get("source_url"):
        return ""
    verb = ("Reproduced verbatim from the upstream documentation for local reference; prose is the "
            "source's own. " if meta.get("verbatim") else "")
    return (f"\\n## Source\\n\\n{verb}Upstream: {meta['source_url']}\\n")


def leaf_skill_md(meta: dict, skill_dir: Path, *, validate_path: str) -> str:
    \"\"\"Render the full SKILL.md for a leaf (flat or sub-) skill from meta and its reference count.\"\"\"
    title, n = meta["title"], ref_count(skill_dir)
    when = meta.get("when_to_use") or meta.get("description", "")
    return f\"\"\"---
name: {meta['name']}
description: {meta['description']}
---

# {title} Reference

Faithful reference for {title}, split into one focused file per subject across {n} reference files.
Identifiers (API/type/function names, flags, paths, enums, numbers) are preserved verbatim.

## When to use this

Use this skill when the task involves {when}

## Workflow

1. Open `references/INDEX.md` (or `references/topics.json`) and pick the one file that matches.
2. Read only that file; open another only if the task spans subjects. Grep across files when needed: `rg -n "PATTERN" references/*.md`.
3. Treat every identifier as an exact reference fact — never invent or paraphrase.

## Gotchas

{REF}

## References

All depth lives in `references/` — start at `references/INDEX.md`, metadata in `references/topics.json`. One subject per file.
{source_note(meta)}
## Verification

```powershell
python {VALIDATOR} validate {validate_path}
```
\"\"\"


def router_skill_md(meta: dict, skill_dir: Path, *, validate_path: str) -> str:
    \"\"\"Render the top-level router SKILL.md from meta, with a Routes table over the sub-skill dirs.\"\"\"
    title = meta["title"]
    subs = meta.get("subskills", {})
    rows = "\\n".join(
        f"| {subs.get(k, {}).get('title', k)} | {subs.get(k, {}).get('when_to_use', subs.get(k, {}).get('description', k))} | `{k}/SKILL.md` |"
        for k in sub_dirs(skill_dir))
    return f\"\"\"---
name: {meta['name']}
description: >-
  {meta['description']}
---

# {title} Reference

Faithful, task-routed reference for {title}, split into one focused file per subject. Identifiers are
preserved verbatim. Routes to the area sub-skills below — open the one that matches and use its
`references/INDEX.md`.

## When to use this

Use this skill when the task involves {meta.get('when_to_use') or meta.get('description','')}

## Routes

| Area | Use for | Open |
| --- | --- | --- |
{rows}

## Workflow

1. Identify the area above and open that sub-skill's `SKILL.md` (or its `references/INDEX.md`).
2. Read the one reference file that matches.
3. Treat every identifier as an exact reference fact.

## Gotchas

{REF}

## References

Each sub-skill carries its own `references/INDEX.md`, `references/topics.json`, and per-subject files.
{source_note(meta)}
## Verification

```powershell
python {VALIDATOR} validate --package {validate_path}
```
\"\"\"


def sub_dirs(skill_dir: Path) -> list:
    \"\"\"Return the sorted names of immediate sub-skill directories (those containing a SKILL.md).\"\"\"
    return sorted(d.name for d in skill_dir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())


def cmd_finalize(argv=None) -> int:
    \"\"\"Parse `finalize` CLI args and write the gold SKILL.md + GOTCHA.md for a router or flat skill.

    Returns 0 on success.
    \"\"\"
    global VALIDATOR
    ap = argparse.ArgumentParser(prog="skill_builder.py finalize")
    ap.add_argument("--validator", default=VALIDATOR,
                    help="validator path used in the generated SKILL.md Verification command.")
    ap.add_argument("--skill", required=True)
    ap.add_argument("--meta", required=True)
    args = ap.parse_args(argv)
    VALIDATOR = args.validator
    skill_rel = Path(args.skill).as_posix()
    skill = Path(args.skill)
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))

    if meta.get("router"):
        write(skill / "SKILL.md", router_skill_md(meta, skill, validate_path=skill_rel))
        write(skill / "GOTCHA.md", gotcha_md(meta["title"], meta.get("gotchas")))
        for k in sub_dirs(skill):
            sm = dict(meta.get("subskills", {}).get(k, {}))
            sm.setdefault("name", k)
            sm.setdefault("title", k.replace("-", " ").title())
            sm.setdefault("description", f"Use when working with {sm['title']} ({meta['title']}).")
            sm.setdefault("source_url", meta.get("source_url"))
            sm["verbatim"] = meta.get("verbatim", False)
            write(skill / k / "SKILL.md",
                  leaf_skill_md(sm, skill / k, validate_path=f"{skill_rel}/{k}"))
            write(skill / k / "GOTCHA.md", gotcha_md(sm["title"], meta.get("gotchas")))
        print(f"finalized router '{meta['name']}' + {len(sub_dirs(skill))} sub-skills")
    else:
        write(skill / "SKILL.md", leaf_skill_md(meta, skill, validate_path=skill_rel))
        write(skill / "GOTCHA.md", gotcha_md(meta["title"], meta.get("gotchas")))
        print(f"finalized flat skill '{meta['name']}' ({ref_count(skill)} reference files)")
    return 0

def main(argv=None) -> int:
    \"\"\"Standalone entry point for `python -m builder_components.finalize`; delegates to cmd_finalize.\"\"\"
    return cmd_finalize(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.ingest===
_SRC['builder_components.ingest'] = """
\"\"\"Ingest source docs (HTML / mdBook / rustdoc / PDF) into a corpus JSONL (was the ingest section).\"\"\"

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from .htmlmd import html_to_md, split_main


# ==============================================================================
# INGEST — source docs -> corpus JSONL (was ingest_*.py)
# ==============================================================================

def _ingest_slug(s: str) -> str:
    \"\"\"Slugify a string into a lowercase hyphenated token, falling back to 'page' if empty.\"\"\"
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-") or "page"


def _balanced_section(html_text: str, open_match, tag: str) -> str:
    \"\"\"Inner HTML of an opening <tag ...> up to its depth-matched </tag>.\"\"\"
    start = open_match.end()
    depth = 1
    for m in re.finditer(rf"<{tag}\\b|</{tag}\\s*>", html_text[start:], re.IGNORECASE):
        if m.group(0)[1] == "/":
            depth -= 1
            if depth == 0:
                return html_text[start:start + m.start()]
        else:
            depth += 1
    return html_text[start:]


def extract_content_section(html_text, content_id="main-content",
                            drop_section_ids=("synthetic-implementations", "blanket-implementations")):
    \"\"\"Return a generator-rendered page's documentation body: the balanced
    <section id="{content_id}"> (falling back to <main>), minus any boilerplate
    sections whose <h2 id> is in drop_section_ids. Defaults reproduce rustdoc; point
    content_id / drop_section_ids at any similarly structured generator output.\"\"\"
    m = re.search(r'<section[^>]*id="%s"[^>]*>' % content_id, html_text, re.IGNORECASE)
    if m:
        body = _balanced_section(html_text, m, "section")
    else:
        m2 = re.search(r"<main\\b[^>]*>", html_text, re.IGNORECASE)
        body = _balanced_section(html_text, m2, "main") if m2 else html_text
    cut = len(body)
    for sid in drop_section_ids:
        mm = re.search(r'<h2[^>]*id="%s"' % sid, body, re.IGNORECASE)
        if mm:
            cut = min(cut, mm.start())
    return body[:cut]


def cmd_ingest_html(argv=None) -> int:
    \"\"\"Ingest manifest-listed HTML pages into a corpus JSONL: one page-chunk record per file.\"\"\"
    ap = argparse.ArgumentParser(prog="skill_builder.py ingest html")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--src-dir", required=True)
    ap.add_argument("--skill", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    src = Path(args.src_dir)

    rows = []
    for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\\t")
        rows.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))

    recs, seen = [], set()
    for i, (lf, url, section) in enumerate(rows, 1):
        p = src / lf
        if not p.is_file():
            print(f"  WARN missing {lf}")
            continue
        md, heads = html_to_md(split_main(p.read_text(encoding="utf-8")), url)
        if not md.strip():
            continue
        title = next((t for lvl, t, _ in heads if lvl <= 1 and t.strip()), "")
        if not title:
            title = next((t for _, t, _ in heads if t.strip()),
                         _ingest_slug(url.rstrip("/").rsplit("/", 1)[-1]).replace("-", " ").title())
        rec = {"chunk_id": f"{args.skill}-{i:04d}", "title": title.strip(),
               "source_url": url, "text": md, "tags": []}
        if section:
            rec["subskill"] = section
            rec["section"] = "reference"
        recs.append(rec)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\\n") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\\n")
    kb = sum(len(r["text"].encode("utf-8")) for r in recs) / 1024
    print(f"{args.skill}: {len(recs)} page-chunks, {kb:.0f} KB total -> {out}")
    return 0


def cmd_ingest_mdbook(argv=None) -> int:
    \"\"\"Ingest a single concatenated mdBook HTML file into a corpus JSONL, splitting at top-level
    (`# `) page headings (fence-aware) and dropping pages whose title matches an --exclude substring.\"\"\"
    ap = argparse.ArgumentParser(prog="skill_builder.py ingest mdbook")
    ap.add_argument("--html", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--skill", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--exclude", default="",
                    help="comma-separated title substrings (case-insensitive) to drop (e.g. meta/coverage pages)")
    args = ap.parse_args(argv)
    excludes = [e.strip().lower() for e in args.exclude.split(",") if e.strip()]

    raw = Path(args.html).read_text(encoding="utf-8")
    md, _heads = html_to_md(split_main(raw), args.base)

    # Split at top-level (`# `) page headings; everything until the next `# ` is that page.
    # FENCE-AWARE: a `# ` line inside a ``` / ~~~ code block is a code comment, not a heading.
    chunks: list[tuple[str, str]] = []
    cur_title, cur = None, []
    in_fence = False
    for ln in md.split("\\n"):
        st = ln.lstrip()
        if st.startswith("```") or st.startswith("~~~"):
            in_fence = not in_fence
            if cur_title is not None:
                cur.append(ln)
            continue
        m = None if in_fence else re.match(r"^# (.+)$", ln)   # h1 only ("## " won't match)
        if m:
            if cur_title is not None:
                chunks.append((cur_title, "\\n".join(cur).strip()))
            cur_title, cur = m.group(1).strip(), []
        elif cur_title is not None:
            cur.append(ln)
    if cur_title is not None:
        chunks.append((cur_title, "\\n".join(cur).strip()))

    seen: set[str] = set()
    recs = []
    for i, (title, text) in enumerate(chunks, 1):
        if not text:
            continue
        if any(e in title.lower() for e in excludes):
            continue
        s = _ingest_slug(title)
        u, n = s, 2
        while u in seen:
            u = f"{s}-{n}"; n += 1
        seen.add(u)
        rec = {"chunk_id": f"{args.skill}-{i:04d}", "title": title,
               "source_url": f"{args.base.rstrip('/')}/{u}", "text": text, "tags": []}
        recs.append(rec)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\\n") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\\n")
    total = sum(len(r["text"].encode("utf-8")) for r in recs)
    print(f"{args.skill}: {len(recs)} page-chunks, {total/1024:.0f} KB total -> {out}")
    return 0

def cmd_ingest_rustdoc(argv=None) -> int:
    \"\"\"Turn crawled generator-rendered API pages (e.g. rustdoc) into a corpus JSONL.

    Each item renders as its own HTML page; the doc body is the balanced
    <section id=--content-id> minus the auto-generated boilerplate sections in
    --drop-section-id. --strip-label drops a chrome label line. Defaults reproduce
    rustdoc; override them for any similarly structured generator. Manifest lines:
    localfile <TAB> url.\"\"\"
    ap = argparse.ArgumentParser(prog="skill_builder.py ingest rustdoc")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--src-dir", required=True)
    ap.add_argument("--skill", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--content-id", default="main-content",
                    help="id of the <section> holding the doc body (default: 'main-content').")
    ap.add_argument("--drop-section-id", action="append", default=None,
                    help="<h2 id> of a boilerplate section to drop (repeatable; default: "
                         "synthetic-implementations, blanket-implementations).")
    ap.add_argument("--strip-label", action="append", default=None,
                    help="chrome label line to strip from the Markdown (repeatable; default: "
                         "'Expand description').")
    args = ap.parse_args(argv)
    src = Path(args.src_dir)
    drop_ids = tuple(args.drop_section_id if args.drop_section_id is not None
                     else ["synthetic-implementations", "blanket-implementations"])
    strip_labels = args.strip_label if args.strip_label is not None else ["Expand description"]

    rows = []
    for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\\t")
        rows.append((parts[0], parts[1]))

    recs, missing = [], 0
    for i, (lf, url) in enumerate(rows, 1):
        p = src / lf
        if not p.is_file():
            missing += 1
            continue
        md, heads = html_to_md(extract_content_section(
            p.read_text(encoding="utf-8", errors="replace"), args.content_id, drop_ids), url)
        for label in strip_labels:
            md = re.sub(r"[ \\t]*" + re.escape(label) + r"[ \\t]*\\n?", "\\n", md)
        if not md.strip():
            continue
        title = next((t for lvl, t, _ in heads if lvl <= 1 and t.strip()), "")
        if not title:
            title = _ingest_slug(url.rstrip("/").rsplit("/", 1)[-1]).replace("-", " ")
        recs.append({"chunk_id": f"{args.skill}-{i:05d}", "title": title.strip(),
                     "source_url": url, "text": md, "tags": []})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\\n") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\\n")
    kb = sum(len(r["text"].encode("utf-8")) for r in recs) / 1024
    print(f"{args.skill}: {len(recs)} pages ({missing} missing), {kb:.0f} KB total -> {out}")
    return 0


def run(cmd) -> str:
    \"\"\"Run a subprocess and return its captured stdout as UTF-8 text (undecodable bytes replaced).\"\"\"
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout


def qpdf_outline(pdf: str):
    \"\"\"Return the PDF's outline (bookmark) tree via `qpdf --json`, or [] if absent.\"\"\"
    data = json.loads(run(["qpdf", "--json", "--json-key=outlines", pdf]) or "{}")
    return data.get("outlines", [])


def npages(pdf: str) -> int:
    \"\"\"Return the PDF's page count via `qpdf --show-npages` (0 if unavailable).\"\"\"
    return int((run(["qpdf", "--show-npages", pdf]) or "0").strip() or 0)


def pdf_pages(pdf: str, layout: bool):
    \"\"\"Extract the PDF's text with pdftotext (optionally -layout) and return it split per page.\"\"\"
    cmd = ["pdftotext", "-q", "-enc", "UTF-8"] + (["-layout"] if layout else []) + [pdf, "-"]
    return run(cmd).split("\\f")


def flatten(nodes, depth=0, acc=None):
    \"\"\"Flatten a nested outline tree into a depth-tagged list of {title, page, depth} dicts.\"\"\"
    if acc is None:
        acc = []
    for nd in nodes:
        acc.append({"title": (nd.get("title") or "").strip(),
                    "page": nd.get("destpageposfrom1"), "depth": depth})
        flatten(nd.get("kids") or [], depth + 1, acc)
    return acc


def norm(s: str) -> str:
    \"\"\"Collapse runs of whitespace to single spaces and strip the result.\"\"\"
    return re.sub(r"\\s+", " ", s or "").strip()


def _pdf_slug(s: str) -> str:
    \"\"\"Slugify a string into a lowercase hyphenated token, falling back to 'section' if empty.\"\"\"
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-") or "section"


#: Bullet glyphs poppler emits for the manual's list markers (incl. the U+0082 PUA-mapped dot).
_BUL = "•‣▪●⁃∙·◦⁌․"
_PAGENUM = re.compile(r"\\d{1,4}")
_CHAPNUM = re.compile(r"Chapter\\s+\\d+", re.IGNORECASE)        # per-chapter running label
_REFFOOT = re.compile(r"\\|\\s*Chapter\\s+\\d+", re.IGNORECASE)   # reference footer "Part | Chapter N  Title"
_LEADER = re.compile(r"\\.{5,}|�{3,}")        # printed-TOC dot/glyph leaders
_TOC_HEADS = {"contents", "in this chapter", "table of contents"}
_HEAD_OK = re.compile(r"^[A-Z0-9(\\"'].*$")


_CAPS = re.compile(r"[A-Z0-9 &/.\\-]+")


def detect_boilerplate(pages):
    \"\"\"Return (caps_headers, footer_prefixes). The running header is an ALL-CAPS part name that
    recurs in the page EDGE zone (top-2 / bottom-3 non-blank lines) — its position flips between
    top and bottom in pdftotext reading order, so we count it wherever it lands in the edge, which
    catches every part (FAIRLIGHT, DELIVER, CLOUD, ...) while ignoring mid-page UI labels. The
    footer is the recurring 4-word prefix of the last non-page-number line.\"\"\"
    caps, foot4 = Counter(), Counter()
    for pg in pages:
        nb = [l for l in pg.split("\\n") if l.strip()]
        if not nb:
            continue
        for l in reversed(nb):
            if _PAGENUM.fullmatch(l.strip()):
                continue
            foot4[" ".join(norm(l).split()[:4])] += 1
            break
        for l in nb[:2] + nb[-3:]:
            n = norm(l)
            if n.isupper() and 2 <= len(n) <= 30 and _CAPS.fullmatch(n):
                caps[n] += 1
    npg = max(1, len(pages))
    caps_headers = {n for n, c in caps.items() if c >= 3}
    footers = {p for p, c in foot4.items() if c >= max(3, int(npg * 0.2)) and p}
    return caps_headers, footers


def clean_page(pg, caps_headers, footers):
    \"\"\"Drop running header (all-caps part name, any edge position), footer (by prefix or
    '| Chapter N'), page numbers, per-chapter mini-TOC, and printed-TOC leader lines.\"\"\"
    lines = pg.split("\\n")
    nb = [i for i, l in enumerate(lines) if l.strip()]
    if not nb:
        return ""
    foot_zone = set(nb[-3:])
    out = []
    for i, l in enumerate(lines):
        s = l.strip()
        if not s:
            out.append("")
            continue
        if _PAGENUM.fullmatch(s):
            continue
        if _CHAPNUM.fullmatch(s) or norm(s).lower() in _TOC_HEADS:   # chapter-number label / mini-TOC heading
            continue
        if _LEADER.search(s):                                        # printed-TOC leader line ("Title.....3085")
            continue
        if norm(s) in caps_headers:                                  # all-caps part running header (COLOR/FAIRLIGHT/...)
            continue
        if _REFFOOT.search(s):                                       # reference footer "Part | Chapter N  Title"
            continue
        if i in foot_zone and " ".join(norm(s).split()[:4]) in footers:
            continue
        l2 = l.rstrip().replace("�", "")                        # drop stray undecodable glyphs
        if l2.strip():
            out.append(l2)
    return "\\n".join(out)


def _is_heuristic_heading(s):
    \"\"\"A short, label-like line (section title not in the outline) — used only when it follows a break.\"\"\"
    if not (2 <= len(s) <= 55) or s[-1] in ".,:;)":
        return False
    if not _HEAD_OK.match(s) or len(s.split()) > 8:
        return False
    return True


def build_chapter(text, heading_keys, chapter_title):
    \"\"\"text = cleaned, page-joined chapter text. Classify lines into headings / bullets / prose,
    promoting outline titles (by depth) and conservative in-text labels, then reflow prose runs.
    A heuristic heading is a short, label-like line that (a) follows a break or a finished sentence
    and (b) is followed by a capitalized line/bullet — which separates real section titles from
    mid-paragraph line wraps.\"\"\"
    text = re.sub(r"(\\w)-\\n(\\w)", r"\\1\\2", text)              # de-hyphenate wrapped words
    text = re.sub(r"\\s*[%s]\\s*" % re.escape(_BUL), "\\n• ", text)  # split mid-line bullets
    lines = [l.strip() for l in text.split("\\n")]
    n = len(lines)
    out, pbuf, lbuf = [], [], []
    prev_break, last_end = True, ""
    seen_h, ct = set(), norm(chapter_title)

    def flush_p():
        \"\"\"Emit the buffered prose lines as one reflowed paragraph and clear the buffer.\"\"\"
        if pbuf:
            out.append(" ".join(pbuf)); pbuf.clear()

    def flush_l():
        \"\"\"Emit the buffered list items as one block and clear the buffer.\"\"\"
        if lbuf:
            out.append("\\n".join(lbuf)); lbuf.clear()

    for idx in range(n):
        s = lines[idx]
        if not s:
            flush_p(); flush_l(); prev_break = True
            continue
        if s.startswith("•"):
            flush_p(); lbuf.append("- " + s.lstrip("• ").strip()); prev_break = True
            continue
        key = norm(s)
        if key == ct:                                  # printed chapter title — already the H1
            flush_p(); flush_l(); prev_break = True
            continue
        lvl = heading_keys.get(key)
        if lvl and key not in seen_h and len(s) < 120:
            seen_h.add(key); flush_p(); flush_l(); out.append("#" * lvl + " " + s); prev_break = True
            continue
        nxt = next((lines[j] for j in range(idx + 1, n) if lines[j]), "")
        before = prev_break or last_end in ".!?"
        after = (not nxt) or nxt.startswith("•") or nxt[:1].isupper()
        if before and after and _is_heuristic_heading(s):
            flush_p(); flush_l(); out.append("### " + s); prev_break = True
            continue
        flush_l(); pbuf.append(s); prev_break = False; last_end = s[-1:]
    flush_p(); flush_l()
    body = "\\n\\n".join(b for b in out if b.strip())
    return f"# {chapter_title}\\n\\n{body}".strip() + "\\n"


def cmd_ingest_pdf(argv=None) -> int:
    \"\"\"Ingest a PDF into a corpus JSONL: chunk by outline entries at --chunk-depth, clean page
    boilerplate, rebuild chapter Markdown, and write (or append) one record per chunk.\"\"\"
    ap = argparse.ArgumentParser(prog="skill_builder.py ingest pdf")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--base", required=True, help="synthetic source_url base, e.g. https://host/my-skill")
    ap.add_argument("--skill", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--part", default="", help="path segment to group this PDF's chapters under (e.g. new-features)")
    ap.add_argument("--chunk-depth", type=int, default=0, help="outline depth that defines a chunk (0=top level)")
    ap.add_argument("--layout", action="store_true", help="use pdftotext -layout (better tables, worse prose reflow)")
    ap.add_argument("--skip-titles", default="Contents,Table of Contents,Index")
    ap.add_argument("--start-index", type=int, default=1, help="first chunk_id number (for ordering across PDFs)")
    ap.add_argument("--part-offset", type=int, default=0, help="add to depth-0 part numbers so a second PDF sorts after the first")
    args = ap.parse_args(argv)

    skip = {norm(t) for t in args.skip_titles.split(",") if t.strip()}
    entries = [e for e in flatten(qpdf_outline(args.pdf)) if e["page"]]
    total_pages = npages(args.pdf)
    pages = pdf_pages(args.pdf, args.layout)
    caps_headers, footers = detect_boilerplate(pages)

    # Ancestor slug path (crumb) per entry, with depth-0 parts numbered for stable ordering, so
    # build.py groups chapter files under their part (e.g. .../05-the-cut-page/<chapter>).
    crumbs, stack, partno = [], [], args.part_offset
    for e in entries:
        d = e["depth"]
        stack = stack[:d]
        s = _pdf_slug(e["title"])
        if d == 0:
            partno += 1
            s = f"{partno:02d}-{s}"
        stack = stack + [s]
        crumbs.append(list(stack))

    # Chunk = an outline entry at depth <= chunk-depth; its page span runs to the next such entry.
    chunk_idx = [i for i, e in enumerate(entries)
                 if e["depth"] <= args.chunk_depth and norm(e["title"]) not in skip]
    part_prefix = (args.part.strip("/") + "/") if args.part else ""
    recs = []
    n = args.start_index
    for ci, i in enumerate(chunk_idx):
        e = entries[i]
        start = e["page"]
        nxt = next((entries[j]["page"] for j in chunk_idx[ci + 1:] if entries[j]["page"] > start),
                   total_pages + 1)
        end = nxt - 1
        text = "\\n".join(clean_page(pg, caps_headers, footers) for pg in pages[start - 1:end])
        if not text.strip():
            continue
        # heading dictionary: deeper outline titles falling inside this chunk's page span
        hk = {norm(x["title"]): min(6, x["depth"] - e["depth"] + 1) for x in entries
              if x["depth"] > args.chunk_depth and start <= (x["page"] or 0) <= end and norm(x["title"])}
        md = build_chapter(text, hk, e["title"] or f"Chapter {n}")
        src = f"{args.base.rstrip('/')}/{part_prefix}{'/'.join(crumbs[i])}"
        recs.append({"chunk_id": f"{args.skill}-{n:04d}", "title": e["title"] or f"Chapter {n}",
                     "source_url": src, "text": md, "tags": []})
        n += 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"
    with out.open(mode, encoding="utf-8", newline="\\n") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\\n")
    kb = sum(len(r["text"].encode("utf-8")) for r in recs) / 1024
    print(f"{args.skill}: {len(recs)} chapters from {Path(args.pdf).name} "
          f"({total_pages}p, {len(caps_headers)} hdr + {len(footers)} ftr boilerplate), {kb:.0f} KB -> {out} ({mode})")
    return 0

_INGEST_FORMATS = {"html": cmd_ingest_html, "mdbook": cmd_ingest_mdbook,
                   "rustdoc": cmd_ingest_rustdoc, "pdf": cmd_ingest_pdf}


def main(argv=None) -> int:
    \"\"\"Standalone entry for `python -m builder_components.ingest <html|mdbook|rustdoc|pdf> ...`.

    Selects the source-format handler from the first positional argument and delegates the remaining
    arguments to it. Returns the process exit code (0 ok; 2 on an unknown or missing format). Reads
    ``sys.argv[1:]`` when ``argv`` is None.
    \"\"\"
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m builder_components.ingest {html|mdbook|rustdoc|pdf} [options]")
        return 0
    fn = _INGEST_FORMATS.get(argv[0])
    if not fn:
        print(f"unknown ingest format: {argv[0]}", file=__import__("sys").stderr)
        return 2
    return fn(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.policy_engine===
_SRC['builder_components.policy_engine'] = """
\"\"\"skill_policy engine — skill discovery, Claude/Codex settings I/O, change computation,
and audit/manifest reporting.

A pure library: no argparse and no stdout policy of its own. The CLI lives in policy_cmd.py, which
imports from here. Stdlib only. Frontmatter parsing and project-root resolution come from
builder_components.util (deduped from the former sibling scripts).
\"\"\"

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from .util.frontmatter import parse_frontmatter


TOOL_VERSION = "skill_policy 0.1.0"

# Claude skillOverrides states (https://code.claude.com/docs/en/skills).
CLAUDE_STATES = ("on", "name-only", "user-invocable-only", "off")
DEFAULT_POLICY = "on"  # a skill absent from skillOverrides is treated as "on"
ABSENT = "<absent>"    # sentinel recorded when a skill has no override key

# Broadly-applicable skills: high missed-use cost -> recommend leaving them "on".
# Everything else is treated as specialized -> recommend "user-invocable-only"
# (adjust per project: keep "on" where the project actually uses that domain).
BROAD_SKILLS = frozenset(
    {"git", "github", "cli-design", "powershell-vsdevshell", "skill-drafting"}
)

WORK_SUBDIR = ("AI", "work", "skill-policy")
WORK_GITIGNORE_CONTENT = "*\\n*/\\n!.gitignore\\n"
WORK_GITIGNORE_REQUIRED = ("*", "*/", "!.gitignore")



# --------------------------------------------------------------------------- #
# Helpers (adapted from the sibling scripts' conventions)
# --------------------------------------------------------------------------- #
def _stamp() -> str:
    \"\"\"Return the current local time as a human-readable 'YYYY-MM-DD HH:MM:SS' string.\"\"\"
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp_file() -> str:
    \"\"\"Return the current local time as a filename-safe 'YYYYMMDD-HHMMSS' string.\"\"\"
    return datetime.now().strftime("%Y%m%d-%H%M%S")




def _work_dir(repo_root: Path) -> Path:
    \"\"\"Return the AI/work/skill-policy scratch dir under `repo_root`, refusing if it is a skill package.\"\"\"
    if (repo_root / "SKILL.md").is_file():  # guard: never write AI/work inside a skill package
        raise RuntimeError(f"refusing to use AI/work inside a skill package: {repo_root}")
    return repo_root.joinpath(*WORK_SUBDIR)


def _ensure_work_gitignore(work_dir: Path) -> None:
    \"\"\"Keep repo-local scratch under AI/work untracked by default (codex script pattern).\"\"\"
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        gitignore = work_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(WORK_GITIGNORE_CONTENT, encoding="utf-8")
            return
        text = gitignore.read_text(encoding="utf-8")
        active = {
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        missing = [p for p in WORK_GITIGNORE_REQUIRED if p not in active]
        if missing:
            prefix = "" if not text or text.endswith(("\\n", "\\r")) else "\\n"
            with gitignore.open("a", encoding="utf-8") as handle:
                handle.write(prefix)
                handle.write("\\n# Protect local skill-policy work products.\\n")
                for pattern in missing:
                    handle.write(pattern + "\\n")
    except OSError as exc:
        raise RuntimeError(
            f"could not verify {work_dir}/.gitignore safety ({type(exc).__name__})"
        ) from exc




def _read_text(path: Path) -> str:
    \"\"\"Read and return the file at `path` as UTF-8 text.\"\"\"
    return path.read_text(encoding="utf-8")


def _sha256_file(path: Path) -> str:
    \"\"\"Return the hex SHA-256 of the file at `path`, or "" if it cannot be read.\"\"\"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _is_link_to(path: Path):
    \"\"\"Return the real target if `path` is a junction/symlink, else None.\"\"\"
    try:
        real = os.path.realpath(str(path))
    except OSError:
        return None
    if os.path.normcase(os.path.abspath(str(path))) != os.path.normcase(real):
        return real
    return None


def _est_tokens(chars: int) -> int:
    \"\"\"Estimate token count from a character count (~4 chars per token).\"\"\"
    return round(chars / 4)


# Minimum Claude Code version reported (community-sourced; unverified by Anthropic
# primary docs) to have working skillOverrides. Used only for an informational note.
CLAUDE_SKILLOVERRIDES_BASELINE = (2, 1, 129)


def _parse_ver(text: str):
    \"\"\"Return the first 'N.N.N' version in `text` as an int tuple, or None if absent.\"\"\"
    m = re.search(r"(\\d+)\\.(\\d+)\\.(\\d+)", text or "")
    return tuple(int(g) for g in m.groups()) if m else None


def _version_ge(installed: str, baseline=CLAUDE_SKILLOVERRIDES_BASELINE):
    \"\"\"True/False if comparable, else None (unparseable).\"\"\"
    parsed = _parse_ver(installed)
    if parsed is None:
        return None
    return parsed >= tuple(baseline)


def _claude_version_note() -> str:
    \"\"\"Best-effort, informational only. Never blocks.\"\"\"
    import subprocess  # local import: only when auditing Claude
    try:
        out = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "Claude version: not detected (skillOverrides needs >= 2.1.129; community-sourced figure)."
    ge = _version_ge(out)
    ver = (_parse_ver(out) or ("?",))
    ver_s = ".".join(str(p) for p in ver)
    if ge is True:
        return f"Claude {ver_s}: skillOverrides supported."
    if ge is False:
        return f"WARNING: Claude {ver_s} may predate working skillOverrides (>= 2.1.129)."
    return "Claude version: unparseable; assuming skillOverrides works."


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _layout(skill_dir: Path) -> str:
    \"\"\"flat | router(N): a router has immediate subdirs that each carry a SKILL.md.\"\"\"
    try:
        subs = [
            d for d in skill_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        ]
    except OSError:
        subs = []
    return f"router({len(subs)})" if subs else "flat"


def _has_side_effects(skill_dir: Path) -> bool:
    \"\"\"Return True if `skill_dir` ships a scripts/ directory (treated as a side-effect marker).\"\"\"
    return (skill_dir / "scripts").is_dir()


def _recommend(name: str) -> tuple:
    \"\"\"Return (recommended_policy, confidence, rationale). Transparent rubric.\"\"\"
    if name in BROAD_SKILLS:
        return ("on", "high", "broadly-applicable; high missed-use cost -> keep available")
    return (
        "user-invocable-only",
        "medium",
        "specialized; low missed-use cost in a mixed project -- set to 'on' if this project uses it",
    )


def _make_skill_record(
    name: str,
    runtime_dir: Path,
    platform: str,
    scope: str,
    current_policy: str,
    controllable: bool,
) -> dict:
    \"\"\"Build the full per-skill record (footprint, layout, recommendation, evidence) for one skill.

    Reads SKILL.md frontmatter from `runtime_dir`, classifies the path (store/junction/real), and
    downgrades `controllable` for plugin skills. Returns the record dict.
    \"\"\"
    skill_md = runtime_dir / "SKILL.md"
    text = _read_text(skill_md) if skill_md.is_file() else ""
    fm = parse_frontmatter(text)
    display_name = fm.get("name", name)
    description = fm.get("description", "")
    name_len = len(display_name)
    desc_len = len(description)
    footprint = name_len + desc_len
    target = _is_link_to(runtime_dir)
    if scope == "store":
        path_kind = "store (not surfaced)"
        source_path = str(runtime_dir)
    elif target:
        path_kind = "junction-to-source"
        source_path = target
    else:
        path_kind = "real"
        source_path = str(runtime_dir)
    rec, conf, rationale = _recommend(name)
    warnings = []
    real = (target or str(runtime_dir)).replace("\\\\", "/").lower()
    if "/plugins/" in real:
        controllable = False
        warnings.append("plugin skill -- not controllable via skillOverrides; manage via /plugin")
    return {
        "id": f"{platform}::{scope}::{name}",
        "name": name,
        "display_name": display_name,
        "platform": platform,
        "scope": scope,
        "source_path": source_path,
        "runtime_path": str(runtime_dir),
        "path_kind": path_kind,
        "skill_md_chars": len(text),
        "skill_md_lines": text.count("\\n") + (1 if text and not text.endswith("\\n") else 0),
        "name_len": name_len,
        "desc_len": desc_len,
        "footprint_chars": footprint,
        "est_tokens": _est_tokens(footprint),
        "layout": _layout(runtime_dir),
        "breadth": "broad" if name in BROAD_SKILLS else "specialized",
        "side_effects": _has_side_effects(runtime_dir),
        "current_policy": current_policy,
        "recommended_policy": rec,
        "confidence": conf,
        "rationale": rationale,
        "controllable": controllable,
        "warnings": warnings,
        "source_evidence": {
            "skill_md_sha256": _sha256_file(skill_md),
            "git_head": "(informational; NOT validated)",
        },
    }


def _iter_skill_dirs(root: Path):
    \"\"\"Yield each immediate subdirectory of `root` that holds a SKILL.md, skipping dotfiles/INDEX.md.\"\"\"
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name == "INDEX.md":
            continue
        if (child / "SKILL.md").is_file():
            yield child


def discover_claude(
    project_dir: Path,
    extra_roots,
    overrides: dict,
    include_store,
) -> list:
    \"\"\"Discover Claude skills from <project>/.claude/skills + extra roots (+ store).\"\"\"
    found = {}
    roots = [(project_dir / ".claude" / "skills", "project")]
    for r in extra_roots or []:
        roots.append((Path(r), "explicit"))
    for root, scope in roots:
        for skill_dir in _iter_skill_dirs(root):
            name = skill_dir.name
            policy = overrides.get(name, DEFAULT_POLICY)
            rec = _make_skill_record(name, skill_dir, "claude", scope, policy, True)
            found.setdefault(name, rec)
    if include_store is not None:
        store = Path(include_store)
        for skill_dir in _iter_skill_dirs(store):
            name = skill_dir.name
            if name in found:
                continue
            # Not surfaced -> no idle cost yet; policy entry (if any) is inert.
            policy = overrides.get(name, DEFAULT_POLICY)
            current = "not surfaced (0)" if policy == DEFAULT_POLICY else f"{policy} (inert until surfaced)"
            found[name] = _make_skill_record(name, skill_dir, "claude", "store", current, True)
    return list(found.values())


def discover_codex(project_dir: Path, home: Path) -> list:
    \"\"\"AUDIT-ONLY discovery of Codex skills (project .agents/skills + ~/.codex/skills).\"\"\"
    out = []
    seen = set()
    roots = [
        (project_dir / ".agents" / "skills", "project"),
        (project_dir / ".codex" / "skills", "project-legacy"),
        (home / ".codex" / "skills", "user-legacy"),
        (home / ".agents" / "skills", "user"),
    ]
    for root, scope in roots:
        for skill_dir in _iter_skill_dirs(root):
            key = (scope, skill_dir.name)
            if key in seen:
                continue
            seen.add(key)
            rec = _make_skill_record(
                skill_dir.name, skill_dir, "codex", scope, "implicit (default)", False
            )
            rec["advisory"] = (
                "Codex audit-only: no central per-skill policy override; explicit-only "
                "invocation is currently unreliable (openai/codex#23454)."
            )
            out.append(rec)
    return out


# --------------------------------------------------------------------------- #
# Claude settings I/O
# --------------------------------------------------------------------------- #
def resolve_settings_path(scope: str, project_dir: Path, home: Path, explicit) -> Path:
    \"\"\"Resolve the Claude settings file for `scope` (local/project/user), honoring `explicit` first.

    Raises ValueError on an unknown scope.
    \"\"\"
    if explicit:
        return Path(explicit)
    if scope == "local":
        return project_dir / ".claude" / "settings.local.json"
    if scope == "project":
        return project_dir / ".claude" / "settings.json"
    if scope == "user":
        return home / ".claude" / "settings.json"
    raise ValueError(f"unknown scope: {scope}")


def load_settings(path: Path) -> dict:
    \"\"\"Return parsed settings, or {} if the file is missing. Refuse malformed JSON.\"\"\"
    if not path.exists():
        return {}
    raw = _read_text(path)
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"refusing to touch malformed JSON settings file: {path} ({exc})"
        )
    if not isinstance(data, dict):
        raise RuntimeError(f"settings root is not a JSON object: {path}")
    return data


def get_overrides(settings: dict) -> dict:
    \"\"\"Return a copy of the settings' skillOverrides map; refuse if it is present but not an object.\"\"\"
    ov = settings.get("skillOverrides", {})
    if ov in (None, {}):
        return {}
    if not isinstance(ov, dict):
        raise RuntimeError("existing skillOverrides is not a JSON object; refusing to edit")
    return dict(ov)


def compute_changes(current_overrides: dict, decisions) -> list:
    \"\"\"decisions: iterable of (name, selected_policy). Return effective changes only.\"\"\"
    changes = []
    for name, selected in decisions:
        if selected not in CLAUDE_STATES:
            raise RuntimeError(f"invalid policy '{selected}' for skill '{name}'")
        before = current_overrides.get(name, ABSENT)
        after = ABSENT if selected == "on" else selected  # "on" == default == remove key
        if before == after:
            continue
        op = "remove" if after == ABSENT else ("set" if before == ABSENT else "change")
        changes.append({"name": name, "before": before, "after": after, "op": op})
    return changes


def apply_changes_to_settings(settings: dict, changes) -> dict:
    \"\"\"Return a deep copy of `settings` with `changes` applied to skillOverrides (dropping the key if empty).\"\"\"
    new = json.loads(json.dumps(settings))  # deep copy, preserves unknown keys
    overrides = dict(new.get("skillOverrides", {}) or {})
    for ch in changes:
        if ch["after"] == ABSENT:
            overrides.pop(ch["name"], None)
        else:
            overrides[ch["name"]] = ch["after"]
    if overrides:
        new["skillOverrides"] = overrides
    else:
        new.pop("skillOverrides", None)
    return new


def atomic_write_json(path: Path, obj: dict) -> None:
    \"\"\"Write JSON atomically (temp in same dir, validate, os.replace). Strict JSON.\"\"\"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2) + "\\n"
    json.loads(text)  # validate before replacing the live file
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".skillpolicy-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\\n") as handle:
            handle.write(text)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def backup_file(path: Path, work_dir: Path) -> str:
    \"\"\"Copy `path` into work_dir/backups with a timestamped name; return the backup path ("" if absent).\"\"\"
    if not path.exists():
        return ""
    backups = work_dir / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    dest = backups / f"{path.name}.{_stamp_file()}.bak"
    dest.write_bytes(path.read_bytes())
    return str(dest)


# --------------------------------------------------------------------------- #
# Reports & manifest
# --------------------------------------------------------------------------- #
def _footprint_summary(skills) -> dict:
    \"\"\"Summarize surfaced (non-store) skills: count, total footprint chars, and estimated tokens.\"\"\"
    surfaced = [s for s in skills if s["scope"] != "store"]
    total = sum(s["footprint_chars"] for s in surfaced)
    return {"surfaced_count": len(surfaced), "total_footprint_chars": total, "total_est_tokens": _est_tokens(total)}


def write_audit_report(work_dir: Path, skills, platform: str, settings_path) -> tuple:
    \"\"\"Write timestamped Markdown and JSON audit reports for `skills` into `work_dir`.

    Returns (md_path, json_path).
    \"\"\"
    work_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp_file()
    md_path = work_dir / f"audit-{platform}-{stamp}.md"
    json_path = work_dir / f"audit-{platform}-{stamp}.json"
    fp = _footprint_summary(skills)
    lines = [
        f"# Skill invocation policy audit ({platform})",
        "",
        f"- Generated: {_stamp()}",
        f"- Tool: {TOOL_VERSION}",
        f"- Settings file: {settings_path}",
        f"- Surfaced skills: {fp['surfaced_count']} | est. idle listing ~{fp['total_est_tokens']} tokens",
        "",
        "| Skill | Platform | Scope | Current | ~tokens | Breadth | Side-fx | Recommended | Conf | Controllable |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in sorted(skills, key=lambda x: (x["platform"], x["scope"], x["name"])):
        lines.append(
            "| {name} | {platform} | {scope} | {current_policy} | {est_tokens} | {breadth} | {sfx} | {rec} | {conf} | {ctrl} |".format(
                sfx="yes" if s["side_effects"] else "-",
                rec=s["recommended_policy"] if s["platform"] == "claude" else "(audit-only)",
                conf=s["confidence"] if s["platform"] == "claude" else "-",
                ctrl="yes" if s["controllable"] else "no",
                **s,
            )
        )
    lines += [
        "",
        "Recommendations assume a general/mixed project; keep a domain skill `on` where the "
        "project uses it. Codex rows are audit-only (no central policy override; explicit-only "
        "currently unreliable per openai/codex#23454). Footprint is an estimate (name+description "
        "chars / 4), not exact token usage.",
        "",
    ]
    md_path.write_text("\\n".join(lines), encoding="utf-8", newline="\\n")
    json_path.write_text(
        json.dumps({"generated": _stamp(), "tool": TOOL_VERSION, "platform": platform,
                    "settings_path": str(settings_path), "footprint": fp, "skills": skills},
                   indent=2) + "\\n",
        encoding="utf-8", newline="\\n",
    )
    return md_path, json_path


def build_manifest(skills, platform: str, scope: str, settings_path) -> dict:
    \"\"\"Build a user-editable decision manifest (Claude skills only) with unapproved recommendations.\"\"\"
    rows = []
    for s in skills:
        if s["platform"] != "claude":
            continue  # only Claude is appliable
        rows.append({
            "id": s["id"],
            "name": s["name"],
            "display_name": s["display_name"],
            "platform": "claude",
            "scope": s["scope"],
            "source_path": s["source_path"],
            "runtime_path": s["runtime_path"],
            "path_kind": s["path_kind"],
            "current_policy": s["current_policy"],
            "recommended_policy": s["recommended_policy"],
            "selected_policy": None,   # user fills; null = no change
            "approved": False,         # must be true to apply
            "rationale": s["rationale"],
            "warnings": s["warnings"],
            "controllable": s["controllable"],
            "expected_operations": [],
            "source_evidence": s["source_evidence"],
        })
    return {
        "schema_version": 1,
        "generated": _stamp(),
        "tool": TOOL_VERSION,
        "platform": platform,
        "scope": {"type": scope, "settings_path": str(settings_path)},
        "skills": rows,
    }


def load_manifest(path: Path) -> dict:
    \"\"\"Load and schema-check a decision manifest at `path`; raise RuntimeError on any problem.\"\"\"
    if not path.exists():
        raise RuntimeError(f"decision manifest not found: {path} (run `plan` first)")
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"manifest is not valid JSON: {path} ({exc})")
    if data.get("schema_version") != 1:
        raise RuntimeError("unsupported manifest schema_version (expected 1)")
    if not isinstance(data.get("skills"), list):
        raise RuntimeError("manifest has no skills array")
    return data


def approved_decisions(manifest: dict) -> list:
    \"\"\"Return [(name, selected_policy)] for approved, controllable Claude rows only.\"\"\"
    out = []
    for row in manifest.get("skills", []):
        if row.get("platform") != "claude":
            continue
        if not row.get("approved"):
            continue
        if row.get("controllable") is False:
            print(f"  ! skipping '{row.get('name')}': {('; '.join(row.get('warnings') or [])) or 'not controllable'}")
            continue
        sel = row.get("selected_policy")
        if sel is None:
            continue
        out.append((row.get("name"), sel))
    return out
"""

# ===MODULE builder_components.recontext===
_SRC['builder_components.recontext'] = """
\"\"\"Recontextualization command group: scan/batch/drain/integrate/promote (was the recontext section).\"\"\"

from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from . import recontext_core as recon
from builder_components.util.config import VALIDATOR


# ==============================================================================
# RECONTEXT — recontextualization primitives over the shared recontext_core engine.
# Turn a *verbatim* doc reference into *original prose* while preserving identifiers,
# and verify it (Gate A/B/C). Every path is a CLI argument — nothing is hardcoded.
# For the locked, gated, subagent-facing writer see recontext_subagent.py.
#
# Orchestration (scan -> batch -> drain -> integrate -> finish -> reconcile -> promote) is fully
# generalized: owners and every root come from a --config JSON or CLI args; nothing is hardcoded to a
# skill, owner, or path. The campaign-specific owner map / absolute paths of the scratch pipeline are
# replaced by `_recon_cfg` below.
# ==============================================================================

# The drain spawns the locked writer and the cleaner/gater as subprocesses of the ONE all-in-one tool:
# `python skill_builder.py recontext-subagent …` and `python skill_builder.py recontext …`. `_BUILDER`
# is the generated all-in-one (`skill_builder.py`) one directory up from this package.
_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BUILDER = os.path.join(_SCRIPTS, "skill_builder.py")


def _recon_cfg(args) -> dict:
    \"\"\"Resolve roots/owner from an optional --config JSON, overridden by CLI args. No hardcoding.\"\"\"
    cfg = {}
    if getattr(args, "config", None):
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))

    def get(name, default=None):
        \"\"\"Resolve a setting from the CLI arg, then the config JSON, then the default.\"\"\"
        return getattr(args, name, None) or cfg.get(name) or default

    return {
        "source_root": get("source_root"),
        "work_root": get("work_root"),
        "store_root": get("store_root"),
        "owner": get("owner", "agent"),
        "python": get("python", sys.executable),
        "validator": get("validator", VALIDATOR),
    }


def _recon_rel(source_root, p) -> str:
    \"\"\"Return p as a POSIX path relative to source_root.\"\"\"
    return Path(p).resolve().relative_to(Path(source_root).resolve()).as_posix()


def _recon_subskill(skill: str, rel: str) -> str:
    \"\"\"Return the sub-skill path between the skill name and the 'references' segment of rel.\"\"\"
    parts = rel.split("/")
    return "/".join(parts[1:parts.index("references")]) if "references" in parts else ""


def _recon_queue(work_root, owner) -> Path:
    \"\"\"Return the path to the owner's queue JSONL file under work_root.\"\"\"
    return Path(work_root) / f"queue.{owner}.jsonl"


def _recon_load_queue(path) -> dict:
    \"\"\"Load the JSONL queue at path into a dict keyed by each row's 'path'.\"\"\"
    rows = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["path"]] = r
    return rows


def _recon_save_queue(path, rows) -> None:
    \"\"\"Write the queue rows back to path as newline-delimited JSON.\"\"\"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\\n") as fh:
        for r in rows.values():
            fh.write(json.dumps(r, ensure_ascii=False) + "\\n")


def _recon_scan(cfg, skill):
    \"\"\"Walk <source_root>/<skill>/**/references/*.md, score+classify each, upsert into the owner's
    queue (idempotent: status/attempts/notes preserved). Returns (counts, queue_path).\"\"\"
    skill_dir = Path(cfg["source_root"]) / skill
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"source skill dir missing: {skill_dir}")
    qpath = _recon_queue(cfg["work_root"], cfg["owner"])
    rows = _recon_load_queue(qpath)
    counts = collections.Counter()
    for p in recon.content_files(skill_dir):
        rel = _recon_rel(cfg["source_root"], p)
        ratio, pw, plc, chrome, marker_ok = recon.score_file(recon.read(p))
        faction, tier, mode, needs_cleanup, review = recon.classify(ratio, pw, plc, chrome, marker_ok)
        prev = rows.get(rel, {})
        rows[rel] = {
            "skill": skill, "subskill": _recon_subskill(skill, rel), "path": rel, "abspath": str(p),
            "owner": cfg["owner"], "bytes": p.stat().st_size, "prose_ratio": ratio, "prose_words": pw,
            "prose_units": plc, "mode": mode, "chrome": chrome, "marker_ok": marker_ok,
            "faction": faction, "tier": tier, "needs_cleanup": needs_cleanup, "review": review,
            "status": prev.get("status", "pending"), "attempts": prev.get("attempts", 0),
            "notes": prev.get("notes", ""),
        }
        counts["total"] += 1
        counts[f"f{faction}"] += 1
        counts[tier] += 1
    _recon_save_queue(qpath, rows)
    return counts, qpath


def _recon_batches(cfg, skill, max_full=5, max_extract=15, f1_size=12):
    \"\"\"Group the skill's pending queue rows into F1 cleanup batches and F2 rewrite batches (by mode).\"\"\"
    rows = [r for r in _recon_load_queue(_recon_queue(cfg["work_root"], cfg["owner"])).values()
            if r["skill"] == skill and r.get("status") == "pending"]
    f1 = [r for r in rows if r["faction"] == 1]
    f2 = [r for r in rows if r["faction"] == 2]

    def grp(items, n):
        \"\"\"Split items into consecutive chunks of at most n elements.\"\"\"
        return [items[i:i + n] for i in range(0, len(items), n)]

    def fent(r):
        \"\"\"Project a queue row into the minimal file entry a batch needs.\"\"\"
        return {"abspath": r["abspath"], "rel": r["path"], "mode": r["mode"], "tier": r["tier"]}

    f1_batches = [[fent(r) for r in b] for b in grp(f1, f1_size)]
    f2_batches = []
    for mode in ("full", "extract"):
        cap = max_full if mode == "full" else max_extract
        for b in grp([r for r in f2 if r["mode"] == mode], cap):
            f2_batches.append({"mode": mode, "files": [fent(r) for r in b]})
    return {"skill": skill, "f1_batches": f1_batches, "f2_batches": f2_batches,
            "pending_f1": len(f1), "pending_f2": len(f2)}


_DRAIN_JS = r'''export const meta = {
  name: 'recontext-__SKILL__',
  description: 'Recontextualize pending __SKILL__ files through the locked, gated writer',
  phases: [{ title: 'F1' }, { title: 'F2' }],
}
const SKILL = "__SKILL__";
const PY = __PY__;
const BUILDER = __BUILDER__;
const WR = __WR__;
const SR = __SR__;
const BATCHES = __BATCHES__;
const WAVE = __WAVE__;
function chunk(a, n){ const o=[]; for(let i=0;i<a.length;i+=n) o.push(a.slice(i,i+n)); return o; }
async function runWaves(t){ const o=[]; for(const g of chunk(t,WAVE)){ const r=await parallel(g); for(const x of r) o.push(x);} return o; }
const FILE={type:'object',additionalProperties:false,properties:{rel:{type:'string'},status:{type:'string'},gate_a:{type:'boolean'},gate_b_residue:{type:'number'},gate_b_ratio:{type:'number'},gate_c:{type:'boolean'},mode:{type:'string'},tier:{type:'string'},needs_review:{type:'boolean'},notes:{type:'string'}},required:['rel','status','gate_a','gate_c']};
const SCHEMA={type:'object',additionalProperties:false,properties:{files:{type:'array',items:FILE}},required:['files']};

function f1prompt(b, lbl){
  const list = b.map(f => '- ' + f.abspath + '  (rel: ' + f.rel + ')').join("\\n");
  return `Faction-1 CLEANUP-ONLY for ${b.length} ${SKILL} files (NO rewriting). Label ${lbl}.
For EACH file: copy <abspath> to WORK = "${WR}/working/" + <rel> (create parent dirs), then run:
  ${PY} "${BUILDER}" recontext clean "<WORK>" --skill-title "${SKILL}"
  ${PY} "${BUILDER}" recontext gate "<abspath>" "<WORK>" --faction 1
Parse the gate JSON. NEVER edit the source; NEVER write outside "${WR}"; NEVER run git.
Files:
${list}
Return {files:[{rel:<rel>, status:(gate_a&&gate_c?"clean":"error"), gate_a, gate_b_residue:0, gate_b_ratio:1, gate_c, mode:"none", tier:"none", needs_review:false, notes:""}]}.`;
}

function f2prompt(b, lbl){
  const list = b.files.map((f,i) => `${i}. [${f.mode}/${f.tier}] ${f.abspath}  (rel: ${f.rel})`).join("\\n");
  return `Faction-2 RECONTEXTUALIZE ${b.files.length} ${SKILL} files (mode=${b.mode}) through the LOCKED writer. Label ${lbl}.
You NEVER write rewrite artifacts yourself: the locked writer is the only artifact writer and it GATES every rewrite (Gate A identifiers, Gate B 13-word residue, Gate C cruft), writing ONLY on PASS.
For EACH file below (worker id = "${lbl}-f" + <index>):
  1. ${PY} "${BUILDER}" recontext-subagent prepare --work-root "${WR}" --skill ${SKILL} --worker <wid> --source "<abspath>" --source-root "${SR}" --rel "<rel>" --mode ${b.mode} --tier <tier>
  2. ${PY} "${BUILDER}" recontext-subagent show --work-root "${WR}" --skill ${SKILL} --worker <wid>   (prints the contract + the work)
  3. Produce the rewrite per the contract: mode "extract" -> EXACTLY {"items":[...]} (same i/cell keys + order + count as the packet); mode "full" -> the WHOLE rewritten file as raw text. Preserve every identifier / code span / link target / number / table; reword prose so no ~13-word run matches the source.
  4. Pipe the rewrite to: ${PY} "${BUILDER}" recontext-subagent submit --work-root "${WR}" --skill ${SKILL} --worker <wid>
     If submit prints "FAIL" (a gate failed), fix exactly what it reports and resubmit until it prints "PASS submit".
  5. Read "${WR}/recontext/${SKILL}/<wid>/result.json" and use its files[0] verdict in your return.
NEVER edit the source tree or the store; NEVER run git.
Files:
${list}
Return {files:[{rel, status:(all gates pass?"up-to-standard":"needs-rework"), gate_a, gate_b_residue, gate_b_ratio, gate_c, mode:"${b.mode}", tier, needs_review, notes}]}.`;
}

const f1t = BATCHES.f1_batches.map((b,i) => () => agent(f1prompt(b,'f1-'+SKILL+'-b'+(i+1)), {schema:SCHEMA, phase:'F1', label:'f1-b'+(i+1)}));
const f2t = BATCHES.f2_batches.map((b,i) => () => agent(f2prompt(b,'f2-'+SKILL+'-b'+(i+1)), {schema:SCHEMA, phase:'F2', label:'f2-'+b.mode+'-b'+(i+1)}));
const f1 = await runWaves(f1t);
const f2 = await runWaves(f2t);
return { skill: SKILL, f1: f1.filter(Boolean), f2: f2.filter(Boolean) };
'''


def _recon_drain_js(cfg, skill, batches, wave) -> str:
    \"\"\"Render the drain Workflow JS by substituting cfg/skill/batches/wave into the _DRAIN_JS template.\"\"\"
    repl = {
        "__SKILL__": skill,
        "__PY__": json.dumps(cfg["python"]),
        "__BUILDER__": json.dumps(_BUILDER),
        "__WR__": json.dumps(str(Path(cfg["work_root"]))),
        "__SR__": json.dumps(str(Path(cfg["source_root"]))),
        "__BATCHES__": json.dumps(batches),
        "__WAVE__": str(int(wave)),
    }
    js = _DRAIN_JS
    for k, v in repl.items():
        js = js.replace(k, v)
    return js


def _recon_integrate(cfg, skill):
    \"\"\"Place every gated work.md the locked writer produced for <skill> into <work_root>/working/<rel>.
    Re-gates (faction 2) as a cheap backstop; never places a failing file. `finish` owns queue state.\"\"\"
    work_root, source_root = Path(cfg["work_root"]), Path(cfg["source_root"])
    placed, skipped = [], []
    base = work_root / "recontext" / skill
    for result in (sorted(base.glob("*/result.json")) if base.is_dir() else []):
        rec = json.loads(result.read_text(encoding="utf-8"))
        if rec.get("errors"):
            skipped.append((str(result), f"errors: {rec['errors']}"))
            continue
        for f in rec.get("files", []):
            rel, work = f["rel"], Path(f["work"])
            src = source_root / Path(*rel.split("/"))
            if not work.is_file() or not src.is_file():
                skipped.append((rel, "missing work/source"))
                continue
            if not recon.run_gates(recon.read(src), recon.read(work), faction=2)["passed"]:
                skipped.append((rel, "re-gate failed"))
                continue
            dest = work_root / "working" / Path(*rel.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(work, dest)
            placed.append(rel)
    return placed, skipped


def _recon_finish(cfg, skill):
    \"\"\"Re-gate every working file for <skill> against its source; re-queue any failure.\"\"\"
    work_root, source_root = Path(cfg["work_root"]), Path(cfg["source_root"])
    qpath = _recon_queue(work_root, cfg["owner"])
    rows = _recon_load_queue(qpath)
    wdir = work_root / "working" / skill
    passed, failed = [], []
    for p in (recon.content_files(wdir) if wdir.is_dir() else []):
        rel = p.resolve().relative_to((work_root / "working").resolve()).as_posix()
        src = source_root / Path(*rel.split("/"))
        if not src.is_file():
            failed.append((rel, "no source"))
            continue
        faction = rows.get(rel, {}).get("faction", 2)
        if recon.run_gates(recon.read(src), recon.read(p), faction=faction)["passed"]:
            passed.append(rel)
            if rel in rows:
                rows[rel]["status"] = "done"
        else:
            failed.append((rel, "gate failed"))
            if rel in rows:
                rows[rel]["status"] = "pending"
    _recon_save_queue(qpath, rows)
    return passed, failed


def _recon_reconcile(cfg, skill):
    \"\"\"Verify every source content file is queued and done.\"\"\"
    rows = _recon_load_queue(_recon_queue(Path(cfg["work_root"]), cfg["owner"]))
    src_rels = {_recon_rel(cfg["source_root"], p)
                for p in recon.content_files(Path(cfg["source_root"]) / skill)}
    queued = {r["path"] for r in rows.values() if r["skill"] == skill}
    done = {r["path"] for r in rows.values() if r["skill"] == skill and r.get("status") == "done"}
    return {"skill": skill, "source": len(src_rels), "queued": len(queued), "done": len(done),
            "missing_from_queue": sorted(src_rels - queued), "pending": sorted(queued - done)}


def _recon_promote(cfg, skill, validate_package=False):
    \"\"\"Validate the finished working skill, then move it into the store and write a done marker.\"\"\"
    if not cfg["store_root"]:
        return False, "promote requires --store-root (or config store_root)"
    work_root, store_root = Path(cfg["work_root"]), Path(cfg["store_root"])
    wdir = work_root / "working" / skill
    if not wdir.is_dir():
        return False, f"working skill dir missing: {wdir}"
    validator = Path(cfg["validator"])
    if validator.is_file():
        cmd = ([cfg["python"], str(validator), "validate"]
               + (["--package"] if validate_package else []) + [str(wdir)])
        r = subprocess.run(cmd, text=True, capture_output=True)
        if r.returncode != 0:
            return False, f"validator failed: {(r.stdout + r.stderr).strip()[:400]}"
    dest = store_root / skill
    if dest.exists():
        return False, f"store dir already exists (refusing to overwrite): {dest}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(wdir), str(dest))
    marker = work_root / "done-markers" / f"{skill}.{cfg['owner']}.done"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{skill} promoted by {cfg['owner']}\\n", encoding="utf-8")
    return True, str(dest)


def cmd_recontext(argv=None) -> int:
    \"\"\"Parse and dispatch the `recontext` subcommands (clean/extract/splice/gate/triage and the
    scan/batch/drain/integrate/finish/reconcile/promote orchestration). Returns a process exit code.\"\"\"
    ap = argparse.ArgumentParser(prog="skill_builder.py recontext",
                                 description="Recontextualization primitives (clean/extract/splice/gate/triage).")
    sub = ap.add_subparsers(dest="op", required=True)

    sp = sub.add_parser("clean", help="strip scrape chrome + normalize marker/blanks (in place)")
    sp.add_argument("file")
    sp.add_argument("--skill-title", default=None, help="skill name; normalizes the marker blockquote")
    sp.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser("extract", help="extract prose units into a rewrite packet")
    sp.add_argument("source")
    sp.add_argument("--out", help="write the packet JSON here (else stdout)")

    sp = sub.add_parser("splice", help="re-insert rewrites at exact prose-unit positions (tamper-proof)")
    sp.add_argument("source")
    sp.add_argument("rewrites", help='a {"items":[{"i","cell","text"}]} JSON file')
    sp.add_argument("out")

    sp = sub.add_parser("gate", help="run Gate A/B/C on a (source, working) pair -> JSON verdict")
    sp.add_argument("source")
    sp.add_argument("working")
    sp.add_argument("--faction", type=int, default=2, choices=(1, 2))
    sp.add_argument("--min-run", type=int, default=13)

    sp = sub.add_parser("triage", help="classify one file into faction/tier/mode by prose density")
    sp.add_argument("source")

    def add_roots(p, store=False):
        \"\"\"Add the shared --config/root/owner/skill args (plus store-root/validator when store=True).\"\"\"
        p.add_argument("--config", help="JSON with source_root/work_root/store_root/owner/python/validator")
        p.add_argument("--source-root", help="read-only source tree (contains <skill>/.../references/*.md)")
        p.add_argument("--work-root", help="writable sandbox (queues, assignments, working copies)")
        p.add_argument("--owner", help="queue namespace (default: agent)")
        p.add_argument("--python", help="python used inside generated drain workflows")
        if store:
            p.add_argument("--store-root", help="finished-skill destination for promote")
            p.add_argument("--validator", help="path to skill_builder.py (the 'validate' subcommand is appended)")
        p.add_argument("--skill", required=True)

    sp = sub.add_parser("scan", help="scan a skill's source -> the owner's queue (faction/tier/mode)")
    add_roots(sp)
    sp = sub.add_parser("batch", help="group the queue's pending rows into work batches (JSON)")
    add_roots(sp)
    sp.add_argument("--max-full", type=int, default=5)
    sp.add_argument("--max-extract", type=int, default=15)
    sp = sub.add_parser("drain", help="generate a Workflow script that drives the locked writer")
    add_roots(sp)
    sp.add_argument("--max-full", type=int, default=5)
    sp.add_argument("--max-extract", type=int, default=15)
    sp.add_argument("--wave", type=int, default=8, help="max concurrent agents per wave")
    sp.add_argument("--out", help="path for the generated drain-<skill>.wf.js (default: <work-root>)")
    sp = sub.add_parser("integrate", help="place the locked writer's gated output + mark queue done")
    add_roots(sp)
    sp = sub.add_parser("finish", help="re-gate all working files for a skill; re-queue failures")
    add_roots(sp)
    sp = sub.add_parser("reconcile", help="verify every source file is queued and done")
    add_roots(sp)
    sp = sub.add_parser("promote", help="validate the finished working skill and move it to the store")
    add_roots(sp, store=True)
    sp.add_argument("--validate-package", action="store_true", help="validate as a router/package")

    args = ap.parse_args(argv)

    if args.op == "clean":
        text = recon.read(Path(args.file))
        title = recon.skill_title(args.skill_title) if args.skill_title else None
        new, actions = recon.clean_text(text, title)
        if not args.dry_run and new != text:
            recon.write(Path(args.file), new)
        print(f"{args.file}: {actions or ['none']}" + ("  (dry-run)" if args.dry_run else ""))
        return 0

    if args.op == "extract":
        packet = recon.extract(recon.read(Path(args.source)))
        packet["file"] = str(Path(args.source))
        out = json.dumps(packet, ensure_ascii=False, indent=1)
        if args.out:
            Path(args.out).write_text(out, encoding="utf-8")
            print(f"{args.source}: {len(packet['items'])} prose items -> {args.out}")
        else:
            print(out)
        return 0

    if args.op == "splice":
        rewrites = recon.load_rewrites(json.loads(Path(args.rewrites).read_text(encoding="utf-8")))
        out_text, stats = recon.splice(recon.read(Path(args.source)), rewrites)
        recon.write(Path(args.out), out_text)
        print(json.dumps(stats))
        return 0

    if args.op == "gate":
        verdict = recon.run_gates(recon.read(Path(args.source)), recon.read(Path(args.working)),
                                  args.faction, args.min_run)
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if verdict["passed"] else 1

    if args.op == "triage":
        ratio, pw, plc, chrome, marker_ok = recon.score_file(recon.read(Path(args.source)))
        faction, tier, mode, needs_cleanup, review = recon.classify(ratio, pw, plc, chrome, marker_ok)
        print(json.dumps({"file": str(Path(args.source)), "prose_ratio": ratio, "prose_words": pw,
                          "prose_units": plc, "chrome": chrome, "marker_ok": marker_ok,
                          "faction": faction, "tier": tier, "mode": mode,
                          "needs_cleanup": needs_cleanup, "review": review},
                         ensure_ascii=False, indent=2))
        return 0

    # ----- orchestration (config/CLI-driven; no hardcoded skill/owner/path) -----
    if args.op in ("scan", "batch", "drain", "integrate", "finish", "reconcile", "promote"):
        cfg = _recon_cfg(args)
        missing = [k for k in ("source_root", "work_root") if not cfg[k]
                   and not (args.op == "promote" and k == "source_root")]
        if missing:
            print(f"recontext {args.op}: missing required root(s): {', '.join('--' + m.replace('_', '-') for m in missing)}")
            return 2

        if args.op == "scan":
            counts, qpath = _recon_scan(cfg, args.skill)
            print(f"{args.skill}: total={counts['total']} F1={counts['f1']} F2={counts['f2']} "
                  f"(light={counts['light']} medium={counts['medium']} heavy={counts['heavy']}) -> {qpath}")
            return 0

        if args.op == "batch":
            print(json.dumps(_recon_batches(cfg, args.skill, args.max_full, args.max_extract),
                             ensure_ascii=False, indent=2))
            return 0

        if args.op == "drain":
            batches = _recon_batches(cfg, args.skill, args.max_full, args.max_extract)
            js = _recon_drain_js(cfg, args.skill, batches, args.wave)
            out = Path(args.out) if args.out else Path(cfg["work_root"]) / f"drain-{args.skill}.wf.js"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(js, encoding="utf-8", newline="\\n")
            print(f"{args.skill}: pending F1={batches['pending_f1']} F2={batches['pending_f2']} -> {out}")
            print("Launch with the Workflow tool: {scriptPath: \\"" + str(out) + "\\"}")
            return 0

        if args.op == "integrate":
            placed, skipped = _recon_integrate(cfg, args.skill)
            print(f"{args.skill}: integrated {len(placed)} gated file(s); skipped {len(skipped)}")
            for rel, why in skipped[:25]:
                print(f"  skip {rel}: {why}")
            return 0 if not skipped else 1

        if args.op == "finish":
            passed, failed = _recon_finish(cfg, args.skill)
            print(f"{args.skill}: {len(passed)} pass, {len(failed)} re-queued -> "
                  f"{'READY-TO-PROMOTE' if not failed else 'NOT-READY'}")
            for rel, why in failed[:25]:
                print(f"  fail {rel}: {why}")
            return 0 if not failed else 1

        if args.op == "reconcile":
            rep = _recon_reconcile(cfg, args.skill)
            print(json.dumps(rep, ensure_ascii=False, indent=2))
            return 0 if not rep["missing_from_queue"] and not rep["pending"] else 1

        if args.op == "promote":
            ok, detail = _recon_promote(cfg, args.skill, args.validate_package)
            print(f"{args.skill}: {'PROMOTED -> ' + detail if ok else 'NOT promoted: ' + detail}")
            return 0 if ok else 1

    return 2

def main(argv=None) -> int:
    \"\"\"Standalone entry point for `python -m builder_components.recontext`; delegates to cmd_recontext.\"\"\"
    return cmd_recontext(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.recontext_subagent===
_SRC['builder_components.recontext_subagent'] = """
#!/usr/bin/env python3
\"\"\"recontext_subagent.py — the locked artifact writer for recontextualization subagents.

A Claude/Codex subagent that recontextualizes a verbatim documentation file MUST go through this
script; it never writes rewrite artifacts with the Write tool. The script is the rail: it derives
every writable path internally, refuses any caller-supplied output path, confines all writes under a
single caller-declared `--work-root`, and — crucially — runs the real cleanup + Gate A/B/C verifier
before it writes anything, so a `PASS` is a *gated* PASS, never an unverified claim.

It is portable and self-contained: no hardcoded skill, owner, repo, or absolute path, and no
dependency on gitignored scratch — all algorithms come from the sibling `recontext_core` module that
ships with the skill.

Subcommands:
  prepare    (orchestrator) Build the assignment + packet under <work-root>/recontext/<skill>/<worker>.
  show       (subagent)     Print the assignment, the rewrite contract, and the work to rewrite.
  submit     (subagent)     Read the rewrite from stdin, splice/clean it, GATE it (A/B/C), and only
                            on PASS write the canonical artifacts. Refuses to write failing work.
  audit      (anyone)       Recursively report misplaced legacy `_pkt_/_rw_/_result_` artifacts.

Modes (per the rewrite contract):
  extract    sparse prose: stdin is {"items":[{"i","cell","text"}]}; spliced back at exact positions.
  full       prose-dense:  stdin is the WHOLE rewritten file text; cleaned + gated in place.

Exit codes: 0 success · 1 validation/gate/audit failure · 2 command-line usage error.
\"\"\"
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from . import recontext_core as core

try:  # stdin must accept any source glyph regardless of console code page (core does stdout/stderr)
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass


TOOL_NAME = "recontext_subagent"
TOOL_VERSION = "0.2.0"
SCHEMA_VERSION = 2
MIN_RUN = 13
FACTION = 2  # this tool only handles recontextualization (Faction-2) files

SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
WORKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MODE_CHOICES = ("extract", "full")
ASSIGNMENT_SUBDIR = "recontext"
# Legacy hand-written misplaced-artifact names (the failure this tool exists to prevent). The new
# canonical names (packet.json/rewrite.json/work.md/result.json) deliberately do NOT match this.
LEGACY_ARTIFACT_RE = re.compile(r"^_(?:pkt|rw|result)_.+", re.IGNORECASE)

# A small style denylist of filler tics. NOT a fidelity guard — Gate A/B/C below are the real
# verifier. Kept only to reject obvious boilerplate before the gates run.
STYLE_BANNED_PHRASES = (
    "@@P", "in practice", "as applicable", "for this flow", "in that case",
    "as noted", "for reference", "specifically here", "this item this note",
)


class UsageFailure(Exception):
    \"\"\"Raised for usage errors that argparse cannot express cleanly (exit 2).\"\"\"


class ValidationFailure(Exception):
    \"\"\"Raised for path, schema, gate, or audit failures (exit 1).\"\"\"


def _print(message: str = "") -> None:
    \"\"\"Print message to stdout and flush immediately.\"\"\"
    print(message, flush=True)


# --------------------------------------------------------------------------- #
# Path safety — every writable path is derived internally and confined to --work-root.
# --------------------------------------------------------------------------- #
def _resolve(path_text, *, strict: bool = False) -> Path:
    \"\"\"Return path_text resolved to an absolute Path; strict=True requires it to exist.\"\"\"
    return Path(path_text).resolve(strict=strict)


def _is_under(child: Path, parent: Path) -> bool:
    \"\"\"True if child is contained within parent.\"\"\"
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _require_under(child: Path, parent: Path, label: str) -> Path:
    \"\"\"Return child resolved, raising ValidationFailure (named by label) if it escapes parent.\"\"\"
    child_resolved = _resolve(child)
    parent_resolved = _resolve(parent)
    if child_resolved != parent_resolved and not _is_under(child_resolved, parent_resolved):
        raise ValidationFailure(f"{label} resolves outside the work root: {child_resolved}")
    return child_resolved


def _validate_work_root(value) -> Path:
    \"\"\"The single writable sandbox, caller-declared. Must already exist (the orchestrator owns it),
    so a typo can't silently create a sandbox in the wrong place. No equality to any fixed path —
    that is what makes the tool portable to any repo.\"\"\"
    root = _resolve(value)
    if not root.exists():
        raise ValidationFailure(f"--work-root does not exist: {root}")
    if not root.is_dir():
        raise ValidationFailure(f"--work-root is not a directory: {root}")
    return root


def _validate_source_root(value) -> Path:
    \"\"\"Resolve value as the read-only source root, requiring it to exist.\"\"\"
    root = _resolve(value)
    if not root.exists():
        raise ValidationFailure(f"--source-root does not exist: {root}")
    return root


def _validate_skill(value: str) -> str:
    \"\"\"Return value if it is a valid skill slug, else raise ValidationFailure.\"\"\"
    if not SKILL_RE.fullmatch(value):
        raise ValidationFailure(f"invalid --skill: {value!r}")
    return value


def _validate_worker(value: str) -> str:
    \"\"\"Return value if it is a valid worker id with no path traversal, else raise ValidationFailure.\"\"\"
    if not WORKER_RE.fullmatch(value) or ".." in value or "/" in value or "\\\\" in value:
        raise ValidationFailure(f"invalid --worker: {value!r}")
    return value


def _validate_mode(value: str) -> str:
    \"\"\"Return value if it is a recognized mode (extract/full), else raise ValidationFailure.\"\"\"
    if value not in MODE_CHOICES:
        raise ValidationFailure(f"invalid --mode: {value!r}")
    return value


def _validate_tier(value: str) -> str:
    \"\"\"Return value if it is a non-empty tier free of path/control characters, else raise.\"\"\"
    if not value or any(ch in value for ch in "\\\\/\\0\\r\\n"):
        raise ValidationFailure(f"invalid --tier: {value!r}")
    return value


def _validate_rel(value: str, skill: str) -> str:
    \"\"\"Return a normalized POSIX rel path that is relative, traversal-free, and begins with skill/.\"\"\"
    normalized = value.replace("\\\\", "/")
    rel = PurePosixPath(normalized)
    if rel.is_absolute():
        raise ValidationFailure("--rel must be relative")
    if any(part in {"", ".", ".."} for part in rel.parts):
        raise ValidationFailure(f"--rel contains traversal or empty segments: {value!r}")
    if not rel.parts or rel.parts[0] != skill:
        raise ValidationFailure(f"--rel must begin with {skill}/: {value!r}")
    return "/".join(rel.parts)


def _rel_to_path(root: Path, rel: str) -> Path:
    \"\"\"Join a POSIX rel path onto root, segment by segment.\"\"\"
    return root.joinpath(*PurePosixPath(rel).parts)


def _assignment_dir(work_root: Path, skill: str, worker: str) -> Path:
    \"\"\"Return the per-worker assignment directory under work_root, confined to work_root.\"\"\"
    target = work_root / ASSIGNMENT_SUBDIR / skill / worker
    return _require_under(target, work_root, "assignment directory")


def _assignment_paths(adir: Path) -> dict:
    \"\"\"Return the canonical artifact paths (assignment/packet/rewrite/work/result) within adir.\"\"\"
    return {
        "assignment": adir / "assignment.json",
        "packet": adir / "packet.json",
        "rewrite": adir / "rewrite.json",
        "work": adir / "work.md",
        "result": adir / "result.json",
    }


def _safe_mkdir(path: Path, work_root: Path) -> None:
    \"\"\"Create path (and parents), asserting before and after that it stays under work_root.\"\"\"
    _require_under(path, work_root, "directory")
    path.mkdir(parents=True, exist_ok=True)
    real = _resolve(path, strict=True)
    if real != _resolve(work_root) and not _is_under(real, _resolve(work_root)):
        raise ValidationFailure(f"directory resolves outside work root: {real}")


def _atomic_write_bytes(output: Path, data: bytes, work_root: Path) -> None:
    \"\"\"Write atomically and confine the *final* landing spot: create the temp under a
    strict-resolved parent with O_EXCL, then re-assert the resolved output is under work_root
    immediately before os.replace. Any failure unlinks the temp so no orphan .tmp is left.\"\"\"
    out = _require_under(output, work_root, "output path")
    _safe_mkdir(out.parent, work_root)
    tmp = out.with_name(out.name + ".tmp")
    try:
        if tmp.exists():
            tmp.unlink()
        # O_EXCL: never follow/overwrite a pre-existing temp (e.g. a planted symlink)
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:  # fdopen owns fd; closes it on exit even on error
            handle.write(data)
        # re-assert containment at the last moment (defends against a swapped parent)
        final = _resolve(out)
        if final != _resolve(output) or (
            final != _resolve(work_root) and not _is_under(final, _resolve(work_root))
        ):
            raise ValidationFailure(f"output path moved outside work root before write: {final}")
        os.replace(tmp, out)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _atomic_write_json(output: Path, payload: Any, work_root: Path) -> None:
    \"\"\"Serialize payload to sorted, indented JSON and atomically write it under work_root.\"\"\"
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\\n"
    _atomic_write_bytes(output, text.encode("utf-8"), work_root)


def _atomic_write_text(output: Path, text: str, work_root: Path) -> None:
    \"\"\"Atomically write text (ensuring a trailing newline) as UTF-8 under work_root.\"\"\"
    if not text.endswith("\\n"):
        text += "\\n"
    _atomic_write_bytes(output, text.encode("utf-8"), work_root)


def _reject_duplicate_pairs(pairs):
    \"\"\"object_pairs_hook that builds a dict but raises ValidationFailure on any duplicate key.\"\"\"
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValidationFailure(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _load_json_file(path: Path, label: str):
    \"\"\"Load JSON from path (rejecting duplicate keys), raising ValidationFailure named by label.\"\"\"
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_reject_duplicate_pairs)
    except FileNotFoundError as exc:
        raise ValidationFailure(f"missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationFailure(f"malformed {label}: {path}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Packet / rewrite validation (extract mode).
# --------------------------------------------------------------------------- #
def _normalize_packet_items(packet: Any) -> list:
    \"\"\"Validate and normalize a packet's items into a list of {i, cell, text}, rejecting
    malformed types and duplicate (i, cell) keys.\"\"\"
    if not isinstance(packet, dict) or not isinstance(packet.get("items"), list):
        raise ValidationFailure("packet is missing an items list")
    items, seen = [], set()
    for raw in packet["items"]:
        if not isinstance(raw, dict) or "i" not in raw or "cell" not in raw or "text" not in raw:
            raise ValidationFailure("packet item is missing i, cell, or text")
        i, cell, text = raw["i"], raw["cell"], raw["text"]
        if isinstance(i, bool) or not isinstance(i, int):
            raise ValidationFailure(f"packet item has non-integer i: {raw!r}")
        if cell is not None and (isinstance(cell, bool) or not isinstance(cell, int)):
            raise ValidationFailure(f"packet item has malformed cell: {raw!r}")
        if not isinstance(text, str):
            raise ValidationFailure(f"packet item has non-string text: {raw!r}")
        key = (i, cell)
        if key in seen:
            raise ValidationFailure(f"packet has duplicate item key: {key}")
        seen.add(key)
        items.append({"i": i, "cell": cell, "text": text})
    return items


def _check_banned(text: str, where: str) -> None:
    \"\"\"Raise ValidationFailure (naming where) if text contains any banned filler phrase.\"\"\"
    lowered = text.lower()
    for phrase in STYLE_BANNED_PHRASES:
        if phrase.lower() in lowered:
            raise ValidationFailure(f"{where} contains banned filler phrase: {phrase!r}")


def _validate_rewrite_payload(rewrite: Any, packet_items: list) -> list:
    \"\"\"Strict shape/key/order check of an extract-mode submission against the packet. This is the
    schema rail; fidelity is enforced separately by the gates.\"\"\"
    if not isinstance(rewrite, dict) or set(rewrite) != {"items"}:
        raise ValidationFailure('rewrite JSON must be exactly {"items":[...]}')
    raw_items = rewrite["items"]
    if not isinstance(raw_items, list):
        raise ValidationFailure("rewrite items must be a list")
    if len(raw_items) != len(packet_items):
        raise ValidationFailure(
            f"rewrite item count {len(raw_items)} does not match packet count {len(packet_items)}")
    expected = [(it["i"], it["cell"]) for it in packet_items]
    seen, normalized = set(), []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict) or set(raw) != {"i", "cell", "text"}:
            raise ValidationFailure("each rewrite item must contain exactly i, cell, and text")
        i, cell, text = raw["i"], raw["cell"], raw["text"]
        if isinstance(i, bool) or not isinstance(i, int):
            raise ValidationFailure(f"rewrite item has non-integer i at offset {index}")
        if cell is not None and (isinstance(cell, bool) or not isinstance(cell, int)):
            raise ValidationFailure(f"rewrite item has malformed cell at offset {index}")
        if not isinstance(text, str):
            raise ValidationFailure(f"rewrite item has non-string text at offset {index}")
        pair = (i, cell)
        if pair in seen:
            raise ValidationFailure(f"duplicate rewrite item key: {pair}")
        seen.add(pair)
        if pair != expected[index]:
            raise ValidationFailure(
                f"rewrite item key/order mismatch at offset {index}: {pair} != {expected[index]}")
        _check_banned(text, f"rewrite item {pair}")
        normalized.append({"i": i, "cell": cell, "text": text})
    if set(expected) != seen:
        missing = sorted(set(expected) - seen)
        extra = sorted(seen - set(expected))
        raise ValidationFailure(f"rewrite keys do not match packet; missing={missing} extra={extra}")
    return normalized


# --------------------------------------------------------------------------- #
# Assignment load / validate.
# --------------------------------------------------------------------------- #
_ASSIGNMENT_KEYS = {
    "schema_version", "tool", "generated_utc", "skill", "worker", "rel",
    "source", "source_root", "work_root", "mode", "tier", "faction", "paths",
}


def _load_assignment(work_root: Path, skill: str, worker: str):
    \"\"\"Load and fully validate the worker's assignment.json, verifying schema, identity, derived
    paths, and that source matches source_root+rel. Returns (assignment, paths, source, mode).\"\"\"
    skill = _validate_skill(skill)
    worker = _validate_worker(worker)
    adir = _assignment_dir(work_root, skill, worker)
    paths = _assignment_paths(adir)
    assignment = _load_json_file(paths["assignment"], "assignment")
    if not isinstance(assignment, dict) or set(assignment) != _ASSIGNMENT_KEYS:
        raise ValidationFailure("assignment has unexpected schema")
    if assignment["schema_version"] != SCHEMA_VERSION:
        raise ValidationFailure("unsupported assignment schema_version")
    if assignment["tool"] != TOOL_NAME:
        raise ValidationFailure("assignment was not created by this tool")
    if assignment["skill"] != skill or assignment["worker"] != worker:
        raise ValidationFailure("assignment skill/worker does not match request")
    mode = _validate_mode(str(assignment["mode"]))
    _validate_tier(str(assignment["tier"]))
    rel = _validate_rel(str(assignment["rel"]), skill)
    source_root = _validate_source_root(str(assignment["source_root"]))
    source = _resolve(str(assignment["source"]), strict=True)
    _require_under(source, source_root, "assignment source")
    expected_source = _resolve(_rel_to_path(source_root, rel), strict=True)
    if source != expected_source:
        raise ValidationFailure(f"assignment source does not match rel: {source} != {expected_source}")
    # the stored paths must be exactly the canonical derived ones (no caller-chosen output paths)
    canonical = {k: str(v) for k, v in paths.items() if k != "assignment"}
    if assignment["paths"] != canonical:
        raise ValidationFailure("assignment paths do not match the canonical derived paths")
    for label, p in paths.items():
        if label != "assignment":
            _require_under(p, work_root, f"{label} path")
    return assignment, paths, source, mode


# --------------------------------------------------------------------------- #
# Commands.
# --------------------------------------------------------------------------- #
def cmd_prepare(args: argparse.Namespace) -> int:
    \"\"\"Build the assignment (and, in extract mode, the prose packet) for a worker under work_root.\"\"\"
    work_root = _validate_work_root(args.work_root)
    source_root = _validate_source_root(args.source_root)
    skill = _validate_skill(args.skill)
    worker = _validate_worker(args.worker)
    rel = _validate_rel(args.rel, skill)
    mode = _validate_mode(args.mode)
    tier = _validate_tier(args.tier)

    source = _resolve(_require_under(_resolve(args.source), source_root, "source"), strict=True)
    expected_source = _resolve(_rel_to_path(source_root, rel), strict=True)
    if source != expected_source:
        raise ValidationFailure(f"--source must equal --source-root plus --rel: {source} != {expected_source}")

    adir = _assignment_dir(work_root, skill, worker)
    paths = _assignment_paths(adir)
    if paths["assignment"].exists() and not paths["result"].exists() and not args.force:
        raise ValidationFailure(
            f"a live (unsubmitted) assignment already exists for {skill}/{worker}; "
            f"pass --force to overwrite or use a distinct --worker")
    _safe_mkdir(adir, work_root)

    source_text = core.read(source)
    item_count = None
    if mode == "extract":
        packet = core.extract(source_text)
        packet["file"] = str(source)
        items = _normalize_packet_items(packet)
        if not items:
            raise ValidationFailure("extract mode found no prose units; this file is Faction-1 (use full or cleanup)")
        _atomic_write_json(paths["packet"], packet, work_root)
        item_count = len(items)

    assignment = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "skill": skill,
        "worker": worker,
        "rel": rel,
        "source": str(source),
        "source_root": str(source_root),
        "work_root": str(work_root),
        "mode": mode,
        "tier": tier,
        "faction": FACTION,
        "paths": {k: str(v) for k, v in paths.items() if k != "assignment"},
    }
    _atomic_write_json(paths["assignment"], assignment, work_root)
    detail = f"items={item_count}" if mode == "extract" else "whole-file"
    _print(f"PASS prepare skill={skill} worker={worker} mode={mode} {detail} dir={adir}")
    return 0


def _contract_lines(mode: str) -> list:
    \"\"\"Return the rewrite-contract bullet lines shown to the subagent for the given mode.\"\"\"
    common = [
        "- Submit ONLY through `recontext_subagent submit` (stdin); never write artifacts yourself.",
        "- Preserve EXACTLY: identifiers, API/class/method names, namespaced tokens (Foo::Bar),"
        " commands/flags/env vars, file paths, numbers+units, enum values, UI labels, bold setting"
        " names, every fenced code block and inline-code span, and all link targets/URLs.",
        "- Reword narrative prose so no run of ~13+ words matches the source. Do NOT invent facts,"
        " params, or versions; do NOT add an 'Inspired by'/source line.",
        "- submit runs the real cleanup + Gate A (identifiers) + Gate B (13-word residue) +"
        " Gate C (cruft). It writes ONLY on a passing gate, so a PASS is verified, not assumed.",
    ]
    if mode == "extract":
        return [
            '- Return exactly {"items":[{"i":...,"cell":...,"text":"..."}]} with the packet item'
            " order unchanged (same i/cell keys, same count).",
        ] + common
    return [
        "- Return the WHOLE rewritten file as raw text on stdin (not JSON). Reword every prose unit"
        " in place; leave code/signatures/tables structurally intact. If the source flattened code"
        " into prose, wrap it in a fenced block or `inline code` byte-for-byte.",
    ] + common


def cmd_show(args: argparse.Namespace) -> int:
    \"\"\"Print the assignment, rewrite contract, and the work to rewrite (packet or whole source).\"\"\"
    work_root = _validate_work_root(args.work_root)
    assignment, paths, source, mode = _load_assignment(work_root, args.skill, args.worker)
    _print("PASS show")
    _print("ASSIGNMENT")
    _print(json.dumps(assignment, ensure_ascii=False, indent=2, sort_keys=True))
    _print("REWRITE CONTRACT")
    for line in _contract_lines(mode):
        _print(line)
    if mode == "extract":
        packet = _load_json_file(paths["packet"], "packet")
        _print("PACKET")
        _print(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print("SOURCE (rewrite the whole file; return raw text on stdin)")
        _print(core.read(source))
    return 0


def _verdict_fields(verdict: dict) -> dict:
    \"\"\"Flatten a gate verdict into the per-file result fields (status + gate_a/b/c summary).\"\"\"
    gb = verdict["gate_b"]
    return {
        "status": "up-to-standard",
        "gate_a": bool(verdict["gate_a"]["passed"]),
        "gate_b_residue": int(gb.get("runs_remaining", 0)),
        "gate_b_ratio": gb.get("ratio"),
        "gate_c": bool(verdict["gate_c"]["passed"]),
    }


def _gate_or_fail(source_text: str, work_text: str) -> dict:
    \"\"\"Run gates A/B/C and return the verdict, raising ValidationFailure with reasons on any failure.\"\"\"
    verdict = core.run_gates(source_text, work_text, faction=FACTION, min_run=MIN_RUN)
    if not verdict["passed"]:
        reasons = []
        if not verdict["gate_a"]["passed"]:
            reasons.append(f"Gate A lost identifiers: {verdict['gate_a']['hard_fail_categories']} "
                           f"{verdict['gate_a']['lost']}")
        if verdict["gate_b"]["required"] and not verdict["gate_b"]["passed"]:
            reasons.append(f"Gate B residue ({verdict['gate_b']['runs_remaining']} run(s)): "
                           f"{verdict['gate_b']['runs'][:5]}")
        if not verdict["gate_c"]["passed"]:
            reasons.append(f"Gate C cruft ({verdict['gate_c']['count']}): {verdict['gate_c']['cruft_lines'][:5]}")
        raise ValidationFailure("rewrite failed the gates; nothing was written. " + " | ".join(reasons))
    return verdict


def cmd_submit(args: argparse.Namespace) -> int:
    \"\"\"Read the rewrite from stdin, splice/clean it, gate it (A/B/C), and write artifacts only on PASS.\"\"\"
    work_root = _validate_work_root(args.work_root)
    assignment, paths, source, mode = _load_assignment(work_root, args.skill, args.worker)
    source_text = core.read(source)

    raw_stdin = sys.stdin.read()
    if not raw_stdin.strip():
        raise ValidationFailure("submit requires the rewrite on stdin")

    rw_path = None
    if mode == "extract":
        packet_items = _normalize_packet_items(_load_json_file(paths["packet"], "packet"))
        try:
            rewrite = json.loads(raw_stdin, object_pairs_hook=_reject_duplicate_pairs)
        except json.JSONDecodeError as exc:
            raise ValidationFailure(f"rewrite JSON did not parse: {exc}") from exc
        normalized = _validate_rewrite_payload(rewrite, packet_items)
        work_text, _stats = core.splice(source_text, normalized)
        verdict = _gate_or_fail(source_text, work_text)
        _atomic_write_json(paths["rewrite"], {"items": normalized}, work_root)
        rw_path = str(paths["rewrite"])
    else:  # full
        _check_banned(raw_stdin, "submitted file")
        work_text, _actions = core.clean_text(raw_stdin, core.skill_title(assignment["skill"]))
        verdict = _gate_or_fail(source_text, work_text)
        rw_path = str(paths["work"])

    _atomic_write_text(paths["work"], work_text, work_root)

    fields = _verdict_fields(verdict)
    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "skill": assignment["skill"],
        "worker": assignment["worker"],
        "verification": {
            "gates_run": True,
            "faction": FACTION,
            "min_run": MIN_RUN,
            "checks": ["schema", "banned_phrases", "gate_a", "gate_b", "gate_c"],
        },
        "files": [{
            "rel": assignment["rel"],
            "mode": mode,
            "tier": assignment["tier"],
            "rw": rw_path,                 # extract: rewrite.json · full: work.md (the integrator key)
            "work": str(paths["work"]),    # the gated, recontextualized file
            **fields,
            "needs_review": False,
            "notes": "",
        }],
        "errors": [],
    }
    _atomic_write_json(paths["result"], result, work_root)
    _print(f"PASS submit skill={assignment['skill']} worker={assignment['worker']} mode={mode} "
           f"gate_a={fields['gate_a']} gate_b_residue={fields['gate_b_residue']} "
           f"gate_c={fields['gate_c']} result={paths['result']}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    \"\"\"Recursively report misplaced legacy `_pkt_/_rw_/_result_` artifacts (case-insensitive) and
    reparse points anywhere under --root. Read-only: never deletes or moves anything.\"\"\"
    root = _resolve(args.root, strict=True)
    if not root.is_dir():
        raise ValidationFailure(f"--root is not a directory: {root}")
    skip = {p.lower() for p in (args.skip or [])}
    offenders, links = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        # prune skipped subtrees (e.g. .git, node_modules, the legitimate work tree)
        dirnames[:] = [d for d in dirnames if (Path(dirpath) / d).resolve().as_posix().lower() not in skip
                       and d.lower() not in {".git", "node_modules", "__pycache__"}]
        for name in filenames:
            if LEGACY_ARTIFACT_RE.match(name):
                offenders.append(Path(dirpath) / name)
        try:
            for d in dirnames:
                p = Path(dirpath) / d
                if os.path.islink(str(p)) or (
                    hasattr(os.lstat(str(p)), "st_file_attributes")
                    and os.lstat(str(p)).st_file_attributes & 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    links.append(p)
        except OSError:
            pass
    if offenders or links:
        _print(f"FAIL audit found {len(offenders)} misplaced artifact(s), {len(links)} reparse point(s):")
        for p in sorted(offenders):
            _print(f"  artifact: {p}")
        for p in sorted(links):
            _print(f"  reparse:  {p}")
        return 1
    _print(f"PASS audit: no misplaced artifacts under {root}")
    return 0


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    \"\"\"Build the argparse parser for the prepare/show/submit/audit subcommands.\"\"\"
    parser = argparse.ArgumentParser(
        prog="skill_builder.py recontext-subagent",
        description="Locked, gated, portable artifact writer for recontextualization subagents.",
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(sp):
        \"\"\"Add the shared --work-root/--skill/--worker arguments to a subparser.\"\"\"
        sp.add_argument("--work-root", required=True,
                        help="the single writable sandbox (must already exist); all writes are confined here")
        sp.add_argument("--skill", required=True)
        sp.add_argument("--worker", required=True)

    prepare = sub.add_parser("prepare", help="build the assignment + packet")
    add_common(prepare)
    prepare.add_argument("--source", required=True, help="the read-only source file to recontextualize")
    prepare.add_argument("--source-root", required=True, help="the read-only source tree --source lives under")
    prepare.add_argument("--rel", required=True, help="source path relative to --source-root, starting with <skill>/")
    prepare.add_argument("--mode", required=True, choices=list(MODE_CHOICES))
    prepare.add_argument("--tier", required=True)
    prepare.add_argument("--force", action="store_true", help="overwrite an existing unsubmitted assignment")
    prepare.set_defaults(func=cmd_prepare)

    show = sub.add_parser("show", help="display the assignment, contract, and work to rewrite")
    add_common(show)
    show.set_defaults(func=cmd_show)

    submit = sub.add_parser("submit", help="gate the rewrite from stdin and write artifacts on PASS")
    add_common(submit)
    submit.set_defaults(func=cmd_submit)

    audit = sub.add_parser("audit", help="recursively report misplaced legacy artifacts / reparse points")
    audit.add_argument("--root", required=True, help="tree to scan")
    audit.add_argument("--skip", action="append", help="absolute subtree path to skip (repeatable)")
    audit.set_defaults(func=cmd_audit)

    return parser


def cmd_recontext_subagent(argv=None) -> int:
    \"\"\"Run the locked, gated artifact writer: the `recontext-subagent` subcommand of `skill_builder.py`.

    Parses the subagent argument vector (`prepare`/`show`/`submit`/`audit` from `build_parser`) and
    dispatches to the bound handler. Catches the writer's own failure types so a subagent never sees a
    raw traceback it might try to "fix" by hand: returns 2 on usage error, 1 on a validation/gate
    failure (or any unexpected exception), 0 on success. Reads ``sys.argv[1:]`` when ``argv`` is None
    (argparse default).
    \"\"\"
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        return int(args.func(args))
    except UsageFailure as exc:
        _print(f"USAGE {TOOL_NAME}: {exc}")
        return 2
    except ValidationFailure as exc:
        _print(f"FAIL {args.command}: {exc}")
        return 1
    except Exception as exc:  # never surface a raw traceback that a subagent might "fix" by hand
        _print(f"FAIL {args.command}: unexpected {type(exc).__name__}: {exc}")
        return 1


def main(argv=None) -> int:
    \"\"\"Standalone entry for `python -m builder_components.recontext_subagent`; delegates to the cmd.\"\"\"
    return cmd_recontext_subagent(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.validate===
_SRC['builder_components.validate'] = """
#!/usr/bin/env python3
\"\"\"Validate a Codex/Claude skill package using lightweight stdlib checks.

Usage:
  python skill_builder.py validate <skill_dir>
      Validate a single (leaf) skill directory.
  python skill_builder.py validate --package <router_dir>
      Validate a router skill plus every product subskill beneath it, and
      check routing integrity, in one run. A router does not need its own
      references/ corpus; each immediate subdirectory that contains a
      SKILL.md is treated as a product subskill and validated as a leaf.
\"\"\"

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .util.frontmatter import parse_frontmatter


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Only flag genuine authoring placeholders. Documentation legitimately contains
# angle brackets (HTML/XML samples, code placeholders like <YOUR_CLIENT_ID>), so a
# generic <...> rule produces false positives on real reference content.
PLACEHOLDER_RE = re.compile(r"\\b(?:TODO|TBD)\\b")


def read_text(path: Path) -> str:
    \"\"\"Read and return the file at `path` as UTF-8 text.\"\"\"
    return path.read_text(encoding="utf-8")


def fail(errors: list[str], message: str) -> None:
    \"\"\"Append a validation failure `message` to the `errors` accumulator.\"\"\"
    errors.append(message)


def validate_frontmatter(skill_dir: Path, errors: list[str]) -> str:
    \"\"\"Validate SKILL.md frontmatter, required sections, and gotchas; return its raw text.

    Appends any problems to `errors`. Returns "" when SKILL.md is missing.
    \"\"\"
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        fail(errors, "SKILL.md is missing")
        return ""
    text = read_text(skill_md)
    frontmatter = parse_frontmatter(text)
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if not name:
        fail(errors, "SKILL.md frontmatter is missing name")
    if not description:
        fail(errors, "SKILL.md frontmatter is missing description")
    if name and not NAME_RE.fullmatch(name):
        fail(errors, f"skill name is not kebab-case: {name}")
    if name and name != skill_dir.name:
        fail(errors, f"skill name does not match folder name: {name} != {skill_dir.name}")
    trigger_terms = ("use when", "when", "trigger", "fires", "asks", "working with")
    if description and not any(term in description.lower() for term in trigger_terms):
        fail(errors, "description lacks concrete trigger language")
    required_sections = ("workflow", "references", "verification")
    lower_text = text.lower()
    for section in required_sections:
        if section not in lower_text:
            fail(errors, f"SKILL.md is missing {section} guidance")
    # Gotchas may live inline in SKILL.md OR in a sibling GOTCHA.md it references.
    gotcha_path = skill_dir / "GOTCHA.md"
    has_gotcha_file = gotcha_path.is_file()
    if "gotchas" not in lower_text and not has_gotcha_file:
        fail(errors, "SKILL.md is missing gotchas guidance (inline, or a sibling GOTCHA.md)")
    if has_gotcha_file and not read_text(gotcha_path).strip():
        fail(errors, "GOTCHA.md is present but empty")
    if "gotcha.md" in lower_text and not has_gotcha_file:
        fail(errors, "SKILL.md references GOTCHA.md but no sibling GOTCHA.md exists")
    return text


def validate_references(skill_dir: Path, errors: list[str]) -> None:
    \"\"\"Validate the references/ corpus: INDEX.md, topics.json schema, and each topic file.

    Appends any problems to `errors`.
    \"\"\"
    references_dir = skill_dir / "references"
    index_path = references_dir / "INDEX.md"
    topics_path = references_dir / "topics.json"
    if not references_dir.is_dir():
        fail(errors, "references/ directory is missing")
        return
    if not index_path.is_file():
        fail(errors, "references/INDEX.md is missing")
    if not topics_path.is_file():
        fail(errors, "references/topics.json is missing")
        return
    try:
        topics_doc = json.loads(read_text(topics_path))
    except json.JSONDecodeError as exc:
        fail(errors, f"references/topics.json is invalid JSON: {exc}")
        return
    topics = topics_doc.get("topics")
    if not isinstance(topics, list) or not topics:
        fail(errors, "references/topics.json has no topics array")
        return
    index_text = read_text(index_path) if index_path.is_file() else ""
    seen_files: set[str] = set()
    for idx, topic in enumerate(topics, start=1):
        if not isinstance(topic, dict):
            fail(errors, f"topic {idx} is not an object")
            continue
        file_value = topic.get("file")
        topic_name = topic.get("topic")
        summary = topic.get("summary")
        keywords = topic.get("keywords")
        if not topic_name:
            fail(errors, f"topic {idx} is missing topic")
        if not summary:
            fail(errors, f"topic {idx} is missing summary")
        if not isinstance(keywords, list) or not keywords:
            fail(errors, f"topic {idx} is missing keywords")
        if not isinstance(file_value, str) or not file_value.startswith("references/"):
            fail(errors, f"topic {idx} has invalid file value")
            continue
        if file_value in seen_files:
            fail(errors, f"duplicate topic file in topics.json: {file_value}")
        seen_files.add(file_value)
        ref_path = skill_dir / file_value
        if not ref_path.is_file():
            fail(errors, f"topic file does not exist: {file_value}")
            continue
        if file_value.replace("references/", "") not in index_text:
            fail(errors, f"topic file is not listed in references/INDEX.md: {file_value}")


def check_placeholder_text(rel: str, text: str, errors: list[str]) -> None:
    \"\"\"Flag authoring placeholders (TODO/TBD) in `text`, skipping code fences and inline code.

    `rel` is the file label used in failure messages; problems are appended to `errors`.
    \"\"\"
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or "allow-placeholder" in line:
            continue  # code samples legitimately contain TODO/TBD
        # Strip inline-code spans first: a `TODO`/`TBD` referenced in prose (e.g. the
        # instruction "mark it `TODO` — never invent") is legitimate, not an unfilled placeholder.
        if PLACEHOLDER_RE.search(re.sub(r"`[^`]*`", "", line)):
            fail(errors, f"placeholder-like text in {rel}:{line_number}")


def validate_placeholders(skill_dir: Path, errors: list[str]) -> None:
    \"\"\"Run placeholder checks over the authored surface (SKILL.md and references metadata).\"\"\"
    # Placeholder/TODO checks target the AUTHORED surface (SKILL.md and the
    # references index/metadata). Ingested reference content legitimately contains
    # words like "TBD"/"TODO" (e.g. version tables, source headings), so it is exempt.
    for rel in ("SKILL.md", "references/INDEX.md", "references/topics.json"):
        path = skill_dir / rel
        if path.is_file():
            check_placeholder_text(rel, read_text(path), errors)


def validate_leaf(skill_dir: Path) -> list[str]:
    \"\"\"Validate a single leaf skill directory and return the list of error messages (empty = pass).\"\"\"
    errors: list[str] = []
    if not skill_dir.exists():
        return [f"skill directory does not exist: {skill_dir}"]
    if not skill_dir.is_dir():
        return [f"skill path is not a directory: {skill_dir}"]
    validate_frontmatter(skill_dir, errors)
    validate_references(skill_dir, errors)
    validate_placeholders(skill_dir, errors)
    return errors


def discover_subskills(router_dir: Path) -> list[Path]:
    \"\"\"Return the sorted immediate subdirectories of `router_dir` that contain a SKILL.md.\"\"\"
    return sorted(
        d for d in router_dir.iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    )


def validate_router(router_dir: Path) -> tuple[list[str], list[Path]]:
    \"\"\"Validate a router skill. references/ is optional; subskills are required.

    Returns (router_errors, subskill_dirs).
    \"\"\"
    errors: list[str] = []
    if not router_dir.is_dir():
        return [f"router path is not a directory: {router_dir}"], []
    validate_frontmatter(router_dir, errors)
    # A router routes to product subskills and need not ship its own corpus.
    # Validate references/ only if the router chooses to keep one.
    if (router_dir / "references").is_dir():
        validate_references(router_dir, errors)
    skill_md = router_dir / "SKILL.md"
    router_text = read_text(skill_md) if skill_md.is_file() else ""
    if skill_md.is_file():
        check_placeholder_text("SKILL.md", router_text, errors)
    subskills = discover_subskills(router_dir)
    if not subskills:
        fail(errors, "router has no product subskills (no immediate subdir with a SKILL.md)")
    for sub in subskills:
        if sub.name not in router_text:
            fail(errors, f"subskill not referenced in router SKILL.md: {sub.name}")
    return errors, subskills


def validate(skill_dir: Path) -> list[str]:
    \"\"\"Validate a single leaf skill (backward-compatible alias for validate_leaf).\"\"\"
    # Backward-compatible single-leaf entry point.
    return validate_leaf(skill_dir)


def _report(label: str, target: Path, errors: list[str]) -> bool:
    \"\"\"Print a PASS/FAIL line (with any errors) for `target` and return True when there are no errors.\"\"\"
    if errors:
        print(f"FAIL{label}: {target}")
        for error in errors:
            print(f"- {error}")
        return False
    print(f"PASS{label}: {target}")
    return True


def cmd_validate(argv: list[str] | None = None) -> int:
    \"\"\"Validate one skill (leaf) or a whole router package, and report PASS/FAIL.

    This is the `validate` subcommand of `skill_builder.py` (and the `-m builder_components.validate`
    entry point). Argument forms (parsed positionally, no argparse, to keep the contract minimal):

    - ``<skill_directory>`` — validate a single leaf skill; exit 0 on PASS, 1 on any error.
    - ``--package <router_directory>`` — validate a router plus every product subskill beneath it and
      check routing integrity; exit 0 only if the router and all subskills pass.

    Returns the process exit code (0 ok, 1 validation failure, 2 usage error). Reads ``sys.argv[1:]``
    when ``argv`` is None.
    \"\"\"
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 2 and args[0] == "--package":
        router_dir = Path(args[1]).resolve()
        router_errors, subskills = validate_router(router_dir)
        ok = _report(" (router)", router_dir, router_errors)
        for sub in subskills:
            ok = _report("", sub, validate_leaf(sub)) and ok
        print(f"PACKAGE {'PASS' if ok else 'FAIL'}: {router_dir} ({len(subskills)} subskills)")
        return 0 if ok else 1
    if len(args) != 1:
        print("Usage: python skill_builder.py validate [--package] <skill_directory>", file=sys.stderr)
        return 2
    skill_dir = Path(args[0]).resolve()
    errors = validate(skill_dir)
    _report("", skill_dir, errors)
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    \"\"\"Standalone entry point for `python -m builder_components.validate`; delegates to cmd_validate.\"\"\"
    return cmd_validate(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.corpus===
_SRC['builder_components.corpus'] = """
\"\"\"Build corpus model + text cleaning: record loading, sectioning, and HTML/markdown
normalization (was the corpus + cleaning sections of skill_builder.py; merged because they are
mutually dependent).\"\"\"

from __future__ import annotations

import collections
import glob as globmod
import html
import json
import re
from urllib.parse import unquote
from urllib.parse import urljoin
from .ingest import norm


# ==============================================================================
# BUILD — corpus -> reference skill (was build_skill_corpus.py)
# ==============================================================================

# =============================================================================
# CONFIGURATION  --  edit this region for your corpus.
# Paths are passed on the CLI (never hardcoded); the hooks below describe how to
# interpret YOUR records. Sensible, corpus-neutral defaults are provided.
# =============================================================================

#: Soft per-file size target in bytes. Files are packed up to this size at natural
#: boundaries; a single source page/section larger than this is split deterministically.
TARGET_BYTES = 24 * 1024

#: Default scratch/work directory that RELATIVE --records globs resolve against, so you can
#: keep corpora in the repo's working area without typing the prefix every time. This repo's
#: convention is "AI/work"; override per-repo or per-run with --work-dir. No deeper subfolder
#: is assumed — you pick the corpus path (--records) and the output skill path (--out) yourself.
DEFAULT_WORK_DIR = "AI/work"

#: Cleanup toggles. All are safe, deterministic transforms applied to rendered prose.
#: These are the DEFAULT (generic cleanup) values; the `--verbatim` CLI preset flips the first four
#: off, for faithful reproduction of already-clean upstream docs (e.g. HTML/PDF ingested verbatim).
RESOLVE_REFS = True          # rewrite relative links/images against each chunk's source_url
COMPACT_TABLES = True        # strip Markdown table alignment padding; join multi-line cells
BACKTICK_IDENTIFIERS = True  # wrap bare ALL_CAPS_UNDERSCORE tokens in backticks
STRIP_HTML_COMMENTS = True   # drop <!-- ... --> and [//]: # (...) editorial comments
RUN_PRETTIER = True          # run `npx prettier` to normalize whitespace (optional; skipped if absent)

#: Filename / display-title style. Defaults preserve section-prefixed filenames. `--verbatim` sets
#: SECTION_PREFIX=False (filename from the page slug; folder/INDEX give context) and
#: STRIP_ORDER_PREFIX=True (drop a 2+digit ordering prefix from display titles, keep it in filenames).
SECTION_PREFIX = True
STRIP_ORDER_PREFIX = False

#: Maps the JSON keys in YOUR records to the fields the engine expects. Change the
#: right-hand values to match your data; the left-hand keys must stay as written.
FIELD_MAP = {
    "id": "chunk_id",
    "text": "text",
    "source_url": "source_url",
    "tags": "tags",
    "title": "title",
    "symbols": "symbols",  # optional: code identifiers to preserve/verify; safe if absent
}


def _field(rec: dict, key: str):
    \"\"\"Read a normalized field from a raw record using FIELD_MAP (falls back to the key).\"\"\"
    return rec.get(FIELD_MAP.get(key, key), rec.get(key))


def load_records(globs: list[str]) -> list[dict]:
    \"\"\"Load + merge JSONL records from one or more globs into normalized dicts.

    Each output dict has: id, text, source_url, tags (list), title (str), symbols (list).
    Records sharing an id across files are MERGED (first non-empty value per field wins),
    so you can keep prose in one file and metadata in another and pass both globs.

    EDIT THIS only if your corpus isn't JSONL-one-record-per-line; otherwise just point
    --records at your files and set FIELD_MAP above.
    \"\"\"
    merged: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
    for pattern in globs:
        for path in sorted(globmod.glob(pattern)):
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    raw = json.loads(line)
                    rid = str(_field(raw, "id") or "")
                    if not rid:
                        continue
                    cur = merged.setdefault(rid, {"id": rid, "text": "", "source_url": "",
                                                  "tags": [], "title": "", "symbols": [],
                                                  "subskill": "", "section": ""})
                    for k in ("text", "source_url", "title", "subskill", "section"):
                        if not cur[k] and _field(raw, k):
                            cur[k] = _field(raw, k)
                    for k in ("tags", "symbols"):
                        if not cur[k] and _field(raw, k):
                            cur[k] = list(_field(raw, k) or [])
    return [r for r in merged.values() if r["text"]]


def subskill_of(rec: dict) -> str:
    \"\"\"Sub-skill key for ROUTER mode, or "" for a single flat skill.

    Reads the ingester-provided `subskill` field; absent => "" => one flat skill (the common case).
    To key off something else (e.g. a tag), edit this hook:
        tags = rec.get("tags") or []; return str(tags[0]) if tags else "general"
    \"\"\"
    return str(rec.get("subskill") or "")


def section_of(rec: dict) -> str:
    \"\"\"SECTION (category) key used to group reference files within a skill.

    Prefers the ingester-provided `section` field; else the first tag; else "reference".
    Sections become INDEX.md / task-router headings (and the filename prefix when SECTION_PREFIX).
    \"\"\"
    tags = rec.get("tags") or []
    return str(rec.get("section") or (tags[0] if tags else "reference"))


#: Per-sub-skill metadata for ROUTER mode: {subskill_key: {"title","purpose","triggers"}}.
#: Leave empty for a flat skill. `purpose`/`triggers` feed the generated SKILL.md prose.
SUBSKILL_META: dict[str, dict] = {}


def subskill_meta(key: str) -> dict:
    \"\"\"Title/purpose/triggers for a sub-skill, with readable fallbacks if unspecified.\"\"\"
    meta = SUBSKILL_META.get(key, {})
    title = meta.get("title") or key.replace("-", " ").replace("_", " ").strip().title() or "Reference"
    return {
        "title": title,
        "purpose": meta.get("purpose") or f"{title} reference material.",
        "triggers": meta.get("triggers") or f"tasks about {title}",
    }


#: Optional human labels for section keys: {section_key: "Human Label"}.
SECTION_LABELS: dict[str, str] = {}
#: Optional per-(subskill, section) label overrides where the generic name is wrong.
SECTION_LABEL_OVERRIDES: dict[tuple, str] = {}


def section_label(subskill: str, section: str) -> str:
    \"\"\"Human-readable label for a section, used in INDEX/router headings.\"\"\"
    return (SECTION_LABEL_OVERRIDES.get((subskill, section))
            or SECTION_LABELS.get(section)
            or section.replace("-", " ").replace("_", " ").strip().title())


def hierarchical_path(source_url: str, section: str) -> list[str]:
    \"\"\"Turn a chunk's source_url into a list of path segments used to GROUP/pack files.

    The packer walks this hierarchy: pages that share a prefix get grouped into one file
    when small, and big nodes are split deeper. So a good path = the source's own folder
    structure (e.g. category/subcategory/page).

    Default: decode %xx, drop the scheme+host, strip a known doc-root marker if present,
    drop file extensions, and drop a trailing 'index'. Customize the markers/logic for
    your source layout. Returning [] falls back to a single bucket.
    \"\"\"
    rel = unquote(re.sub(r"^[a-z]+://[^/]+/", "", source_url or "", flags=re.IGNORECASE))
    for marker in ("/src/pages/", "/main/", "/master/"):
        i = rel.find(marker)
        if i != -1:
            rel = rel[i + len(marker):]
            break
    segs = []
    for s in rel.split("/"):
        if not s:
            continue
        s = re.sub(r"\\.d\\.ts$", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\\.(md|html?|ts|tsx|jsx|json|rst|txt)$", "", s, flags=re.IGNORECASE)
        segs.append(s)
    while len(segs) > 1 and segs[-1].lower() in ("index", "readme"):
        segs = segs[:-1]
    return segs or ["page"]


def is_cruft(source_url: str) -> bool:
    \"\"\"Return True to EXCLUDE a chunk as non-documentation crawl noise.

    Default excludes nothing. Customize for your corpus, e.g.:
        rel = source_url.lower()
        if "node_modules" in rel:
            return True
        base = re.sub(r"\\\\.[a-z0-9.]+$", "", rel.rsplit("/", 1)[-1])
        return base in {"config", "404", "sidenav"}
    \"\"\"
    return False


#: Sections whose source is a SINGLE huge page listing many "objects" (e.g. an API
#: reference dumped to one page). Listing such a section here makes the engine split it
#: by parsed object name (see object_of) instead of treating it as one page. Usually empty.
OBJECT_DUMP_SECTIONS: set = set()

#: Title fragments that mark a *sub-section of the current object* (not a new object) when
#: splitting an OBJECT_DUMP_SECTIONS page. Tune to your reference's heading vocabulary.
SECTION_WORDS = {
    "properties", "property", "methods", "method", "attributes", "attribute", "example",
    "examples", "parameters", "parameter", "returns", "return", "remarks", "events",
    "event", "constants", "constant", "members", "member", "arguments", "syntax", "objects",
}


def object_of(records: list[dict]) -> list[tuple]:
    \"\"\"Stateful split of a single-page dump into (object_name, record) pairs.

    Walks records in order; a chunk whose cleaned title is a SECTION_WORDS fragment belongs
    to the current object, anything else starts a new object. Only used for sections listed
    in OBJECT_DUMP_SECTIONS. Customize the heuristic if your dump titles differ.
    \"\"\"
    pairs = []
    current = "Overview"
    for r in records:
        title = clean_title(r.get("title") or "")
        norm = re.sub(r"[^a-z0-9]", "", title.lower())
        is_section = norm in SECTION_WORDS or norm.startswith(
            ("example", "method", "propert", "attribute", "parameter", "return", "constant", "event", "syntax"))
        if not is_section and title:
            current = re.sub(r"\\s+object$", "", obj_token(r.get("title") or ""), flags=re.IGNORECASE).strip() or current
        pairs.append((current, r))
    return pairs


# =============================================================================
# ENGINE  --  deterministic; generally no need to edit below this line.
# =============================================================================

# ---- text cleaning -----------------------------------------------------------

_BR = re.compile(r"</?br\\s*/?>", re.IGNORECASE)
_BOLD = re.compile(r"</?(?:b|strong)\\s*>", re.IGNORECASE)
_ITAL = re.compile(r"</?(?:i|em)\\s*>", re.IGNORECASE)
_HTMLTAG = re.compile(
    r"</?(?:div|span|p|u|small|sub|sup|td|tr|th|thead|tbody|tfoot|table|caption|col|colgroup|"
    r"ul|ol|li|dl|dt|dd|a|img|script|style|h[1-6]|pre|code|hr|nav|section|article|header|footer|"
    r"aside|main|figure|figcaption|blockquote|button|svg|path|iframe|noscript|center|font)\\b[^>]*>",
    re.IGNORECASE,
)
_MD_BOLD = re.compile(r"\\*\\*(.+?)\\*\\*")
_TRAILING_NUM = re.compile(r"\\s*\\(\\d+\\)\\s*$")
_SEP_SPLIT = re.compile(r"\\s+[–—−-]\\s+")
_EMPTY_TABLE = re.compile(r"^\\s*\\|[\\s|]*\\|\\s*$")
_NAV = re.compile(r"^\\s*(View more View less|More like this|Was this page helpful\\??|On this page|"
                  r"Table of contents|Back to top|Print this page)\\s*$", re.IGNORECASE)
_MD_COMMENT = re.compile(r"^\\s*\\[//\\]: #")
#: A *clean* code-fence delimiter: 3+ backticks or tildes plus an optional language token and
#: nothing else. Lines like a `~~~~^^^^` Python-traceback caret (literal content inside a fence)
#: must NOT toggle fence state, or every block after them desyncs.
_FENCE = re.compile(r"^(?:`{3,}|~{3,})[\\w+.\\-]*$")


def _is_fence(stripped: str) -> bool:
    \"\"\"True only for a clean opening/closing code-fence delimiter line (see _FENCE).\"\"\"
    return bool(_FENCE.match(stripped))


def _strip_emphasis(t: str) -> str:
    \"\"\"Drop Markdown bold markers and HTML entities from a short string (e.g. a title).\"\"\"
    t = html.unescape(t or "")
    t = _MD_BOLD.sub(r"\\1", t)
    return t.replace("**", "").strip()


def clean_title(title: str) -> str:
    \"\"\"Normalize a chunk title for use as a heading: unescape, drop ' (n)', stray <br>, bold.\"\"\"
    t = html.unescape(title or "").replace("​", "").replace("\\\\<", "<").replace("\\\\>", ">")
    t = re.sub(r"</?br\\s*/?>", "", t, flags=re.IGNORECASE)
    return _strip_emphasis(_TRAILING_NUM.sub("", t))


def obj_token(title: str) -> str:
    \"\"\"Extract the trailing object/topic token from a separator-delimited title.

    'Foo APIs - Bar (2)' -> 'Bar'. Used by object_of and for object-dump file naming.
    \"\"\"
    t = _TRAILING_NUM.sub("", html.unescape(title or ""))
    parts = _SEP_SPLIT.split(t)
    return _strip_emphasis(parts[-1] if parts else t)


def _strip_html_segment(segment: str) -> str:
    \"\"\"Convert/strip HTML in a non-code prose segment, leaving XML/code-like tokens alone.\"\"\"
    segment = segment.replace("\\\\<", "<").replace("\\\\>", ">")
    segment = _BR.sub("\\n", segment)
    segment = _BOLD.sub("**", segment)
    segment = _ITAL.sub("*", segment)
    return _HTMLTAG.sub("", segment)


def _normalize_prose_line(line: str) -> str:
    \"\"\"Apply HTML normalization to the parts of a line that are OUTSIDE inline `code` spans.\"\"\"
    parts = line.split("`")
    for i in range(0, len(parts), 2):
        parts[i] = _strip_html_segment(parts[i])
    return "`".join(parts)


def clean_body(text: str) -> str:
    \"\"\"Decode entities, drop HTML comments, normalize stray HTML to Markdown, and demote
    in-body headings to level >= 3 — all OUTSIDE fenced code blocks (code is left verbatim).\"\"\"
    text = html.unescape(text or "")
    if STRIP_HTML_COMMENTS:
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    out: list[str] = []
    in_fence = False
    for line in text.split("\\n"):
        stripped = line.lstrip()
        if _is_fence(stripped):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if STRIP_HTML_COMMENTS and _MD_COMMENT.match(line):
            continue
        if stripped.startswith("#"):
            i = 0
            while i < len(line) and line[i] == "#":
                i += 1
            if 1 <= i <= 2 and i < len(line) and line[i] == " ":
                line = "###" + line[i:]
        out.append(_normalize_prose_line(line))
    return re.sub(r"\\n{3,}", "\\n\\n", "\\n".join(out)).strip()


def strip_cruft(text: str) -> str:
    \"\"\"Remove empty Markdown table rows, common nav phrases, and `[//]: #` comments (outside fences).\"\"\"
    out = []
    in_fence = False
    for line in text.split("\\n"):
        s = line.lstrip()
        if _is_fence(s):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and (_EMPTY_TABLE.match(line) or _NAV.match(line) or _MD_COMMENT.match(line)):
            continue
        out.append(line)
    return re.sub(r"\\n{3,}", "\\n\\n", "\\n".join(out)).strip()


def body_of(chunk: dict) -> str:
    \"\"\"Full per-chunk prose cleanup: clean_body + strip_cruft.\"\"\"
    return strip_cruft(clean_body(chunk.get("text", "")))


# ---- link / image resolution -------------------------------------------------

_IMG_RE = re.compile(r"!\\[([^\\]]*)\\]\\(\\s*([^)\\s]+)(?:\\s+\\"[^\\"]*\\")?\\s*\\)")
_LINK_RE = re.compile(r"(?<!!)\\[([^\\]]+)\\]\\(\\s*([^)\\s]+)(?:\\s+\\"[^\\"]*\\")?\\s*\\)")


def _humanize(name: str) -> str:
    \"\"\"Turn a file/anchor stem into a short human description ('address-output' -> 'address output').\"\"\"
    stem = re.sub(r"\\.[a-z0-9]+$", "", name, flags=re.IGNORECASE)
    return re.sub(r"[-_%0-9]+", " ", stem).strip() or "image"


def resolve_refs(text: str, source_url: str, linkmap: dict) -> str:
    \"\"\"Resolve relative links/images against the source page's URL (outside code fences).

    Images become a descriptive labeled link to the online source image. Links to a page
    that exists IN the skill are rewritten to the local file; everything else points at the
    resolved online source. Anchors resolve to the source page's section. External links
    are left untouched. Pass a balanced-fence text block (e.g. a whole source page) so
    fence tracking is correct.
    \"\"\"
    def img_repl(m):
        \"\"\"Rewrite one Markdown image: resolve a relative src against source_url, else keep a
        link-free "Figure: <desc>" placeholder so no broken local path survives.\"\"\"
        alt, src = m.group(1).strip(), m.group(2).strip()
        desc = alt or _humanize(unquote(src.split("/")[-1]))
        if src.startswith(("http://", "https://")):
            return f"[Figure: {desc}]({src})"
        if source_url and "<" not in src and ">" not in src and " " not in src:
            return f"[Figure: {desc}]({urljoin(source_url, src)})"
        return f"Figure: {desc}"  # unresolvable/placeholder src -> description only, no broken link

    def link_repl(m):
        \"\"\"Rewrite one Markdown link: leave external/mailto links, resolve anchors and relative
        targets against source_url, and drop to plain label text when nothing can be resolved.\"\"\"
        label, target = m.group(1), m.group(2).strip()
        if target.startswith(("http://", "https://", "mailto:")):
            return m.group(0)
        if target.startswith("#"):
            return f"[{label}]({source_url}{target})" if source_url else label
        if not source_url:
            return label
        base, frag = (target.split("#", 1) + [""])[:2]
        abs_url = urljoin(source_url, base)
        if abs_url in linkmap:
            return f"[{label}]({linkmap[abs_url]})"  # local in-skill file (anchor dropped)
        return f"[{label}]({abs_url}{('#' + frag) if frag else ''})"  # online source

    out = []
    in_fence = False
    for line in text.split("\\n"):
        s = line.lstrip()
        if _is_fence(s):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        line = _IMG_RE.sub(img_repl, line)   # images first (they are !-prefixed links)
        line = _LINK_RE.sub(link_repl, line)
        out.append(line)
    return "\\n".join(out)


# ---- table compaction & identifier backticking -------------------------------

_PIPE = re.compile(r"(?<!\\\\)\\|")
_SEP = re.compile(r"^\\s*\\|?[\\s:|-]*-{1,}[\\s:|-]*\\|?\\s*$")
_IDENT = re.compile(r"(\\*\\*)?((?:[A-Z][A-Z0-9]*)(?:\\\\?_[A-Z0-9]+)+)(\\*\\*)?")


def _cells(rowtext: str) -> list[str]:
    \"\"\"Split a Markdown table row on unescaped pipes, dropping empty leading/trailing cells.\"\"\"
    parts = _PIPE.split(rowtext)
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [c.strip() for c in parts]


def compact_tables(text: str) -> str:
    \"\"\"Re-emit Markdown tables with single-space padding; join multi-line cells inline.

    Reclaims column-alignment padding and repairs tables whose cells span multiple source
    lines (which break GFM parsing). Code fences are left untouched.
    \"\"\"
    lines = text.split("\\n")
    out: list[str] = []
    i, n = 0, len(lines)
    in_fence = False
    while i < n:
        line = lines[i]
        st = line.lstrip()
        if _is_fence(st):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if (not in_fence) and len(_PIPE.findall(line)) >= 2 and i + 1 < n and _SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            header = _cells(line)
            ncols = len(header)
            out.append("| " + " | ".join(header) + " |")
            out.append("| " + " | ".join(["---"] * ncols) + " |")
            i += 2
            while i < n and lines[i].strip() != "" and len(_PIPE.findall(lines[i])) > 0:
                buf = lines[i]
                i += 1
                guard = 0
                while len(_PIPE.findall(buf)) < ncols + 1 and i < n and guard < 300:
                    nxt = lines[i].strip()
                    i += 1
                    guard += 1
                    if nxt:
                        buf += " " + nxt
                cells = _cells(buf)
                if len(cells) < ncols:
                    cells += [""] * (ncols - len(cells))
                elif len(cells) > ncols:
                    cells = cells[:ncols - 1] + [" ".join(cells[ncols - 1:])]
                out.append("| " + " | ".join(cells) + " |")
            continue
        out.append(line)
        i += 1
    return "\\n".join(out)


def backtick_identifiers(text: str) -> str:
    \"\"\"Wrap bare ALL_CAPS_UNDERSCORE identifiers in backticks and unescape their underscores
    (e.g. **FOO\\\\_BAR** -> `FOO_BAR`), outside code fences and inline code spans.\"\"\"
    out: list[str] = []
    in_fence = False
    for line in text.split("\\n"):
        st = line.lstrip()
        if _is_fence(st):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        parts = line.split("`")
        for k in range(0, len(parts), 2):
            parts[k] = _IDENT.sub(lambda m: "`" + m.group(2).replace("\\\\_", "_") + "`", parts[k])
        out.append("`".join(parts))
    return "\\n".join(out)


# ---- leaves, packing, naming -------------------------------------------------
"""

# ===MODULE builder_components.policy_cmd===
_SRC['builder_components.policy_cmd'] = """
\"\"\"Manage skill *invocation policy* across Claude Code and (read-only) Codex.

Every installed skill costs idle context: at session start each platform injects
each skill's name + description into the model's listing before any invocation.
This tool lets you keep rarely-used skills installed and explicitly invocable while
hiding them from the model's automatic listing -- WITHOUT modifying the clean source
skill repos.

Actions (default is read-only):
  audit     Inventory skills in the selected scope(s)/platform(s); show current
            policy + an estimated idle-listing footprint; write a report. No writes.
  plan      Generate a user-editable decision manifest (JSON) pre-filled with
            recommendations. Recommendations are NEVER auto-approved.
  preview   Show the exact change `apply` would make from a manifest. No writes.
  apply     Apply ONLY approved decisions (Claude skillOverrides). Backup + atomic
            write + rollback record. An empty/zero-approval selection makes NO changes.
  restore   Revert a previous apply using its rollback record.

Platform support:
  Claude    Fully managed. Writes `skillOverrides` into a Claude settings file
            (default: <project>/.claude/settings.local.json -- what the /skills menu
            writes). States: on / name-only / user-invocable-only / off. Reverting a
            skill to default removes its key (absent => on).
  Codex     AUDIT-ONLY. Codex has no central per-skill *policy* override (config.toml
            `[[skills.config]]` is enable/disable-by-path only), and explicit-only
            local skills are currently unreliable to invoke (open bug
            https://github.com/openai/codex/issues/23454). This tool therefore reports
            Codex skills and never writes Codex config or agents/openai.yaml.

Stdlib only. Mirrors conventions of the sibling scripts (PASS/FAIL stdout, exit
0 ok / 1 failure / 2 usage; AI/work/ scratch; YYYY-MM-DD HH:mm:ss stamps).
\"\"\"

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .util.repo_paths import _find_repo_root
from .policy_engine import (
    ABSENT,
    TOOL_VERSION,
    _claude_version_note,
    _ensure_work_gitignore,
    _footprint_summary,
    _read_text,
    _stamp,
    _stamp_file,
    _work_dir,
    apply_changes_to_settings,
    approved_decisions,
    atomic_write_json,
    backup_file,
    build_manifest,
    compute_changes,
    discover_claude,
    discover_codex,
    get_overrides,
    load_manifest,
    load_settings,
    resolve_settings_path,
    write_audit_report,
)


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #
def _context(args):
    \"\"\"Resolve common run context from `args`: (repo_root, project_dir, home, work_dir, settings_path).\"\"\"
    cwd = Path.cwd()
    repo_root = _find_repo_root(cwd)
    project_dir = repo_root
    home = Path(os.path.expanduser("~"))
    work_dir = _work_dir(repo_root)
    settings_path = resolve_settings_path(args.scope, project_dir, home, args.settings)
    return repo_root, project_dir, home, work_dir, settings_path


def cmd_audit(args) -> int:
    \"\"\"Run the read-only `audit` action: inventory skills, write a report, print the footprint.\"\"\"
    repo_root, project_dir, home, work_dir, settings_path = _context(args)
    _ensure_work_gitignore(work_dir)
    settings = load_settings(settings_path)
    overrides = get_overrides(settings)
    include_store = None
    if args.include_store is not None:
        include_store = args.include_store or str(repo_root / "skills")
    skills = []
    if args.platform in ("claude", "both"):
        skills += discover_claude(project_dir, args.skills_root, overrides, include_store)
    if args.platform in ("codex", "both"):
        skills += discover_codex(project_dir, home)
    md_path, json_path = write_audit_report(work_dir, skills, args.platform, settings_path)
    fp = _footprint_summary(skills)
    if args.json:
        print(json.dumps({"footprint": fp, "skills": skills}, indent=2))
    else:
        print(f"audit: {len(skills)} skills | settings: {settings_path}")
        if args.platform in ("claude", "both"):
            print(f"  {_claude_version_note()}")
        print(f"  surfaced idle listing ~{fp['total_est_tokens']} tokens across {fp['surfaced_count']} skills")
        for s in sorted(skills, key=lambda x: (x["platform"], x["name"])):
            tag = "" if s["platform"] == "claude" else " [audit-only]"
            print(f"  - {s['platform']}/{s['scope']:<13} {s['name']:<22} cur={s['current_policy']:<28} "
                  f"~{s['est_tokens']}t rec={s['recommended_policy'] if s['platform']=='claude' else '-'}{tag}")
        print(f"  report: {md_path}")
        print(f"  report: {json_path}")
    print("PASS audit (read-only)")
    return 0


def cmd_plan(args) -> int:
    \"\"\"Run the `plan` action: write a user-editable, unapproved decision manifest for Claude skills.\"\"\"
    repo_root, project_dir, home, work_dir, settings_path = _context(args)
    _ensure_work_gitignore(work_dir)
    settings = load_settings(settings_path)
    overrides = get_overrides(settings)
    include_store = None
    if args.include_store is not None:
        include_store = args.include_store or str(repo_root / "skills")
    skills = discover_claude(project_dir, args.skills_root, overrides, include_store)
    manifest = build_manifest(skills, "claude", args.scope, settings_path)
    manifest_path = Path(args.manifest) if args.manifest else work_dir / f"decisions-{args.scope}.json"
    if manifest_path.exists() and not args.force:
        print(f"FAIL plan: manifest already exists: {manifest_path} (use --force to overwrite)", file=sys.stderr)
        return 1
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\\n", encoding="utf-8", newline="\\n")
    print(f"plan: wrote {len(manifest['skills'])} Claude skills to {manifest_path}")
    print("  Edit it: set selected_policy + approved:true for the skills you choose, then `preview` / `apply`.")
    print("  Recommendations are NOT decisions; nothing is applied until you approve.")
    print("PASS plan")
    return 0


def _diff_for(args, require_changes_for_apply):
    \"\"\"Load the manifest and compute the effective changes shared by preview/apply.

    Returns (manifest_path, target, settings, current, decisions, changes, work_dir).
    \"\"\"
    repo_root, project_dir, home, work_dir, settings_path = _context(args)
    manifest_path = Path(args.manifest) if args.manifest else work_dir / f"decisions-{args.scope}.json"
    manifest = load_manifest(manifest_path)
    # The manifest records the settings file it was planned against; honor an explicit override.
    target = Path(args.settings) if args.settings else Path(manifest.get("scope", {}).get("settings_path", settings_path))
    settings = load_settings(target)
    current = get_overrides(settings)
    decisions = approved_decisions(manifest)
    changes = compute_changes(current, decisions)
    return manifest_path, target, settings, current, decisions, changes, work_dir


def _print_changes(changes) -> None:
    \"\"\"Print each change as 'op name before -> after' (ABSENT rendered as 'default(on)').\"\"\"
    if not changes:
        print("  (no effective changes)")
        return
    for ch in changes:
        before = "default(on)" if ch["before"] == ABSENT else ch["before"]
        after = "default(on)" if ch["after"] == ABSENT else ch["after"]
        print(f"  {ch['op']:<7} {ch['name']:<24} {before}  ->  {after}")


def cmd_preview(args) -> int:
    \"\"\"Run the read-only `preview` action: show the exact changes `apply` would make.\"\"\"
    manifest_path, target, settings, current, decisions, changes, work_dir = _diff_for(args, False)
    print(f"preview: manifest {manifest_path}")
    print(f"  target settings: {target}")
    print(f"  approved decisions: {len(decisions)}")
    _print_changes(changes)
    print("PASS preview (no writes)")
    return 0


def cmd_apply(args) -> int:
    \"\"\"Run the `apply` action: back up, atomically write approved Claude skillOverrides, and record rollback.

    Honors --dry-run (no writes), the user-scope C-drive guard, and interactive/--yes confirmation.
    \"\"\"
    manifest_path, target, settings, current, decisions, changes, work_dir = _diff_for(args, True)
    if args.dry_run:
        print(f"apply --dry-run: target {target}")
        _print_changes(changes)
        print("PASS apply --dry-run (no writes)")
        return 0
    if not decisions:
        print("apply: no approved decisions in manifest -> no changes.")
        print("PASS apply (nothing to do)")
        return 0
    if not changes:
        print("apply: approved decisions already match current settings -> no changes (idempotent).")
        print("PASS apply (nothing to do)")
        return 0
    # C-drive guard for user scope.
    if args.scope == "user" and not args.yes:
        print(f"FAIL apply: --scope user targets {target} (C: drive). Re-run with --yes to confirm.", file=sys.stderr)
        return 1
    print(f"apply: {len(changes)} change(s) to {target}")
    _print_changes(changes)
    if not args.yes and sys.stdin.isatty():
        resp = input("Proceed? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("apply: aborted by user -> no changes.")
            return 0
    elif not args.yes and not sys.stdin.isatty():
        print("FAIL apply: non-interactive run requires --yes to confirm.", file=sys.stderr)
        return 1
    backup = backup_file(target, work_dir)
    new_settings = apply_changes_to_settings(settings, changes)
    atomic_write_json(target, new_settings)
    record = {
        "stamp": _stamp(),
        "tool": TOOL_VERSION,
        "settings_path": str(target),
        "backup_path": backup,
        "manifest_path": str(manifest_path),
        "changes": changes,
    }
    rec_path = work_dir / f"rollback-{_stamp_file()}.json"
    rec_path.write_text(json.dumps(record, indent=2) + "\\n", encoding="utf-8", newline="\\n")
    print(f"  backup:   {backup or '(none; file did not exist)'}")
    print(f"  rollback: {rec_path}")
    print("  NOTE: start a new Claude Code session for the change to take effect; verify via /skills and /context.")
    print("PASS apply")
    return 0


def cmd_restore(args) -> int:
    \"\"\"Run the `restore` action: revert exactly the keys a prior apply changed, using its rollback record.

    Uses the newest rollback record when --record is omitted; honors --dry-run.
    \"\"\"
    repo_root, project_dir, home, work_dir, settings_path = _context(args)
    if args.record:
        rec_path = Path(args.record)
    else:
        records = sorted(work_dir.glob("rollback-*.json"))
        if not records:
            print(f"FAIL restore: no rollback records found in {work_dir}", file=sys.stderr)
            return 1
        rec_path = records[-1]
    record = json.loads(_read_text(rec_path))
    target = Path(record["settings_path"])
    settings = load_settings(target)
    # Surgically revert exactly the keys this apply changed.
    revert = [{"name": ch["name"], "before": ch["after"], "after": ch["before"], "op": "restore"}
              for ch in record["changes"]]
    if args.dry_run:
        print(f"restore --dry-run from {rec_path} -> {target}")
        _print_changes(revert)
        print("PASS restore --dry-run (no writes)")
        return 0
    backup = backup_file(target, work_dir)
    new_settings = apply_changes_to_settings(settings, revert)
    atomic_write_json(target, new_settings)
    print(f"restore: reverted {len(revert)} key(s) in {target} (from {rec_path})")
    print(f"  pre-restore backup: {backup or '(none)'}")
    print("PASS restore")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    \"\"\"Build the argparse parser with shared options and the audit/plan/preview/apply/restore subcommands.\"\"\"
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--platform", choices=("claude", "codex", "both"), default="both")
    parent.add_argument("--scope", choices=("local", "project", "user"), default="local")
    parent.add_argument("--settings", default=None, help="explicit settings file (overrides --scope)")
    parent.add_argument("--skills-root", action="append", default=[], help="extra skill root(s); repeatable")
    parent.add_argument("--include-store", nargs="?", const="", default=None,
                        help="also enumerate store skills not yet surfaced (default: <repo>/skills)")
    parent.add_argument("--manifest", default=None, help="decision manifest path")
    parent.add_argument("--json", action="store_true", help="machine-readable stdout")

    ap = argparse.ArgumentParser(prog="skill_builder.py policy", description="Manage skill invocation policy (Claude apply; Codex audit-only).")
    sub = ap.add_subparsers(dest="action")

    sub.add_parser("audit", parents=[parent], help="read-only inventory + current policy + footprint")

    p_plan = sub.add_parser("plan", parents=[parent], help="generate a decision manifest (unapproved)")
    p_plan.add_argument("--force", action="store_true", help="overwrite an existing manifest")

    sub.add_parser("preview", parents=[parent], help="show the exact change apply would make")

    p_apply = sub.add_parser("apply", parents=[parent], help="apply approved Claude decisions")
    p_apply.add_argument("--yes", action="store_true", help="non-interactive confirm")
    p_apply.add_argument("--dry-run", action="store_true", help="preview semantics; no writes")

    p_restore = sub.add_parser("restore", parents=[parent], help="roll back a previous apply")
    p_restore.add_argument("--record", default=None, help="rollback record (default: newest)")
    p_restore.add_argument("--dry-run", action="store_true", help="show revert; no writes")
    return ap


_DISPATCH = {
    "audit": cmd_audit,
    "plan": cmd_plan,
    "preview": cmd_preview,
    "apply": cmd_apply,
    "restore": cmd_restore,
}


def cmd_policy(argv=None) -> int:
    \"\"\"Run the skill-invocation-policy manager: the `policy` subcommand of `skill_builder.py`.

    Parses the policy argument vector (the `audit`/`plan`/`preview`/`apply`/`restore` subparsers from
    `build_parser`) and dispatches to the matching `cmd_*` handler. `audit` (read-only) is the default
    when no recognized subcommand is given, so a bare `policy` invocation is always safe. Returns the
    process exit code (0 ok, 1 on a handled RuntimeError, 2 on usage error). Reads ``sys.argv[1:]`` when
    ``argv`` is None.
    \"\"\"
    ap = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    # Default action is `audit` (read-only). If the first token is not a known
    # subcommand and not a top-level help flag, treat the run as `audit ...`.
    if not raw or (raw[0] not in _DISPATCH and raw[0] not in ("-h", "--help")):
        raw = ["audit"] + raw
    args = ap.parse_args(raw)
    action = args.action or "audit"
    if action not in _DISPATCH:
        ap.print_help()
        return 2
    try:
        return _DISPATCH[action](args)
    except RuntimeError as exc:
        print(f"FAIL {action}: {exc}", file=sys.stderr)
        return 1


def main(argv=None) -> int:
    \"\"\"Standalone entry point for `python -m builder_components.policy_cmd`; delegates to cmd_policy.\"\"\"
    return cmd_policy(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.packing===
_SRC['builder_components.packing'] = """
\"\"\"Pack/split reference content into right-sized files (was the packing section of skill_builder.py).\"\"\"

from __future__ import annotations

import collections
import re
from .corpus import OBJECT_DUMP_SECTIONS, SECTION_PREFIX, STRIP_ORDER_PREFIX, TARGET_BYTES, _is_fence, clean_title, hierarchical_path, object_of


def slug(s: str) -> str:
    \"\"\"Filesystem-safe kebab slug.\"\"\"
    s = re.sub(r"\\.(md|html?)$", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return re.sub(r"-{2,}", "-", s) or "page"


def _titlecase(seg: str) -> str:
    \"\"\"Turn a slug segment into a Title Case display string (dashes/underscores -> spaces).\"\"\"
    return seg.replace("-", " ").replace("_", " ").strip().title()


def build_leaves(records: list[dict], section: str) -> list[dict]:
    \"\"\"A LEAF is an atomic unit never split across files: one source page, or — for an
    OBJECT_DUMP_SECTIONS section — one parsed object. Returns leaf dicts with path/title/chunks/bytes.\"\"\"
    leaves: list[dict] = []
    if section in OBJECT_DUMP_SECTIONS:
        groups: "collections.OrderedDict[str, list]" = collections.OrderedDict()
        for obj, r in object_of(records):
            groups.setdefault(obj, []).append(r)
        for obj, chunks in groups.items():
            leaves.append({"path": [slug(obj)], "title": obj, "chunks": chunks,
                           "bytes": sum(len(c["text"].encode("utf-8")) for c in chunks)})
        return leaves
    by_page: "collections.OrderedDict[str, list]" = collections.OrderedDict()
    for r in records:
        by_page.setdefault(r.get("source_url") or r["id"], []).append(r)
    for url, chunks in by_page.items():
        title = clean_title(chunks[0].get("title") or "") or (hierarchical_path(url, section)[-1])
        leaves.append({"path": hierarchical_path(url, section), "title": title, "chunks": chunks,
                       "bytes": sum(len(c["text"].encode("utf-8")) for c in chunks)})
    return leaves


def pack(leaves: list[dict], depth: int) -> list[list[dict]]:
    \"\"\"Size-balanced partition: group leaves sharing a path prefix into <=TARGET_BYTES files,
    descending the hierarchy where a node is too big, merging small siblings together.\"\"\"
    total = sum(l["bytes"] for l in leaves)
    if total <= TARGET_BYTES or len(leaves) == 1:
        return [leaves]
    buckets: "collections.OrderedDict[str, list]" = collections.OrderedDict()
    for l in leaves:
        key = l["path"][depth] if len(l["path"]) > depth else ""
        buckets.setdefault(key, []).append(l)
    if len(buckets) == 1:
        maxlen = max(len(l["path"]) for l in leaves)
        return pack(leaves, depth + 1) if depth + 1 < maxlen else [leaves]
    files: list[list[dict]] = []
    cur: list[dict] = []
    cur_bytes = 0
    for grp in buckets.values():
        gb = sum(l["bytes"] for l in grp)
        if gb > TARGET_BYTES:
            if cur:
                files.append(cur); cur = []; cur_bytes = 0
            files.extend(pack(grp, depth + 1))
        else:
            if cur and cur_bytes + gb > TARGET_BYTES:
                files.append(cur); cur = []; cur_bytes = 0
            cur.extend(grp); cur_bytes += gb
    if cur:
        files.append(cur)
    return files


def common_prefix(leaves: list[dict]) -> list[str]:
    \"\"\"Longest shared leading path among a file's leaves (used for naming/titles).\"\"\"
    paths = [l["path"] for l in leaves]
    pref = []
    for i in range(min(len(p) for p in paths)):
        seg = paths[0][i]
        if all(p[i] == seg for p in paths):
            pref.append(seg)
        else:
            break
    return pref


def split_text_by_headings(text: str) -> list[str]:
    \"\"\"Split one oversized chunk's body into <=TARGET_BYTES pieces at heading or blank-line
    boundaries, never inside a fenced code block.\"\"\"
    blocks: list[list[str]] = []
    cur: list[str] = []
    fence = False
    for line in text.split("\\n"):
        s = line.lstrip()
        if _is_fence(s):
            fence = not fence
            cur.append(line)
            continue
        if not fence and (line.startswith("## ") or line.startswith("### ")) and cur:
            blocks.append(cur)
            cur = [line]
        elif not fence and line.strip() == "":
            cur.append(line)
            blocks.append(cur)
            cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append(cur)
    pieces, buf, bb = [], [], 0
    for block in blocks:
        bt = "\\n".join(block)
        bs = len(bt.encode("utf-8"))
        if buf and bb + bs > TARGET_BYTES:
            pieces.append("\\n".join(buf)); buf = []; bb = 0
        buf.append(bt); bb += bs
    if buf:
        pieces.append("\\n".join(buf))
    return pieces


def split_oversize(leaf: dict) -> list[list[dict]]:
    \"\"\"Split one oversized page/object leaf into consecutive <=TARGET_BYTES chunk-runs;
    a single chunk that alone exceeds the target is exploded at its heading boundaries.\"\"\"
    expanded: list[dict] = []
    for c in leaf["chunks"]:
        if len(c["text"].encode("utf-8")) > TARGET_BYTES:
            for piece in split_text_by_headings(c["text"]):
                expanded.append({**c, "text": piece})
        else:
            expanded.append(c)
    runs, cur, cb = [], [], 0
    for c in expanded:
        cs = len(c["text"].encode("utf-8"))
        if cur and cb + cs > TARGET_BYTES:
            runs.append(cur); cur = []; cb = 0
        cur.append(c); cb += cs
    if cur:
        runs.append(cur)
    return runs


def title_for(section: str, leaves: list[dict], used: set) -> tuple[str, str]:
    \"\"\"Pick a unique kebab filename (prefixed by the section) and a human display title
    derived from the distinguishing subtopics this file covers.\"\"\"
    pref = common_prefix(leaves)
    base = pref[-1] if pref else (leaves[0]["title"] or "page")
    code = slug(section)
    s = slug(base)
    if SECTION_PREFIX:
        stem = s if (s == code or s.startswith(code + "-")) else f"{code}-{s}"
    else:
        stem = s  # verbatim: no section prefix (the folder/INDEX give context)
    name = stem
    n = 2
    while name in used:
        name = f"{stem}-{n}"; n += 1
    used.add(name)
    depth = len(pref)
    nexts: list[str] = []
    for leaf in leaves:
        if len(leaf["path"]) > depth and leaf["path"][depth] not in nexts:
            nexts.append(leaf["path"][depth])
    # STRIP_ORDER_PREFIX (verbatim): drop a 2+digit ordering prefix from the DISPLAY title
    # (e.g. "06-the-cut-page" -> "The Cut Page"); the prefix stays in the filename. 1-digit kept.
    def _disp(seg: str) -> str:
        \"\"\"Title-case a path segment, dropping a 2+digit order prefix when STRIP_ORDER_PREFIX.\"\"\"
        return _titlecase(re.sub(r"^\\d{2,}-", "", seg) if STRIP_ORDER_PREFIX else seg)
    if nexts:
        disp = ", ".join(_disp(x) for x in nexts[:4]) + (" ..." if len(nexts) > 4 else "")
    else:
        disp = _disp(base)
    return name + ".md", disp


def disambiguate_titles(plans: list[dict]) -> None:
    \"\"\"Prefix the first genuinely-differing path segment (or the section) to any H1 title
    that collides within a skill, so every file's title is distinct.\"\"\"
    by_title: "collections.defaultdict[str, list]" = collections.defaultdict(list)
    for p in plans:
        by_title[p["title"]].append(p)
    for grp in by_title.values():
        if len(grp) < 2:
            continue
        paths = {id(p): common_prefix(p["leaves"]) for p in grp}
        for p in grp:
            path = paths[id(p)]
            others = [q for q in grp if q is not p]
            disting = next((seg for i, seg in enumerate(path)
                            if any(i >= len(paths[id(q)]) or paths[id(q)][i] != seg for q in others)), None)
            if not disting and any(q["section"] != p["section"] for q in others):
                disting = p["section"]
            if disting:
                p["title"] = f"{_titlecase(disting)} — {p['title']}"
"""

# ===MODULE builder_components.build===
_SRC['builder_components.build'] = """
\"\"\"Build a reference skill package from a corpus (was the build orchestration section of skill_builder.py).\"\"\"

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from builder_components.util.text_io import write_text
from builder_components.util.repo_paths import _project_ai_dir
from .corpus import BACKTICK_IDENTIFIERS, COMPACT_TABLES, RESOLVE_REFS, RUN_PRETTIER, TARGET_BYTES, _IMG_RE, _LINK_RE, _is_fence, backtick_identifiers, body_of, clean_title, compact_tables, is_cruft, load_records, resolve_refs, section_label, section_of, subskill_meta, subskill_of
from .ingest import run
from .packing import _titlecase, build_leaves, disambiguate_titles, pack, slug, split_oversize, title_for


# ---- rendering ---------------------------------------------------------------

def render_file(skill_title: str, file_leaves: list[dict], title: str, linkmap: dict) -> str:
    \"\"\"Render one reference file: H1 + attribution + (Overview for multi-topic files) + per-leaf
    sections. Link/image resolution runs per-leaf (a whole page) so fences stay balanced.\"\"\"
    lines = [f"# {title}", "", f"> {skill_title} reference. Original prose; identifiers preserved verbatim.", ""]
    single = len(file_leaves) == 1
    if not single:
        covers = list(dict.fromkeys(l["title"] for l in file_leaves if l["title"]))[:18]
        lines += ["## Overview", "", "Covers: " + "; ".join(covers) + ".", ""]
    level = "##" if single else "###"
    for leaf in file_leaves:
        src = next((c.get("source_url", "") for c in leaf["chunks"] if c.get("source_url")), "")
        block: list[str] = []
        if not single and leaf["title"]:
            block += [f"## {leaf['title']}", ""]
        last = None
        for chunk in leaf["chunks"]:
            ct = clean_title(chunk.get("title") or "")
            if ct and leaf["title"] and ct != leaf["title"]:
                ct = re.sub(r"^" + re.escape(leaf["title"]) + r"\\s*[—–:-]\\s*", "", ct) or ct
            if ct and ct != leaf["title"] and ct != last:
                block += [f"{level} {ct}", ""]
                last = ct
            b = body_of(chunk)
            if b:
                block += [b, ""]
        text = "\\n".join(block)
        lines.append(resolve_refs(text, src, linkmap) if RESOLVE_REFS else text)
    text = "\\n".join(lines)
    if COMPACT_TABLES:
        text = compact_tables(text)
    if BACKTICK_IDENTIFIERS:
        text = backtick_identifiers(text)
    return re.sub(r"\\n{3,}", "\\n\\n", text).strip() + "\\n"




def write_index(refs: Path, subskill: str, skill_title: str, fm: list) -> None:
    \"\"\"Write references/INDEX.md: a per-section table of every file with a one-line summary.\"\"\"
    lines = [f"# {skill_title} References — Index", "",
             "Each file is one focused, original-prose reference (identifiers preserved verbatim). "
             "Open only what the SKILL.md router points to.", ""]
    for sec in sorted({f[0] for f in fm}):
        lines += [f"## {section_label(subskill, sec)}", "", "| File | Covers |", "| --- | --- |"]
        for s, fname, disp, _, _ in fm:
            if s == sec:
                lines.append(f"| [{fname}]({fname}) | {disp} |")
        lines.append("")
    write_text(refs / "INDEX.md", "\\n".join(lines).rstrip() + "\\n")


def write_topics(refs: Path, subskill: str, fm: list) -> None:
    \"\"\"Write references/topics.json (machine-readable topic -> file + keywords).\"\"\"
    topics = [{"topic": disp, "file": f"references/{fname}",
               "summary": f"{section_label(subskill, s)}: {disp}.",
               "keywords": [slug(disp), s]} for (s, fname, disp, _, _) in fm]
    write_text(refs / "topics.json", json.dumps({"schema_version": 1, "topics": topics}, ensure_ascii=False, indent=2) + "\\n")


def write_leaf_skill(skill_dir: Path, name: str, title: str, purpose: str, triggers: str, subskill: str, fm: list) -> None:
    \"\"\"Write a (sub)skill SKILL.md: frontmatter + workflow + a section-grouped task router.\"\"\"
    by_s: dict[str, list] = {}
    for (s, fname, disp, _, _) in fm:
        by_s.setdefault(s, []).append((disp, fname))
    parts = []
    for s in sorted(by_s):
        parts += [f"### {section_label(subskill, s)}", "", "| Topic | Read |", "| --- | --- |"]
        parts += [f"| {disp} | references/{fname} |" for disp, fname in by_s[s]]
        parts.append("")
    router = "\\n".join(parts).strip()
    md = f\"\"\"---
name: {name}
description: {triggers}
---

# {title} Reference

Use this skill for {purpose}

## Workflow

1. Identify the section the task touches.
2. Use the task router below or `references/INDEX.md` to open the one reference file that matches.
3. Treat every label, identifier, API/method name, endpoint, enum value, and number as an exact reference fact.

## Task router

Load only the reference the task needs. Files are grouped by section.

{router}

## Gotchas

- Stay inside these references unless the task explicitly needs other material.
- Verify implementation-sensitive claims (versions, endpoints, entitlements) against the live system before relying on them.

## References

Start at `references/INDEX.md`; metadata in `references/topics.json`. One subject per file.

## Verification

- Validate this skill with your skill-package validator and re-run the builder's `--verify`.
\"\"\"
    write_text(skill_dir / "SKILL.md", md)


def write_router(out: Path, name: str, title: str, description: str, subskills: list[tuple]) -> None:
    \"\"\"Write the top-level router SKILL.md for a multi-sub-skill build.\"\"\"
    rows = "\\n".join(f"| {subskill_meta(k)['title']} | {subskill_meta(k)['purpose']} | `{k}/SKILL.md` |"
                     for k, _ in subskills)
    md = f\"\"\"---
name: {name}
description: {description}
---

# {title} Router

Entry point that routes to product/area sub-skills; each is a direct subdirectory with its own
`SKILL.md` and a flat `references/` folder of focused, readable reference files.

## Workflow

1. Identify the sub-skill the task belongs to.
2. Open that sub-skill's `SKILL.md` and use its task router (or `references/INDEX.md`).
3. Read the one reference file that matches.

## Routes

| Sub-skill | Use for | Open |
| --- | --- | --- |
{rows}

## Gotchas

- Treat labels, identifiers, API names, endpoints, enum values, and version numbers as exact facts.

## References

Each sub-skill carries its own `references/INDEX.md`, `references/topics.json`, and per-subject files.

## Verification

- Validate the whole package with your skill-package validator (router + sub-skills).
\"\"\"
    write_text(out / "SKILL.md", md)


# ---- build orchestration -----------------------------------------------------

def _build_one(skill_dir: Path, subskill: str, skill_title: str, records: list[dict]) -> list:
    \"\"\"Build one skill's references/ + INDEX + topics from its records. Returns files_meta.\"\"\"
    refs = skill_dir / "references"
    if refs.exists():
        shutil.rmtree(refs)
    refs.mkdir(parents=True, exist_ok=True)

    by_section: dict[str, list] = collections.defaultdict(list)
    for r in records:
        by_section[section_of(r)].append(r)

    # Pass A: assign every file (name + leaves), no rendering yet.
    used: set = set()
    plans: list[dict] = []
    for section in sorted(by_section):
        for file_leaves in pack(build_leaves(by_section[section], section), 0):
            if len(file_leaves) == 1 and file_leaves[0]["bytes"] > TARGET_BYTES:
                leaf = file_leaves[0]
                runs = split_oversize(leaf)
                for i, run in enumerate(runs, 1):
                    sub = [{"path": leaf["path"], "title": leaf["title"], "chunks": run,
                            "bytes": sum(len(c["text"].encode("utf-8")) for c in run)}]
                    fname, disp = title_for(section, sub, used)
                    label = f"{disp} (part {i})" if len(runs) > 1 else disp
                    plans.append({"section": section, "fname": fname, "title": label, "leaves": sub})
                continue
            fname, disp = title_for(section, file_leaves, used)
            plans.append({"section": section, "fname": fname, "title": disp, "leaves": file_leaves})

    disambiguate_titles(plans)

    linkmap: dict = {}
    for pl in plans:
        for leaf in pl["leaves"]:
            for ch in leaf["chunks"]:
                su = ch.get("source_url")
                if su:
                    linkmap.setdefault(su, pl["fname"])

    files_meta = []
    for pl in plans:
        md = render_file(skill_title, pl["leaves"], pl["title"], linkmap)
        write_text(refs / pl["fname"], md)
        files_meta.append((pl["section"], pl["fname"], pl["title"], len(pl["leaves"]), len(md.encode("utf-8"))))

    write_index(refs, subskill, skill_title, files_meta)
    write_topics(refs, subskill, files_meta)
    return files_meta


def build(records: list[dict], out: Path, skill_name: str, skill_desc: str) -> dict:
    \"\"\"Build the whole skill (flat or router) under `out`. Returns a report dict.\"\"\"
    records = [r for r in records if not is_cruft(r.get("source_url") or "")]
    groups: dict[str, list] = collections.defaultdict(list)
    for r in records:
        groups[subskill_of(r) or ""].append(r)
    keys = [k for k in groups if k]
    report = {"out": str(out), "records": len(records), "subskills": {}, "router": bool(keys)}

    if not keys:  # flat single skill
        fm = _build_one(out, "", _titlecase(skill_name), groups[""])
        meta = {"title": _titlecase(skill_name), "purpose": "the reference material below.",
                "triggers": skill_desc}
        write_leaf_skill(out, skill_name, meta["title"], meta["purpose"], meta["triggers"], "", fm)
        report["subskills"][""] = len(fm)
        return report

    for k in sorted(groups):  # router of sub-skills
        if not k:
            continue
        m = subskill_meta(k)
        fm = _build_one(out / k, k, m["title"], groups[k])
        write_leaf_skill(out / k, k, m["title"], m["purpose"], m["triggers"], k, fm)
        report["subskills"][k] = len(fm)
    write_router(out, skill_name, _titlecase(skill_name), skill_desc, [(k, groups[k]) for k in sorted(keys)])
    return report


def post_process(out: Path) -> None:
    \"\"\"Optional whitespace normalization with prettier, then re-compact tables / re-backtick
    identifiers (prettier re-pads tables, so the deterministic passes run last). Skipped cleanly
    if prettier is unavailable.\"\"\"
    if RUN_PRETTIER:
        ignore = out / ".prettierignore-empty"
        try:
            ignore.write_text("", encoding="utf-8")
            subprocess.run(f'npx --no-install prettier --write --prose-wrap preserve '
                           f'--ignore-path "{ignore.as_posix()}" "{out.as_posix()}/**/*.md"',
                           shell=True, check=False, capture_output=True, timeout=900)
            ignore.unlink(missing_ok=True)
        except Exception as exc:  # prettier is a normalizer; the passes below are the real cleanup
            print(f"  prettier skipped: {exc}")
    for f in out.rglob("*.md"):
        t = f.read_text(encoding="utf-8")
        t2 = t
        if COMPACT_TABLES:
            t2 = compact_tables(t2)
        if BACKTICK_IDENTIFIERS:
            t2 = backtick_identifiers(t2)
        if t2 != t:
            f.write_text(t2, encoding="utf-8", newline="\\n")


def verify(out: Path) -> bool:
    \"\"\"Self-check the built skill: report file count, size distribution, residual raw image
    embeds / broken-looking relative links, and prose HTML. Returns True if clean enough.\"\"\"
    md_files = [f for f in out.rglob("*.md") if f.name != "INDEX.md" and f.name != "SKILL.md"]
    sizes = sorted(f.stat().st_size / 1024 for f in md_files)
    raw_img = raw_relpath = prose_html = 0
    htmltag = re.compile(r"</?(?:div|span|br|b|strong|td|tr|li|ul|table|script|style|p|h[1-6])\\b", re.IGNORECASE)
    for f in md_files:
        in_fence = False
        for line in f.read_text(encoding="utf-8").split("\\n"):
            s = line.lstrip()
            if _is_fence(s):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            raw_img += len(_IMG_RE.findall(line))
            for _, t in _LINK_RE.findall(line):
                if t.startswith("/") or "../" in t:
                    raw_relpath += 1
            outside = "".join(line.split("`")[i] for i in range(0, len(line.split("`")), 2))
            if htmltag.search(outside):
                prose_html += 1
    big = [f.name for f in md_files if f.stat().st_size > TARGET_BYTES * 1.6]
    print(f"  files={len(md_files)}  median={sizes[len(sizes)//2] if sizes else 0:.1f}KB  "
          f"max={sizes[-1] if sizes else 0:.1f}KB  over~40KB={len(big)}")
    print(f"  residual raw image embeds={raw_img}  raw relative-path links={raw_relpath}  prose-HTML lines={prose_html}")
    ok = raw_relpath == 0
    print("  VERIFY:", "OK" if ok else "review residual relative-path links")
    return ok


def _is_reparse_point(p: Path) -> bool:
    \"\"\"True if p itself is a Windows junction/symlink (reparse point) — checked WITHOUT resolving, so a
    per-skill junction (.agents/skills/<s> or .claude/skills/<s> -> the store) is detected before any copy.\"\"\"
    try:
        import os, stat
        return bool(os.lstat(str(p)).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return p.is_symlink()


def cmd_build(argv=None) -> int:
    \"\"\"Parse `build` CLI args, load records, build the skill, post-process, mirror, and verify.

    Returns 0 on success (or a clean verify), 1 if --verify fails, 2 if no records load.
    \"\"\"
    global TARGET_BYTES, RUN_PRETTIER, RESOLVE_REFS, COMPACT_TABLES, BACKTICK_IDENTIFIERS, \\
        SECTION_PREFIX, STRIP_ORDER_PREFIX
    ap = argparse.ArgumentParser(prog="skill_builder.py build", description="Build a readable per-subject reference skill from a JSONL chunk corpus.")
    ap.add_argument("--records", action="append", required=True, metavar="GLOB",
                    help="Glob of JSONL record files (repeatable; files merged by id). "
                         "Relative globs resolve under --work-dir.")
    ap.add_argument("--out", required=True, help="Output skill directory to (re)write (relative to CWD, or absolute).")
    ap.add_argument("--mirror", action="append", default=[], metavar="DIR",
                    help="Additional PLAIN directory to copy the built skill to (repeatable). Build directly "
                         "in the store; do NOT --mirror to the .agents/.claude per-skill junctions (a junction "
                         "target is skipped with a warning).")
    ap.add_argument("--work-dir", default=None,
                    help="Base directory for relative --records globs (default: <project-root>/AI/work).")
    ap.add_argument("--name", default=None, help="Skill name (kebab). Default: the --out folder name.")
    ap.add_argument("--description", default="Use when the task needs this reference material.",
                    help="SKILL.md frontmatter description (make it trigger-rich).")
    ap.add_argument("--target-bytes", type=int, default=None,
                    help="Per-file size target in bytes (default: %d)." % TARGET_BYTES)
    ap.add_argument("--no-prettier", action="store_true", help="Skip the prettier normalization pass.")
    ap.add_argument("--verbatim", action="store_true",
                    help="Verbatim preset for ingested-doc corpora: no link rewriting, table "
                         "compaction, identifier-backticking, or prettier; filenames from the page "
                         "slug; 2+digit ordering prefixes dropped from display titles.")
    ap.add_argument("--verify", action="store_true", help="Run the built-in audit after building.")
    args = ap.parse_args(argv)

    if args.verbatim:
        RESOLVE_REFS = COMPACT_TABLES = BACKTICK_IDENTIFIERS = RUN_PRETTIER = False
        SECTION_PREFIX = False
        STRIP_ORDER_PREFIX = True
    if args.target_bytes:
        TARGET_BYTES = args.target_bytes
    if args.no_prettier:
        RUN_PRETTIER = False

    work = Path(args.work_dir) if args.work_dir else _project_ai_dir(Path.cwd(), "AI", "work")
    record_globs = [g if Path(g).is_absolute() else str(work / g) for g in args.records]
    out = Path(args.out).resolve()
    name = args.name or out.name
    records = load_records(record_globs)
    if not records:
        print("No records loaded — check --records glob(s), --work-dir, and FIELD_MAP.")
        return 2

    report = build(records, out, name, args.description)
    post_process(out)
    for m in args.mirror:
        mp = Path(m)
        if _is_reparse_point(mp):
            print(f"WARNING: --mirror target '{mp}' is a junction/symlink (a per-skill link to the store); "
                  f"skipping. Build directly in the store; the junction already surfaces this skill to both agents.",
                  file=sys.stderr)
            continue
        dst = mp.resolve()
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(out, dst)

    mode = "router" if report["router"] else "flat"
    print(f"built {mode} skill '{name}' at {out}: {report['records']} records -> "
          f"{sum(report['subskills'].values())} files across {len(report['subskills'])} (sub)skill(s)")
    if args.mirror:
        print(f"mirrored to: {', '.join(args.mirror)}")
    ok = True
    if args.verify:
        ok = verify(out)
    return 0 if ok else 1

def main(argv=None) -> int:
    \"\"\"Standalone entry point for `python -m builder_components.build`; delegates to cmd_build.\"\"\"
    return cmd_build(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.maintain===
_SRC['builder_components.maintain'] = """
\"\"\"In-place gold maintenance of an existing skill (was the maintain section of skill_builder.py).\"\"\"

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from .corpus import TARGET_BYTES
from .ingest import run
from .packing import split_text_by_headings


# ==============================================================================
# MAINTAIN — in-place gold maintenance (was maintain_skill.py)
# ==============================================================================

_HEADING = re.compile(r"(?m)^#{2,3} ")


def subskill_dirs(skill: Path):
    \"\"\"Return the skill's sub-skill dirs (those with a SKILL.md), or [skill] itself if it is flat.\"\"\"
    subs = [d for d in sorted(skill.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]
    return subs if subs else [skill]


def ref_files(refs: Path):
    \"\"\"Return the sorted reference .md files in a directory, excluding INDEX.md.\"\"\"
    return sorted(p for p in refs.glob("*.md") if p.name != "INDEX.md")


def h1_title(text: str) -> str:
    \"\"\"Return the text of the first `# ` H1 heading, or an empty string if there is none.\"\"\"
    for ln in text.split("\\n"):
        if ln.startswith("# "):
            return ln[2:].strip()
    return ""


def has_subheadings(text: str) -> bool:
    \"\"\"Return True if the text contains any level-2 or level-3 (`## `/`### `) heading.\"\"\"
    return bool(_HEADING.search(text))


def split_runs(text: str, max_bytes: int):
    \"\"\"Split into <=max_bytes runs at heading/blank boundaries (fence-aware).\"\"\"
    global TARGET_BYTES
    old = TARGET_BYTES
    TARGET_BYTES = max_bytes
    try:
        pieces = split_text_by_headings(text)
    finally:
        TARGET_BYTES = old
    runs, cur, cb = [], [], 0
    for pc in pieces:
        b = len(pc.encode("utf-8"))
        if cur and cb + b > max_bytes:
            runs.append("\\n".join(cur)); cur = []; cb = 0
        cur.append(pc); cb += b
    if cur:
        runs.append("\\n".join(cur))
    return runs


_ENTRY_START = re.compile(r"\\*\\*[^*]+\\*\\*[)\\s.:]*$")  # line ends with a bold name/label token


def _is_entry_start(line: str) -> bool:
    \"\"\"A line that begins a new self-contained item: a sub-heading, or a short bold-label line such as
    '> Boolean **propertyName**' or '**someName**'. Description / prose lines are NOT entry starts, so a
    name is never separated from the description that follows it.\"\"\"
    s = line.strip()
    if re.match(r"#{2,6}\\s", s):
        return True
    s = s.lstrip("> ").strip()
    return len(s) <= 90 and bool(_ENTRY_START.search(s))


def split_atomic(text: str, max_bytes: int):
    \"\"\"Split a list-style file into <=max_bytes pieces ONLY at entry boundaries (a sub-heading or a
    short bold-label line that starts a new item), so a name is never separated from its description and
    a table row is never cut. Returns None when it cannot split cleanly — one entry already exceeds
    max_bytes (e.g. a monolithic table), or there are fewer than two entries — so the caller leaves the
    file whole (oversize is acceptable when a clean split is not possible).\"\"\"
    entries, cur = [], []
    for l in text.split("\\n"):
        if _is_entry_start(l) and cur:
            entries.append("\\n".join(cur)); cur = [l]
        else:
            cur.append(l)
    if cur:
        entries.append("\\n".join(cur))
    if len(entries) < 3 or any(len(e.encode("utf-8")) > max_bytes for e in entries):
        return None
    runs, run, rb = [], [], 0
    for e in entries:
        eb = len(e.encode("utf-8"))
        if run and rb + eb > max_bytes:
            runs.append("\\n".join(run)); run = []; rb = 0
        run.append(e); rb += eb
    if run:
        runs.append("\\n".join(run))
    return runs


def _degenerate(runs) -> bool:
    \"\"\"A split is no good if it produced <2 pieces or a tiny first piece (content lost / no break).\"\"\"
    return (not runs) or len(runs) < 2 or len(runs[0].encode("utf-8")) < 256


def audit(skill: Path, max_bytes: int):
    \"\"\"Survey each (sub)skill's references, reporting file counts, oversize files (with subheading
    status), and topics.json drift (files missing from / dangling in topics.json).\"\"\"
    report = []
    for sk in subskill_dirs(skill):
        refs = sk / "references"
        if not refs.is_dir():
            continue
        files = ref_files(refs)
        present = {p.name for p in files}
        listed = set()
        tj = refs / "topics.json"
        if tj.is_file():
            try:
                d = json.loads(tj.read_text(encoding="utf-8"))
                listed = {Path(t.get("file", "")).name for t in d.get("topics", [])}
            except Exception:
                listed = set()
        oversize = []
        for p in files:
            sz = p.stat().st_size
            if sz > max_bytes:
                txt = p.read_text(encoding="utf-8")
                oversize.append((p.name, sz, has_subheadings(txt)))
        report.append({
            "subskill": sk.name if sk is not skill else "(flat)",
            "files": len(files),
            "oversize": sorted(oversize, key=lambda x: -x[1]),
            "missing_in_topics": sorted(present - listed) if listed else [],
            "dangling_topics": sorted(listed - present),
        })
    return report


def _next_name(stem: str, used: set) -> str:
    \"\"\"Return the next unused `{stem}-{n}.md` filename and record it in `used`.\"\"\"
    n = 2
    while f"{stem}-{n}.md" in used:
        n += 1
    name = f"{stem}-{n}.md"
    used.add(name)
    return name


def patch_topics(refs: Path, orig: str, parts: list):
    \"\"\"Insert topics.json entries for the new split parts of `orig`, cloning its metadata and labeling
    each with a '(part k)' topic suffix. No-op if topics.json is absent.\"\"\"
    tj = refs / "topics.json"
    if not tj.is_file():
        return
    d = json.loads(tj.read_text(encoding="utf-8"))
    topics = d.get("topics", [])
    for i, t in enumerate(topics):
        if Path(t.get("file", "")).name == orig:
            new = []
            for k, pn in enumerate(parts, start=2):
                e = dict(t)
                e["file"] = f"references/{pn}"
                e["topic"] = f'{t.get("topic", orig)} (part {k})'
                new.append(e)
            topics[i + 1:i + 1] = new
            break
    tj.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8", newline="\\n")


def patch_index(refs: Path, orig: str, parts: list):
    \"\"\"Insert INDEX.md table rows for the new split parts of `orig`, reusing its 'covers' cell with a
    '(part k)' suffix. No-op if INDEX.md is absent.\"\"\"
    idx = refs / "INDEX.md"
    if not idx.is_file():
        return
    lines = idx.read_text(encoding="utf-8").split("\\n")
    for i, ln in enumerate(lines):
        if f"]({orig})" in ln and ln.lstrip().startswith("|"):
            m = re.match(r"\\s*\\|\\s*\\[.*?\\]\\(.*?\\)\\s*\\|(.*)\\|\\s*$", ln)
            covers = (m.group(1).strip() if m else "")
            rows = [f"| [{pn}]({pn}) | {covers} (part {k}) |" for k, pn in enumerate(parts, start=2)]
            lines[i + 1:i + 1] = rows
            break
    idx.write_text("\\n".join(lines), encoding="utf-8", newline="\\n")


def apply_splits(skill: Path, max_bytes: int, force: bool, act_above: int):
    \"\"\"Split each reference file larger than `act_above` into <=max_bytes pieces in place, patching
    INDEX/topics. Atomic (no-subheading) files are split only with `force`; unsplittable files are
    skipped. Returns (changed, skipped) lists of per-file outcomes.\"\"\"
    changed, skipped = [], []
    for sk in subskill_dirs(skill):
        refs = sk / "references"
        if not refs.is_dir():
            continue
        used = {p.name for p in refs.glob("*.md")}
        for p in ref_files(refs):
            if p.stat().st_size <= act_above:           # only touch files above this; pieces target max_bytes
                continue
            text = p.read_text(encoding="utf-8")
            atomic = not has_subheadings(text)
            if atomic and not force:
                skipped.append((sk.name, p.name, "atomic; use --force")); continue
            runs = split_atomic(text, max_bytes) if atomic else split_runs(text, max_bytes)
            if _degenerate(runs):                       # primary strategy failed; try the other one
                runs = split_runs(text, max_bytes) if atomic else split_atomic(text, max_bytes)
            if _degenerate(runs):                       # genuinely unsplittable (monolithic table / one huge line)
                skipped.append((sk.name, p.name, "unsplittable (no clean break point)")); continue
            stem = p.stem
            title = re.sub(r"\\s*\\(part \\d+\\)\\s*$", "", h1_title(text)) or stem
            p.write_text(runs[0].rstrip() + "\\n", encoding="utf-8", newline="\\n")  # part 1 keeps name + H1
            parts = []
            for k, run in enumerate(runs[1:], start=2):
                name = _next_name(stem, used)
                body = run if run.lstrip().startswith("#") else f"# {title} (part {k})\\n\\n{run}"
                (refs / name).write_text(body.rstrip() + "\\n", encoding="utf-8", newline="\\n")
                parts.append(name)
            patch_index(refs, p.name, parts)
            patch_topics(refs, p.name, parts)
            changed.append((sk.name, p.name, len(parts) + 1))
    return changed, skipped


_CAMEL = re.compile(r"[a-z][A-Z]")


def _distinctive_terms(refs: Path) -> dict:
    \"\"\"{distinctive topic-name -> filename} from topics.json; skips short / common single words to
    avoid over-linking. Multi-word titles and identifier-like names qualify.\"\"\"
    tj = refs / "topics.json"
    if not tj.is_file():
        return {}
    try:
        d = json.loads(tj.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for t in d.get("topics", []):
        name = (t.get("topic") or "").strip()
        fn = Path(t.get("file", "")).name
        if not name or not fn or len(name) < 5:
            continue
        if len(name.split()) >= 2 or _CAMEL.search(name) or "." in name or len(name) >= 10:
            out[name] = fn
    return out


def _no_code(text: str) -> str:
    \"\"\"Blank out fenced + inline code so a match never lands inside code.\"\"\"
    out, fence = [], False
    for l in text.split("\\n"):
        if l.lstrip().startswith("```"):
            fence = not fence; out.append(""); continue
        out.append("" if fence else re.sub(r"`[^`]*`", "", l))
    return "\\n".join(out)


def cross_link(skill: Path, max_links: int = 6):
    \"\"\"Append/refresh a '## See also' footer on each reference file, linking other topics in the same
    (sub)skill whose distinctive name appears in the file (and isn't already linked inline). Safe and
    idempotent: only the footer is touched — prose, SKILL.md and GOTCHA.md are left alone. This is the
    lightweight, conservative cross-link capability; richer inline/curated linking is a later pass.\"\"\"
    changed = []
    for sk in subskill_dirs(skill):
        refs = sk / "references"
        if not refs.is_dir():
            continue
        terms = _distinctive_terms(refs)
        if not terms:
            continue
        for p in ref_files(refs):
            text = p.read_text(encoding="utf-8")
            body = re.split(r"\\n## See also\\n", text, 1)[0].rstrip()
            searchable = _no_code(body)
            linked = set(re.findall(r"\\]\\(([^)/]+\\.md)\\)", body))
            related, seen = [], set()
            for name, fn in terms.items():
                if fn == p.name or fn in linked or fn in seen:
                    continue
                if re.search(r"\\b" + re.escape(name) + r"\\b", searchable):
                    related.append((name, fn)); seen.add(fn)
            related = related[:max_links]
            footer = ("\\n\\n## See also\\n\\n" + "\\n".join(f"- [{n}]({fn})" for n, fn in related) + "\\n") if related else "\\n"
            new = body + footer
            if new != text:
                p.write_text(new, encoding="utf-8", newline="\\n")
                if related:
                    changed.append((sk.name, p.name, len(related)))
    return changed


def cmd_maintain(argv=None) -> int:
    \"\"\"Run the `maintain` subcommand: audit a skill's references and print the report, then optionally
    apply oversize splits and/or refresh 'See also' cross-link footers. Returns an exit code.\"\"\"
    ap = argparse.ArgumentParser(prog="skill_builder.py maintain")
    ap.add_argument("skill")
    ap.add_argument("--apply", action="store_true", help="split oversize heading-structured files in place")
    ap.add_argument("--force", action="store_true", help="also size-split atomic (no-subheading) files")
    ap.add_argument("--max-bytes", type=int, default=TARGET_BYTES, help="target size for resulting pieces")
    ap.add_argument("--act-above", type=int, default=None,
                    help="only split files larger than this (default: --max-bytes); pieces still target --max-bytes")
    ap.add_argument("--cross-link", action="store_true",
                    help="add/refresh a 'See also' footer on each reference file (links related topics by distinctive name)")
    args = ap.parse_args(argv)
    skill = Path(args.skill)

    rep = audit(skill, args.max_bytes)
    print(f"# audit: {skill}  (max-bytes={args.max_bytes})")
    for r in rep:
        flags = []
        if r["oversize"]:
            flags.append("oversize=" + ", ".join(
                f"{n}({sz//1024}KB,{'has-headings' if hh else 'ATOMIC'})" for n, sz, hh in r["oversize"]))
        if r["missing_in_topics"]:
            flags.append("missing_in_topics=" + ",".join(r["missing_in_topics"]))
        if r["dangling_topics"]:
            flags.append("dangling_topics=" + ",".join(r["dangling_topics"]))
        status = "; ".join(flags) if flags else "clean"
        print(f"  [{r['subskill']}] files={r['files']}  {status}")

    if args.apply:
        changed, skipped = apply_splits(skill, args.max_bytes, args.force, args.act_above or args.max_bytes)
        if changed:
            print("# applied splits:")
            for sub, f, n in changed:
                print(f"  [{sub}] {f} -> {n} files")
        for sub, f, why in skipped:
            print(f"# skipped: [{sub}] {f} ({why})")
        if not changed and not skipped:
            print("# nothing eligible.")

    if args.cross_link:
        cl = cross_link(skill)
        if cl:
            print("# cross-linked (See also footers added/refreshed):")
            for sub, f, n in cl:
                print(f"  [{sub}] {f} -> {n} related")
        else:
            print("# cross-link: no distinctive cross-references found (no footers added).")
    return 0

def main(argv=None) -> int:
    \"\"\"Standalone entry point for `python -m builder_components.maintain`; delegates to cmd_maintain.\"\"\"
    return cmd_maintain(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.split_engine===
_SRC['builder_components.split_engine'] = """
\"\"\"Split engine: parse a source reference into topics, group/assign/render them, and regenerate
INDEX/topics/symbols (was the split section of skill_builder.py; the cmd_split CLI lives in split_cmd.py).\"\"\"

from __future__ import annotations

import argparse
import glob as globmod
import json
import re
from collections import Counter
from collections import OrderedDict
from pathlib import Path
from builder_components.util.text_io import write_text
from .corpus import TARGET_BYTES, backtick_identifiers, clean_body, clean_title, compact_tables, strip_cruft
from .packing import _titlecase, slug


# ==============================================================================
# SPLIT — split oversized references by topic (was split_reference_md.py)
# ==============================================================================

# --- share the proven helpers from the sibling builder (no duplication) -------


# =============================================================================
# CONFIGURATION  (CLI flags override these; a --legend overrides per file)
# =============================================================================

TOPIC_LEVEL = 3
\"\"\"Heading level whose blocks are topics. 3 => split on `### `.\"\"\"

SECTION = "Entries"
\"\"\"Name of the `## ` section whose sub-headings are the topics. Empty string =>
treat the whole file (everything after the `# H1`) as the topic source.\"\"\"

GROUP_CONSECUTIVE = True
\"\"\"Merge consecutive blocks that share a normalized title into one topic.\"\"\"

MAX_BYTES = 0
\"\"\"0 => one file per topic. >0 => pack whole topics (never splitting one) into
files up to this many UTF-8 bytes.\"\"\"

STRIP_PREFIX = ""
\"\"\"Prefix removed from a source filename stem before deriving its subject token
and label when no explicit token is supplied (e.g. "myproj-").\"\"\"

ADD_BLOCKQUOTE = ""
\"\"\"Optional one-line provenance blockquote placed under each topic's H1.
`{source}` expands to the source group title, `{skill}` to --skill-title.
Empty => no blockquote (the most faithful option).\"\"\"

INDEX_TOPIC_HEADING = "Topic Files"
\"\"\"The `## ` heading in INDEX.md whose body is replaced with the file listing.
Every other INDEX section is preserved. If absent, the listing is inserted
right after the index preamble.\"\"\"

CLEAN = False
\"\"\"Apply build_skill_corpus's cleaning passes (HTML/entity normalization,
heading demotion inside bodies, cruft removal) to each topic body. Off by
default so already-clean prose is copied verbatim and `--verify` is exact.\"\"\"

SPLIT_COMPACT_TABLES = False
\"\"\"When --clean is on, also re-pad/repair Markdown tables in topic bodies.\"\"\"


# =============================================================================
# DERIVED-VALUE HOOKS  (edit if a corpus needs different label/token logic)
# =============================================================================

def subject_token(source: Path, explicit: str = "") -> str:
    \"\"\"Short kebab token identifying a source file, used to disambiguate topic
    filenames that collide across sources. Uses the legend's `subject_token`
    when given, else slugs the filename stem (minus STRIP_PREFIX).\"\"\"
    if explicit:
        return slug(explicit)
    stem = source.stem
    if STRIP_PREFIX and stem.startswith(STRIP_PREFIX):
        stem = stem[len(STRIP_PREFIX):]
    return slug(stem)


def source_label(source: Path, h1: str) -> str:
    \"\"\"Human label for a source file's group in INDEX.md: its `# H1` if present,
    else a title-cased token.\"\"\"
    return h1.strip() if h1.strip() else _titlecase(subject_token(source))


def normalize_topic_title(raw: str) -> str:
    \"\"\"Normalize a topic heading for grouping/titles (drop trailing ' (n)',
    HTML, bold).\"\"\"
    return clean_title(raw) or raw.strip()


# =============================================================================
# ENGINE
# =============================================================================

def _read(path: Path) -> str:
    \"\"\"Read a file's full text as UTF-8.\"\"\"
    return path.read_text(encoding="utf-8")


def parse_source(text: str, topic_level: int, section: str):
    \"\"\"Return (h1, topic_blocks, nonsection_blocks, section_preamble).

    topic_blocks: list of (raw_title, body) in document order.
    nonsection_blocks: list of (heading, body) for `## ` sections that are NOT
    the topic section (boilerplate to fold into INDEX).
    \"\"\"
    lines = text.split("\\n")
    h1 = ""
    for ln in lines:
        if ln.startswith("# ") and not ln.startswith("## "):
            h1 = ln[2:].strip()
            break

    # Partition into level-2 sections (preamble = anything before the first one).
    sections: "list[tuple[str, list[str]]]" = []
    cur_head = None
    cur_body: list[str] = []
    for ln in lines:
        if ln.startswith("## "):
            if cur_head is not None:
                sections.append((cur_head, cur_body))
            cur_head = ln[3:].strip()
            cur_body = []
        else:
            cur_body.append(ln)
    if cur_head is not None:
        sections.append((cur_head, cur_body))

    if section:
        target_body: list[str] = []
        nonsection: list[tuple[str, str]] = []
        want = section.strip().lower()
        for head, body in sections:
            if head.strip().lower() == want:
                target_body = body
            else:
                nonsection.append((head, "\\n".join(body).strip()))
    else:
        # Whole file: everything after the H1 is the topic source.
        target_body = []
        capture = False
        for ln in lines:
            if not capture:
                if ln.startswith("# ") and not ln.startswith("## "):
                    capture = True
                continue
            target_body.append(ln)
        nonsection = []

    blocks, preamble = _split_blocks(target_body, topic_level)
    return h1, blocks, nonsection, preamble


def _split_blocks(body_lines: list[str], topic_level: int):
    \"\"\"Split a section's lines into (title, body) blocks at the topic heading
    level. Text before the first heading is returned as the preamble.\"\"\"
    hmark = "#" * topic_level + " "
    blocks: list[tuple[str, str]] = []
    cur_title = None
    cur: list[str] = []
    pre: list[str] = []
    for ln in body_lines:
        if ln.startswith(hmark):
            if cur_title is None:
                pre = cur
            else:
                blocks.append((cur_title, "\\n".join(cur).strip()))
            cur_title = ln[len(hmark):].strip()
            cur = []
        else:
            cur.append(ln)
    if cur_title is None:
        pre = cur
    else:
        blocks.append((cur_title, "\\n".join(cur).strip()))
    return blocks, "\\n".join(pre).strip()


def group_topics(blocks: list[tuple[str, str]], group_consecutive: bool):
    \"\"\"Collapse consecutive same-title blocks into one topic. Returns
    list of (title, body) where body is the verbatim block bodies joined.\"\"\"
    grouped: list[list] = []  # [title, [bodies]]
    for raw_title, body in blocks:
        title = normalize_topic_title(raw_title)
        if group_consecutive and grouped and grouped[-1][0] == title:
            grouped[-1][1].append(body)
        else:
            grouped.append([title, [body]])
    return [(t, "\\n\\n".join(b for b in bodies if b)) for t, bodies in grouped]


def assign_filenames(topics: list[dict]) -> None:
    \"\"\"Assign a unique `fname` to each topic dict in place.

    Clean `slug(title).md` where unique; on cross-source collision prefix the
    subject token; residual collisions get a numeric suffix. Deterministic and
    order-stable.\"\"\"
    base_counts = Counter(t["base"] for t in topics)
    for t in topics:
        t["slug"] = (f"{t['token']}-{t['base']}" if base_counts[t["base"]] > 1 else t["base"]) or "topic"
    seen: dict[str, int] = {}
    for t in topics:
        s = t["slug"]
        if s in seen:
            seen[s] += 1
            t["fname"] = f"{s}-{seen[s]}.md"
        else:
            seen[s] = 1
            t["fname"] = f"{s}.md"


def render_topic(title: str, body: str, blockquote: str) -> str:
    \"\"\"Build a topic file: `# Title`, optional blockquote, then the body.\"\"\"
    if CLEAN:
        body = strip_cruft(clean_body(body))
        if SPLIT_COMPACT_TABLES:
            body = compact_tables(backtick_identifiers(body))
    parts = [f"# {title}", ""]
    if blockquote:
        parts += [blockquote, ""]
    parts.append(body)
    return "\\n".join(parts).rstrip() + "\\n"


def pack_topics(topics: list[dict], max_bytes: int) -> list[dict]:
    \"\"\"When --max-bytes is set, merge adjacent topics from the SAME source into
    combined files up to max_bytes (never splitting a topic). Returns a new list
    of topic dicts. With max_bytes <= 0 the input is returned unchanged.\"\"\"
    if max_bytes <= 0:
        return topics
    out: list[dict] = []
    i = 0
    n = len(topics)
    while i < n:
        first = topics[i]
        titles = [first["title"]]
        bodies = [first["body"]]
        size = len(first["body"].encode("utf-8"))
        j = i + 1
        while j < n and topics[j]["src"] == first["src"]:
            b = len(topics[j]["body"].encode("utf-8"))
            if size + b > max_bytes:
                break
            titles.append(topics[j]["title"])
            bodies.append(topics[j]["body"])
            size += b
            j += 1
        merged = dict(first)
        if len(titles) > 1:
            merged["title"] = ", ".join(titles)
            merged["body"] = "\\n\\n".join(f"## {t}\\n\\n{b}" for t, b in zip(titles, bodies))
        out.append(merged)
        i = j
    return out


# ---- index / topics / symbols regeneration ----------------------------------

def _dedupe_blocks(blocks: list[tuple[str, str]]) -> "list[tuple[str, str]]":
    \"\"\"Drop blocks with empty or duplicate (heading, body) content, preserving first-seen order.\"\"\"
    seen = set()
    out = []
    for head, body in blocks:
        key = (head.strip(), body.strip())
        if body.strip() and key not in seen:
            seen.add(key)
            out.append((head.strip(), body.strip()))
    return out


def regen_index(out_dir: Path, skill_title: str, source_order: list[str],
                topics_by_source: "OrderedDict[str, list]", group_titles: dict,
                notes: list[tuple[str, str]], index_topic_heading: str) -> None:
    \"\"\"Rewrite INDEX.md: replace the topic-listing section, preserve all others,
    and fold deduplicated source boilerplate into '## Source notes'.\"\"\"
    listing = [f"## {index_topic_heading}", ""]
    for src in source_order:
        rows = topics_by_source.get(src, [])
        if not rows:
            continue
        listing.append(f"### {group_titles.get(src, src)}")
        listing.append("")
        listing.append("| File | Topic |")
        listing.append("| --- | --- |")
        for title, fname in rows:
            listing.append(f"| [{fname}]({fname}) | {title} |")
        listing.append("")
    listing_text = "\\n".join(listing).rstrip()

    notes_text = ""
    if notes:
        nl = ["## Source notes", "",
              "Boilerplate carried over from the original combined reference files."]
        for head, body in notes:
            nl += ["", f"### {head}", "", body]
        notes_text = "\\n".join(nl).rstrip()

    idx = out_dir / "INDEX.md"
    if idx.exists():
        text = _read(idx)
        lines = text.split("\\n")
        pre: list[str] = []
        secs: list[tuple[str, list[str]]] = []
        cur = None
        body: list[str] = []
        for ln in lines:
            if ln.startswith("## "):
                if cur is None:
                    pre = body
                else:
                    secs.append((cur, body))
                cur = ln[3:].strip()
                body = []
            else:
                body.append(ln)
        if cur is None:
            pre = body
        else:
            secs.append((cur, body))

        result = "\\n".join(pre).rstrip() + "\\n\\n"
        replaced = False
        ordered: list[tuple[str, list[str] | None]] = []
        for head, b in secs:
            if head == index_topic_heading:
                ordered.append(("__LISTING__", None))
                replaced = True
            elif head == "Source notes":
                continue  # re-added at the end
            else:
                ordered.append((head, b))
        if not replaced:
            ordered.insert(0, ("__LISTING__", None))
        if notes_text:
            ordered.append(("__NOTES__", None))
        for head, b in ordered:
            if head == "__LISTING__":
                result += listing_text + "\\n\\n"
            elif head == "__NOTES__":
                result += notes_text + "\\n\\n"
            else:
                result += f"## {head}\\n\\n" + "\\n".join(b).strip() + "\\n\\n"
        write_text(idx, result.rstrip() + "\\n")
    else:
        parts = [f"# {skill_title} Reference Index", "", listing_text]
        if notes_text:
            parts += ["", notes_text]
        write_text(idx, "\\n".join(parts).rstrip() + "\\n")


def regen_topics(out_dir: Path, topics: list[dict]) -> None:
    \"\"\"Rewrite topics.json as a flat {title: {file, corpus_search_hints}} map,
    inheriting each topic's source file's existing search hints when available.\"\"\"
    tj = out_dir / "topics.json"
    hints_by_file: dict[str, list] = {}
    if tj.exists():
        try:
            data = json.loads(_read(tj))
            if isinstance(data, dict) and "topics" not in data:
                for _title, meta in data.items():
                    f = (meta or {}).get("file")
                    if f:
                        hints_by_file[Path(f).name] = (meta or {}).get("corpus_search_hints", []) or []
        except (ValueError, AttributeError):
            pass

    title_counts = Counter(t["title"] for t in topics)
    used: set[str] = set()
    new: "OrderedDict[str, dict]" = OrderedDict()
    for t in topics:
        key = t["title"]
        if title_counts[t["title"]] > 1:
            key = f"{t['title']} ({t['src_label']})"
        base = key
        i = 2
        while key in used:
            key = f"{base} ({i})"
            i += 1
        used.add(key)
        new[key] = {"file": t["fname"],
                    "corpus_search_hints": hints_by_file.get(t["src_name"], [])}
    write_text(tj, json.dumps(new, ensure_ascii=False, indent=2) + "\\n")


def remap_symbols(symbols_path: Path, topic_texts: list[tuple[str, str]],
                  source_map: "dict | None" = None,
                  files_by_source: "dict | None" = None) -> int:
    \"\"\"Recompute each group's `reference_files` after a split, leaving
    `corpus_chunk_ids` and all other fields/order intact.

    Two modes:
      * source_map given — each group key is mapped to a SOURCE filename and its
        reference_files become the topic files derived from that source doc
        (precise, deterministic). Groups absent from the map are left unchanged.
      * otherwise — term presence: files whose text contains the group key
        (word-boundary, case-insensitive). Unreliable when keys are normalized
        labels not present verbatim in the prose.

    Returns the number of groups updated.\"\"\"
    data = json.loads(_read(symbols_path))
    updated = 0
    for term, meta in data.items():
        if not isinstance(meta, dict) or "reference_files" not in meta:
            continue
        if source_map is not None:
            if term in source_map:
                meta["reference_files"] = sorted((files_by_source or {}).get(source_map[term], []))
                updated += 1
            continue
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE)
        meta["reference_files"] = sorted(fname for fname, txt in topic_texts if pat.search(txt))
        updated += 1
    write_text(symbols_path, json.dumps(data, ensure_ascii=False, indent=2) + "\\n")
    return updated


# ---- verification ------------------------------------------------------------

def _split_verify(out_dir: Path, topics: list[dict], src_concat: str,
           index_topic_heading: str) -> bool:
    \"\"\"Prove coverage (no dropped/duplicated content), report sizes, and check
    INDEX/topics consistency. Returns True on success.\"\"\"
    ok = True
    # 1. Content coverage: reconstruct from disk and compare to the source.
    recon = []
    for t in topics:
        fpath = out_dir / t["fname"]
        text = _read(fpath)
        b = _strip_topic_header(text, t["title"])
        recon.append(b.strip())
    recon_concat = "\\n\\n".join(x for x in recon if x)
    if recon_concat != src_concat:
        ok = False
        # localize the first divergence for a useful message
        a, b = src_concat, recon_concat
        k = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
        print(f"  COVERAGE MISMATCH at char {k}: source has {len(a)}B, "
              f"reconstructed {len(b)}B")
        print(f"    source : ...{a[max(0,k-40):k+40]!r}")
        print(f"    written: ...{b[max(0,k-40):k+40]!r}")
    else:
        print(f"  coverage OK: {len(topics)} topic files reproduce "
              f"{len(src_concat)}B of source content exactly")

    # 2. Size distribution.
    sizes = sorted(len((out_dir / t["fname"]).read_bytes()) for t in topics)
    if sizes:
        med = sizes[len(sizes) // 2]
        print(f"  sizes: files={len(sizes)} median={med/1024:.1f}KB "
              f"max={sizes[-1]/1024:.1f}KB min={sizes[0]/1024:.1f}KB")
        over = [s for s in sizes if s > TARGET_BYTES]
        if over:
            print(f"  note: {len(over)} file(s) exceed {TARGET_BYTES/1024:.0f}KB "
                  f"(single atomic topics; acceptable)")

    # 3. INDEX & topics list every file, with no orphans/dangling.
    fnames = {t["fname"] for t in topics}
    idx = out_dir / "INDEX.md"
    tj = out_dir / "topics.json"
    idx_text = _read(idx) if idx.exists() else ""
    listed_idx = set(re.findall(r"\\[([^\\]]+\\.md)\\]\\(", idx_text))
    missing_idx = fnames - listed_idx
    if missing_idx:
        ok = False
        print(f"  INDEX missing {len(missing_idx)} file(s): {sorted(missing_idx)[:5]}")
    if tj.exists():
        tdata = json.loads(_read(tj))
        listed_tj = {Path(v["file"]).name for v in tdata.values() if isinstance(v, dict) and v.get("file")}
        missing_tj = fnames - listed_tj
        dangling_tj = listed_tj - fnames
        if missing_tj:
            ok = False
            print(f"  topics.json missing {len(missing_tj)} file(s): {sorted(missing_tj)[:5]}")
        if dangling_tj:
            ok = False
            print(f"  topics.json dangling {len(dangling_tj)} entry(ies): {sorted(dangling_tj)[:5]}")
    if not (missing_idx or (tj.exists() and (missing_tj or dangling_tj))):
        print("  INDEX/topics consistency OK (every file listed, no orphans)")
    print("  VERIFY: OK" if ok else "  VERIFY: FAILED")
    return ok


def _strip_topic_header(text: str, title: str) -> str:
    \"\"\"Remove the `# Title` line and an optional immediate blockquote from a
    rendered topic file, returning the body.\"\"\"
    lines = text.split("\\n")
    out = []
    i = 0
    # drop leading H1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        i += 1
    # drop blank + optional blockquote
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    while i < len(lines) and lines[i].lstrip().startswith(">"):
        i += 1
    out = lines[i:]
    return "\\n".join(out).strip()


# =============================================================================
# DRIVER
# =============================================================================

def _file_specs(args) -> list[dict]:
    \"\"\"Resolve the list of source files + per-file params from --legend or --md.\"\"\"
    specs: list[dict] = []
    defaults = {"topic_level": args.topic_level, "section": args.section,
                "group_consecutive": args.group_consecutive, "subject_token": ""}
    if args.legend:
        legend = json.loads(Path(args.legend).read_text(encoding="utf-8"))
        ldef = {**defaults, **legend.get("defaults", {})}
        for entry in legend.get("files", []):
            spec = {**ldef, **entry}
            spec["path"] = Path(spec["path"])
            specs.append(spec)
    else:
        paths: list[Path] = []
        for pattern in args.md:
            hits = [Path(p) for p in globmod.glob(pattern)]
            paths.extend(hits if hits else [Path(pattern)])
        for p in paths:
            specs.append({**defaults, "path": p})
    return specs
"""

# ===MODULE builder_components.lint===
_SRC['builder_components.lint'] = """
\"\"\"Link / topics health check (was the lint section of skill_builder.py).\"\"\"

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from builder_components.util.repo_paths import _project_ai_dir
from .maintain import ref_files, subskill_dirs


# ==============================================================================
# LINT — link/topics health check (was lint_skill.py)
# ==============================================================================

_LINK = re.compile(r"(?<!!)\\]\\(([^)#?]+\\.md)(?:#[^)]*)?\\)")


def lint_subskill(sk: Path) -> dict:
    \"\"\"Check one (sub)skill's references for dangling local .md links and topics.json drift, returning
    {dangling, missing_in_topics, dangling_topics} issue lists.\"\"\"
    refs = sk / "references"
    issues = {"dangling": [], "missing_in_topics": [], "dangling_topics": []}
    if not refs.is_dir():
        return issues
    files = ref_files(refs)
    names = {p.name for p in files}

    # dangling local links — resolve each target relative to the SOURCE file's own directory, so a
    # SKILL.md link to GOTCHA.md (a sibling) or a reference's sibling link resolves correctly.
    for src in [refs / "INDEX.md", sk / "SKILL.md", *files]:
        if not src.is_file():
            continue
        for tgt in _LINK.findall(src.read_text(encoding="utf-8")):
            if "://" in tgt:                       # online link (e.g. https://…/x.md) — not a local file
                continue
            if not (src.parent / tgt).is_file():
                issues["dangling"].append(f"{src.name} -> {tgt}")

    # topics.json <-> files drift
    tj = refs / "topics.json"
    if tj.is_file():
        listed = set()
        try:
            listed = {Path(t.get("file", "")).name
                      for t in json.loads(tj.read_text(encoding="utf-8")).get("topics", [])}
        except Exception:
            pass
        issues["missing_in_topics"] = sorted(names - listed)
        issues["dangling_topics"] = sorted(listed - names)
    return issues


def cmd_lint(argv=None) -> int:
    \"\"\"Run the `lint` subcommand: check each (sub)skill for link/topics issues, write a report to the
    out dir, and print a summary. Returns 0 when clean, 1 otherwise.\"\"\"
    ap = argparse.ArgumentParser(prog="skill_builder.py lint")
    ap.add_argument("skill")
    ap.add_argument("--out", default=None,
                    help="report directory (default: <project-root>/AI/lint, resolved from $DEVROOT/CWD)")
    args = ap.parse_args(argv)
    skill = Path(args.skill)
    name = skill.name
    out_dir = Path(args.out) if args.out else _project_ai_dir(skill.resolve(), "AI", "lint")

    lines = [f"# Lint: {name}", ""]
    totals = {"dangling": 0, "missing_in_topics": 0, "dangling_topics": 0}
    for sk in subskill_dirs(skill):
        iss = lint_subskill(sk)
        label = sk.name if sk is not skill else "(flat)"
        flagged = {k: v for k, v in iss.items() if v}
        for k, v in iss.items():
            totals[k] += len(v)
        if flagged:
            lines.append(f"## {label}")
            for k, v in flagged.items():
                lines.append(f"- **{k}** ({len(v)}): " + "; ".join(v[:25]) + (" …" if len(v) > 25 else ""))
            lines.append("")
    clean = sum(totals.values()) == 0
    if clean:
        lines.append("Clean — no link/content issues found.")

    out = out_dir / f"{name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\\n".join(lines).rstrip() + "\\n", encoding="utf-8", newline="\\n")
    summary = "clean" if clean else ", ".join(f"{k}={v}" for k, v in totals.items() if v)
    print(f"{name}: {summary}  -> {out.as_posix()}")
    return 0 if clean else 1

def main(argv=None) -> int:
    \"\"\"Standalone entry point for `python -m builder_components.lint`; delegates to cmd_lint.\"\"\"
    return cmd_lint(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.split_cmd===
_SRC['builder_components.split_cmd'] = """
\"\"\"Split CLI: the `split` subcommand (cmd_split), on top of split_engine.\"\"\"

from __future__ import annotations

import argparse
import json
from .packing import _titlecase
from .packing import slug
from builder_components.util.text_io import write_text
from collections import OrderedDict
from pathlib import Path
from .split_engine import (
    ADD_BLOCKQUOTE,
    INDEX_TOPIC_HEADING,
    MAX_BYTES,
    SECTION,
    STRIP_PREFIX,
    TOPIC_LEVEL,
    _dedupe_blocks,
    _file_specs,
    _read,
    _split_verify,
    assign_filenames,
    group_topics,
    pack_topics,
    parse_source,
    regen_index,
    regen_topics,
    remap_symbols,
    render_topic,
    source_label,
    subject_token,
)


def cmd_split(argv=None) -> int:
    \"\"\"Run the `split` subcommand: parse args, split each source into topic files, and regenerate
    INDEX/topics (optionally remapping symbols, replacing inputs, and verifying). Returns an exit code.\"\"\"
    global TOPIC_LEVEL, SECTION, GROUP_CONSECUTIVE, MAX_BYTES, STRIP_PREFIX
    global ADD_BLOCKQUOTE, INDEX_TOPIC_HEADING, CLEAN, SPLIT_COMPACT_TABLES

    ap = argparse.ArgumentParser(
        prog="skill_builder.py split",
        description="Split heading-structured Markdown reference docs into one file per topic.")
    ap.add_argument("--md", nargs="+", default=[],
                    help="Input .md globs/paths (omit when using --legend).")
    ap.add_argument("--legend", help="JSON legend: per-file split params (see module docstring).")
    ap.add_argument("--out", help="Output references dir (default: the inputs' own directory).")
    ap.add_argument("--topic-level", type=int, default=TOPIC_LEVEL,
                    help=f"Heading level whose blocks are topics (default {TOPIC_LEVEL} => '###').")
    ap.add_argument("--section", default=SECTION,
                    help=f"'## ' section holding the topics (default '{SECTION}'; '' => whole file).")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--group-consecutive", dest="group_consecutive", action="store_true", default=True,
                     help="Merge consecutive same-title blocks into one topic (default).")
    grp.add_argument("--no-group-consecutive", dest="group_consecutive", action="store_false",
                     help="Treat every block as its own topic.")
    ap.add_argument("--max-bytes", type=int, default=MAX_BYTES,
                    help="0 => one file per topic; >0 => pack whole topics up to this size.")
    ap.add_argument("--strip-prefix", default=STRIP_PREFIX,
                    help="Prefix removed from source stems when deriving subject tokens/labels.")
    ap.add_argument("--blockquote", default=ADD_BLOCKQUOTE,
                    help="Optional provenance blockquote under each H1 ('{source}'/'{skill}' expand).")
    ap.add_argument("--skill-title", default="",
                    help="Title for a freshly created INDEX.md (default: derived from --out's parent).")
    ap.add_argument("--index-topic-heading", default=INDEX_TOPIC_HEADING,
                    help=f"INDEX '## ' section whose body is replaced (default '{INDEX_TOPIC_HEADING}').")
    ap.add_argument("--clean", action="store_true",
                    help="Apply HTML/entity/cruft cleaning to bodies (default: verbatim).")
    ap.add_argument("--compact-tables", action="store_true",
                    help="With --clean, also re-pad Markdown tables.")
    ap.add_argument("--remap-symbols", help="symbols.json whose reference_files should be remapped after the split.")
    ap.add_argument("--symbols-source-map",
                    help="JSON mapping each symbols.json group key to a SOURCE filename; that group's "
                         "reference_files become the topic files derived from that source (precise mode).")
    ap.add_argument("--replace-inputs", action="store_true",
                    help="Delete the original big source files after writing topics.")
    ap.add_argument("--verify", action="store_true", help="Run coverage/size/consistency checks.")
    args = ap.parse_args(argv)

    if not args.md and not args.legend:
        ap.error("provide --md or --legend")

    SECTION = args.section
    GROUP_CONSECUTIVE = args.group_consecutive
    MAX_BYTES = args.max_bytes
    STRIP_PREFIX = args.strip_prefix
    ADD_BLOCKQUOTE = args.blockquote
    INDEX_TOPIC_HEADING = args.index_topic_heading
    CLEAN = args.clean
    SPLIT_COMPACT_TABLES = args.compact_tables

    specs = _file_specs(args)
    if not specs:
        ap.error("no input files matched")
    out_dir = Path(args.out) if args.out else specs[0]["path"].parent
    skill_title = args.skill_title or _titlecase(out_dir.parent.name)

    topics: list[dict] = []
    source_order: list[str] = []
    group_titles: dict[str, str] = {}
    notes_all: list[tuple[str, str]] = []
    src_blocks_concat: list[str] = []
    processed_sources: list[Path] = []

    for spec in specs:
        path: Path = spec["path"]
        if not path.exists():
            print(f"WARN: source not found, skipping: {path}")
            continue
        h1, blocks, nonsection, _pre = parse_source(
            _read(path), spec["topic_level"], spec["section"])
        token = subject_token(path, spec.get("subject_token", ""))
        label = source_label(path, h1)
        key = str(path)
        source_order.append(key)
        group_titles[key] = label
        notes_all.extend(nonsection)
        grouped = group_topics(blocks, spec["group_consecutive"])
        for title, body in grouped:
            src_blocks_concat.append(body)
            topics.append({"title": title, "body": body, "base": slug(title),
                           "token": token, "src": key, "src_name": path.name,
                           "src_label": label})
        processed_sources.append(path)

    if not topics:
        print("No topics found.")
        return 1

    topics = pack_topics(topics, MAX_BYTES)
    assign_filenames(topics)

    blockquote_for = lambda lab: (ADD_BLOCKQUOTE.replace("{source}", lab).replace("{skill}", skill_title)
                                  if ADD_BLOCKQUOTE else "")
    topics_by_source: "OrderedDict[str, list]" = OrderedDict((s, []) for s in source_order)
    for t in topics:
        write_text(out_dir / t["fname"], render_topic(t["title"], t["body"], blockquote_for(t["src_label"])))
        topics_by_source.setdefault(t["src"], []).append((t["title"], t["fname"]))

    regen_index(out_dir, skill_title, source_order, topics_by_source, group_titles,
                _dedupe_blocks(notes_all), INDEX_TOPIC_HEADING)
    regen_topics(out_dir, topics)

    print(f"split {len(processed_sources)} source file(s) -> {len(topics)} topic file(s) in {out_dir}")

    if args.remap_symbols:
        sp = Path(args.remap_symbols)
        if sp.exists():
            topic_texts = [(t["fname"], _read(out_dir / t["fname"])) for t in topics]
            source_map = None
            files_by_source = None
            if args.symbols_source_map:
                source_map = json.loads(Path(args.symbols_source_map).read_text(encoding="utf-8"))
                files_by_source = {}
                for t in topics:
                    files_by_source.setdefault(t["src_name"], []).append(t["fname"])
            n = remap_symbols(sp, topic_texts, source_map, files_by_source)
            print(f"remapped reference_files in {n} symbols.json group(s)"
                  f" by {'source map' if source_map is not None else 'term presence'}")
        else:
            print(f"WARN: --remap-symbols path not found: {sp}")

    if args.replace_inputs:
        written = {t["fname"] for t in topics}
        for p in processed_sources:
            if p.name not in written and p.parent == out_dir:
                p.unlink()
        print(f"removed {len(processed_sources)} original source file(s)")

    if args.verify:
        print("verify:")
        ok = _split_verify(out_dir, topics, "\\n\\n".join(x for x in src_blocks_concat if x), INDEX_TOPIC_HEADING)
        return 0 if ok else 1
    return 0

def main(argv=None) -> int:
    \"\"\"Standalone entry point for `python -m builder_components.split_cmd`; delegates to cmd_split.\"\"\"
    return cmd_split(argv)


if __name__ == "__main__":
    raise SystemExit(main())
"""

# ===MODULE builder_components.cli===
_SRC['builder_components.cli'] = """
\"\"\"Command dispatch for the skill_builder CLI: the single entry point that fans out to every
subcommand (the build pipeline plus the folded-in validate / policy / recontext-subagent tools).

This module is the top of the dependency graph — it imports every `cmd_*`, so the bundler emits it
last. The same dispatch backs both `python skill_builder.py <cmd>` (the generated all-in-one) and
`python -m builder_components.cli <cmd>` (the source package).\"\"\"

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

_USAGE = \"\"\"skill_builder.py — build documentation skill packages (stdlib only).

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

Run `python skill_builder.py <command> --help` for that command's options.\"\"\"

_INGEST_USAGE = ("usage: python skill_builder.py ingest {html|mdbook|rustdoc|pdf} [options]\\n"
                 "Run `python skill_builder.py ingest <format> --help` for options.")

_INGEST = {"html": cmd_ingest_html, "mdbook": cmd_ingest_mdbook,
           "rustdoc": cmd_ingest_rustdoc, "pdf": cmd_ingest_pdf}
_COMMANDS = {"build": cmd_build, "finalize": cmd_finalize, "split": cmd_split,
             "maintain": cmd_maintain, "index": cmd_index, "lint": cmd_lint,
             "recontext": cmd_recontext, "readme": cmd_readme,
             "validate": cmd_validate, "policy": cmd_policy,
             "recontext-subagent": cmd_recontext_subagent}


def _rebuild(argv) -> int:
    \"\"\"Regenerate (or --check) the all-in-one scripts/skill_builder.py from the source components.

    Convenience wrapper for `python builder_components/_assemble.py`. Works when running from the
    source package (where the `_assemble` submodule is importable from disk); when invoked on the
    GENERATED bundle the source compiler is not present, so we point the caller at the source command.
    \"\"\"
    try:
        from . import _assemble  # type: ignore
    except Exception:
        print("rebuild from source: python builder_components/_assemble.py", file=sys.stderr)
        return 2
    return _assemble.main(argv)


def main(argv=None) -> int:
    \"\"\"Parse argv[0] as the subcommand and dispatch to its handler (returns the process exit code).

    `ingest` takes a second positional selecting the source format; `--rebuild` regenerates the
    all-in-one file; `-h`/`--help`/empty prints the command list. Reads ``sys.argv[1:]`` when ``argv``
    is None.
    \"\"\"
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
            print(f"unknown ingest format: {rest[0]}\\n{_INGEST_USAGE}")
            return 2
        return fn(rest[1:])
    fn = _COMMANDS.get(cmd)
    if not fn:
        print(f"unknown command: {cmd}\\n{_USAGE}")
        return 2
    return fn(rest)


if __name__ == "__main__":
    raise SystemExit(main())
"""

_bootstrap()
from builder_components.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
