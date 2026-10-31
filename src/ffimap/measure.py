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
import time
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

# The tree counters of docs/schema.md, by prefix and the family under it.
#
# `--sites` validates a dotted name against this rather than against a list of
# every leaf. The leaves below a family are open on purpose: the ffibox arms
# are generated from a vocabulary of 17 traits and 10 primitives, so an
# exhaustive list would be a second copy of the schema that drifts from the
# driver's. The two segments checked are the ones a typo lands in.
TREE_SITE_FAMILIES = {
    "raw_ptr": ("taken", "returned", "deref", "casted_to"),
    "void_ptr": ("taken", "returned"),
    "ty": ("storing_raw_ptr", "field", "impl", "wrapping_unsafe_cell", "total"),
    "fn": ("safe", "unsafe", "ffibox", "total"),
    "code": ("loc", "unsafe_block", "unsafe_call"),
}


def is_tree_counter(name: str) -> bool:
    """True when `name` is a dotted path into a known schema family."""
    head, _, rest = name.partition(".")
    family = rest.partition(".")[0]
    return bool(rest) and family in TREE_SITE_FAMILIES.get(head, ())


class DriverUnavailable(Exception):
    """The driver could not measure this tree. Carries the reason to report."""


# ---------------------------------------------------------------- nesting
#
# The counters are a TREE: the driver emits dotted keys (`raw_ptr.taken.safe.pub`)
# and `nest_ptr` folds them into records, so a parent total is in the document
# rather than reconstructed by a consumer who has to know which leaves belong
# together.
#
# Two relationships, which a flat name could not tell apart:
#
#   * a PARTITION -- disjoint children that sum to the parent. `pub` + `priv`,
#     `safe` + `unsafe`.
#   * an `of_which` SUBSET -- a child that re-counts some of the parent's own
#     occurrences from another angle, so it must NEVER be summed in.
#     `code.unsafe_block.of_which.ffi_export` is a subset of the blocks
#     `code.unsafe_block.total` counted.
#
# `sites` stays keyed by the leaf's dotted name: a site list belongs to one
# leaf, not to a parent.


def sys_crates(named: list[str] | None = None) -> list[str]:
    """The crates whose `#[repr(C)]` types are C's and whose types the field
    walk descends through, by crate (lib target) name: exactly the ones
    ``--sys-crates`` named, with `-` normalized to `_`.

    They are not discovered. Both signals that look like they would do it
    over-report: `prettyplease` carries a Cargo `links` key to detect
    duplicate versions of itself, and bindgen's `clang_sys` matches `*-sys`,
    yet neither is any part of the scanned crate's C surface. Each would land
    in the peel set and have its `#[repr(C)]` types taken for C's. What the
    caller names cannot be wrong that way, so an empty set means a crate with
    no C below it rather than a crate whose C went unfound."""
    return sorted({n.replace("-", "_") for n in named or ()})


def _collect_emissions(stdout: str, sys: set[str] | frozenset = frozenset()
                       ) -> tuple[dict, int, dict]:
    """Merge driver JSON lines; return the sites, the crate count and the flat
    counter keys. Sys crates -- named `*_sys`, or in ``sys`` -- are bindings,
    never the subject."""
    sites: dict[str, list] = {}
    ptr: dict[str, int] = {}
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
        if "counts" not in d:
            continue
        seen += 1
        for k, n in d.get("counts", {}).items():
            ptr[k] = ptr.get(k, 0) + int(n)
        for k, rows in d.get("sites", {}).items():
            sites.setdefault(k, []).extend(rows)
    return sites, seen, ptr


def nest_ptr(flat: dict[str, int]) -> dict:
    """Nest the driver's dotted counter keys into the schema's tree.

    Derived ``total`` keys are added bottom-up, summing every child except
    ``of_which``, whose children are overlapping shares and are never summed.

    Two nodes are left without one. A top-level prefix, because summing across
    families there would mix grains -- ``raw_ptr.taken`` counts signature
    positions and ``raw_ptr.deref`` counts body sites, and their sum means
    nothing. And any node that already carries a ``total``, which is how the
    explicit denominators ``ty.total`` and ``code.loc.total`` survive.
    """
    tree: dict = {}
    for key, n in flat.items():
        node = tree
        parts = key.split(".")
        for part in parts[:-1]:
            nxt = node.setdefault(part, {})
            if not isinstance(nxt, dict):          # a leaf and a node collided
                raise ValueError(f"counter {key!r} nests under a leaf")
            node = nxt
        prev = node.get(parts[-1], 0)
        if isinstance(prev, dict):
            raise ValueError(f"counter {key!r} is both a leaf and a prefix")
        node[parts[-1]] = prev + int(n)

    def totals(node: dict, depth: int, is_of_which: bool) -> int:
        subtotal = 0
        for name, child in list(node.items()):
            if isinstance(child, dict):
                got = totals(child, depth + 1, name == "of_which")
                if name != "of_which":
                    subtotal += got
            elif name != "of_which":
                subtotal += child
        # The `of_which` node itself gets none: its children are overlapping
        # shares, so their sum is not a quantity. Each share still does -- the
        # `pub` / `priv` split inside one share is a partition.
        if depth > 1 and "total" not in node and not is_of_which:
            node["total"] = subtotal
            return subtotal
        got = node.get("total")
        return got if isinstance(got, int) else subtotal

    totals(tree, 0, False)
    return tree


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
    # A strictly future mtime, not `touch()`. Cargo compares the recorded
    # fingerprint against the file's mtime, and two scans less than a
    # filesystem tick apart leave that mtime unchanged -- so the second is
    # served from cache and measures nothing. A canary that scanned the same
    # fixture twice in one process hit exactly that.
    stamp = time.time() + 1
    for pkg in json.loads(meta.stdout)["packages"]:
        for tgt in pkg["targets"]:
            root = Path(tgt["src_path"])
            if root.is_file():
                os.utime(root, (stamp, stamp))


def measure(ws: Path, ffibox: bool = False, sys: list[str] | None = None,
            seams: list[str] | None = None) -> tuple[dict, dict]:
    """Return ``(sites per counter, the counter tree)`` for ``ws``.

    ``ffibox`` asserts the crate is built on ffibox, which turns on the
    vocabulary's arms (`ty.field.ffibox`, `ty.impl.ffibox`, `fn.ffibox`).
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
    sites, seen, ptr = _collect_emissions(r.stdout, set(sys or ()))
    if not seen:
        raise DriverUnavailable(
            "no crate emitted metrics — the build was served from cache, so "
            "nothing was measured")
    return sites, nest_ptr(ptr)
