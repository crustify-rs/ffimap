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


def site_counters(requested: list[str], ffibox: bool = False) -> list[str]:
    """Validate `--sites` names; `all` expands to every site-bearing counter.
    The `--ffibox` counters are valid only when that scan runs."""
    valid = measure.SITE_COUNTERS + (measure.FFIBOX_COUNTERS if ffibox else ())
    if "all" in requested:
        return list(valid)
    # An ffibox counter takes a key from its breakdown, `<counter>:<key>`
    # (`fn_sig_ffibox_owner_pub:CVal`), for that key's positions alone.
    # A shared-borrow counter takes a pointer origin, `<counter>:<origin>`
    # (`ptr_wrapper_shared_borrow_wr:self`).
    def keyed(n: str) -> bool:
        head, sep, key = n.partition(":")
        if not sep:
            return False
        if head in measure.PROVENANCE_COUNTERS:
            return key in measure.ORIGINS
        return ffibox and head in measure.FFIBOX_COUNTERS
    unknown = [n for n in requested if n not in valid and not keyed(n)]
    if unknown:
        hint = (" (the --ffibox counters need --ffibox)"
                if any(n.partition(":")[0] in measure.FFIBOX_COUNTERS for n in unknown) else "")
        raise SystemExit(
            "ffimap: --sites takes counters that count source locations; "
            f"unknown or siteless: {' '.join(unknown)}{hint}. Valid: "
            + " ".join(valid) + ", or all; an --ffibox counter also takes "
            "<counter>:<key> for one key of its breakdown, and a shared-borrow "
            "counter <counter>:<origin> for one of " + ", ".join(measure.ORIGINS))
    return list(dict.fromkeys(requested))


def compose(workspace: Path, sites: list[str] | None = None,
            ffibox: bool = False, sys_crates: list[str] | None = None) -> dict:
    """Scan the workspace and return the metrics document.

    ``sites`` names counters whose source locations to report, as a ``sites``
    record beside ``counts`` with one list per counter. ``ffibox`` adds the
    ``ffibox`` record: the crate's ffibox surface. ``sys_crates`` add to the
    sys crates found by Cargo's `links` keys; the set is recorded in
    ``sys_crates``, since which types are C's rests on it.
    """
    wanted = site_counters(sites, ffibox) if sites else None
    sys = measure.sys_crates(workspace, sys_crates)
    doc: dict = {"crate_path": str(workspace), "sys_crates": sys}
    all_sites: dict = {}
    try:
        doc["counts"], all_sites, breakdowns = measure.measure(
            workspace, ffibox=ffibox, sys=sys)
        doc["counts_unavailable"] = None
    except measure.DriverUnavailable as e:
        # No counts rather than substitute ones: see measure.py.
        doc["counts"] = None
        doc["counts_unavailable"] = str(e)
        breakdowns = None
        # stderr: `--json` owns stdout, and the document records the failure.
        print(f"[ffimap] no counts: {e}".rstrip(), file=stderr)
    if ffibox:
        doc["ffibox"] = _ffibox_record(breakdowns)
    doc["provenance"] = _provenance(all_sites) if doc["counts"] is not None else None
    if wanted is not None:
        doc["sites"] = {k: all_sites.get(k, []) for k in wanted}
    doc["derived"] = _derive(doc)
    return doc


def _provenance(all_sites: dict) -> dict:
    """``{counter: {origin: N}}`` for the shared-borrow counters, from the
    driver's `<counter>:<origin>` sites; each counter's origins sum to it."""
    return {k: {o: sum(r["count"] for r in all_sites.get(f"{k}:{o}", []))
                for o in measure.ORIGINS}
            for k in measure.PROVENANCE_COUNTERS}


def _ffibox_record(breakdowns: dict | None) -> dict | None:
    """``{"counts": {counter: total}, "by": {counter: {key: N}}}``, every
    counter present; ``None`` when the build produced no counts."""
    if breakdowns is None:
        return None
    by = {k: dict(sorted(breakdowns.get(k, {}).items())) for k in measure.FFIBOX_COUNTERS}
    return {"counts": {k: sum(v.values()) for k, v in by.items()}, "by": by}


