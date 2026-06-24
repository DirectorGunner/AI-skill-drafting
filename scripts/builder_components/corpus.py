"""Build corpus model + text cleaning: record loading, sectioning, and HTML/markdown
normalization (was the corpus + cleaning sections of skill_builder.py; merged because they are
mutually dependent)."""

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
        """Rewrite one Markdown image: resolve a relative src against source_url, else keep a
        link-free "Figure: <desc>" placeholder so no broken local path survives."""
        alt, src = m.group(1).strip(), m.group(2).strip()
        desc = alt or _humanize(unquote(src.split("/")[-1]))
        if src.startswith(("http://", "https://")):
            return f"[Figure: {desc}]({src})"
        if source_url and "<" not in src and ">" not in src and " " not in src:
            return f"[Figure: {desc}]({urljoin(source_url, src)})"
        return f"Figure: {desc}"  # unresolvable/placeholder src -> description only, no broken link

    def link_repl(m):
        """Rewrite one Markdown link: leave external/mailto links, resolve anchors and relative
        targets against source_url, and drop to plain label text when nothing can be resolved."""
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
    """Split a Markdown table row on unescaped pipes, dropping empty leading/trailing cells."""
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
