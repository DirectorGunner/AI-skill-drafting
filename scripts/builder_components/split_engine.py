"""Split engine: parse a source reference into topics, group/assign/render them, and regenerate
INDEX/topics/symbols (was the split section of skill_builder.py; the cmd_split CLI lives in split_cmd.py)."""

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
    """Read a file's full text as UTF-8."""
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
    """Drop blocks with empty or duplicate (heading, body) content, preserving first-seen order."""
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
