"""measure.py — the deterministic pass.

Runs the rustc driver (``ffimap/driver/``) over the subject workspace and
returns its tree-wide metrics block.

Resolution-aware because the questions are: which C type a pointer points at,
whether a reference covers memory C writes, what survived `cfg` and macro
expansion. None of that is answerable from source text.

WHAT IT COSTS. A rustc driver has to compile the crate, and an FFI wrapper
often needs system libraries that are not installed. When the build fails there
are NO counts rather than substitute ones: ``compose`` reports ``counts: null``
and says why. A number absent is recoverable; a number that looks like
ffimap's but was produced differently is not.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

# INSIDE the package, not beside it: package data cannot ship a sibling of
# `src/`, so only here does a non-editable `pip install` carry the crate.
_DRIVER_CRATE = Path(__file__).resolve().parent / "driver"

# The dated nightly the driver is written against. A `rustc_private` driver
# compiles only against the compiler internals it was ported to, so a floating
# `nightly` breaks the scan whenever the toolchain updates. Both the driver and
# the measured workspace build use this channel; `cargo +nightly` would
# override the crate's `rust-toolchain.toml` and defeat the pin.
_TOOLCHAIN = tomllib.loads(
    (_DRIVER_CRATE / "rust-toolchain.toml").read_text())["toolchain"]["channel"]

# Count fields summed across the per-crate emissions, and site arrays
# concatenated. The set the driver emits; kept explicit so a field added there
# is a visible edit here rather than a silent passthrough.
_COUNTS = (
    "code_lines", "total_stmts", "safe_fns_pub", "safe_fns_priv",
    "unsafe_blocks", "unsafe_block_stmts", "unsafe_block_lines",
    "unsafe_block_code_lines", "unsafe_blocks_wrapper_impl",
    "unsafe_blocks_ffi_export", "unsafe_fns", "unsafe_fns_pub",
    "unsafe_fns_priv", "unsafe_impls", "unsafe_traits",
    "unsafe_send_impl", "unsafe_sync_impl",
    "c_type_layout_wrapper",
    "c_type_borrow_fn_sig_sanctioned_pub",
    "c_type_borrow_fn_sig_sanctioned_priv",
    "c_type_borrow_fn_sig_non_sanctioned_pub",
    "c_type_borrow_fn_sig_non_sanctioned_priv",
    "c_type_borrow_fn_sig_opaque_pub",
    "c_type_borrow_fn_sig_opaque_priv",
    "c_type_borrow_fn_body_non_sanctioned",
    "c_type_borrow_fn_body_opaque",
    "c_type_borrow_fn_body_generic",
    "c_type_borrow_ty_non_sanctioned_pub_fields_pub",
    "c_type_borrow_ty_non_sanctioned_pub_fields_priv",
    "c_type_borrow_ty_non_sanctioned_priv",
    "c_type_borrow_ty_opaque_pub_fields_pub",
    "c_type_borrow_ty_opaque_pub_fields_priv",
    "c_type_borrow_ty_opaque_priv",
    "raw_ptr_as_slice_borrow",
    "c_type_by_val_fn_sig_pub", "c_type_by_val_fn_sig_priv",
    "c_type_by_val_ty_pub_fields_pub", "c_type_by_val_ty_pub_fields_priv",
    "c_type_by_val_ty_priv", "c_type_std_owner_fn_sig_pub",
    "c_type_std_owner_fn_sig_priv", "c_type_std_owner_ty_pub_fields_pub",
    "c_type_std_owner_ty_pub_fields_priv", "c_type_std_owner_ty_priv",
    "non_c_type_borrow_pub_safe", "non_c_type_borrow_pub_unsafe",
    "non_c_type_borrow_priv_safe", "non_c_type_borrow_priv_unsafe",
    "raw_ptr_ty_pub_fields_pub", "raw_ptr_ty_pub_fields_priv",
    "raw_ptr_ty_priv", "raw_ptr_fn_pub_safe", "raw_ptr_fn_pub_unsafe",
    "raw_ptr_fn_priv_safe", "raw_ptr_fn_priv_unsafe", "raw_ptr_has_c_type_wrapper",
    "safe_fns_seam_pub",
    "safe_fns_seam_priv",
    "unsafe_fns_seam_pub",
    "unsafe_fns_seam_priv",
    "raw_ptr_fn_seam_pub_safe",
    "raw_ptr_fn_seam_pub_unsafe",
    "raw_ptr_fn_seam_priv_safe",
    "raw_ptr_fn_seam_priv_unsafe",
    "raw_ptr_derefs_rd", "raw_ptr_derefs_wr", "raw_ptr_derefs_outside_impl",
    "void_ptr_ty_pub_fields_pub", "void_ptr_ty_pub_fields_priv",
    "void_ptr_ty_priv", "void_ptr_fn_pub_safe", "void_ptr_fn_pub_unsafe",
    "void_ptr_fn_priv_safe", "void_ptr_fn_priv_unsafe",
    "drop_impl", "clone_impl",
    "c_type_std_value_impl_pub", "c_type_std_value_impl_priv",
    "c_type_std_value_impl_derived", "ffi_calls",
)
#: The counters that count source locations, so `--sites` can list them. Line
#: and statement totals (`code_lines`, `total_stmts`, `unsafe_block_*lines`,
#: `unsafe_block_stmts`) have no sites.
SITE_COUNTERS = (
    "safe_fns_pub", "safe_fns_priv", "unsafe_blocks",
    "unsafe_blocks_wrapper_impl", "unsafe_blocks_ffi_export", "unsafe_fns",
    "unsafe_fns_pub", "unsafe_fns_priv", "unsafe_impls", "unsafe_traits",
    "unsafe_send_impl", "unsafe_sync_impl",
    "c_type_layout_wrapper",
    "c_type_borrow_fn_sig_sanctioned_pub",
    "c_type_borrow_fn_sig_sanctioned_priv",
    "c_type_borrow_fn_sig_non_sanctioned_pub",
    "c_type_borrow_fn_sig_non_sanctioned_priv",
    "c_type_borrow_fn_sig_opaque_pub",
    "c_type_borrow_fn_sig_opaque_priv",
    "c_type_borrow_fn_body_non_sanctioned",
    "c_type_borrow_fn_body_opaque",
    "c_type_borrow_fn_body_generic",
    "c_type_borrow_ty_non_sanctioned_pub_fields_pub",
    "c_type_borrow_ty_non_sanctioned_pub_fields_priv",
    "c_type_borrow_ty_non_sanctioned_priv",
    "c_type_borrow_ty_opaque_pub_fields_pub",
    "c_type_borrow_ty_opaque_pub_fields_priv",
    "c_type_borrow_ty_opaque_priv",
    "raw_ptr_as_slice_borrow",
    "c_type_by_val_fn_sig_pub", "c_type_by_val_fn_sig_priv",
    "c_type_by_val_ty_pub_fields_pub", "c_type_by_val_ty_pub_fields_priv",
    "c_type_by_val_ty_priv", "c_type_std_owner_fn_sig_pub",
    "c_type_std_owner_fn_sig_priv", "c_type_std_owner_ty_pub_fields_pub",
    "c_type_std_owner_ty_pub_fields_priv", "c_type_std_owner_ty_priv",
    "non_c_type_borrow_pub_safe",
    "non_c_type_borrow_pub_unsafe", "non_c_type_borrow_priv_safe",
    "non_c_type_borrow_priv_unsafe", "raw_ptr_ty_pub_fields_pub",
    "raw_ptr_ty_pub_fields_priv", "raw_ptr_ty_priv", "raw_ptr_fn_pub_safe",
    "raw_ptr_fn_pub_unsafe", "raw_ptr_fn_priv_safe", "raw_ptr_fn_priv_unsafe",
    "raw_ptr_has_c_type_wrapper", "raw_ptr_derefs_rd", "raw_ptr_derefs_wr", "raw_ptr_derefs_outside_impl",
    "safe_fns_seam_pub",
    "safe_fns_seam_priv",
    "unsafe_fns_seam_pub",
    "unsafe_fns_seam_priv",
    "raw_ptr_fn_seam_pub_safe",
    "raw_ptr_fn_seam_pub_unsafe",
    "raw_ptr_fn_seam_priv_safe",
    "raw_ptr_fn_seam_priv_unsafe",
    "void_ptr_ty_pub_fields_pub", "void_ptr_ty_pub_fields_priv",
    "void_ptr_ty_priv", "void_ptr_fn_pub_safe", "void_ptr_fn_pub_unsafe",
    "void_ptr_fn_priv_safe", "void_ptr_fn_priv_unsafe",
    "drop_impl", "clone_impl",
    "c_type_std_value_impl_pub", "c_type_std_value_impl_priv",
    "ffi_calls",
)
#: The owner and handle counters, in the driver's order. Each is a breakdown
#: `{type, handle kind or trait: N}` rather than a number, and each counts
#: source locations, so all of them take `--sites`. Always measured: the
#: `non_ffibox` half counts what the crate wrote itself, which holds with or
#: without ffibox.
FFIBOX_COUNTERS = (
    "fn_sig_ffibox_owner_pub", "fn_sig_ffibox_owner_priv",
    "fn_sig_ffibox_handle_pub", "fn_sig_ffibox_handle_priv",
    "fn_sig_non_ffibox_owner_pub", "fn_sig_non_ffibox_owner_priv",
    "fn_sig_non_ffibox_handle_pub", "fn_sig_non_ffibox_handle_priv",
    "ty_pub_fields_pub_ffibox_owner", "ty_pub_fields_priv_ffibox_owner",
    "ty_priv_ffibox_owner", "ty_pub_fields_pub_ffibox_handle",
    "ty_pub_fields_priv_ffibox_handle", "ty_priv_ffibox_handle",
    "ty_pub_fields_pub_non_ffibox_owner", "ty_pub_fields_priv_non_ffibox_owner",
    "ty_priv_non_ffibox_owner", "ty_pub_fields_pub_non_ffibox_handle",
    "ty_pub_fields_priv_non_ffibox_handle", "ty_priv_non_ffibox_handle",
    "ffibox_impl_macro", "ffibox_impl_manual", "ffibox_define_ctype_macro",
    "ffibox_define_ctype_manual", "ffibox_ccell_not_layout",
    "ffibox_layout_not_ccell",
)


class DriverUnavailable(Exception):
    """The driver could not measure this tree. Carries the reason to report."""


# ---------------------------------------------------------------- nesting
#
# `counts` is emitted as a TREE. The driver counts flat, suffixed names
# (`raw_ptr_fn_pub_safe`); this spec folds them into one record per family so
# that the parent total is in the document rather than reconstructed by a
# consumer who has to know which suffixes belong together.
#
# Two relationships, which the flat names could not tell apart:
#
#   * a PARTITION -- disjoint children that sum to the parent. `pub` + `priv`,
#     `safe` + `unsafe`, a public type's `pub` + `priv` fields.
#   * an `of_which` SUBSET -- a child that re-counts some of the parent's own
#     occurrences from another angle, so it must NEVER be summed in.
#     `unsafe_blocks_wrapper_impl` is a subset of `unsafe_blocks`;
#     `unsafe_send_impl` is "of `unsafe_impls`";
#     `raw_ptr_derefs_outside_impl` is "of both" rd and wr;
#     `raw_ptr_has_c_type_wrapper` is "of those positions".
#
# `sites` and the `--ffibox` `by` breakdowns stay keyed by the flat LEAF name:
# a site list and a breakdown belong to one leaf, not to a parent.

#: flat leaf name -> path in the tree. Partition leaves only.
_PARTITION: dict[str, tuple[str, ...]] = {}
for _stem in ("raw_ptr", "void_ptr", "c_type_by_val", "c_type_std_owner"):
    _ty = f"{_stem}_ty"
    _PARTITION[f"{_ty}_pub_fields_pub"] = (_ty, "pub", "fields", "pub")
    _PARTITION[f"{_ty}_pub_fields_priv"] = (_ty, "pub", "fields", "priv")
    _PARTITION[f"{_ty}_priv"] = (_ty, "priv")
for _stem in ("raw_ptr", "void_ptr"):
    for _v in ("pub", "priv"):
        for _s in ("safe", "unsafe"):
            _PARTITION[f"{_stem}_fn_{_v}_{_s}"] = (f"{_stem}_fn", _v, _s)
for _stem in ("c_type_by_val", "c_type_std_owner"):
    for _v in ("pub", "priv"):
        _PARTITION[f"{_stem}_fn_sig_{_v}"] = (f"{_stem}_fn_sig", _v)
for _v in ("pub", "priv"):
    for _s in ("safe", "unsafe"):
        _PARTITION[f"non_c_type_borrow_{_v}_{_s}"] = ("non_c_type_borrow", _v, _s)
    _PARTITION[f"safe_fns_{_v}"] = ("safe_fns", _v)
    _PARTITION[f"unsafe_fns_{_v}"] = ("unsafe_fns", _v)
_PARTITION["raw_ptr_derefs_rd"] = ("raw_ptr_derefs", "rd")
_PARTITION["raw_ptr_derefs_wr"] = ("raw_ptr_derefs", "wr")
# Borrows into C memory: POSITION first, then kind, then visibility. Only the
# kinds that occur in a position exist (see the driver's `Counts`): no
# `fn_sig.generic`, no `fn_body.sanctioned`, no `ty.sanctioned`.
for _k in ("sanctioned", "non_sanctioned", "opaque"):
    for _v in ("pub", "priv"):
        _PARTITION[f"c_type_borrow_fn_sig_{_k}_{_v}"] = ("c_type_borrow", "fn_sig", _k, _v)
for _k in ("non_sanctioned", "opaque", "generic"):
    _PARTITION[f"c_type_borrow_fn_body_{_k}"] = ("c_type_borrow", "fn_body", _k)
for _k in ("non_sanctioned", "opaque"):
    _PARTITION[f"c_type_borrow_ty_{_k}_pub_fields_pub"] = ("c_type_borrow", "ty", _k, "pub", "fields", "pub")
    _PARTITION[f"c_type_borrow_ty_{_k}_pub_fields_priv"] = ("c_type_borrow", "ty", _k, "pub", "fields", "priv")
    _PARTITION[f"c_type_borrow_ty_{_k}_priv"] = ("c_type_borrow", "ty", _k, "priv")

#: flat leaf name -> (parent path, name under `of_which`). Never summed.
_PARTITION["c_type_std_value_impl_pub"] = ("c_type_std_value_impl", "pub")
_PARTITION["c_type_std_value_impl_priv"] = ("c_type_std_value_impl", "priv")

_OF_WHICH: dict[str, tuple[tuple[str, ...], str]] = {
    "unsafe_blocks_wrapper_impl": (("unsafe_blocks",), "wrapper_impl"),
    "unsafe_blocks_ffi_export": (("unsafe_blocks",), "ffi_export"),
    "unsafe_send_impl": (("unsafe_impls",), "send"),
    "unsafe_sync_impl": (("unsafe_impls",), "sync"),
    "raw_ptr_derefs_outside_impl": (("raw_ptr_derefs",), "outside_impl"),
    # Of the C types implementing a forced-`&self` std trait, those where at
    # least one such impl is derived: the borrow over C memory was never
    # weighed. A subset of the total, so never summed in.
    "c_type_std_value_impl_derived": (("c_type_std_value_impl",), "derived"),
    # `--seams` names: the share of each fn-signature leaf that is seam
    # plumbing -- the conversion between a wrapper and its raw pointer -- which
    # a consumer of the safe API never performs. A subset, never summed in.
    "safe_fns_seam_pub": (("safe_fns", "pub"), "seam"),
    "safe_fns_seam_priv": (("safe_fns", "priv"), "seam"),
    "unsafe_fns_seam_pub": (("unsafe_fns", "pub"), "seam"),
    "unsafe_fns_seam_priv": (("unsafe_fns", "priv"), "seam"),
    "raw_ptr_fn_seam_pub_safe": (("raw_ptr_fn", "pub", "safe"), "seam"),
    "raw_ptr_fn_seam_pub_unsafe": (("raw_ptr_fn", "pub", "unsafe"), "seam"),
    "raw_ptr_fn_seam_priv_safe": (("raw_ptr_fn", "priv", "safe"), "seam"),
    "raw_ptr_fn_seam_priv_unsafe": (("raw_ptr_fn", "priv", "unsafe"), "seam"),
}

#: the paths that carry an `of_which`, so a PARTITION leaf landing on one is
#: stored as `{"total": n}` rather than a bare number and still has somewhere
#: to hang its subset.
_OF_WHICH_PARENTS: frozenset[tuple[str, ...]] = frozenset(
    parent for parent, _ in _OF_WHICH.values())

#: a flat counter that is already a family's total: cross-checked, not stored
#: twice. `unsafe_fns` == `unsafe_fns_pub` + `unsafe_fns_priv`.
_PARENT_TOTALS: dict[str, tuple[str, ...]] = {"unsafe_fns": ("unsafe_fns",)}

#: a flat counter that is a family's total but has NO partition children, only
#: `of_which` subsets -- so its total is the emitted number, never a sum.
_EXPLICIT_TOTAL: frozenset[str] = frozenset({"unsafe_blocks", "unsafe_impls"})

# `raw_ptr_has_c_type_wrapper` and `raw_ptr_as_slice_borrow` stay top-level
# scalars. The first is a subset of the `raw_ptr_ty` AND `raw_ptr_fn` positions
# together, the second counts borrows rather than positions, so neither has one
# parent whose total would mean anything.


def _set(tree: dict, path: tuple[str, ...], value) -> None:
    node = tree
    for k in path[:-1]:
        node = node.setdefault(k, {})
        if not isinstance(node, dict):
            raise AssertionError(f"nesting conflict at {path}")
    node[path[-1]] = value


def _totals(node: dict) -> int:
    """Depth-first: give every internal node a `total` that sums its PARTITION
    children, ignoring `of_which`, and return it.

    A node that already carries an explicit `total` keeps it: it came from a
    flat counter the driver emits for the whole family (`unsafe_blocks`), whose
    only children are `of_which` subsets that must not be summed.
    """
    if "of_which" in node and not isinstance(node["of_which"], dict):
        raise AssertionError("of_which must be a record")
    if isinstance(node.get("total"), int):
        for k, v in node.items():
            if k not in ("total", "of_which") and isinstance(v, dict):
                _totals(v)
        return node["total"]
    total = 0
    for k, v in node.items():
        if k in ("total", "of_which"):
            continue
        total += _totals(v) if isinstance(v, dict) else int(v)
    node["total"] = total
    return total


def nest_counts(flat: dict) -> dict:
    """Fold the driver's flat counters into the tree described above.

    Every name in ``flat`` must be placed, so a counter added to the driver
    fails here rather than vanishing from the document.
    """
    tree: dict = {}
    # Ordered passes: a family's node must exist as a record before an
    # `of_which` subset is hung off it, and `unsafe_blocks` / `unsafe_impls`
    # are flat counters that become their family's explicit total.
    for name, value in flat.items():
        if name in _PARTITION:
            path = _PARTITION[name]
            if path in _OF_WHICH_PARENTS:
                _set(tree, path + ("total",), int(value))
            else:
                _set(tree, path, int(value))
    for name in _EXPLICIT_TOTAL:
        if name in flat:
            _set(tree, (name, "total"), int(flat[name]))
    for name, value in flat.items():
        if name in _PARTITION or name in _OF_WHICH or name in _PARENT_TOTALS \
                or name in _EXPLICIT_TOTAL:
            continue
        tree[name] = int(value)           # a scalar with no family
    for name, value in flat.items():
        if name in _OF_WHICH:
            parent, leaf = _OF_WHICH[name]
            _set(tree, parent + ("of_which", leaf), int(value))
    for node in tree.values():
        if isinstance(node, dict):
            _totals(node)
    for name, path in _PARENT_TOTALS.items():
        if name in flat:
            node = tree
            for k in path:
                node = node[k]
            if node["total"] != int(flat[name]):
                raise AssertionError(
                    f"{name}={flat[name]} but its children sum to {node['total']}")
    return tree


#: the `--ffibox` leaves, folded the same way.
_FFIBOX_PARTITION: dict[str, tuple[str, ...]] = {}
for _box in ("ffibox", "non_ffibox"):
    for _kind in ("owner", "handle"):
        for _v in ("pub", "priv"):
            _FFIBOX_PARTITION[f"fn_sig_{_box}_{_kind}_{_v}"] = ("fn_sig", _box, _kind, _v)
        _FFIBOX_PARTITION[f"ty_pub_fields_pub_{_box}_{_kind}"] = ("ty", _box, _kind, "pub", "fields", "pub")
        _FFIBOX_PARTITION[f"ty_pub_fields_priv_{_box}_{_kind}"] = ("ty", _box, _kind, "pub", "fields", "priv")
        _FFIBOX_PARTITION[f"ty_priv_{_box}_{_kind}"] = ("ty", _box, _kind, "priv")


def nest_ffibox(flat: dict) -> dict:
    """Fold the `--ffibox` counter totals into the same tree shape. The
    remaining counters (`ffibox_impl_*`, `ffibox_define_ctype_*`,
    `ffibox_ccell_not_layout`, `ffibox_layout_not_ccell`) have no visibility
    split and stay scalars."""
    tree: dict = {}
    for name, value in flat.items():
        if name in _FFIBOX_PARTITION:
            _set(tree, _FFIBOX_PARTITION[name], int(value))
        else:
            tree[name] = int(value)
    for node in tree.values():
        if isinstance(node, dict):
            _totals(node)
    return tree



def _at(tree: dict, path: tuple[str, ...]):
    node = tree
    for k in path:
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node


def flatten_counts(tree: dict) -> dict:
    """The inverse of :func:`nest_counts`, for consumers that want the flat
    names (the human summary, and the round-trip test that keeps the two
    specs honest)."""
    flat: dict = {}
    for name, path in _PARTITION.items():
        v = _at(tree, path + ("total",)) if path in _OF_WHICH_PARENTS else _at(tree, path)
        if v is not None:
            flat[name] = v
    for name, (parent, leaf) in _OF_WHICH.items():
        v = _at(tree, parent + ("of_which", leaf))
        if v is not None:
            flat[name] = v
    for name, path in _PARENT_TOTALS.items():
        v = _at(tree, path + ("total",))
        if v is not None:
            flat[name] = v
    for name in _EXPLICIT_TOTAL:
        v = _at(tree, (name, "total"))
        if v is not None:
            flat[name] = v
    for name, v in tree.items():
        if not isinstance(v, dict):
            flat[name] = v
    return flat


def flatten_ffibox(tree: dict) -> dict:
    """The inverse of :func:`nest_ffibox`."""
    flat: dict = {}
    for name, path in _FFIBOX_PARTITION.items():
        v = _at(tree, path)
        if v is not None:
            flat[name] = v
    for name, v in tree.items():
        if not isinstance(v, dict):
            flat[name] = v
    return flat

def sys_crates(ws: Path, extra: list[str] | None = None) -> list[str]:
    """The crates whose `#[repr(C)]` types are C's, by crate (lib target)
    name: every package in the build's dependency graph with a Cargo `links`
    key or named `*-sys` (bindings that link nothing themselves, such as
    `pcre2-sys`, set no `links`), plus ``extra``. `cargo metadata` resolves the graph; when it cannot,
    only the workspace's own packages are read."""
    names: set[str] = {n.replace("-", "_") for n in extra or ()}
    for args in (["--format-version", "1"], ["--no-deps", "--format-version", "1"]):
        r = subprocess.run(["cargo", "metadata", *args], cwd=ws,
                           capture_output=True, text=True)
        if r.returncode == 0:
            for pkg in json.loads(r.stdout)["packages"]:
                if not (pkg.get("links") or pkg["name"].endswith(("-sys", "_sys"))):
                    continue
                libs = [t["name"] for t in pkg["targets"]
                        if {"lib", "rlib", "staticlib", "cdylib", "dylib"} & set(t["kind"])]
                names.update(n.replace("-", "_") for n in libs or [pkg["name"]])
            break
    return sorted(names)


