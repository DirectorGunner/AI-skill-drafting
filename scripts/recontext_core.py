#!/usr/bin/env python3
"""recontext_core.py — generalized, stdlib-only recontextualization primitives.

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
"""
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
_FENCE = re.compile(r"^(?:`{3,}|~{3,})[\w+.\-]*$")


def is_fence(stripped: str) -> bool:
    """True only for a clean opening/closing code-fence delimiter line."""
    return bool(_FENCE.match(stripped))


def iter_lines(text):
    """Yield (line, in_fence) for each line. The fence delimiter itself is in_fence=True."""
    in_fence = False
    for ln in text.split("\n"):
        if is_fence(ln.strip()):
            in_fence = not in_fence
            yield ln, True
            continue
        yield ln, in_fence


def strip_code(text: str) -> str:
    """Return prose-only text (fenced code blocks removed, delimiters dropped)."""
    out = []
    for ln, in_fence in iter_lines(text):
        if in_fence:
            continue
        out.append(ln)
    return "\n".join(out)


def code_blocks(text: str):
    """Return the list of fenced code-block bodies (verbatim, joined by \\n)."""
    blocks, cur, in_fence = [], [], False
    for ln in text.split("\n"):
        if is_fence(ln.strip()):
            if in_fence:
                blocks.append("\n".join(cur))
                cur = []
            in_fence = not in_fence
            continue
        if in_fence:
            cur.append(ln)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


# --------------------------------------------------------------------------- #
# Word / n-gram originality (locked 13-word gate).
# --------------------------------------------------------------------------- #
def words(t: str):
    return re.findall(r"\w+", t.lower())


def maxruns(a, b, n):
    """Maximal runs of >= n consecutive words in a that also appear in b."""
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
    """A token that is functional, not prose: snake_case, has a digit, file ext, URL."""
    return ("_" in tok) or any(c.isdigit() for c in tok) or tok in _EXEMPT_EXTS \
        or tok in ("http", "https", "www")


def looks_exempt(run: str):
    """Exempt a shared run ONLY if it is genuinely identifier-dominated — never just because
    a long prose run happens to contain one underscore."""
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
    r"^> .+ reference\. (Original prose|Verbatim docs); identifiers preserved verbatim\.\s*$"
)


def marker_line(skill_title: str) -> str:
    return f"> {skill_title} reference. Original prose; identifiers preserved verbatim."


# --------------------------------------------------------------------------- #
# Chrome / scrape-artifact patterns. Line-anchored and conservative.
# --------------------------------------------------------------------------- #
SECTION_TITLED_SUB = re.compile(r'Section titled\s+[“"][^”"]*[”"]\s*')

CHROME_PATTERNS = [
    re.compile(r'^\s*Section titled\s+[“"].*[”"]\s*$'),
    re.compile(r'^\s*Was this page helpful\??\s*$', re.I),
    re.compile(r'^\s*On this page\s*$', re.I),
    re.compile(r'^\s*Edit this page.*$', re.I),
    re.compile(r'^\s*Table of contents\s*$', re.I),
    re.compile(r'^\s*Back to top\s*$', re.I),
    re.compile(r'^\s*Print this page\s*$', re.I),
    re.compile(r'^\s*(?:Support|Sponsor)\s+(?:us\s+)?on\s+Open\s+Collective.*$', re.I),
    re.compile(r'^\s*\[(?:Support on Open Collective|Sponsor on GitHub)\]\(.*$', re.I),
    re.compile(r'^\s*©.*(?:contributor|reserved|license|\d{4}).*$', re.I),
    re.compile(r'^\s*\(c\)\s+\d{4}.*$', re.I),
    re.compile(r'^\s*All rights reserved\.?\s*$', re.I),
    re.compile(r'^\s*Licensed under\s+.*$', re.I),
    re.compile(r'^\s*\[[^\]]*Previous\]\([^)]*\)\s*\[[^\]]*Next\]\(.*$', re.I),
]