def _derive(doc: dict) -> dict:
    """Ratios a reader actually compares crates on.

    Absolute unsafe-block counts are close to meaningless across crates of
    different sizes, and *lower is not automatically better*: a wrapper over C
    must contain unsafe, and folding 600 small audited blocks into 200 large
    ones makes the crate worse while improving the number. So the headline
    figures here are the ones that ARE categorical — how much unsafety the
    crate pushes across its public API boundary, where the caller has to
    discharge it.
    """
    c = doc.get("counts") or {}
    if not c:
        return {}
    loc = c.get("code_lines") or 0
    ub = c.get("unsafe_blocks") or 0
    fns = c.get("unsafe_fns") or 0
    pub_fns = (c.get("safe_fns_pub") or 0) + (c.get("unsafe_fns_pub") or 0)
    priv_fns = (c.get("safe_fns_priv") or 0) + (c.get("unsafe_fns_priv") or 0)
    return {
        # Categorical: what the crate's public interface hands its callers.
        "fns_pub": pub_fns,
        "fns_priv": priv_fns,
        "unsafe_fn_pub_ratio": round((c.get("unsafe_fns_pub") or 0) / fns, 4) if fns else None,
        "unsafe_fn_share_of_pub_fns": round((c.get("unsafe_fns_pub") or 0) / pub_fns, 4) if pub_fns else None,
        "raw_ptr_pub": (c.get("raw_ptr_ty_pub_fields_pub") or 0)
                       + (c.get("raw_ptr_ty_pub_fields_priv") or 0) + (c.get("raw_ptr_fn_pub_safe") or 0)
                       + (c.get("raw_ptr_fn_pub_unsafe") or 0),
        "raw_ptr_pub_safe_interface": (c.get("raw_ptr_ty_pub_fields_pub") or 0)
                                      + (c.get("raw_ptr_fn_pub_safe") or 0),
        # Context, explicitly NOT a quality score. See the docstring.
        "unsafe_loc_ratio": round((c.get("unsafe_block_code_lines") or 0) / loc, 4) if loc else None,
        "loc_per_unsafe_block": round(loc / ub, 1) if ub else None,
    }




