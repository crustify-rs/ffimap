"""cli.py — the `ffimap` command.

    ffimap WORKSPACE [--ffibox] [--sys-crates CRATE,...]
                     [--seams NAMES] [--regions NAMES] [--barriers NAMES]
                     [--sites COUNTER ...]
    ffimap diff BEFORE AFTER
    ffimap api extract RUSTDOC_JSON
    ffimap api diff BEFORE AFTER [--items KEYS] [--raw] [--format json|text]

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
             "ty.ffibox.wrapper.as.borrowed.std.pub, code.unsafe_call.ffi): a "
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
        "--regions", type=lambda v: [n for n in v.replace(",", "\n").split() if n],
        default=None, metavar="NAMES",
        help="Module names that are regions -- the modules a crate confines "
             "a kind of code to, such as its unsafe FFI (`ffi_import`, "
             "`ffi_export`). Newline- or comma-separated. The unsafe blocks are "
             "then reported by the region they sit in, as "
             "code.unsafe_block.of_which.region.<name>, with the rest as "
             "outside_regions, and the unsafe fns outside every region as "
             "fn.unsafe.of_which.outside_regions. A module is in a region when "
             "it, or a module enclosing it, has one of these names. ffimap "
             "never guesses the names.")
    p.add_argument(
        "--barriers", type=lambda v: [n for n in v.replace(",", "\n").split() if n],
        default=None, metavar="NAMES",
        help="Function names that are the crate's own panic barriers: helpers "
             "that call `catch_unwind` for their caller, such as a `wrap(|| "
             "...)`. Newline- or comma-separated. A fn with a foreign ABI that "
             "calls one counts in fn.extern_abi.of_which.catches_unwind, as one "
             "calling `catch_unwind` itself does. ffimap never guesses the "
             "names.")
    p.add_argument(
        "--features", type=lambda v: [f for f in v.split(",") if f], default=None,
        metavar="FEATURE[,FEATURE...]",
        help="Cargo features to enable for the scanned build, on top of the "
             "defaults, passed to `cargo check --features`. Code a feature "
             "gates is compiled, and so counted, only when it is named, such "
             "as an export gateway compiled under a feature of its own. The "
             "set is recorded in the scanner's `features`, and two scans are "
             "compared only when it is the same.")
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
                       sys_crates=args.sys_crates, seams=args.seams,
                       regions=args.regions, barriers=args.barriers,
                       features=args.features)
    print(json.dumps(doc, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ffimap", description=DESCRIPTION,
        epilog="`ffimap diff BEFORE AFTER` compares two documents of one crate "
               "instead of scanning; `ffimap diff --help` describes it. "
               "`ffimap api` measures a crate's API per C item from rustdoc "
               "JSON; `ffimap api --help` describes it.")
    p.add_argument("workspace", metavar="WORKSPACE",
                   help="Directory of the Cargo workspace (or package) to scan.")
    add_arguments(p)
    return p


def build_diff_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ffimap diff",
        description="Compare two documents of one crate: the counters that "
                    "moved, with their values before and after, and, where "
                    "both documents carry sites for a counter, the files and "
                    "lines its increments were added at or removed from. "
                    "Prints a JSON document; scans nothing.")
    p.add_argument("before", metavar="BEFORE", help="The earlier document.")
    p.add_argument("after", metavar="AFTER", help="The later document.")
    return p


def run_diff(argv: list[str]) -> int:
    from ffimap import diff
    args = build_diff_parser().parse_args(argv)
    docs = [json.loads(Path(p).read_text()) for p in (args.before, args.after)]
    try:
        out = diff.diff(*docs)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


def _names(v: str) -> list[str]:
    return [n for n in v.replace(",", "\n").split() if n]


def build_api_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ffimap api",
        description="A crate's consumer-facing API per C item, from the "
                    "rustdoc JSON of `cargo +nightly rustdoc -p CRATE --lib -- "
                    "-Z unstable-options --output-format json`. A C item is "
                    "the `<kind>::<path>` of a `Wraps` or `Replaces` anchor; "
                    "its surface is the public signatures of the Rust items "
                    "carrying that anchor and of the handles and owners tied "
                    "to them. Builds nothing and needs no driver.")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")
    ex = sub.add_parser(
        "extract", help="Print the per-C-item surface of one rustdoc JSON.",
        description="Print, as sorted JSON, each C item's stand-ins with "
                    "their public paths and normalised signatures, the items "
                    "tied to them, the public surface no anchor reaches, the "
                    "anchors that do not parse, and coverage counts.")
    ex.add_argument("doc", metavar="RUSTDOC_JSON")
    for sp in (ex,):
        _dep_args(sp)
    df = sub.add_parser(
        "diff", help="Classify each C item between two documents.",
        description="Classify each C item as kept, extended, changed, removed "
                    "or new between two documents, each a rustdoc JSON or an "
                    "`ffimap api extract`, and record an anchor that moved "
                    "between Wraps and Replaces.")
    df.add_argument("before", metavar="BEFORE")
    df.add_argument("after", metavar="AFTER")
    df.add_argument(
        "--items", type=_names, default=None, metavar="KEYS",
        help="Restrict the C items to these `<kind>::<path>` keys, such as a "
             "batch's worklist. Newline-, comma- or space-separated, so "
             "`--items \"$(cat worklist)\"` works. Keys found in neither "
             "document are listed under `missing`.")
    _dep_args(df)
    df.add_argument(
        "--raw", action="store_true",
        help="Decide each status from the raw records, the stand-ins' and "
             "associated items' signatures as they stand, instead of the "
             "contract view, under which a handle or owner that changes form "
             "but keeps what a consumer may rely on is kept.")
    df.add_argument(
        "--format", choices=("json", "text"), default="json",
        help="json (the default) prints the whole classification; text prints "
             "only what is not kept or new, with its changes, and the totals.")
    return p


def _read_json(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not JSON: {e}") from None


def _dep_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--dep", action="append", default=[], metavar="RUSTDOC_JSON",
        help="The rustdoc JSON of a crate the measured one depends on, such as "
             "ffibox's, so that the methods and trait impls its handles and "
             "owners inherit from that crate's types are resolved. Repeatable. "
             "Without it a contract that needs them is reported unresolved and "
             "compared on its raw record.")
    p.add_argument(
        "--plumbing", type=_names, default=["ffibox"], metavar="CRATES",
        help="Crates whose wrapper types and traits are plumbing, not API: "
             "a form inherits only their reborrows and dereferences, and "
             "their traits are no part of a contract. Default: ffibox.")


def run_api(argv: list[str]) -> int:
    from ffimap import api, rustdoc
    args = build_api_parser().parse_args(argv)
    try:
        deps = [rustdoc.load(d) for d in args.dep]
        plumbing = frozenset(args.plumbing)
        if args.command == "extract":
            out = api.extract(rustdoc.load(args.doc), deps, plumbing)
        else:
            docs = [api.as_extract(_read_json(p), p, deps, plumbing)
                    for p in (args.before, args.after)]
            out = api.diff(*docs, items=args.items, raw=args.raw)
            if args.format == "text":
                sys.stdout.write(api.render_text(out))
                return 0
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


def main() -> None:
    if sys.argv[1:2] == ["diff"]:
        raise SystemExit(run_diff(sys.argv[2:]))
    if sys.argv[1:2] == ["api"]:
        raise SystemExit(run_api(sys.argv[2:]))
    args = build_parser().parse_args()
    ws = Path(args.workspace).resolve()
    if not ws.is_dir():
        print(f"error: workspace does not exist: {ws}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(run(ws, args))


if __name__ == "__main__":
    main()