_UNICODE_SPACE = re.compile("[\u00A0\u2002\u2003\u2007\u2008\u2009\u200A\u202F\uFEFF]")
_PUA = re.compile("[\uE000-\uF8FF]")                          # icon-font glyphs (Font Awesome)
_FIGURE_EMPTY = re.compile(r"\(Figure:\s*\)")                 # empty image-placeholder stub
_FIGURE_ANY = re.compile(r"\(Figure:[^)]*\)")                 # any figure caption (image alt-text)
_RUSTDOC_NAV = re.compile(r"\[(?:Read more|Source)\]\([^)]*\)")  # rustdoc nav labels
_SECTION_SIGN = re.compile(r"\s*§")                           # rustdoc trailing section sign
_MIDDOT = re.compile(r"\s+·(?=\s)")                           # rustdoc version separator


def scrape_cruft_subs(line: str) -> str:
    """Remove substring scrape cruft from one (non-fence) line."""
    line = _UNICODE_SPACE.sub(" ", line)
    line = _PUA.sub("", line)
    line = _FIGURE_EMPTY.sub("", line)
    line = _RUSTDOC_NAV.sub("", line)
    line = _SECTION_SIGN.sub("", line)
    line = _MIDDOT.sub("", line)
    return line


def chrome_hits(text: str):
    """Return [(lineno, line)] matching chrome patterns OR carrying residual scrape glyphs
    (PUA icon fonts, empty figure stubs), outside fences."""
    hits = []
    for i, (ln, in_fence) in enumerate(iter_lines(text)):
        if in_fence:
            continue
        if any(pat.match(ln) for pat in CHROME_PATTERNS) \
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

_TABLE_RE = re.compile(r"^\|")
_TABLE_SEP_RE = re.compile(r"^\|?\s*[-:]+\s*\|")
_BARE_BULLET_RE = re.compile(r"^[-*+]\s+`?\[?[\w./:-]+`?\]?\s*$")


def is_prose_line(stripped: str) -> bool:
    """True if a stripped line is copyrightable narrative prose to rewrite.
    Generous capture (>=6 words, >=1 stopword); Gate B (13-word) is the residue backstop."""
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
    """Yield (line_index, raw_line) for each prose line (fence-aware)."""
    for i, (ln, in_fence) in enumerate(iter_lines(text)):
        if in_fence:
            continue
        if is_prose_line(ln.strip()):
            yield i, ln


_URL_STRIP = re.compile(r"https?://\S+")
_LINK_FULL_STRIP = re.compile(r"\[[^\]]*\]\([^)]*\)")  # whole [label](url) — label is nav/UI, preserved
_LINKTARGET_STRIP = re.compile(r"\]\(\s*[^)]*\)")      # any remaining ](url)
_INLINE_STRIP = re.compile(r"`[^`]*`")


def _strip_preserved(s: str) -> str:
    """Remove the things we keep verbatim before the n-gram: inline code, FULL markdown links
    (the [label] display text is a navigational/UI label, not copyrightable prose), and URLs."""
    s = _INLINE_STRIP.sub(" ", s)
    s = _LINK_FULL_STRIP.sub(" ", s)
    s = _LINKTARGET_STRIP.sub("] ", s)
    s = _URL_STRIP.sub(" ", s)
    s = _FIGURE_ANY.sub(" ", s)        # figure captions are image alt-text, not residue
    return s


def _looks_like_signature(cell: str) -> bool:
    """A code signature masquerading as prose (e.g. `bool operator== (const T& O) const`).
    Such cells must NOT be reworded — some signature tokens aren't in Gate A's protected set."""
    if re.search(r"\boperator\b", cell):
        return True
    if re.search(r"\)\s*const\b", cell):              # trailing ) const
        return True
    if "(" in cell and ")" in cell and re.search(r"[A-Z]\w*\s*[&*]\s*\w", cell):
        return True                                   # Type& / Type* param inside a call
    return False


