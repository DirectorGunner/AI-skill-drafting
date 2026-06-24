"""Recontextualization command group: scan/batch/drain/integrate/promote (was the recontext section)."""

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
    """Resolve roots/owner from an optional --config JSON, overridden by CLI args. No hardcoding."""
    cfg = {}
    if getattr(args, "config", None):
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))

    def get(name, default=None):
        """Resolve a setting from the CLI arg, then the config JSON, then the default."""
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
    """Return p as a POSIX path relative to source_root."""
    return Path(p).resolve().relative_to(Path(source_root).resolve()).as_posix()


def _recon_subskill(skill: str, rel: str) -> str:
    """Return the sub-skill path between the skill name and the 'references' segment of rel."""
    parts = rel.split("/")
    return "/".join(parts[1:parts.index("references")]) if "references" in parts else ""


def _recon_queue(work_root, owner) -> Path:
    """Return the path to the owner's queue JSONL file under work_root."""
    return Path(work_root) / f"queue.{owner}.jsonl"


def _recon_load_queue(path) -> dict:
    """Load the JSONL queue at path into a dict keyed by each row's 'path'."""
    rows = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["path"]] = r
    return rows


def _recon_save_queue(path, rows) -> None:
    """Write the queue rows back to path as newline-delimited JSON."""
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
    """Group the skill's pending queue rows into F1 cleanup batches and F2 rewrite batches (by mode)."""
    rows = [r for r in _recon_load_queue(_recon_queue(cfg["work_root"], cfg["owner"])).values()
            if r["skill"] == skill and r.get("status") == "pending"]
    f1 = [r for r in rows if r["faction"] == 1]
    f2 = [r for r in rows if r["faction"] == 2]

    def grp(items, n):
        """Split items into consecutive chunks of at most n elements."""
        return [items[i:i + n] for i in range(0, len(items), n)]

    def fent(r):
        """Project a queue row into the minimal file entry a batch needs."""
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
    """Render the drain Workflow JS by substituting cfg/skill/batches/wave into the _DRAIN_JS template."""
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
    marker.write_text(f"{skill} promoted by {cfg['owner']}\n", encoding="utf-8")
    return True, str(dest)


def cmd_recontext(argv=None) -> int:
    """Parse and dispatch the `recontext` subcommands (clean/extract/splice/gate/triage and the
    scan/batch/drain/integrate/finish/reconcile/promote orchestration). Returns a process exit code."""
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
        """Add the shared --config/root/owner/skill args (plus store-root/validator when store=True)."""
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

def main(argv=None) -> int:
    """Standalone entry point for `python -m builder_components.recontext`; delegates to cmd_recontext."""
    return cmd_recontext(argv)


if __name__ == "__main__":
    raise SystemExit(main())
