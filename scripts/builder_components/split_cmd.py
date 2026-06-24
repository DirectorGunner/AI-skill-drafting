"""Split CLI: the `split` subcommand (cmd_split), on top of split_engine."""

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
    """Run the `split` subcommand: parse args, split each source into topic files, and regenerate
    INDEX/topics (optionally remapping symbols, replacing inputs, and verifying). Returns an exit code."""
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

def main(argv=None) -> int:
    """Standalone entry point for `python -m builder_components.split_cmd`; delegates to cmd_split."""
    return cmd_split(argv)


if __name__ == "__main__":
    raise SystemExit(main())
