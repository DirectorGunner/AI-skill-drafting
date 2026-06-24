#!/usr/bin/env python3
"""skill_builder.py — one generalized, stdlib-only engine for building documentation skill packages.

Subcommands (run `python skill_builder.py <cmd> --help` for each):
  ingest {html|mdbook|rustdoc|pdf}   source docs -> a corpus JSONL of text chunks
  build                              corpus JSONL -> a flat or router reference skill
  finalize                           bring a built skill up to the gold SKILL.md/GOTCHA.md standard
  split                              split oversized reference .md files into one file per topic
  maintain                           in-place gold maintenance: audit / split oversize / cross-link
  index                              build a cross-skill master INDEX.md (+ optional covers: seeding)
  lint                               read-only link/topics health check -> AI/lint/<skill>.md

Deterministic and generalized: every function works for any similar input, named for the operation it
performs; format-specific values (content selectors, boilerplate section ids, chrome labels, the
validator path) are CLI options with sensible defaults, never bespoke literals. Paths are supplied on
the command line. This file is the consolidation of the former ingest_*/htmlmd/build_skill_corpus/
finalize_gold/split_reference_md/maintain_skill/build_master_index/lint_skill scripts into one builder.
"""
from __future__ import annotations
import argparse
import collections
import glob as globmod
import html
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, OrderedDict
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin

#: Validator path used in the SKILL.md Verification command that `finalize` generates. Repo default;
#: override per-run with `finalize --validator`. The only repo-relative literal, and it is a default.
VALIDATOR = ".agents/skills/skill-drafting/scripts/validate_skill_package.py"

#: The shared, path-agnostic recontextualization engine (sibling module, ships with the skill). Used
#: by the `recontext` command group below; the same module backs the locked `recontext_subagent.py`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recontext_core as recon  # noqa: E402 (intentional: resolve sibling module before use)


def _find_repo_root(start) -> Path:
    """The VS Code project root that owns `start`: the immediate child of $DEVROOT containing it
    (%DEVROOT%\\<project>), else the nearest enclosing repo/workspace that is NOT a per-skill package.
    Every skills/<name>/ is its own git repo (its root has SKILL.md), so resolving to the nearest .git
    would wrongly land inside a skill; this climbs past skills to the owning project. Keeps default
    AI/lint and AI/work scratch at the project root, never inside a skill, regardless of CWD."""
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
    """Default AI/ scratch path under the owning project root; refuses to land inside a skill package."""
    root = _find_repo_root(start)
    if (root / "SKILL.md").is_file():  # guard: fail loudly rather than pollute a skill
        raise SystemExit(f"refusing to write {'/'.join(parts)} inside a skill package: {root}")
    return root.joinpath(*parts)


# ==============================================================================
# SHARED — HTML -> Markdown (was htmlmd.py)
# ==============================================================================

_SKIP = {"script", "style", "head", "nav", "header", "footer", "aside", "noscript", "svg", "button", "form"}
_BLOCK = {"p", "div", "section", "article", "ul", "ol", "li", "pre", "blockquote", "table",
          "tr", "thead", "tbody", "h1", "h2", "h3", "h4", "h5", "h6", "hr"}


class _MD(HTMLParser):
    def __init__(self, base_url: str = ""):
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
        if self.cell is not None:
            self.cell.append(s)
        elif self.link_text and self.href is not None:
            self.link_text.append(s)
        else:
            self.out.append(s)

    def _nl(self, n=1):
        if self.cell is None and not (self.link_text and self.href is not None):
            self.out.append("\n" * n)

    # ---- tags ----
    def handle_starttag(self, tag, attrs):
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
            self._emit("  \n")
        elif tag == "hr":
            self._nl(2); self._emit("---"); self._nl(2)
        elif tag == "pre":
            if not self.pre_lang and "rust" in a.get("class", ""):
                self.pre_lang = "rust"   # rustdoc: <pre class="rust item-decl">
            self.pre_depth += 1
            self._nl(2); self._emit("```" + self.pre_lang); self._nl(1)
        elif tag == "code":
            cls = a.get("class", "")
            m = re.search(r"language-([\w+-]+)", cls) or re.search(r"\b(rust|python|bash|sh|json|toml|c|cpp|js|ts|html)\b", cls)
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
            m = re.search(r"highlight-(\w+)", cls)
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
            cap = alt or re.sub(r"[-_]+", " ", re.sub(r"\.[a-z0-9]+$", "", src.rsplit("/", 1)[-1], flags=re.I))
            self._emit(f"(Figure: {cap})")

    def handle_endtag(self, tag):
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
        if self.skip_depth:
            return
        if self.pre_depth:
            self._emit(data)
            return
        text = data
        if self._cur_h is not None:
            self._cur_h[1].append(text)
        # collapse whitespace outside code/pre
        collapsed = re.sub(r"\s+", " ", text)
        if collapsed:
            self._emit(collapsed)

    def _flush_table(self):
        rows = [r for r in self.table_rows if r]
        if not rows:
            return
        self.out.append("\n")
        ncols = max(len(r) for r in rows)
        head = rows[0] + [""] * (ncols - len(rows[0]))
        self.out.append("| " + " | ".join(head) + " |\n")
        self.out.append("| " + " | ".join(["---"] * ncols) + " |\n")
        for r in rows[1:]:
            r = r + [""] * (ncols - len(r))
            self.out.append("| " + " | ".join(r) + " |\n")
        self.out.append("\n")


def _balanced_div_inner(html: str, open_match: "re.Match") -> str:
    """Given a match for an opening <div ...>, return its inner HTML up to the matching </div>
    (depth-balanced — handles the nested divs that a non-greedy regex would stop short on)."""
    start = open_match.end()
    depth = 1
    for m in re.finditer(r"<div\b|</div\s*>", html[start:], re.IGNORECASE):
        if m.group(0)[1] == "/":
            depth -= 1
            if depth == 0:
                return html[start:start + m.start()]
        else:
            depth += 1
    return html[start:]


def split_main(html: str) -> str:
    """Return the inner HTML of the doc body. Tries, in order: a div with role="main" (Sphinx),
    <main>, <div id="content">, <body>, else the whole document."""
    m = re.search(r'<div\b[^>]*\brole=["\']main["\'][^>]*>', html, re.IGNORECASE)
    if m:
        return _balanced_div_inner(html, m)
    for pat in (r"<main\b[^>]*>(.*?)</main>", r'<div[^>]*id="content"[^>]*>(.*?)</div>\s*</div>'):
        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1)
    m = re.search(r"<body\b[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else html


def html_to_md(html: str, base_url: str = "") -> tuple[str, list]:
    """Convert HTML to Markdown. Returns (markdown, headings) where headings is a list of
    (level, text, id). Pass the doc body (use split_main first for full pages)."""
    p = _MD(base_url)
    p.feed(html)
    md = "".join(p.out)
    md = unescape(md)
    md = md.replace("​", "")                  # strip zero-width-space anchor artifacts
    md = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]*$", "", md)  # drop headings left empty after that
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n", p.headings

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
    """Read a normalized field from a raw record using FIELD_MAP (falls back to the key)."""
    return rec.get(FIELD_MAP.get(key, key), rec.get(key))


def load_records(globs: list[str]) -> list[dict]:
    """Load + merge JSONL records from one or more globs into normalized dicts.

    Each output dict has: id, text, source_url, tags (list), title (str), symbols (list).
    Records sharing an id across files are MERGED (first non-empty value per field wins),
    so you can keep prose in one file and metadata in another and pass both globs.

    EDIT THIS only if your corpus isn't JSONL-one-record-per-line; otherwise just point
    --records at your files and set FIELD_MAP above.
    """
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
    """Sub-skill key for ROUTER mode, or "" for a single flat skill.

    Reads the ingester-provided `subskill` field; absent => "" => one flat skill (the common case).
    To key off something else (e.g. a tag), edit this hook:
        tags = rec.get("tags") or []; return str(tags[0]) if tags else "general"
    """
    return str(rec.get("subskill") or "")


