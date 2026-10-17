"""cli.py — the `ffimap` command.

    ffimap WORKSPACE [--json] [--ffibox] [--sys-crates CRATE,...]
                     [--sites COUNTER ... | all]

Deterministic: a rustc HIR/typeck pass over the crate's FFI and unsafe
surface. No LLM or network. Two runs over one tree agree exactly, so a diff
between them is a change in the crate.

The flags are registered by `add_arguments` so a host command (`crustify
ffimap`) can expose the same scan with the same flags and help texts, and
`run` executes it, without the two surfaces drifting.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DESCRIPTION = (
    "Map a Rust crate's FFI and unsafe surface with a rustc driver over HIR "
    "and typeck. Reproducible: same tree, same bytes. Needs the crate to "
    "compile; when it does not, there are no counts rather than approximate "
    "ones. It says HOW MUCH unsafety is there, never which of it is wrong.")


def add_arguments(p: argparse.ArgumentParser) -> None:
    """Register the scan's flags (not the workspace positional) on ``p``."""
    p.add_argument("--json", action="store_true",
                   help="Print the document on stdout instead of a summary. "
                        "Redirect it to keep it; ffimap writes no file.")
    p.add_argument(
        "--sites", nargs="+", action="extend", default=None, metavar="COUNTER",
        help="Also report where these counters' increments are in the source: "
             "a `sites` record beside `counts` with one list per counter. Takes "
             "counters that count source locations (e.g. "
             "raw_ptr_fn_pub_safe, raw_ptr_ty_pub_fields_pub, "
             "unsafe_fns_pub, c_type_borrow_non_sanctioned), or `all`. Line and statement totals have "
             "no sites.")
    p.add_argument(
        "--sys-crates", type=lambda v: [c for c in v.split(",") if c], default=None,
        metavar="CRATE[,CRATE...]",
        help="Crates whose #[repr(C)] types are C's, beside the ones found "
             "automatically (every crate with a Cargo `links` key or named "
             "`*-sys`). Use it for bindings that are neither, such as `libc`.")
    p.add_argument(
        "--ffibox", action="store_true",
        help="Also count the crate's ffibox surface: ffibox types and the "
             "crate's Ref/Mut/Locked handles in fn signatures (pub or private, "
             "by kind), and the crate's types implementing ffibox traits "
             "and other traits (ffibox-macro, derived and hand-written). Adds an "
             "`ffibox` record; its counters also take --sites, whole or "
             "for one key of their breakdown (fn_sig_ffibox_owner_pub:CVal).")


def run(workspace: Path, args: argparse.Namespace) -> int:
    """Scan ``workspace`` and print the document or its summary."""
    from ffimap import scan
    doc = scan.compose(workspace, sites=args.sites, ffibox=args.ffibox,
                       sys_crates=args.sys_crates)
    print(json.dumps(doc, indent=2) if args.json else scan.summarize(doc))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ffimap", description=DESCRIPTION)
    p.add_argument("workspace", metavar="WORKSPACE",
                   help="Directory of the Cargo workspace (or package) to scan.")
    add_arguments(p)
    return p


def main() -> None:
    args = build_parser().parse_args()
    ws = Path(args.workspace).resolve()
    if not ws.is_dir():
        print(f"error: workspace does not exist: {ws}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(run(ws, args))


if __name__ == "__main__":
    main()