def _is_cell_prose(cell: str) -> bool:
    """True if a table cell holds copyrightable narrative (>=6 words, >=1 stopword, after
    removing preserved identifiers/links). Identifier-only and signature cells excluded."""
    if _looks_like_signature(cell):
        return False
    wl = re.findall(r"[A-Za-z]+", _strip_preserved(cell).lower())
    return len(wl) >= 6 and any(w in STOPWORDS for w in wl)


def prose_units(text: str):
    """Yield each PROSE UNIT — a whole prose line OR a prose-bearing table cell:
       whole line:  {'i': idx, 'cell': None, 'indent': ws, 'text': stripped_line}
       table cell:  {'i': idx, 'cell': seg_index, 'text': stripped_cell}
    `cell` is the index into line.split('|') (so splice can rejoin exactly)."""
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
    """Return (ratio, prose_word_count, total_word_count, prose_unit_count)."""
    total = len(re.findall(r"[A-Za-z0-9_]+", text))
    pwc = puc = 0
    for u in prose_units(text):
        pwc += len(u["text"].split())
        puc += 1
    return (pwc / total if total else 0.0), pwc, total, puc


def prose_text(text: str) -> str:
    """All prose-unit text (whole lines + prose table cells) — the surface Gate B checks."""
    return "\n".join(u["text"] for u in prose_units(text))


def prose_for_ngram(text: str) -> str:
    """Prose-unit text with preserved identifiers/links/URLs removed before the n-gram."""
    return _strip_preserved(prose_text(text))


# --------------------------------------------------------------------------- #
# Gate A: protected-identifier multisets (source vs working).
# --------------------------------------------------------------------------- #
_INLINE = re.compile(r"`([^`\n]+)`")
_URL = re.compile(r"https?://[^\s)>\]}\"']+")
_LINK_TARGET = re.compile(r"\]\(\s*([^)\s]+)")
_UNESCAPE = re.compile(r"\\([_()\[\]*~#.`])")
_CAMEL = re.compile(r"\b[A-Za-z][a-z0-9]+(?:[A-Z][a-z0-9]+)+[A-Za-z0-9]*\b")
_ALLCAPS = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_QUALIFIED = re.compile(r"\b[A-Za-z_]\w*(?:::[A-Za-z_0-9]+)+\b")
_NUM = re.compile(
    r"(?<![\w.])\d[\d,]*(?:\.\d+)?"
    r"(?:\s?(?:%|px|fps|Hz|kHz|MHz|GHz|ms|ns|µs|us|s|KB|MB|GB|TB|kB|dBFS|dB|"
    r"bits?|bytes?|mm|cm|m|x)\b)?"
)


def extract_protected(text: str) -> dict:
    """Return {category: Counter} of protected tokens. 'code'/'inline'/'url'/'ident' are
    hard-preserve; 'num' is reported as a softer signal."""
    prose = _UNESCAPE.sub(r"\1", strip_code(text))   # normalize prettier escapes
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
    """Identifier-preservation. Baseline = chrome-stripped source. PASS when no hard-category
    token is lost. Returns (passed, detail)."""
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
    """Maximal runs of >= n words in `a` whose every n-gram is in the precomputed bset."""
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
    """PASS when no non-exempt >= min_run-word run is shared with the source. Scans working
    prose PER UNIT against the full source prose n-gram set. Returns (passed, detail)."""
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
    hits = chrome_hits(working_text)
    return (len(hits) == 0), {"cruft_lines": [ln for _, ln in hits][:25], "count": len(hits)}