def section_of(rec: dict) -> str:
    """SECTION (category) key used to group reference files within a skill.

    Prefers the ingester-provided `section` field; else the first tag; else "reference".
    Sections become INDEX.md / task-router headings (and the filename prefix when SECTION_PREFIX).
    """
    tags = rec.get("tags") or []
    return str(rec.get("section") or (tags[0] if tags else "reference"))


#: Per-sub-skill metadata for ROUTER mode: {subskill_key: {"title","purpose","triggers"}}.
#: Leave empty for a flat skill. `purpose`/`triggers` feed the generated SKILL.md prose.
SUBSKILL_META: dict[str, dict] = {}


def subskill_meta(key: str) -> dict:
    """Title/purpose/triggers for a sub-skill, with readable fallbacks if unspecified."""
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
    """Human-readable label for a section, used in INDEX/router headings."""
    return (SECTION_LABEL_OVERRIDES.get((subskill, section))
            or SECTION_LABELS.get(section)
            or section.replace("-", " ").replace("_", " ").strip().title())


def hierarchical_path(source_url: str, section: str) -> list[str]:
    """Turn a chunk's source_url into a list of path segments used to GROUP/pack files.

    The packer walks this hierarchy: pages that share a prefix get grouped into one file
    when small, and big nodes are split deeper. So a good path = the source's own folder
    structure (e.g. category/subcategory/page).

    Default: decode %xx, drop the scheme+host, strip a known doc-root marker if present,
    drop file extensions, and drop a trailing 'index'. Customize the markers/logic for
    your source layout. Returning [] falls back to a single bucket.
    """
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
        s = re.sub(r"\.d\.ts$", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\.(md|html?|ts|tsx|jsx|json|rst|txt)$", "", s, flags=re.IGNORECASE)
        segs.append(s)
    while len(segs) > 1 and segs[-1].lower() in ("index", "readme"):
        segs = segs[:-1]
    return segs or ["page"]


def is_cruft(source_url: str) -> bool:
    """Return True to EXCLUDE a chunk as non-documentation crawl noise.

    Default excludes nothing. Customize for your corpus, e.g.:
        rel = source_url.lower()
        if "node_modules" in rel:
            return True
        base = re.sub(r"\\.[a-z0-9.]+$", "", rel.rsplit("/", 1)[-1])
        return base in {"config", "404", "sidenav"}
    """
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
    """Stateful split of a single-page dump into (object_name, record) pairs.

    Walks records in order; a chunk whose cleaned title is a SECTION_WORDS fragment belongs
    to the current object, anything else starts a new object. Only used for sections listed
    in OBJECT_DUMP_SECTIONS. Customize the heuristic if your dump titles differ.
    """
    pairs = []
    current = "Overview"
    for r in records:
        title = clean_title(r.get("title") or "")
        norm = re.sub(r"[^a-z0-9]", "", title.lower())
        is_section = norm in SECTION_WORDS or norm.startswith(
            ("example", "method", "propert", "attribute", "parameter", "return", "constant", "event", "syntax"))
        if not is_section and title:
            current = re.sub(r"\s+object$", "", obj_token(r.get("title") or ""), flags=re.IGNORECASE).strip() or current
        pairs.append((current, r))
    return pairs


# =============================================================================
# ENGINE  --  deterministic; generally no need to edit below this line.
# =============================================================================

# ---- text cleaning -----------------------------------------------------------

_BR = re.compile(r"</?br\s*/?>", re.IGNORECASE)
_BOLD = re.compile(r"</?(?:b|strong)\s*>", re.IGNORECASE)
_ITAL = re.compile(r"</?(?:i|em)\s*>", re.IGNORECASE)
_HTMLTAG = re.compile(
    r"</?(?:div|span|p|u|small|sub|sup|td|tr|th|thead|tbody|tfoot|table|caption|col|colgroup|"
    r"ul|ol|li|dl|dt|dd|a|img|script|style|h[1-6]|pre|code|hr|nav|section|article|header|footer|"
    r"aside|main|figure|figcaption|blockquote|button|svg|path|iframe|noscript|center|font)\b[^>]*>",
    re.IGNORECASE,
)
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_TRAILING_NUM = re.compile(r"\s*\(\d+\)\s*$")
_SEP_SPLIT = re.compile(r"\s+[–—−-]\s+")
_EMPTY_TABLE = re.compile(r"^\s*\|[\s|]*\|\s*$")
_NAV = re.compile(r"^\s*(View more View less|More like this|Was this page helpful\??|On this page|"
                  r"Table of contents|Back to top|Print this page)\s*$", re.IGNORECASE)
_MD_COMMENT = re.compile(r"^\s*\[//\]: #")
#: A *clean* code-fence delimiter: 3+ backticks or tildes plus an optional language token and
#: nothing else. Lines like a `~~~~^^^^` Python-traceback caret (literal content inside a fence)
#: must NOT toggle fence state, or every block after them desyncs.
_FENCE = re.compile(r"^(?:`{3,}|~{3,})[\w+.\-]*$")


def _is_fence(stripped: str) -> bool:
    """True only for a clean opening/closing code-fence delimiter line (see _FENCE)."""
    return bool(_FENCE.match(stripped))


def _strip_emphasis(t: str) -> str:
    """Drop Markdown bold markers and HTML entities from a short string (e.g. a title)."""
    t = html.unescape(t or "")
    t = _MD_BOLD.sub(r"\1", t)
    return t.replace("**", "").strip()


def clean_title(title: str) -> str:
    """Normalize a chunk title for use as a heading: unescape, drop ' (n)', stray <br>, bold."""
    t = html.unescape(title or "").replace("​", "").replace("\\<", "<").replace("\\>", ">")
    t = re.sub(r"</?br\s*/?>", "", t, flags=re.IGNORECASE)
    return _strip_emphasis(_TRAILING_NUM.sub("", t))


def obj_token(title: str) -> str:
    """Extract the trailing object/topic token from a separator-delimited title.

    'Foo APIs - Bar (2)' -> 'Bar'. Used by object_of and for object-dump file naming.
    """
    t = _TRAILING_NUM.sub("", html.unescape(title or ""))
    parts = _SEP_SPLIT.split(t)
    return _strip_emphasis(parts[-1] if parts else t)


def _strip_html_segment(segment: str) -> str:
    """Convert/strip HTML in a non-code prose segment, leaving XML/code-like tokens alone."""
    segment = segment.replace("\\<", "<").replace("\\>", ">")
    segment = _BR.sub("\n", segment)
    segment = _BOLD.sub("**", segment)
    segment = _ITAL.sub("*", segment)
    return _HTMLTAG.sub("", segment)


def _normalize_prose_line(line: str) -> str:
    """Apply HTML normalization to the parts of a line that are OUTSIDE inline `code` spans."""
    parts = line.split("`")
    for i in range(0, len(parts), 2):
        parts[i] = _strip_html_segment(parts[i])
    return "`".join(parts)


def clean_body(text: str) -> str:
    """Decode entities, drop HTML comments, normalize stray HTML to Markdown, and demote
    in-body headings to level >= 3 — all OUTSIDE fenced code blocks (code is left verbatim)."""
    text = html.unescape(text or "")
    if STRIP_HTML_COMMENTS:
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
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
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def strip_cruft(text: str) -> str:
    """Remove empty Markdown table rows, common nav phrases, and `[//]: #` comments (outside fences)."""
    out = []
    in_fence = False
    for line in text.split("\n"):
        s = line.lstrip()
        if _is_fence(s):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and (_EMPTY_TABLE.match(line) or _NAV.match(line) or _MD_COMMENT.match(line)):
            continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def body_of(chunk: dict) -> str:
    """Full per-chunk prose cleanup: clean_body + strip_cruft."""
    return strip_cruft(clean_body(chunk.get("text", "")))


# ---- link / image resolution -------------------------------------------------

_IMG_RE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")


def _humanize(name: str) -> str:
    """Turn a file/anchor stem into a short human description ('address-output' -> 'address output')."""
    stem = re.sub(r"\.[a-z0-9]+$", "", name, flags=re.IGNORECASE)
    return re.sub(r"[-_%0-9]+", " ", stem).strip() or "image"


def resolve_refs(text: str, source_url: str, linkmap: dict) -> str:
    """Resolve relative links/images against the source page's URL (outside code fences).

    Images become a descriptive labeled link to the online source image. Links to a page
    that exists IN the skill are rewritten to the local file; everything else points at the
    resolved online source. Anchors resolve to the source page's section. External links
    are left untouched. Pass a balanced-fence text block (e.g. a whole source page) so
    fence tracking is correct.
    """
    def img_repl(m):
        alt, src = m.group(1).strip(), m.group(2).strip()
        desc = alt or _humanize(unquote(src.split("/")[-1]))
        if src.startswith(("http://", "https://")):
            return f"[Figure: {desc}]({src})"
        if source_url and "<" not in src and ">" not in src and " " not in src:
            return f"[Figure: {desc}]({urljoin(source_url, src)})"
        return f"Figure: {desc}"  # unresolvable/placeholder src -> description only, no broken link

    def link_repl(m):
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
    for line in text.split("\n"):
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
    return "\n".join(out)


# ---- table compaction & identifier backticking -------------------------------

_PIPE = re.compile(r"(?<!\\)\|")
_SEP = re.compile(r"^\s*\|?[\s:|-]*-{1,}[\s:|-]*\|?\s*$")
_IDENT = re.compile(r"(\*\*)?((?:[A-Z][A-Z0-9]*)(?:\\?_[A-Z0-9]+)+)(\*\*)?")


def _cells(rowtext: str) -> list[str]:
    parts = _PIPE.split(rowtext)
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [c.strip() for c in parts]


def compact_tables(text: str) -> str:
    """Re-emit Markdown tables with single-space padding; join multi-line cells inline.

    Reclaims column-alignment padding and repairs tables whose cells span multiple source
    lines (which break GFM parsing). Code fences are left untouched.
    """
    lines = text.split("\n")
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
    return "\n".join(out)


def backtick_identifiers(text: str) -> str:
    """Wrap bare ALL_CAPS_UNDERSCORE identifiers in backticks and unescape their underscores
    (e.g. **FOO\\_BAR** -> `FOO_BAR`), outside code fences and inline code spans."""
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
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
            parts[k] = _IDENT.sub(lambda m: "`" + m.group(2).replace("\\_", "_") + "`", parts[k])
        out.append("`".join(parts))
    return "\n".join(out)


# ---- leaves, packing, naming -------------------------------------------------

def slug(s: str) -> str:
    """Filesystem-safe kebab slug."""
    s = re.sub(r"\.(md|html?)$", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return re.sub(r"-{2,}", "-", s) or "page"


def _titlecase(seg: str) -> str:
    return seg.replace("-", " ").replace("_", " ").strip().title()


def build_leaves(records: list[dict], section: str) -> list[dict]:
    """A LEAF is an atomic unit never split across files: one source page, or — for an
    OBJECT_DUMP_SECTIONS section — one parsed object. Returns leaf dicts with path/title/chunks/bytes."""
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
    """Size-balanced partition: group leaves sharing a path prefix into <=TARGET_BYTES files,
    descending the hierarchy where a node is too big, merging small siblings together."""
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
    """Longest shared leading path among a file's leaves (used for naming/titles)."""
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
    """Split one oversized chunk's body into <=TARGET_BYTES pieces at heading or blank-line
    boundaries, never inside a fenced code block."""
    blocks: list[list[str]] = []
    cur: list[str] = []
    fence = False
    for line in text.split("\n"):
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
        bt = "\n".join(block)
        bs = len(bt.encode("utf-8"))
        if buf and bb + bs > TARGET_BYTES:
            pieces.append("\n".join(buf)); buf = []; bb = 0
        buf.append(bt); bb += bs
    if buf:
        pieces.append("\n".join(buf))
    return pieces


def split_oversize(leaf: dict) -> list[list[dict]]:
    """Split one oversized page/object leaf into consecutive <=TARGET_BYTES chunk-runs;
    a single chunk that alone exceeds the target is exploded at its heading boundaries."""
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
    """Pick a unique kebab filename (prefixed by the section) and a human display title
    derived from the distinguishing subtopics this file covers."""
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
        return _titlecase(re.sub(r"^\d{2,}-", "", seg) if STRIP_ORDER_PREFIX else seg)
    if nexts:
        disp = ", ".join(_disp(x) for x in nexts[:4]) + (" ..." if len(nexts) > 4 else "")
    else:
        disp = _disp(base)
    return name + ".md", disp


def disambiguate_titles(plans: list[dict]) -> None:
    """Prefix the first genuinely-differing path segment (or the section) to any H1 title
    that collides within a skill, so every file's title is distinct."""
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


# ---- rendering ---------------------------------------------------------------

def render_file(skill_title: str, file_leaves: list[dict], title: str, linkmap: dict) -> str:
    """Render one reference file: H1 + attribution + (Overview for multi-topic files) + per-leaf
    sections. Link/image resolution runs per-leaf (a whole page) so fences stay balanced."""
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
                ct = re.sub(r"^" + re.escape(leaf["title"]) + r"\s*[—–:-]\s*", "", ct) or ct
            if ct and ct != leaf["title"] and ct != last:
                block += [f"{level} {ct}", ""]
                last = ct
            b = body_of(chunk)
            if b:
                block += [b, ""]
        text = "\n".join(block)
        lines.append(resolve_refs(text, src, linkmap) if RESOLVE_REFS else text)
    text = "\n".join(lines)
    if COMPACT_TABLES:
        text = compact_tables(text)
    if BACKTICK_IDENTIFIERS:
        text = backtick_identifiers(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_index(refs: Path, subskill: str, skill_title: str, fm: list) -> None:
    """Write references/INDEX.md: a per-section table of every file with a one-line summary."""
    lines = [f"# {skill_title} References — Index", "",
             "Each file is one focused, original-prose reference (identifiers preserved verbatim). "
             "Open only what the SKILL.md router points to.", ""]
    for sec in sorted({f[0] for f in fm}):
        lines += [f"## {section_label(subskill, sec)}", "", "| File | Covers |", "| --- | --- |"]
        for s, fname, disp, _, _ in fm:
            if s == sec:
                lines.append(f"| [{fname}]({fname}) | {disp} |")
        lines.append("")
    write_text(refs / "INDEX.md", "\n".join(lines).rstrip() + "\n")


def write_topics(refs: Path, subskill: str, fm: list) -> None:
    """Write references/topics.json (machine-readable topic -> file + keywords)."""
    topics = [{"topic": disp, "file": f"references/{fname}",
               "summary": f"{section_label(subskill, s)}: {disp}.",
               "keywords": [slug(disp), s]} for (s, fname, disp, _, _) in fm]
    write_text(refs / "topics.json", json.dumps({"schema_version": 1, "topics": topics}, ensure_ascii=False, indent=2) + "\n")


def write_leaf_skill(skill_dir: Path, name: str, title: str, purpose: str, triggers: str, subskill: str, fm: list) -> None:
    """Write a (sub)skill SKILL.md: frontmatter + workflow + a section-grouped task router."""
    by_s: dict[str, list] = {}
    for (s, fname, disp, _, _) in fm:
        by_s.setdefault(s, []).append((disp, fname))
    parts = []
    for s in sorted(by_s):
        parts += [f"### {section_label(subskill, s)}", "", "| Topic | Read |", "| --- | --- |"]
        parts += [f"| {disp} | references/{fname} |" for disp, fname in by_s[s]]
        parts.append("")
    router = "\n".join(parts).strip()
    md = f"""---
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
"""
    write_text(skill_dir / "SKILL.md", md)


def write_router(out: Path, name: str, title: str, description: str, subskills: list[tuple]) -> None:
    """Write the top-level router SKILL.md for a multi-sub-skill build."""
    rows = "\n".join(f"| {subskill_meta(k)['title']} | {subskill_meta(k)['purpose']} | `{k}/SKILL.md` |"
                     for k, _ in subskills)
    md = f"""---
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
"""
    write_text(out / "SKILL.md", md)


# ---- build orchestration -----------------------------------------------------

def _build_one(skill_dir: Path, subskill: str, skill_title: str, records: list[dict]) -> list:
    """Build one skill's references/ + INDEX + topics from its records. Returns files_meta."""
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
    """Build the whole skill (flat or router) under `out`. Returns a report dict."""
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
    """Optional whitespace normalization with prettier, then re-compact tables / re-backtick
    identifiers (prettier re-pads tables, so the deterministic passes run last). Skipped cleanly
    if prettier is unavailable."""
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
            f.write_text(t2, encoding="utf-8", newline="\n")


def verify(out: Path) -> bool:
    """Self-check the built skill: report file count, size distribution, residual raw image
    embeds / broken-looking relative links, and prose HTML. Returns True if clean enough."""
    md_files = [f for f in out.rglob("*.md") if f.name != "INDEX.md" and f.name != "SKILL.md"]
    sizes = sorted(f.stat().st_size / 1024 for f in md_files)
    raw_img = raw_relpath = prose_html = 0
    htmltag = re.compile(r"</?(?:div|span|br|b|strong|td|tr|li|ul|table|script|style|p|h[1-6])\b", re.IGNORECASE)
    for f in md_files:
        in_fence = False
        for line in f.read_text(encoding="utf-8").split("\n"):
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
    """True if p itself is a Windows junction/symlink (reparse point) — checked WITHOUT resolving, so a
    per-skill junction (.agents/skills/<s> or .claude/skills/<s> -> the store) is detected before any copy."""
    try:
        import os, stat
        return bool(os.lstat(str(p)).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return p.is_symlink()


def cmd_build(argv=None) -> int:
    global TARGET_BYTES, RUN_PRETTIER, RESOLVE_REFS, COMPACT_TABLES, BACKTICK_IDENTIFIERS, \
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

# ==============================================================================
# INGEST — source docs -> corpus JSONL (was ingest_*.py)
# ==============================================================================

def _ingest_slug(s: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-") or "page"


def _balanced_section(html_text: str, open_match, tag: str) -> str:
    """Inner HTML of an opening <tag ...> up to its depth-matched </tag>."""
    start = open_match.end()
    depth = 1
    for m in re.finditer(rf"<{tag}\b|</{tag}\s*>", html_text[start:], re.IGNORECASE):
        if m.group(0)[1] == "/":
            depth -= 1
            if depth == 0:
                return html_text[start:start + m.start()]
        else:
            depth += 1
    return html_text[start:]


def extract_content_section(html_text, content_id="main-content",
                            drop_section_ids=("synthetic-implementations", "blanket-implementations")):
    """Return a generator-rendered page's documentation body: the balanced
    <section id="{content_id}"> (falling back to <main>), minus any boilerplate
    sections whose <h2 id> is in drop_section_ids. Defaults reproduce rustdoc; point
    content_id / drop_section_ids at any similarly structured generator output."""
    m = re.search(r'<section[^>]*id="%s"[^>]*>' % content_id, html_text, re.IGNORECASE)
    if m:
        body = _balanced_section(html_text, m, "section")
    else:
        m2 = re.search(r"<main\b[^>]*>", html_text, re.IGNORECASE)
        body = _balanced_section(html_text, m2, "main") if m2 else html_text
    cut = len(body)
    for sid in drop_section_ids:
        mm = re.search(r'<h2[^>]*id="%s"' % sid, body, re.IGNORECASE)
        if mm:
            cut = min(cut, mm.start())
    return body[:cut]


def cmd_ingest_html(argv=None) -> int:
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
        parts = line.split("\t")
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
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    kb = sum(len(r["text"].encode("utf-8")) for r in recs) / 1024
    print(f"{args.skill}: {len(recs)} page-chunks, {kb:.0f} KB total -> {out}")
    return 0


def cmd_ingest_mdbook(argv=None) -> int:
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
    for ln in md.split("\n"):
        st = ln.lstrip()
        if st.startswith("```") or st.startswith("~~~"):
            in_fence = not in_fence
            if cur_title is not None:
                cur.append(ln)
            continue
        m = None if in_fence else re.match(r"^# (.+)$", ln)   # h1 only ("## " won't match)
        if m:
            if cur_title is not None:
                chunks.append((cur_title, "\n".join(cur).strip()))
            cur_title, cur = m.group(1).strip(), []
        elif cur_title is not None:
            cur.append(ln)
    if cur_title is not None:
        chunks.append((cur_title, "\n".join(cur).strip()))

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
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    total = sum(len(r["text"].encode("utf-8")) for r in recs)
    print(f"{args.skill}: {len(recs)} page-chunks, {total/1024:.0f} KB total -> {out}")
    return 0

def cmd_ingest_rustdoc(argv=None) -> int:
    """Turn crawled generator-rendered API pages (e.g. rustdoc) into a corpus JSONL.

    Each item renders as its own HTML page; the doc body is the balanced
    <section id=--content-id> minus the auto-generated boilerplate sections in
    --drop-section-id. --strip-label drops a chrome label line. Defaults reproduce
    rustdoc; override them for any similarly structured generator. Manifest lines:
    localfile <TAB> url."""
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
        parts = line.split("\t")
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
            md = re.sub(r"[ \t]*" + re.escape(label) + r"[ \t]*\n?", "\n", md)
        if not md.strip():
            continue
        title = next((t for lvl, t, _ in heads if lvl <= 1 and t.strip()), "")
        if not title:
            title = _ingest_slug(url.rstrip("/").rsplit("/", 1)[-1]).replace("-", " ")
        recs.append({"chunk_id": f"{args.skill}-{i:05d}", "title": title.strip(),
                     "source_url": url, "text": md, "tags": []})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    kb = sum(len(r["text"].encode("utf-8")) for r in recs) / 1024
    print(f"{args.skill}: {len(recs)} pages ({missing} missing), {kb:.0f} KB total -> {out}")
    return 0


def run(cmd) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout


def qpdf_outline(pdf: str):
    data = json.loads(run(["qpdf", "--json", "--json-key=outlines", pdf]) or "{}")
    return data.get("outlines", [])


def npages(pdf: str) -> int:
    return int((run(["qpdf", "--show-npages", pdf]) or "0").strip() or 0)


def pdf_pages(pdf: str, layout: bool):
    cmd = ["pdftotext", "-q", "-enc", "UTF-8"] + (["-layout"] if layout else []) + [pdf, "-"]
    return run(cmd).split("\f")


def flatten(nodes, depth=0, acc=None):
    if acc is None:
        acc = []
    for nd in nodes:
        acc.append({"title": (nd.get("title") or "").strip(),
                    "page": nd.get("destpageposfrom1"), "depth": depth})
        flatten(nd.get("kids") or [], depth + 1, acc)
    return acc


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _pdf_slug(s: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-") or "section"


#: Bullet glyphs poppler emits for the manual's list markers (incl. the U+0082 PUA-mapped dot).
_BUL = "•‣▪●⁃∙·◦⁌․"
_PAGENUM = re.compile(r"\d{1,4}")
_CHAPNUM = re.compile(r"Chapter\s+\d+", re.IGNORECASE)        # per-chapter running label
_REFFOOT = re.compile(r"\|\s*Chapter\s+\d+", re.IGNORECASE)   # reference footer "Part | Chapter N  Title"
_LEADER = re.compile(r"\.{5,}|�{3,}")        # printed-TOC dot/glyph leaders
_TOC_HEADS = {"contents", "in this chapter", "table of contents"}
_HEAD_OK = re.compile(r"^[A-Z0-9(\"'].*$")


_CAPS = re.compile(r"[A-Z0-9 &/.\-]+")


def detect_boilerplate(pages):
    """Return (caps_headers, footer_prefixes). The running header is an ALL-CAPS part name that
    recurs in the page EDGE zone (top-2 / bottom-3 non-blank lines) — its position flips between
    top and bottom in pdftotext reading order, so we count it wherever it lands in the edge, which
    catches every part (FAIRLIGHT, DELIVER, CLOUD, ...) while ignoring mid-page UI labels. The
    footer is the recurring 4-word prefix of the last non-page-number line."""
    caps, foot4 = Counter(), Counter()
    for pg in pages:
        nb = [l for l in pg.split("\n") if l.strip()]
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
    """Drop running header (all-caps part name, any edge position), footer (by prefix or
    '| Chapter N'), page numbers, per-chapter mini-TOC, and printed-TOC leader lines."""
    lines = pg.split("\n")
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
    return "\n".join(out)


def _is_heuristic_heading(s):
    """A short, label-like line (section title not in the outline) — used only when it follows a break."""
    if not (2 <= len(s) <= 55) or s[-1] in ".,:;)":
        return False
    if not _HEAD_OK.match(s) or len(s.split()) > 8:
        return False
    return True


def build_chapter(text, heading_keys, chapter_title):
    """text = cleaned, page-joined chapter text. Classify lines into headings / bullets / prose,
    promoting outline titles (by depth) and conservative in-text labels, then reflow prose runs.
    A heuristic heading is a short, label-like line that (a) follows a break or a finished sentence
    and (b) is followed by a capitalized line/bullet — which separates real section titles from
    mid-paragraph line wraps."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)              # de-hyphenate wrapped words
    text = re.sub(r"\s*[%s]\s*" % re.escape(_BUL), "\n• ", text)  # split mid-line bullets
    lines = [l.strip() for l in text.split("\n")]
    n = len(lines)
    out, pbuf, lbuf = [], [], []
    prev_break, last_end = True, ""
    seen_h, ct = set(), norm(chapter_title)

    def flush_p():
        if pbuf:
            out.append(" ".join(pbuf)); pbuf.clear()

    def flush_l():
        if lbuf:
            out.append("\n".join(lbuf)); lbuf.clear()

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
    body = "\n\n".join(b for b in out if b.strip())
    return f"# {chapter_title}\n\n{body}".strip() + "\n"


def cmd_ingest_pdf(argv=None) -> int:
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
        text = "\n".join(clean_page(pg, caps_headers, footers) for pg in pages[start - 1:end])
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
    with out.open(mode, encoding="utf-8", newline="\n") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    kb = sum(len(r["text"].encode("utf-8")) for r in recs) / 1024
    print(f"{args.skill}: {len(recs)} chapters from {Path(args.pdf).name} "
          f"({total_pages}p, {len(caps_headers)} hdr + {len(footers)} ftr boilerplate), {kb:.0f} KB -> {out} ({mode})")
    return 0

# ==============================================================================
# FINALIZE — gold SKILL.md + GOTCHA.md (was finalize_gold.py)
# ==============================================================================

REF = "Recurring failure modes and what to do instead live in the sibling [GOTCHA.md](GOTCHA.md)."

DEFAULT_GOTCHAS = [
    "These reference files are reproduced verbatim from the upstream documentation and split into "
    "focused topics; a file may cover several adjacent subjects — use `references/INDEX.md` or "
    "`rg -n \"PATTERN\" references/*.md` to locate the exact one.",
    "The docs track a specific version; verify version-sensitive APIs, flags, and defaults against the "
    "actual toolchain/build in use before relying on them.",
    "Treat every identifier (API/type/function name, flag, path, enum value, number) as an exact "
    "reference fact — do not invent or paraphrase.",
]


def write(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def ref_count(skill_dir: Path) -> int:
    refs = skill_dir / "references"
    return len([p for p in refs.glob("*.md") if p.name != "INDEX.md"]) if refs.is_dir() else 0


def gotcha_md(title: str, gotchas: list) -> str:
    lead = (f"Recurring failure modes when relying on the {title} reference, and what to do instead. "
            f"Read alongside `SKILL.md`.")
    body = "\n".join(f"- {g}" for g in (gotchas or DEFAULT_GOTCHAS))
    return f"# {title} — Gotchas\n\n{lead}\n\n{body}\n"


def source_note(meta: dict) -> str:
    if not meta.get("source_url"):
        return ""
    verb = ("Reproduced verbatim from the upstream documentation for local reference; prose is the "
            "source's own. " if meta.get("verbatim") else "")
    return (f"\n## Source\n\n{verb}Upstream: {meta['source_url']}\n")


def leaf_skill_md(meta: dict, skill_dir: Path, *, validate_path: str) -> str:
    title, n = meta["title"], ref_count(skill_dir)
    when = meta.get("when_to_use") or meta.get("description", "")
    return f"""---
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
python {VALIDATOR} {validate_path}
```
"""


def router_skill_md(meta: dict, skill_dir: Path, *, validate_path: str) -> str:
    title = meta["title"]
    subs = meta.get("subskills", {})
    rows = "\n".join(
        f"| {subs.get(k, {}).get('title', k)} | {subs.get(k, {}).get('when_to_use', subs.get(k, {}).get('description', k))} | `{k}/SKILL.md` |"
        for k in sub_dirs(skill_dir))
    return f"""---
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
python {VALIDATOR} --package {validate_path}
```
"""


def sub_dirs(skill_dir: Path) -> list:
    return sorted(d.name for d in skill_dir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())


def cmd_finalize(argv=None) -> int:
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

# ==============================================================================
# SPLIT — split oversized references by topic (was split_reference_md.py)
# ==============================================================================

# --- share the proven helpers from the sibling builder (no duplication) -------


# =============================================================================
# CONFIGURATION  (CLI flags override these; a --legend overrides per file)
# =============================================================================

TOPIC_LEVEL = 3
"""Heading level whose blocks are topics. 3 => split on `### `."""

SECTION = "Entries"
"""Name of the `## ` section whose sub-headings are the topics. Empty string =>
treat the whole file (everything after the `# H1`) as the topic source."""

GROUP_CONSECUTIVE = True
"""Merge consecutive blocks that share a normalized title into one topic."""

MAX_BYTES = 0
"""0 => one file per topic. >0 => pack whole topics (never splitting one) into
files up to this many UTF-8 bytes."""

STRIP_PREFIX = ""
"""Prefix removed from a source filename stem before deriving its subject token
and label when no explicit token is supplied (e.g. "myproj-")."""

ADD_BLOCKQUOTE = ""
"""Optional one-line provenance blockquote placed under each topic's H1.
`{source}` expands to the source group title, `{skill}` to --skill-title.
Empty => no blockquote (the most faithful option)."""

INDEX_TOPIC_HEADING = "Topic Files"
"""The `## ` heading in INDEX.md whose body is replaced with the file listing.
Every other INDEX section is preserved. If absent, the listing is inserted
right after the index preamble."""

CLEAN = False
"""Apply build_skill_corpus's cleaning passes (HTML/entity normalization,
heading demotion inside bodies, cruft removal) to each topic body. Off by
default so already-clean prose is copied verbatim and `--verify` is exact."""

SPLIT_COMPACT_TABLES = False
"""When --clean is on, also re-pad/repair Markdown tables in topic bodies."""


# =============================================================================
# DERIVED-VALUE HOOKS  (edit if a corpus needs different label/token logic)
# =============================================================================

def subject_token(source: Path, explicit: str = "") -> str:
    """Short kebab token identifying a source file, used to disambiguate topic
    filenames that collide across sources. Uses the legend's `subject_token`
    when given, else slugs the filename stem (minus STRIP_PREFIX)."""
    if explicit:
        return slug(explicit)
    stem = source.stem
    if STRIP_PREFIX and stem.startswith(STRIP_PREFIX):
        stem = stem[len(STRIP_PREFIX):]
    return slug(stem)


def source_label(source: Path, h1: str) -> str:
    """Human label for a source file's group in INDEX.md: its `# H1` if present,
    else a title-cased token."""
    return h1.strip() if h1.strip() else _titlecase(subject_token(source))


def normalize_topic_title(raw: str) -> str:
    """Normalize a topic heading for grouping/titles (drop trailing ' (n)',
    HTML, bold)."""
    return clean_title(raw) or raw.strip()


# =============================================================================
# ENGINE
# =============================================================================

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_source(text: str, topic_level: int, section: str):
    """Return (h1, topic_blocks, nonsection_blocks, section_preamble).

    topic_blocks: list of (raw_title, body) in document order.
    nonsection_blocks: list of (heading, body) for `## ` sections that are NOT
    the topic section (boilerplate to fold into INDEX).
    """
    lines = text.split("\n")
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
                nonsection.append((head, "\n".join(body).strip()))
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
    """Split a section's lines into (title, body) blocks at the topic heading
    level. Text before the first heading is returned as the preamble."""
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
                blocks.append((cur_title, "\n".join(cur).strip()))
            cur_title = ln[len(hmark):].strip()
            cur = []
        else:
            cur.append(ln)
    if cur_title is None:
        pre = cur
    else:
        blocks.append((cur_title, "\n".join(cur).strip()))
    return blocks, "\n".join(pre).strip()


def group_topics(blocks: list[tuple[str, str]], group_consecutive: bool):
    """Collapse consecutive same-title blocks into one topic. Returns
    list of (title, body) where body is the verbatim block bodies joined."""
    grouped: list[list] = []  # [title, [bodies]]
    for raw_title, body in blocks:
        title = normalize_topic_title(raw_title)
        if group_consecutive and grouped and grouped[-1][0] == title:
            grouped[-1][1].append(body)
        else:
            grouped.append([title, [body]])
    return [(t, "\n\n".join(b for b in bodies if b)) for t, bodies in grouped]


def assign_filenames(topics: list[dict]) -> None:
    """Assign a unique `fname` to each topic dict in place.

    Clean `slug(title).md` where unique; on cross-source collision prefix the
    subject token; residual collisions get a numeric suffix. Deterministic and
    order-stable."""
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
    """Build a topic file: `# Title`, optional blockquote, then the body."""
    if CLEAN:
        body = strip_cruft(clean_body(body))
        if SPLIT_COMPACT_TABLES:
            body = compact_tables(backtick_identifiers(body))
    parts = [f"# {title}", ""]
    if blockquote:
        parts += [blockquote, ""]
    parts.append(body)
    return "\n".join(parts).rstrip() + "\n"


def pack_topics(topics: list[dict], max_bytes: int) -> list[dict]:
    """When --max-bytes is set, merge adjacent topics from the SAME source into
    combined files up to max_bytes (never splitting a topic). Returns a new list
    of topic dicts. With max_bytes <= 0 the input is returned unchanged."""
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
            merged["body"] = "\n\n".join(f"## {t}\n\n{b}" for t, b in zip(titles, bodies))
        out.append(merged)
        i = j
    return out


# ---- index / topics / symbols regeneration ----------------------------------

def _dedupe_blocks(blocks: list[tuple[str, str]]) -> "list[tuple[str, str]]":
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
    """Rewrite INDEX.md: replace the topic-listing section, preserve all others,
    and fold deduplicated source boilerplate into '## Source notes'."""
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
    listing_text = "\n".join(listing).rstrip()

    notes_text = ""
    if notes:
        nl = ["## Source notes", "",
              "Boilerplate carried over from the original combined reference files."]
        for head, body in notes:
            nl += ["", f"### {head}", "", body]
        notes_text = "\n".join(nl).rstrip()

    idx = out_dir / "INDEX.md"
    if idx.exists():
        text = _read(idx)
        lines = text.split("\n")
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

        result = "\n".join(pre).rstrip() + "\n\n"
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
                result += listing_text + "\n\n"
            elif head == "__NOTES__":
                result += notes_text + "\n\n"
            else:
                result += f"## {head}\n\n" + "\n".join(b).strip() + "\n\n"
        write_text(idx, result.rstrip() + "\n")
    else:
        parts = [f"# {skill_title} Reference Index", "", listing_text]
        if notes_text:
            parts += ["", notes_text]
        write_text(idx, "\n".join(parts).rstrip() + "\n")


def regen_topics(out_dir: Path, topics: list[dict]) -> None:
    """Rewrite topics.json as a flat {title: {file, corpus_search_hints}} map,
    inheriting each topic's source file's existing search hints when available."""
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
    write_text(tj, json.dumps(new, ensure_ascii=False, indent=2) + "\n")


def remap_symbols(symbols_path: Path, topic_texts: list[tuple[str, str]],
                  source_map: "dict | None" = None,
                  files_by_source: "dict | None" = None) -> int:
    """Recompute each group's `reference_files` after a split, leaving
    `corpus_chunk_ids` and all other fields/order intact.

    Two modes:
      * source_map given — each group key is mapped to a SOURCE filename and its
        reference_files become the topic files derived from that source doc
        (precise, deterministic). Groups absent from the map are left unchanged.
      * otherwise — term presence: files whose text contains the group key
        (word-boundary, case-insensitive). Unreliable when keys are normalized
        labels not present verbatim in the prose.

    Returns the number of groups updated."""
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
    write_text(symbols_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return updated


# ---- verification ------------------------------------------------------------

def _split_verify(out_dir: Path, topics: list[dict], src_concat: str,
           index_topic_heading: str) -> bool:
    """Prove coverage (no dropped/duplicated content), report sizes, and check
    INDEX/topics consistency. Returns True on success."""
    ok = True
    # 1. Content coverage: reconstruct from disk and compare to the source.
    recon = []
    for t in topics:
        fpath = out_dir / t["fname"]
        text = _read(fpath)
        b = _strip_topic_header(text, t["title"])
        recon.append(b.strip())
    recon_concat = "\n\n".join(x for x in recon if x)
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
    listed_idx = set(re.findall(r"\[([^\]]+\.md)\]\(", idx_text))
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
    """Remove the `# Title` line and an optional immediate blockquote from a
    rendered topic file, returning the body."""
    lines = text.split("\n")
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
    return "\n".join(out).strip()


# =============================================================================
# DRIVER
# =============================================================================

def _file_specs(args) -> list[dict]:
    """Resolve the list of source files + per-file params from --legend or --md."""
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


def cmd_split(argv=None) -> int:
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
        ok = _split_verify(out_dir, topics, "\n\n".join(x for x in src_blocks_concat if x), INDEX_TOPIC_HEADING)
        return 0 if ok else 1
    return 0

# ==============================================================================
# MAINTAIN — in-place gold maintenance (was maintain_skill.py)
# ==============================================================================

_HEADING = re.compile(r"(?m)^#{2,3} ")


def subskill_dirs(skill: Path):
    subs = [d for d in sorted(skill.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]
    return subs if subs else [skill]


def ref_files(refs: Path):
    return sorted(p for p in refs.glob("*.md") if p.name != "INDEX.md")


def h1_title(text: str) -> str:
    for ln in text.split("\n"):
        if ln.startswith("# "):
            return ln[2:].strip()
    return ""


def has_subheadings(text: str) -> bool:
    return bool(_HEADING.search(text))


def split_runs(text: str, max_bytes: int):
    """Split into <=max_bytes runs at heading/blank boundaries (fence-aware)."""
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
            runs.append("\n".join(cur)); cur = []; cb = 0
        cur.append(pc); cb += b
    if cur:
        runs.append("\n".join(cur))
    return runs


_ENTRY_START = re.compile(r"\*\*[^*]+\*\*[)\s.:]*$")  # line ends with a bold name/label token


def _is_entry_start(line: str) -> bool:
    """A line that begins a new self-contained item: a sub-heading, or a short bold-label line such as
    '> Boolean **propertyName**' or '**someName**'. Description / prose lines are NOT entry starts, so a
    name is never separated from the description that follows it."""
    s = line.strip()
    if re.match(r"#{2,6}\s", s):
        return True
    s = s.lstrip("> ").strip()
    return len(s) <= 90 and bool(_ENTRY_START.search(s))


def split_atomic(text: str, max_bytes: int):
    """Split a list-style file into <=max_bytes pieces ONLY at entry boundaries (a sub-heading or a
    short bold-label line that starts a new item), so a name is never separated from its description and
    a table row is never cut. Returns None when it cannot split cleanly — one entry already exceeds
    max_bytes (e.g. a monolithic table), or there are fewer than two entries — so the caller leaves the
    file whole (oversize is acceptable when a clean split is not possible)."""
    entries, cur = [], []
    for l in text.split("\n"):
        if _is_entry_start(l) and cur:
            entries.append("\n".join(cur)); cur = [l]
        else:
            cur.append(l)
    if cur:
        entries.append("\n".join(cur))
    if len(entries) < 3 or any(len(e.encode("utf-8")) > max_bytes for e in entries):
        return None
    runs, run, rb = [], [], 0
    for e in entries:
        eb = len(e.encode("utf-8"))
        if run and rb + eb > max_bytes:
            runs.append("\n".join(run)); run = []; rb = 0
        run.append(e); rb += eb
    if run:
        runs.append("\n".join(run))
    return runs


def _degenerate(runs) -> bool:
    """A split is no good if it produced <2 pieces or a tiny first piece (content lost / no break)."""
    return (not runs) or len(runs) < 2 or len(runs[0].encode("utf-8")) < 256


def audit(skill: Path, max_bytes: int):
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
    n = 2
    while f"{stem}-{n}.md" in used:
        n += 1
    name = f"{stem}-{n}.md"
    used.add(name)
    return name


def patch_topics(refs: Path, orig: str, parts: list):
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
    tj.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def patch_index(refs: Path, orig: str, parts: list):
    idx = refs / "INDEX.md"
    if not idx.is_file():
        return
    lines = idx.read_text(encoding="utf-8").split("\n")
    for i, ln in enumerate(lines):
        if f"]({orig})" in ln and ln.lstrip().startswith("|"):
            m = re.match(r"\s*\|\s*\[.*?\]\(.*?\)\s*\|(.*)\|\s*$", ln)
            covers = (m.group(1).strip() if m else "")
            rows = [f"| [{pn}]({pn}) | {covers} (part {k}) |" for k, pn in enumerate(parts, start=2)]
            lines[i + 1:i + 1] = rows
            break
    idx.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def apply_splits(skill: Path, max_bytes: int, force: bool, act_above: int):
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
            title = re.sub(r"\s*\(part \d+\)\s*$", "", h1_title(text)) or stem
            p.write_text(runs[0].rstrip() + "\n", encoding="utf-8", newline="\n")  # part 1 keeps name + H1
            parts = []
            for k, run in enumerate(runs[1:], start=2):
                name = _next_name(stem, used)
                body = run if run.lstrip().startswith("#") else f"# {title} (part {k})\n\n{run}"
                (refs / name).write_text(body.rstrip() + "\n", encoding="utf-8", newline="\n")
                parts.append(name)
            patch_index(refs, p.name, parts)
            patch_topics(refs, p.name, parts)
            changed.append((sk.name, p.name, len(parts) + 1))
    return changed, skipped


_CAMEL = re.compile(r"[a-z][A-Z]")


def _distinctive_terms(refs: Path) -> dict:
    """{distinctive topic-name -> filename} from topics.json; skips short / common single words to
    avoid over-linking. Multi-word titles and identifier-like names qualify."""
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
    """Blank out fenced + inline code so a match never lands inside code."""
    out, fence = [], False
    for l in text.split("\n"):
        if l.lstrip().startswith("```"):
            fence = not fence; out.append(""); continue
        out.append("" if fence else re.sub(r"`[^`]*`", "", l))
    return "\n".join(out)


def cross_link(skill: Path, max_links: int = 6):
    """Append/refresh a '## See also' footer on each reference file, linking other topics in the same
    (sub)skill whose distinctive name appears in the file (and isn't already linked inline). Safe and
    idempotent: only the footer is touched — prose, SKILL.md and GOTCHA.md are left alone. This is the
    lightweight, conservative cross-link capability; richer inline/curated linking is a later pass."""
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
            body = re.split(r"\n## See also\n", text, 1)[0].rstrip()
            searchable = _no_code(body)
            linked = set(re.findall(r"\]\(([^)/]+\.md)\)", body))
            related, seen = [], set()
            for name, fn in terms.items():
                if fn == p.name or fn in linked or fn in seen:
                    continue
                if re.search(r"\b" + re.escape(name) + r"\b", searchable):
                    related.append((name, fn)); seen.add(fn)
            related = related[:max_links]
            footer = ("\n\n## See also\n\n" + "\n".join(f"- [{n}]({fn})" for n, fn in related) + "\n") if related else "\n"
            new = body + footer
            if new != text:
                p.write_text(new, encoding="utf-8", newline="\n")
                if related:
                    changed.append((sk.name, p.name, len(related)))
    return changed


def cmd_maintain(argv=None) -> int:
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

# ==============================================================================
# INDEX — cross-skill master index (was build_master_index.py)
# ==============================================================================

_STOP = {"and", "the", "for", "with", "use", "using", "a", "an", "to", "of", "in", "on", "or"}


def parse_frontmatter(text: str) -> dict:
    """Line-based YAML-lite parse of the SKILL.md frontmatter: handles inline scalars, folded/literal
    block scalars (`>-`, `>`, `|`), inline lists (`[a, b]`), and block lists (`- a`)."""
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    lines = m.group(1).split("\n")
    fm, i = {}, 0
    while i < len(lines):
        km = re.match(r"^(\w+):\s?(.*)$", lines[i])
        if not km:
            i += 1
            continue
        key, val = km.group(1), km.group(2).strip()
        if val in (">-", ">", ">+", "|", "|-", "|+"):                 # block scalar
            buf, i = [], i + 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                buf.append(lines[i].strip()); i += 1
            fm[key] = " ".join(x for x in buf if x)
            continue
        if val.startswith("[") and val.endswith("]"):                # inline list
            fm[key] = [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
        elif val == "":                                              # maybe a block list follows
            buf, j = [], i + 1
            while j < len(lines) and re.match(r"^\s+-\s", lines[j]):
                buf.append(re.match(r"^\s+-\s*(.+)", lines[j]).group(1).strip().strip("'\"")); j += 1
            fm[key] = buf if buf else ""
            i = j if buf else i + 1
            continue
        else:
            fm[key] = val.strip("'\"")
        i += 1
    return fm


def derive_covers(skill: Path) -> list:
    """Entities a skill covers. Router → its sub-skill area names (clean). Flat → distinctive
    topics.json keywords filtered to clean single-concept terms (drops concatenated slugs)."""
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
    """Insert/replace a `covers:` block list in a SKILL.md frontmatter, preserving the bespoke body
    byte-for-byte. Idempotent: an existing covers: block (inline or list) is stripped and rewritten."""
    p = skill / "SKILL.md"
    text = p.read_text(encoding="utf-8")
    m = re.match(r"^(---\n)(.*?)(\n---\n)", text, re.DOTALL)
    if not m:
        return False
    lines = m.group(2).split("\n")
    out, i = [], 0
    while i < len(lines):
        cm = re.match(r"^covers:\s*(\S.*)?$", lines[i])
        if cm:
            i += 1
            if not cm.group(1):                       # block list follows — drop its items too
                while i < len(lines) and re.match(r"^\s+-\s", lines[i]):
                    i += 1
            continue
        out.append(lines[i]); i += 1
    body = "\n".join(out).rstrip("\n")
    block = "covers:\n" + "\n".join(f"  - {c}" for c in covers)
    p.write_text(m.group(1) + body + "\n" + block + m.group(3) + text[m.end():],
                 encoding="utf-8", newline="\n")
    return True


def skill_info(skill: Path) -> dict:
    fm = parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8")) if (skill / "SKILL.md").is_file() else {}
    covers = fm.get("covers") or derive_covers(skill)
    desc = fm.get("description", "")
    trigger = re.split(r"(?<=[.])\s", desc, 1)[0] if desc else ""
    return {"name": fm.get("name", skill.name), "trigger": trigger[:200], "covers": covers}


def build_master_text(root: Path) -> str:
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
    return "\n".join(out).rstrip() + "\n"


def cmd_index(argv=None) -> int:
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
    (root / "INDEX.md").write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {root}/INDEX.md ({text.count(chr(10))} lines)")
    if args.mirror:
        mroot = Path(args.mirror)
        (mroot / "INDEX.md").write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {mroot}/INDEX.md (mirror)")
    return 0

# ==============================================================================
# LINT — link/topics health check (was lint_skill.py)
# ==============================================================================

_LINK = re.compile(r"(?<!!)\]\(([^)#?]+\.md)(?:#[^)]*)?\)")


def lint_subskill(sk: Path) -> dict:
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
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    summary = "clean" if clean else ", ".join(f"{k}={v}" for k, v in totals.items() if v)
    print(f"{name}: {summary}  -> {out.as_posix()}")
    return 0 if clean else 1

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

_SUBAGENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recontext_subagent.py")
_BUILDER = os.path.abspath(__file__)


def _recon_cfg(args) -> dict:
    """Resolve roots/owner from an optional --config JSON, overridden by CLI args. No hardcoding."""
    cfg = {}
    if getattr(args, "config", None):
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))

    def get(name, default=None):
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
    return Path(p).resolve().relative_to(Path(source_root).resolve()).as_posix()


def _recon_subskill(skill: str, rel: str) -> str:
    parts = rel.split("/")
    return "/".join(parts[1:parts.index("references")]) if "references" in parts else ""


def _recon_queue(work_root, owner) -> Path:
    return Path(work_root) / f"queue.{owner}.jsonl"


def _recon_load_queue(path) -> dict:
    rows = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["path"]] = r
    return rows


def _recon_save_queue(path, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows.values():
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _recon_scan(cfg, skill):
    """Walk <source_root>/<skill>/**/references/*.md, score+classify each, upsert into the owner's
    queue (idempotent: status/attempts/notes preserved). Returns (counts, queue_path)."""
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
    rows = [r for r in _recon_load_queue(_recon_queue(cfg["work_root"], cfg["owner"])).values()
            if r["skill"] == skill and r.get("status") == "pending"]
    f1 = [r for r in rows if r["faction"] == 1]
    f2 = [r for r in rows if r["faction"] == 2]

    def grp(items, n):
        return [items[i:i + n] for i in range(0, len(items), n)]

    def fent(r):
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
const SUBAGENT = __SUBAGENT__;
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
  const list = b.map(f => '- ' + f.abspath + '  (rel: ' + f.rel + ')').join("\n");
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
  const list = b.files.map((f,i) => `${i}. [${f.mode}/${f.tier}] ${f.abspath}  (rel: ${f.rel})`).join("\n");
  return `Faction-2 RECONTEXTUALIZE ${b.files.length} ${SKILL} files (mode=${b.mode}) through the LOCKED writer. Label ${lbl}.
You NEVER write rewrite artifacts yourself: the locked writer is the only artifact writer and it GATES every rewrite (Gate A identifiers, Gate B 13-word residue, Gate C cruft), writing ONLY on PASS.
For EACH file below (worker id = "${lbl}-f" + <index>):
  1. ${PY} "${SUBAGENT}" prepare --work-root "${WR}" --skill ${SKILL} --worker <wid> --source "<abspath>" --source-root "${SR}" --rel "<rel>" --mode ${b.mode} --tier <tier>
  2. ${PY} "${SUBAGENT}" show --work-root "${WR}" --skill ${SKILL} --worker <wid>   (prints the contract + the work)
  3. Produce the rewrite per the contract: mode "extract" -> EXACTLY {"items":[...]} (same i/cell keys + order + count as the packet); mode "full" -> the WHOLE rewritten file as raw text. Preserve every identifier / code span / link target / number / table; reword prose so no ~13-word run matches the source.
  4. Pipe the rewrite to: ${PY} "${SUBAGENT}" submit --work-root "${WR}" --skill ${SKILL} --worker <wid>
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
    repl = {
        "__SKILL__": skill,
        "__PY__": json.dumps(cfg["python"]),
        "__SUBAGENT__": json.dumps(_SUBAGENT),
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
    """Place every gated work.md the locked writer produced for <skill> into <work_root>/working/<rel>.
    Re-gates (faction 2) as a cheap backstop; never places a failing file. `finish` owns queue state."""
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
    """Re-gate every working file for <skill> against its source; re-queue any failure."""
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
    """Verify every source content file is queued and done."""
    rows = _recon_load_queue(_recon_queue(Path(cfg["work_root"]), cfg["owner"]))
    src_rels = {_recon_rel(cfg["source_root"], p)
                for p in recon.content_files(Path(cfg["source_root"]) / skill)}
    queued = {r["path"] for r in rows.values() if r["skill"] == skill}
    done = {r["path"] for r in rows.values() if r["skill"] == skill and r.get("status") == "done"}
    return {"skill": skill, "source": len(src_rels), "queued": len(queued), "done": len(done),
            "missing_from_queue": sorted(src_rels - queued), "pending": sorted(queued - done)}


def _recon_promote(cfg, skill, validate_package=False):
    """Validate the finished working skill, then move it into the store and write a done marker."""
    if not cfg["store_root"]:
        return False, "promote requires --store-root (or config store_root)"
    work_root, store_root = Path(cfg["work_root"]), Path(cfg["store_root"])
    wdir = work_root / "working" / skill
    if not wdir.is_dir():
        return False, f"working skill dir missing: {wdir}"
    validator = Path(cfg["validator"])
    if validator.is_file():
        cmd = [cfg["python"], str(validator)] + (["--package"] if validate_package else []) + [str(wdir)]
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
    marker.write_text(f"{skill} promoted by {cfg['owner']}\n", encoding="utf-8")
    return True, str(dest)


def cmd_recontext(argv=None) -> int:
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
        p.add_argument("--config", help="JSON with source_root/work_root/store_root/owner/python/validator")
        p.add_argument("--source-root", help="read-only source tree (contains <skill>/.../references/*.md)")
        p.add_argument("--work-root", help="writable sandbox (queues, assignments, working copies)")
        p.add_argument("--owner", help="queue namespace (default: agent)")
        p.add_argument("--python", help="python used inside generated drain workflows")
        if store:
            p.add_argument("--store-root", help="finished-skill destination for promote")
            p.add_argument("--validator", help="path to validate_skill_package.py")
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
            out.write_text(js, encoding="utf-8", newline="\n")
            print(f"{args.skill}: pending F1={batches['pending_f1']} F2={batches['pending_f2']} -> {out}")
            print("Launch with the Workflow tool: {scriptPath: \"" + str(out) + "\"}")
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

Run `python skill_builder.py <command> --help` for that command's options."""

_INGEST_USAGE = ("usage: python skill_builder.py ingest {html|mdbook|rustdoc|pdf} [options]\n"
                 "Run `python skill_builder.py ingest <format> --help` for options.")

_INGEST = {"html": cmd_ingest_html, "mdbook": cmd_ingest_mdbook,
           "rustdoc": cmd_ingest_rustdoc, "pdf": cmd_ingest_pdf}
_COMMANDS = {"build": cmd_build, "finalize": cmd_finalize, "split": cmd_split,
             "maintain": cmd_maintain, "index": cmd_index, "lint": cmd_lint,
             "recontext": cmd_recontext}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    cmd, rest = argv[0], argv[1:]
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
