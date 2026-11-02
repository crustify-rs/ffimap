"""cli.py — the `ffimap` command.

    ffimap WORKSPACE [--ffibox] [--sys-crates CRATE,...]
                     [--seams NAMES]
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
    "Scan a Rust crate's unsafe surface and raw-pointer usage with a rustc "
    "driver over HIR and typeck. Reproducible: same tree, same bytes. "
    "Needs the crate to "
    "compile; when it does not, there are no counts rather than approximate "
    "ones. It says HOW MUCH unsafety is there, never which of it is wrong.")


def add_arguments(p: argparse.ArgumentParser) -> None:
    """Register the scan's flags (not the workspace positional) on ``p``."""
    p.add_argument(
        "--sites", nargs="+", action="extend", default=None, metavar="COUNTER",
        help="Also report where these counters' increments are in the source: "
             "a `sites` record beside `counts` with one list per counter. "
             "Takes a counter's dotted path down to its LEAF (e.g. "
             "raw_ptr.fn_sig_arg.safe.pub, "
             "ty.ffibox.wrapper.of_which.borrow.pub, code.unsafe_call.ffi): a "
             "path that stops at an arm above one validates and then reads "
             "empty, since the driver emits by leaf. Line totals have no "
             "sites.")
    p.add_argument(
        "--sys-crates", type=lambda v: [c for c in v.split(",") if c], default=None,
        metavar="CRATE[,CRATE...]",
        help="Crates whose #[repr(C)] types are C's: the crate's own "
             "bindings and any other crate it reaches C through, such as "
             "`libc`. The field walk descends through them too, so a pointer "
             "a scanned type holds through one is counted as the scanned "
             "crate's to manage. Nothing is discovered: a Cargo `links` key "
             "and a `*-sys` name both over-report, so unnamed means the peel "
             "set is the scanned crate alone.")
    p.add_argument(
        "--seams", type=lambda v: [n for n in v.replace(",", "\n").split() if n],
        default=None, metavar="NAMES",
        help="Function names that are seams -- the conversion between a "
             "wrapper and its raw pointer (`raw`, `from_raw`, `as_ptr`, "
             "`from_ptr`). Newline- or comma-separated, so `--seams \"$(cat "
             "seams.txt)\"` works. They are counted as usual and ALSO reported "
             "as the `of_which.seam` share of each fn-signature counter, so a "
             "reader can tell plumbing from the pointer management a consumer "
             "of the safe API actually faces. ffimap never guesses the names.")
    p.add_argument(
        "--ffibox", action="store_true",
        help="The crate is built on ffibox. Turns on the vocabulary's arms "
             "-- ty.field.ffibox, ty.impl.ffibox, fn.sig.of_which.ffibox -- and sanctions "
             "the convention's `as_ref(&self)` / `as_mut(&mut self)` layout "
             "accessors, which are matched by name and so hold only where "
             "that convention does.")


def run(workspace: Path, args: argparse.Namespace) -> int:
    """Scan ``workspace`` and print the metrics document on stdout.

    The document is the only output. A rendering of the counters in prose
    would be a second description of the schema, in a place no test reads, so
    there is none: `docs/schema.md` describes them and the JSON carries them.
    """
    from ffimap import scan
    doc = scan.compose(workspace, sites=args.sites, ffibox=args.ffibox,
                       sys_crates=args.sys_crates, seams=args.seams)
    print(json.dumps(doc, indent=2))
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
