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
    """Validate `--sites` names; `all` expands to every site-bearing counter.
    The owner / handle counters are always measured, so they need no flag."""
    valid = measure.SITE_COUNTERS + measure.FFIBOX_COUNTERS
    if "all" in requested:
        # `all` stays the flat counters: the tree's leaves are not enumerable
        # here, and asking for every one of them would be a different request.
        return list(valid)
    # An owner / handle counter takes a key from its breakdown,
    # `<counter>:<key>` (`fn_sig_ffibox_owner_pub:CVal`), for that key alone.
    keyed = lambda n: n.partition(":")[0] in measure.FFIBOX_COUNTERS and ":" in n
    unknown = [n for n in requested
               if n not in valid and not keyed(n)
               and not measure.is_tree_counter(n)]
    if unknown:
        families = " ".join(
            f"{head}.{{{','.join(fams)}}}"
            for head, fams in measure.TREE_SITE_FAMILIES.items())
        raise SystemExit(
            "ffimap: --sites takes counters that count source locations; "
            f"unknown or siteless: {' '.join(unknown)}. Valid: "
            + " ".join(valid) + ", or all; a tree counter is a dotted path "
            "under " + families + "; an owner / handle counter also "
            "takes <counter>:<key> for one key of its breakdown")
    return list(dict.fromkeys(requested))


def compose(workspace: Path, sites: list[str] | None = None,
            ffibox: bool = False, sys_crates: list[str] | None = None,
            seams: list[str] | None = None) -> dict:
    """Scan the workspace and return the metrics document.

    ``sites`` names counters whose source locations to report, as a ``sites``
    record beside ``counts`` with one list per counter. ``ffibox`` asserts the
    crate is built on ffibox, which sanctions the conventions' ``as_ref`` /
    ``as_mut`` layout accessors; the owner and handle record is composed
    either way. ``sys_crates`` names the crates
    whose `#[repr(C)]` types are C's and whose types the field walk descends
    through; nothing is discovered, since which types are C's rests on it. The
    set is recorded in ``sys_crates``. ``seams`` names the
    functions that only convert between a wrapper and its raw pointer; they
    are reported as the ``of_which.seam`` share of each fn-signature counter.
    """
    wanted = site_counters(sites) if sites else None
    sys = measure.sys_crates(sys_crates)
    doc: dict = {"crate_path": str(workspace), "sys_crates": sys}
    all_sites: dict = {}
    flat: dict = {}
    try:
        flat, all_sites, breakdowns, ptr = measure.measure(
            workspace, ffibox=ffibox, sys=sys, seams=seams)
        doc["ptr"] = ptr
        # `derived` reads the flat counters; the document carries the tree.
        doc["counts"] = measure.nest_counts(flat)
        doc["counts_unavailable"] = None
    except measure.DriverUnavailable as e:
        # No counts rather than substitute ones: see measure.py.
        doc["counts"] = None
        doc["counts_unavailable"] = str(e)
        breakdowns = None
        # stderr: `--json` owns stdout, and the document records the failure.
        print(f"[ffimap] no counts: {e}".rstrip(), file=stderr)
    doc["ffibox"] = _ffibox_record(breakdowns)
    if wanted is not None:
        doc["sites"] = {k: all_sites.get(k, []) for k in wanted}
    doc["derived"] = _derive(flat)
    return doc


def _ffibox_record(breakdowns: dict | None) -> dict | None:
    """``{"counts": {counter: total}, "by": {counter: {key: N}}}``, every
    counter present; ``None`` when the build produced no counts."""
    if breakdowns is None:
        return None
    by = {k: dict(sorted(breakdowns.get(k, {}).items())) for k in measure.FFIBOX_COUNTERS}
    flat = {k: sum(v.values()) for k, v in by.items()}
    # `counts` is the tree; `by` stays keyed by the flat leaf name, since a
    # breakdown belongs to one leaf (as a site list does).
    return {"counts": measure.nest_ffibox(flat), "by": by}


def _derive(c: dict) -> dict:
    """Ratios a reader actually compares crates on.

    Absolute unsafe-block counts are close to meaningless across crates of
    different sizes, and *lower is not automatically better*: a wrapper over C
    must contain unsafe, and folding 600 small audited blocks into 200 large
    ones makes the crate worse while improving the number. So the headline
    figures here are the ones that ARE categorical — how much unsafety the
    crate pushes across its public API boundary, where the caller has to
    discharge it.
    """
    if not c:
        return {}
    pub_fns = (c.get("safe_fns_pub") or 0) + (c.get("unsafe_fns_pub") or 0)
    priv_fns = (c.get("safe_fns_priv") or 0) + (c.get("unsafe_fns_priv") or 0)
    # Sums only. No ratios: a ratio moves when its denominator moves, so one
    # reads as a change in the crate when only the other term changed --
    # `unsafe_fns_pub / unsafe_fns` rises when private unsafe fns are DELETED.
    # The counts are all here; a consumer that wants a rate divides its own.
    return {
        # Categorical: what the crate's public interface hands its callers.
        "fns_pub": pub_fns,
        "fns_priv": priv_fns,
        "raw_ptr_pub": (c.get("raw_ptr_ty_pub_fields_pub") or 0)
                       + (c.get("raw_ptr_ty_pub_fields_priv") or 0) + (c.get("raw_ptr_fn_pub_safe") or 0)
                       + (c.get("raw_ptr_fn_pub_unsafe") or 0),
        "raw_ptr_pub_safe_interface": (c.get("raw_ptr_ty_pub_fields_pub") or 0)
                                      + (c.get("raw_ptr_fn_pub_safe") or 0),
    }