def _collect_emissions(stdout: str, sys: set[str] | frozenset = frozenset()
                       ) -> tuple[dict, dict, int, dict]:
    """Merge driver JSON lines; return counts, sites, crate count, and the
    `--ffibox` breakdowns (empty unless the driver emitted them). Sys crates
    -- named `*_sys`, or in ``sys`` -- are bindings, never the subject."""
    out = {k: 0 for k in _COUNTS}
    sites: dict[str, list] = {k: [] for k in SITE_COUNTERS}
    ffibox: dict[str, dict[str, int]] = {}
    seen = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not (line.startswith("{") and '"crate"' in line):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        crate = d.get("crate", "")
        if crate.endswith("_sys") or crate in sys:
            continue
        if "ffibox" in d:
            for k in FFIBOX_COUNTERS:
                by = ffibox.setdefault(k, {})
                for name, n in d["ffibox"].get(k, {}).items():
                    by[name] = by.get(name, 0) + int(n)
            for k, rows in d.get("sites", {}).items():
                sites.setdefault(k, []).extend(rows)
            continue
        if "unsafe_blocks" not in d:
            continue
        seen += 1
        for k in _COUNTS:
            out[k] += int(d.get(k, 0))
        for k, rows in d.get("sites", {}).items():
            sites.setdefault(k, []).extend(rows)
    return out, sites, seen, ffibox


