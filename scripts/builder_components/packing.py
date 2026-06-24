"""Pack/split reference content into right-sized files (was the packing section of skill_builder.py)."""

from __future__ import annotations

import collections
import re
from .corpus import OBJECT_DUMP_SECTIONS, SECTION_PREFIX, STRIP_ORDER_PREFIX, TARGET_BYTES, _is_fence, clean_title, hierarchical_path, object_of


def slug(s: str) -> str:
    """Filesystem-safe kebab slug."""
    s = re.sub(r"\.(md|html?)$", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return re.sub(r"-{2,}", "-", s) or "page"


def _titlecase(seg: str) -> str:
    """Turn a slug segment into a Title Case display string (dashes/underscores -> spaces)."""
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
        """Title-case a path segment, dropping a 2+digit order prefix when STRIP_ORDER_PREFIX."""
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
