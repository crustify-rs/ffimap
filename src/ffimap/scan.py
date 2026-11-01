"""scan.py — composes the document `ffimap` prints.

Composes the rustc driver's metrics for the workspace and the ratios worth
comparing crates on, and hands them back. It writes nothing: the caller
decides whether the document goes to a file and which one, because where a
scan belongs is a campaign's business and not the scanner's.

WHY THIS IS NOT SOMETHING AN AGENT DOES. Not because an agent could not count
— because a count it produced would be a sample. The composer's output is a
pure function of the source tree, so two runs agree and a diff between them is
a change in the crate rather than a change in the model's mood. That is what
makes a number quotable.

Finding what is WORTH LOOKING AT is the opposite kind of work, and it belongs
to a reviewer: one who reads the code, forms suspicions, and defends them.
"""
from __future__ import annotations

from sys import stderr
from pathlib import Path

from ffimap import measure


def site_counters(requested: list[str]) -> list[str]:
    """Validate `--sites` names, each a counter's dotted path.

    There is no `all`: the tree's leaves are not a closed list -- the ffibox
    arms are generated from a vocabulary of traits and primitives -- so asking
    for every one is a different request from naming the few you want.
    """
    unknown = [n for n in requested if not measure.is_tree_counter(n)]
    if unknown:
        families = " ".join(
            f"{head}.{{{','.join(fams)}}}"
            for head, fams in measure.TREE_SITE_FAMILIES.items())
        raise SystemExit(
            "ffimap: --sites takes a counter's dotted path; not a counter: "
            f"{' '.join(unknown)}. A path runs under " + families)
    return list(dict.fromkeys(requested))


def compose(workspace: Path, sites: list[str] | None = None,
            ffibox: bool = False, sys_crates: list[str] | None = None,
            seams: list[str] | None = None) -> dict:
    """Scan the workspace and return the metrics document.

    ``sites`` names counters whose source locations to report, as a ``sites``
    record beside ``counts`` with one list per counter. ``ffibox`` asserts the
    crate is built on ffibox, which turns on the vocabulary's arms
    (``ty.field.ffibox``, ``ty.impl.ffibox``, ``fn.sig``) and sanctions the
    conventions' ``as_ref`` / ``as_mut`` layout accessors. ``sys_crates`` names
    the crates
    whose `#[repr(C)]` types are C's and whose types the field walk descends
    through; nothing is discovered, since which types are C's rests on it. The
    set is recorded in ``sys_crates``. ``seams`` names the
    functions that only convert between a wrapper and its raw pointer; they
    are reported as the ``of_which.seam`` share of each fn-signature counter.
    """
    wanted = site_counters(sites) if sites else None
    sys = measure.sys_crates(sys_crates)
    # What scanned, beside what it found: the inputs that move the figures are
    # the ffimap commit, the toolchain, and the two flags that decide what is
    # counted. Recorded here so a document cannot drift from its provenance.
    doc: dict = {
        "crate_path": str(workspace),
        "sys_crates": sys,
        "scanner": {**measure.scanner(), "ffibox": ffibox,
                    "seams": sorted(seams or ())},
    }
    all_sites: dict = {}
    try:
        all_sites, counts = measure.measure(
            workspace, ffibox=ffibox, sys=sys, seams=seams)
        doc["counts"] = counts
        doc["counts_unavailable"] = None
    except measure.DriverUnavailable as e:
        # No counts rather than substitute ones: see measure.py.
        doc["counts"] = None
        doc["counts_unavailable"] = str(e)
        # stderr: the document owns stdout, and it records the failure too.
        print(f"[ffimap] no counts: {e}".rstrip(), file=stderr)
    if wanted is not None:
        doc["sites"] = {k: all_sites.get(k, []) for k in wanted}
    return doc