def _driver_bin() -> Path:
    """Build the driver if it is not current, and return its path.

    Needs the dated nightly in the crate's own ``rust-toolchain.toml``, with
    ``rustc-dev`` and ``llvm-tools``.

    ALWAYS asks cargo, rather than reusing whatever binary is on disk. A
    `rustc_private` driver links against the exact compiler it was built with,
    and nightly moves daily — so a binary built last week against a different
    nightly loads, runs, and dies on an undefined symbol. Cargo's fingerprint
    already tracks the compiler version, so this is a no-op when nothing
    changed and a rebuild exactly when one is needed.

    Reusing a stale binary is worse than failing: the symbol error surfaces as
    a non-zero `cargo build` in :func:`measure`, which reports it as "the
    workspace does not compile" — a true statement about the wrong program.
    """
    bin_path = _DRIVER_CRATE / "target" / "debug" / "ffimap-driver"
    if shutil.which("cargo") is None:
        if bin_path.is_file():
            return bin_path
        raise DriverUnavailable(
            "the driver is not built and `cargo` is not on PATH")
    if not bin_path.is_file():
        # stderr: `--json` owns stdout.
        print("[ffimap] building the HIR driver (first run only)…",
              file=sys.stderr)
    # The caller's CARGO_TARGET_DIR is for the audited workspace. Inherited
    # here, it would build the driver somewhere other than `bin_path` -- a
    # full rebuild that needs `rustc-dev`, then a stale binary run anyway.
    env = {k: v for k, v in os.environ.items() if k != "CARGO_TARGET_DIR"}
    r = subprocess.run(["cargo", f"+{_TOOLCHAIN}", "build"], cwd=_DRIVER_CRATE,
                       env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise DriverUnavailable(f"driver build failed:\n{r.stderr[-1500:]}")
    return bin_path


def _bust_cache(ws: Path) -> None:
    """Touch every workspace target so cargo recompiles.

    The driver only emits while rustc actually compiles a crate, and nothing
    about running it is in cargo's fingerprint — so a second audit over an
    unchanged tree would be served from cache and measure nothing.

    The roots come from cargo rather than a glob: a glob has to assume both a
    depth and a `src/` directory, and a workspace owes neither. git2-rs breaks
    both at once — `git2` is the root crate and `libgit2-sys` sets
    `path = "lib.rs"`.
    """
    meta = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=ws, capture_output=True, text=True)
    if meta.returncode != 0:
        raise DriverUnavailable(
            f"`cargo metadata` failed:\n{meta.stderr[-1200:]}")
    for pkg in json.loads(meta.stdout)["packages"]:
        for tgt in pkg["targets"]:
            root = Path(tgt["src_path"])
            if root.is_file():
                root.touch()