def run_gates(source_text: str, working_text: str, faction: int = 2, min_run: int = 13) -> dict:
    """Run gates A/B/C on a (source, working) pair. PASS = A and C pass; B is required for
    Faction-2 (recontextualized) files and reported (ratio) for F1."""
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
    """Conservative cleanup outside fenced code: strip scrape chrome, normalize the marker
    blockquote to 'Original prose', collapse blank runs. Returns (new_text, actions)."""
    actions = []

    # 1a. remove inline "Section titled ..." chrome + source-specific scrape cruft (substrings).
    sub_lines, in_fence, subs, cruft = [], False, 0, 0
    for ln in text.split("\n"):
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
    text = "\n".join(sub_lines)

    # 1b. strip whole chrome lines (outside fences)
    keep, in_fence, stripped = [], False, 0
    for ln in text.split("\n"):
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
    text = "\n".join(keep)

    # 2. normalize the marker blockquote to "Original prose"
    out, fixed = [], 0
    for ln in text.split("\n"):
        s = ln.strip()
        if MARKER_RE.match(s) and "Verbatim docs" in s:
            ln = ln.replace("Verbatim docs", "Original prose")
            fixed += 1
        out.append(ln)
    if fixed:
        actions.append("fix_marker")
    text = "\n".join(out)

    # 3. normalize whitespace: strip trailing ws; collapse 3+ blank lines to 1
    lines = [l.rstrip() for l in text.split("\n")]
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
    text = "\n".join(collapsed).rstrip() + "\n"
    if changed:
        actions.append("normalize_blanks")

    return text, actions


# --------------------------------------------------------------------------- #
# Extract (prose packet) and splice (tamper-proof re-insertion).
# --------------------------------------------------------------------------- #
def extract(text: str) -> dict:
    """Extract the prose units of a file into a rewrite packet. For extraction-mode files only
    the prose units are sent to the LLM; identifiers/signatures/tables/code never leave the file.

    Packet schema: {"total_lines": N, "items": [{"i","cell","heading","text"}]}.
    The caller adds the "file" key (the source path) if it wants one.
    """
    lines = text.split("\n")
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
    """Return a list of {'i','cell','text'} items. Accepts {'items':[...]}, a list, or a legacy
    whole-line map {idx: text}."""
    if isinstance(obj, dict) and "items" in obj:
        return obj["items"]
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        return [{"i": int(k), "cell": None, "text": v} for k, v in obj.items()]
    raise ValueError("rewrites must be {'items':[...]}, a list, or {idx: text}")


def splice(source_text: str, rewrites: list):
    """Re-derive the allowed prose-unit (i,cell) keys from the SOURCE, then replace ONLY those
    units with their rewrites. Any rewrite aimed at a non-prose index is ignored, so identifiers /
    signatures / code can never be altered by a stray index. Returns (out_text, stats)."""
    allowed = {(u["i"], u["cell"]) for u in prose_units(source_text)}
    lines = source_text.split("\n")
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
    return "\n".join(lines), {
        "replaced": replaced,
        "skipped_non_prose": skipped,
        "left_verbatim": len(left),
        "left_verbatim_keys": [[k[0], k[1]] for k in left[:50]],
    }


# --------------------------------------------------------------------------- #
# Triage: classify a file into a faction / tier / mode by prose density.
# --------------------------------------------------------------------------- #
def score_file(text: str):
    """Return (prose_ratio, prose_words, prose_unit_count, chrome_count, marker_ok)."""
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
    """Return (faction, tier, mode, needs_cleanup, review).

    Bias toward Faction-2: mis-routing prose to F1 leaves copyrighted text verbatim (the costly
    error); mis-routing an identifier file to F2 only wastes some tokens. mode = 'extract' (send
    only prose lines) when the prose fraction is below EXTRACT_THRESHOLD, else 'full' (whole-file).
    tier (light/medium/heavy) = the rewrite workload = number of prose units."""
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
    """All marker-bearing reference content files under a skill dir: **/references/*.md minus
    INDEX.md. The caller supplies skill_dir; nothing is hardcoded."""
    out = []
    for p in Path(skill_dir).rglob("*.md"):
        parts = [x.lower() for x in p.parts]
        if "references" in parts and p.name.lower() != "index.md":
            out.append(p)
    return sorted(out)


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path, text: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def append_jsonl(path, record: dict):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def skill_title(skill: str) -> str:
    return skill.replace("-", " ").title()