def summarize(doc: dict) -> str:
    c = doc.get("counts") or {}
    d = doc.get("derived", {})
    lines: list[str] = []
    if c:
        lines += [
            f"  code lines           {c.get('code_lines')}",
            f"  unsafe blocks        {c.get('unsafe_blocks')}"
            f"   ({d.get('unsafe_loc_ratio')} of code lines — context, not a score)",
            f"  fns                  {d.get('fns_pub', 0) + d.get('fns_priv', 0)}"
            f"   (pub {c.get('safe_fns_pub')} safe + {c.get('unsafe_fns_pub')} unsafe,"
            f" private {c.get('safe_fns_priv')} safe + {c.get('unsafe_fns_priv')} unsafe;"
            f" methods of other crates' traits excluded)",
            f"  unsafe fn            {c.get('unsafe_fns')}"
            f"   ({c.get('unsafe_fns_pub')} pub + {c.get('unsafe_fns_priv')} private;"
            f" methods of other crates' traits excluded)",
            f"  unsafe Send/Sync     {c.get('unsafe_send_impl')} Send + {c.get('unsafe_sync_impl')} Sync"
            f"   (on by-value wrappers: {c.get('ty_wrapper_send_impl')} Send + {c.get('ty_wrapper_sync_impl')} Sync,"
            f" on pointer wrappers: {c.get('ptr_wrapper_send_impl')} Send + {c.get('ptr_wrapper_sync_impl')} Sync)",
            f"  wrappers             {c.get('ty_wrapper')} by value (layout newtypes) + {c.get('ptr_wrapper')} by pointer",
            f"  raw ptr positions    {sum(c.get('raw_ptr_' + k) or 0 for k in ('ty_pub_fields_pub', 'ty_pub_fields_priv', 'ty_priv', 'fn_pub_safe', 'fn_pub_unsafe', 'fn_priv_safe', 'fn_priv_unsafe'))}"
            f"   (pub types: {c.get('raw_ptr_ty_pub_fields_pub')} pub fields + {c.get('raw_ptr_ty_pub_fields_priv')} private fields,"
            f" private types: {c.get('raw_ptr_ty_priv')};"
            f" fn signatures: pub {c.get('raw_ptr_fn_pub_safe')} safe + {c.get('raw_ptr_fn_pub_unsafe')} unsafe,"
            f" private {c.get('raw_ptr_fn_priv_safe')} safe + {c.get('raw_ptr_fn_priv_unsafe')} unsafe)",
            f"  void ptr positions   {sum(c.get('void_ptr_' + k) or 0 for k in ('ty_pub_fields_pub', 'ty_pub_fields_priv', 'ty_priv', 'fn_pub_safe', 'fn_pub_unsafe', 'fn_priv_safe', 'fn_priv_unsafe'))}"
            f"   (pub types: {c.get('void_ptr_ty_pub_fields_pub')} pub fields + {c.get('void_ptr_ty_pub_fields_priv')} private fields,"
            f" private types: {c.get('void_ptr_ty_priv')};"
            f" fn signatures: pub {c.get('void_ptr_fn_pub_safe')} safe + {c.get('void_ptr_fn_pub_unsafe')} unsafe,"
            f" private {c.get('void_ptr_fn_priv_safe')} safe + {c.get('void_ptr_fn_priv_unsafe')} unsafe)",
            f"  non-wrapper borrows  {sum(c.get('ty_non_wrapper_borrow_' + k) or 0 for k in ('pub_safe', 'pub_unsafe', 'priv_safe', 'priv_unsafe'))}"
            f"   (fn-signature references to memory that is not C's: pub {c.get('ty_non_wrapper_borrow_pub_safe')} safe"
            f" + {c.get('ty_non_wrapper_borrow_pub_unsafe')} unsafe, private {c.get('ty_non_wrapper_borrow_priv_safe')} safe"
            f" + {c.get('ty_non_wrapper_borrow_priv_unsafe')} unsafe)",
            f"  borrows into C memory {(c.get('ty_wrapper_borrow_sanctioned') or 0) + (c.get('ty_wrapper_borrow_non_sanctioned') or 0)}"
            f"   ({c.get('ty_wrapper_borrow_sanctioned')} sanctioned, {c.get('ty_wrapper_borrow_non_sanctioned')} non-sanctioned"
            f" in signatures, bodies and fields -- target 0) over {c.get('ty_wrapper')} layout newtypes",
            *(f"  wrapper {label:<13}{sum(c.get(f'ty_wrapper_{fam}_' + k) or 0 for k in ('fn_sig_pub', 'fn_sig_priv', 'ty_pub_fields_pub', 'ty_pub_fields_priv', 'ty_priv'))}"
              f"   (fn signatures: pub {c.get(f'ty_wrapper_{fam}_fn_sig_pub')}, private {c.get(f'ty_wrapper_{fam}_fn_sig_priv')};"
              f" pub types: {c.get(f'ty_wrapper_{fam}_ty_pub_fields_pub')} pub fields + {c.get(f'ty_wrapper_{fam}_ty_pub_fields_priv')} private fields,"
              f" private types: {c.get(f'ty_wrapper_{fam}_ty_priv')})"
              for label, fam in (("by value", "by_val"), ("in std owner", "std_owner"))),
            f"  Deref on wrapper     by value: {c.get('ty_wrapper_deref_impl')} Deref + {c.get('ty_wrapper_deref_mut_impl')} DerefMut,"
            f" by pointer: {c.get('ptr_wrapper_deref_impl')} Deref + {c.get('ptr_wrapper_deref_mut_impl')} DerefMut   (target 0)",
            *(f"  shared borrow {label:<11}{c.get(f'{kind}_shared_borrow_rd')} rd + {c.get(f'{kind}_shared_borrow_wr')} wr"
              f" + {c.get(f'{kind}_shared_borrow_ffi_mut_arg')} *mut to C"
              f"   (wr through self {(doc.get('provenance') or {}).get(f'{kind}_shared_borrow_wr', {}).get('self')}{tail})"
              for label, kind, tail in (("by value", "ty_wrapper", "; wr target 0"), ("by pointer", "ptr_wrapper", ""))),
            f"  ffi calls            {c.get('ffi_calls')}",
        ]
    else:
        lines.append(f"  counts               unavailable — "
                     f"{doc.get('counts_unavailable')}")
    f = doc.get("ffibox")
    if f:
        n, by = f["counts"], f["by"]

        def keys(*counters: str) -> str:
            merged: dict[str, int] = {}
            for k in counters:
                for name, v in by[k].items():
                    merged[name] = merged.get(name, 0) + v
            return ", ".join(f"{name} {v}" for name, v in sorted(merged.items())) or "none"

        kinds = (("ffibox owner", "ffibox_owner"), ("ffibox handle", "ffibox_handle"),
                 ("own owner", "non_ffibox_owner"), ("own handle", "non_ffibox_handle"))
        lines.append("  ffibox")
        for name, k in kinds:
            pub, priv = f"fn_sig_{k}_pub", f"fn_sig_{k}_priv"
            lines.append(
                f"  {name + ' in fn sig':<30}{n[pub]} pub + {n[priv]} private   ({keys(pub, priv)})")
        for name, k in kinds:
            fp, fq, tp = f"ty_pub_fields_pub_{k}", f"ty_pub_fields_priv_{k}", f"ty_priv_{k}"
            lines.append(
                f"  {name + ' in fields':<30}pub types: {n[fp]} pub + {n[fq]} private fields,"
                f" private types: {n[tp]}   ({keys(fp, fq, tp)})")
        lines += [
            f"  ffibox trait impls   {n['ffibox_impl_macro']} by macro + {n['ffibox_impl_manual']} by hand"
            f"   (by hand: {keys('ffibox_impl_manual')})",
            f"  layout types         {n['ffibox_define_ctype_macro']} define_ctype! +"
            f" {n['ffibox_define_ctype_manual']} by hand",
            f"  CCell vs shape       {n['ffibox_ccell_not_layout']} CCell without layout shape,"
            f" {n['ffibox_layout_not_ccell']} layout without CCell"
            f"   ({keys('ffibox_ccell_not_layout', 'ffibox_layout_not_ccell')})",
            f"  own Drop impls       {n['drop_impl']}   ({keys('drop_impl')})",
            f"  own Clone impls      {n['clone_impl']}   ({keys('clone_impl')})",
        ]
    elif "ffibox" in doc:
        lines.append("  ffibox               unavailable — no counts")
    return "\n".join(lines)