def measure(ws: Path, ffibox: bool = False, sys: list[str] | None = None,
            seams: list[str] | None = None) -> tuple[dict, dict, dict | None]:
    """Return ``(tree-wide counts, sites per counter, ffibox breakdowns)`` for
    ``ws``. The breakdowns are ``None`` unless ``ffibox`` asked for them.
    ``sys`` are the sys crates (``sys_crates``): their `#[repr(C)]` types are
    C's, and their emissions are skipped."""
    driver = _driver_bin()
    sysroot = subprocess.run(["rustc", f"+{_TOOLCHAIN}", "--print", "sysroot"],
                             capture_output=True, text=True).stdout.strip()
    if not sysroot:
        raise DriverUnavailable(
            f"no {_TOOLCHAIN} toolchain (`rustup toolchain install {_TOOLCHAIN} "
            "--component rustc-dev --component llvm-tools`)")
    _bust_cache(ws)

    env = dict(os.environ)
    env["RUSTC"] = str(driver)
    env["SYSROOT"] = sysroot
    ld = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{sysroot}/lib" + (f":{ld}" if ld else "")
    if ffibox:
        env["UM_FFIBOX"] = "1"
    env["UM_SYS_CRATES"] = ",".join(sys or ())
    env["UM_SEAM_FNS"] = ",".join(seams or ())

    r = subprocess.run(["cargo", f"+{_TOOLCHAIN}", "build"], cwd=ws, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise DriverUnavailable(
            "the workspace does not compile under the HIR auditor — an FFI "
            "wrapper usually needs its system libraries installed.\n"
            f"{r.stderr[-1200:]}")

    # `-sys` crates are generated bindings, never the audit subject.
    out, sites, seen, ffibox_counts = _collect_emissions(r.stdout, set(sys or ()))
    if not seen:
        raise DriverUnavailable(
            "no crate emitted metrics — the build was served from cache, so "
            "nothing was measured")
    return out, sites, ffibox_counts
