"""Ingest source docs (HTML / mdBook / rustdoc / PDF) into a corpus JSONL (was the ingest section)."""

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
    """Slugify a string into a lowercase hyphenated token, falling back to 'page' if empty."""
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
    """Ingest manifest-listed HTML pages into a corpus JSONL: one page-chunk record per file."""
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
    """Ingest a single concatenated mdBook HTML file into a corpus JSONL, splitting at top-level
    (`# `) page headings (fence-aware) and dropping pages whose title matches an --exclude substring."""
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
    """Run a subprocess and return its captured stdout as UTF-8 text (undecodable bytes replaced)."""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout


def qpdf_outline(pdf: str):
    """Return the PDF's outline (bookmark) tree via `qpdf --json`, or [] if absent."""
    data = json.loads(run(["qpdf", "--json", "--json-key=outlines", pdf]) or "{}")
    return data.get("outlines", [])


def npages(pdf: str) -> int:
    """Return the PDF's page count via `qpdf --show-npages` (0 if unavailable)."""
    return int((run(["qpdf", "--show-npages", pdf]) or "0").strip() or 0)


def pdf_pages(pdf: str, layout: bool):
    """Extract the PDF's text with pdftotext (optionally -layout) and return it split per page."""
    cmd = ["pdftotext", "-q", "-enc", "UTF-8"] + (["-layout"] if layout else []) + [pdf, "-"]
    return run(cmd).split("\f")


def flatten(nodes, depth=0, acc=None):
    """Flatten a nested outline tree into a depth-tagged list of {title, page, depth} dicts."""
    if acc is None:
        acc = []
    for nd in nodes:
        acc.append({"title": (nd.get("title") or "").strip(),
                    "page": nd.get("destpageposfrom1"), "depth": depth})
        flatten(nd.get("kids") or [], depth + 1, acc)
    return acc


def norm(s: str) -> str:
    """Collapse runs of whitespace to single spaces and strip the result."""
    return re.sub(r"\s+", " ", s or "").strip()


def _pdf_slug(s: str) -> str:
    """Slugify a string into a lowercase hyphenated token, falling back to 'section' if empty."""
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
        """Emit the buffered prose lines as one reflowed paragraph and clear the buffer."""
        if pbuf:
            out.append(" ".join(pbuf)); pbuf.clear()

    def flush_l():
        """Emit the buffered list items as one block and clear the buffer."""
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
    """Ingest a PDF into a corpus JSONL: chunk by outline entries at --chunk-depth, clean page
    boilerplate, rebuild chapter Markdown, and write (or append) one record per chunk."""
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

_INGEST_FORMATS = {"html": cmd_ingest_html, "mdbook": cmd_ingest_mdbook,
                   "rustdoc": cmd_ingest_rustdoc, "pdf": cmd_ingest_pdf}


def main(argv=None) -> int:
    """Standalone entry for `python -m builder_components.ingest <html|mdbook|rustdoc|pdf> ...`.

    Selects the source-format handler from the first positional argument and delegates the remaining
    arguments to it. Returns the process exit code (0 ok; 2 on an unknown or missing format). Reads
    ``sys.argv[1:]`` when ``argv`` is None.
    """
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
