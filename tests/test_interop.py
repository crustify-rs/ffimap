"""How a crate meets C from the Rust side, over a fixture hand-derived item by item.

`tests/fixtures/interop/` is a crate built on a stub named `ffibox`, scanned
with `--ffibox` and `--regions ffi_import,ffi_export`. Every expectation below
is read off the annotations in its `lib.rs`, and the negatives carry as much
weight as the positives: a box kept rather than handed over, a foreign
declaration, a trait impl's signature.

Needs the driver, so it skips where cargo and the dated nightly are missing.
"""

import shutil
import unittest
from pathlib import Path

from ffimap import measure, scan

FIXTURE = Path(__file__).parent / "fixtures" / "interop"
REGIONS = ["ffi_import", "ffi_export"]


def _driver_available() -> bool:
    """cargo on the PATH and the driver buildable, as in test_canary."""
    if shutil.which("cargo") is None:
        return False
    try:
        measure._driver_bin()
    except Exception:
        return False
    return True


def at(tree: dict, path: str) -> int | None:
    """A leaf by its dotted path; `None` where the tree has no such node."""
    node = tree
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, int) else node.get("total")


@unittest.skipUnless(_driver_available(), "needs cargo and the dated nightly")
class InteropTests(unittest.TestCase):
    tree: dict
    bare: dict
    sites: dict

    @classmethod
    def setUpClass(cls) -> None:
        wanted = ["fn.extern_abi.pub", "code.fn_ptr.extern_abi.local",
                  "raw_ptr.surrendered.ffibox.owner",
                  "code.unsafe_block.of_which.outside_regions",
                  "static.of_which.mut.pub", "fn.sig.of_which.c_type.ret.pub"]
        doc = scan.compose(FIXTURE, ffibox=True, regions=REGIONS,
                           barriers=["guard"], sites=wanted)
        cls.tree, cls.sites = doc["counts"], doc["sites"]
        cls.bare = scan.compose(FIXTURE)["counts"]

    def eq(self, path: str, n: int) -> None:
        self.assertEqual(at(self.tree, path), n, path)

    # ------------------------------------------------- the fns C calls

    def test_extern_abi_fns_and_their_shares(self) -> None:
        # interop_add, interop_guarded, barrier_guarded, interop_widget_free;
        # on_event and interop_export_read, whose module is private.
        self.eq("fn.extern_abi.pub", 4)
        self.eq("fn.extern_abi.priv", 3)
        self.eq("fn.extern_abi.of_which.exported.pub", 3)
        self.eq("fn.extern_abi.of_which.exported.priv", 1)
        self.eq("fn.extern_abi.of_which.macro.pub", 1)
        self.eq("fn.extern_abi.of_which.raw_ptr_sig.pub", 1)
        self.eq("fn.extern_abi.of_which.raw_ptr_sig.priv", 2)
        self.eq("fn.extern_abi.of_which.ffibox_sig.pub", 1)
        self.eq("fn.extern_abi.of_which.ffibox_macro.pub", 1)

    def test_a_panic_barrier_is_std_or_the_conventions(self) -> None:
        # catch_unwind always; ffibox's barrier only under --ffibox; the
        # crate's own `guard` only with --barriers naming it.
        self.eq("fn.extern_abi.of_which.catches_unwind.pub", 2)
        self.assertEqual(at(self.bare, "fn.extern_abi.of_which.catches_unwind.pub"), 1)
        self.eq("fn.extern_abi.of_which.catches_unwind.priv", 1)
        self.assertEqual(at(self.bare, "fn.extern_abi.of_which.catches_unwind.priv"), 0)
        self.eq("code.call.ffibox.barrier", 1)

    # ------------------------------------------------- what Rust hands C

    def test_fn_pointers_by_whose_fn(self) -> None:
        self.eq("code.fn_ptr.extern_abi.local", 2)    # a coercion and a cast
        self.eq("code.fn_ptr.extern_abi.foreign", 1)  # a C fn handed back
        self.eq("code.fn_ptr.extern_abi.other", 0)
        self.eq("code.fn_ptr.extern_abi.ffibox", 2)  # trampoline, release_fn

    def test_surrendered_by_vocabulary_and_shape(self) -> None:
        self.eq("raw_ptr.surrendered.std.owner", 1)
        self.eq("raw_ptr.surrendered.std.string", 1)
        self.eq("raw_ptr.surrendered.ffibox.owner", 2)
        self.eq("raw_ptr.surrendered.ffibox.string", 1)

    def test_statics_the_crate_defines(self) -> None:
        # LIMIT and interop_flag; STATE. The foreign `sys_global` is none.
        self.eq("static.total.pub", 2)
        self.eq("static.total.priv", 1)
        self.eq("static.of_which.mut.pub", 1)
        self.eq("static.of_which.mut.priv", 1)
        self.eq("static.of_which.exported.pub", 1)
        self.eq("static.of_which.exported.priv", 0)

    def test_a_type_a_macro_wrote_is_a_share(self) -> None:
        self.eq("ty.total.of_which.macro.pub", 1)
        self.eq("ty.total.of_which.macro.priv", 0)

    def test_layouts_shared_with_c(self) -> None:
        self.eq("ty.total.of_which.repr_c.pub", 1)
        self.eq("ty.total.of_which.repr_c.priv", 1)
        self.eq("ty.total.of_which.repr_transparent.pub", 1)
        self.eq("ty.total.of_which.repr_transparent.priv", 0)

    # ------------------------------------------------- what a consumer meets

    def test_c_types_in_the_signatures_the_crate_chose(self) -> None:
        # arg: interop_add 2, checked 1, checked_zero 1. ret: interop_add,
        # interop_guarded, barrier_guarded, register_cast, register_other,
        # give_cstring, give_cstr, checked_zero 1 each, checked 2. The trait
        # impls' `fmt` and `from` are their traits'.
        self.eq("fn.sig.of_which.c_type.arg.pub", 4)
        self.eq("fn.sig.of_which.c_type.ret.pub", 10)
        self.eq("fn.sig.of_which.c_type.arg.priv", 0)
        self.eq("fn.sig.of_which.c_type.ret.priv", 1)  # guarded_by_helper

    def test_result_returns_outside_trait_impls(self) -> None:
        # `fmt` returns `fmt::Result`, which its trait chose.
        self.eq("fn.sig.of_which.result.ret.pub", 2)
        self.eq("fn.sig.of_which.result.ret.priv", 1)

    def test_status_calls(self) -> None:
        self.eq("code.call.ffibox.status", 2)

    def test_std_traits_per_type(self) -> None:
        s = "ty.total.of_which.std_impl"
        for tr, n in {"Debug": 3, "Display": 2, "Clone": 1, "Default": 1,
                      "PartialEq": 1, "From": 1, "Error": 1, "Iterator": 1,
                      "Eq": 0, "Hash": 0}.items():
            self.eq(f"{s}.{tr}.pub", n)
        for tr, n in {"PartialEq": 1, "Eq": 1, "Hash": 1, "Debug": 0}.items():
            self.eq(f"{s}.{tr}.priv", n)

    def test_the_new_primitives_are_vocabulary(self) -> None:
        self.eq("fn.sig.of_which.ffibox.arg.CPayload.pub", 2)
        # give_cbox, and the exported release's `Option<CBox<u8>>`
        self.eq("fn.sig.of_which.ffibox.arg.CBox.pub", 2)
        self.eq("fn.sig.of_which.ffibox.arg.CFnBox.pub", 0)

    # ------------------------------------------------- regions

    def test_unsafe_blocks_by_region(self) -> None:
        self.eq("code.unsafe_block.of_which.region.ffi_import", 3)
        self.eq("code.unsafe_block.of_which.region.ffi_export", 1)
        # register, outside, outside_unsafe, and std's own block in the
        # `write!` a Display impl expands: another crate's macro, outside
        # every region, which a lint on the crate's own code cannot see.
        self.eq("code.unsafe_block.of_which.outside_regions", 4)
        self.eq("code.unsafe_block.total", 8)

    def test_unsafe_fns_outside_regions(self) -> None:
        self.eq("fn.unsafe.of_which.outside_regions.pub", 1)
        self.eq("fn.unsafe.of_which.outside_regions.priv", 0)

    # ------------------------------------------------- gating, and sites

    def test_the_flagged_counters_are_absent_without_their_flag(self) -> None:
        for path in ("code.unsafe_block.of_which.region",
                     "code.unsafe_block.of_which.outside_regions",
                     "fn.unsafe.of_which.outside_regions",
                     "code.call.ffibox", "code.fn_ptr.extern_abi.ffibox",
                     "raw_ptr.surrendered.ffibox",
                     "fn.extern_abi.of_which.ffibox_sig"):
            with self.subTest(counter=path):
                self.assertIsNone(at(self.bare, path))
        # The unflagged ones read the same either way.
        for path in ("fn.extern_abi.pub", "code.fn_ptr.extern_abi.local",
                     "raw_ptr.surrendered.std.owner", "static.total.pub"):
            with self.subTest(counter=path):
                self.assertEqual(at(self.bare, path), at(self.tree, path))

    def test_sites_sum_to_their_counters(self) -> None:
        for name, rows in self.sites.items():
            with self.subTest(counter=name):
                self.assertEqual(sum(r["count"] for r in rows), at(self.tree, name))
                self.assertTrue(all(r["file"].endswith("lib.rs") for r in rows))
