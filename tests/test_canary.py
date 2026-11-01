"""End-to-end counts over a fixture whose expected values are hand-derived.

Every assertion below is read off `tests/fixtures/canary/`, where each item is
annotated with the counters it should move. The point is the NEGATIVES as much
as the positives: an item that moves a counter it should not is as much a
defect as one that fails to move the counter it should, and a unit test over
the classifier functions would catch neither.

Needs the driver, so it needs cargo and the dated nightly. It skips rather
than fails where those are missing; `measure.DriverUnavailable` is how that is
reported.
"""

import shutil
import unittest
from pathlib import Path

from ffimap import measure, scan

FIXTURE = Path(__file__).parent / "fixtures" / "canary"


def _driver_available() -> bool:
    """cargo on the PATH and the driver buildable.

    `_driver_bin` alone is not the precondition: it can hand back a path
    while `cargo metadata`, which the scan runs next, still fails with
    FileNotFoundError. Checking the executable first makes the skip fire on a
    host without a Rust toolchain instead of erroring in setUpClass.
    """
    if shutil.which("cargo") is None:
        return False
    try:
        measure._driver_bin()
    except Exception:
        return False
    return True


@unittest.skipUnless(_driver_available(), "needs cargo and the dated nightly")
class CanaryTests(unittest.TestCase):
    """The fixture is scanned once; every test reads the same tree."""

    tree: dict

    @classmethod
    def setUpClass(cls) -> None:
        doc = scan.compose(FIXTURE, seams=["from_raw"], sys_crates=["canary-sys"])
        cls.tree = doc["counts"]

    def at(self, path: str) -> int:
        """A leaf by its dotted path, 0 where the counter did not fire.

        Absent and zero are the same reading: the driver emits no key for a
        counter that never incremented.
        """
        node = self.tree
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return 0
            node = node[part]
        return node if isinstance(node, int) else node.get("total", 0)

    # ------------------------------------------------------------ signatures

    def test_raw_pointer_positions(self) -> None:
        # 8 safe public: taken_safe_pub, taken_nonnull, taken_twice (x2),
        # taken_void, gateway, safe_with_unsafe, deref_write. NonNull is a
        # carrier, both arguments of taken_twice count independently, and
        # `taken_void`'s `*c_void` is a raw pointer here with the `void` share
        # recording that its pointee is erased.
        self.assertEqual(self.at("raw_ptr.taken.safe.pub"), 8)
        self.assertEqual(self.at("raw_ptr.taken.safe.priv"), 1)
        # 11 unsafe public: taken_unsafe_pub, the four conversion helpers
        # (std_strings takes two), Undeclared::from_raw, calls, calls_seam,
        # unsafe_with_unsafe.
        self.assertEqual(self.at("raw_ptr.taken.unsafe.pub"), 11)
        self.assertEqual(self.at("raw_ptr.returned.safe.pub"), 1)
        self.assertEqual(self.at("raw_ptr.returned.unsafe.priv"), 1)

    def test_void_pointers_are_a_share_of_the_raw_position(self) -> None:
        """`taken_void` and `returned_void` are counted in the position they
        sit in, and labelled `void` there.

        A `*c_void` is a raw pointer with its pointee erased, so a top-level
        family of its own made a reader add two trees to learn how many raw
        pointers a signature carries -- and the flat counters it replaced
        counted such a position in both, so adding them double-counted.
        """
        self.assertEqual(self.at("raw_ptr.taken.of_which.void.safe.pub"), 1)
        self.assertEqual(self.at("raw_ptr.returned.of_which.void.unsafe.pub"), 1)
        # ...and the share is inside the position's own total, never beside it:
        # one of the 8 above is `taken_void`.
        self.assertEqual(self.at("raw_ptr.taken.safe.pub"), 8)

    def test_total_is_the_positions_the_crate_chose(self) -> None:
        """`raw_ptr.total.safe.pub` = 8 taken + 1 returned + 1 public field.

        `in_impl` is outside it -- the 4 positions of `RawSeam`'s two impls do
        not appear -- because a trait fixed those, so a reader comparing
        crates would be reading how often the trait is implemented. A field
        counts on the SAFE arm: reading one takes no `unsafe`, so a public
        field of a public type hands a pointer over without asking for any.
        """
        self.assertEqual(self.at("raw_ptr.total.safe.pub"), 10)
        self.assertEqual(self.at("raw_ptr.total.unsafe.pub"), 12)
        # The same cells with `in_impl` added would be 14 and 12; it is not.
        self.assertEqual(self.at("raw_ptr.in_impl.safe.pub"), 4)

    def test_references_and_embedded_pointers_are_not_positions(self) -> None:
        """`taken_ref` and `taken_holder` must move nothing.

        A reference is not a raw pointer, and a type that happens to embed one
        is not pointer work for the caller, who never touches it. Both are in
        the fixture only to be absent from these totals, which the exact
        counts above already pin.
        """
        self.assertEqual(
            self.at("raw_ptr.taken.safe.pub") + self.at("raw_ptr.taken.safe.priv"), 9)

    def test_seam_share_carries_safety_and_visibility(self) -> None:
        # Undeclared::from_raw is the only declared seam, and it is unsafe and
        # public. The share living under the direction is what lets it be
        # subtracted from the total it is a share of.
        self.assertEqual(self.at("raw_ptr.taken.of_which.seam.unsafe.pub"), 1)
        self.assertEqual(self.at("raw_ptr.taken.of_which.seam.safe.pub"), 0)

    # ----------------------------------------------------------- conversions

    def test_std_conversions_by_shape(self) -> None:
        # Box, Vec, Rc, Arc.
        self.assertEqual(self.at("raw_ptr.casted_to.std.owner"), 4)
        # CStr::from_ptr, CString::from_raw, String::from_raw_parts: the
        # C-string boundary, not `owner`.
        self.assertEqual(self.at("raw_ptr.casted_to.std.string"), 3)
        # slice::from_raw_parts{,_mut}. These are DEFINED in core::slice::raw
        # and re-exported, so a parent-only owner lookup reads 0 here.
        self.assertEqual(self.at("raw_ptr.casted_to.std.slice"), 2)
        # p.as_ref(), NonNull::as_ref(), &*p, &mut *p, and the two in
        # Viewing's Deref/DerefMut. NonNull is a carrier, not a raw pointer,
        # so a receiver test that only accepted raw pointers missed it.
        self.assertEqual(self.at("raw_ptr.casted_to.std.borrow"), 6)

    def test_declared_seam_lands_in_its_own_arm(self) -> None:
        # Undeclared is neither a std nor an ffibox shape, so a declared seam
        # returning one is the residual -- which is what `other` is for.
        self.assertEqual(self.at("raw_ptr.casted_to.local_seam.other"), 1)

    def test_std_and_ffibox_arms_have_no_residual(self) -> None:
        """`other` is structurally zero on the name-table arms.

        Every name in those tables maps to a known shape, so a nonzero reading
        means the table and the shape classifier have drifted apart.
        """
        self.assertEqual(self.at("raw_ptr.casted_to.std.other"), 0)
        self.assertEqual(self.at("raw_ptr.casted_to.ffibox.other"), 0)

    def test_undeclared_conversion_is_silent_not_misfiled(self) -> None:
        """The documented blind spot must stay blind rather than guess.

        Scanned without `--seams`, the crate's own `from_raw` is invisible: it
        must not reappear under `std` or `ffibox`, which would attribute the
        crate's own conversion to someone else's vocabulary.
        """
        tree = scan.compose(FIXTURE, sys_crates=["canary-sys"])["counts"]
        casted = tree["raw_ptr"]["casted_to"]
        self.assertNotIn("local_seam", casted)
        self.assertEqual(casted["std"]["total"], 15)

    # ----------------------------------------------------------------- calls

    def test_call_arms(self) -> None:
        # c_fn, canary_sys::sys_c_fn, the call through the stored
        # `unsafe extern "C" fn` field -- which has no callee item at all, so
        # an is_foreign_item test misses it -- and `Owned::drop`'s free.
        self.assertEqual(self.at("code.unsafe_call.ffi"), 4)
        # transmute. Marked #[rustc_intrinsic] with the Rust ABI, so an ABI
        # test alone would file it under `rust`.
        self.assertEqual(self.at("code.unsafe_call.intrinsic"), 1)
        # local_unsafe_fn plus the 12 std unsafe constructors the conversion
        # helpers call.
        self.assertEqual(self.at("code.unsafe_call.rust"), 13)

    def test_rust_defined_extern_fn_is_not_an_ffi_call(self) -> None:
        """`gateway` has a C ABI but is safe to call and crosses no boundary.

        It is the shape of a port campaign's ffi_export gateway. Were safety
        not gating membership, every call to one would be booked as FFI.
        """
        self.assertEqual(self.at("code.unsafe_call.ffi"), 4)

    # ----------------------------------------------------------------- types

    def test_holders(self) -> None:
        # Owned, Borrowed, Viewing, Asserted, Exposed, Silent, ThroughSys,
        # Undeclared, and canary-vendor's own VendorHolder.
        self.assertEqual(self.at("ty.storing_raw_ptr.pub"), 9)
        for share in ("impl_drop", "impl_clone", "has_lifetime",
                      "impl_deref", "impl_deref_mut", "impl_send_sync",
                      "pub_field"):
            with self.subTest(share=share):
                self.assertEqual(
                    self.at(f"ty.storing_raw_ptr.of_which.{share}.pub"), 1)
        # Exposed, Silent, ThroughSys, Undeclared, VendorHolder. Exposed is in
        # `none` AND in `pub_field`: a public field is an access the type does
        # not govern, not a declaration about the pointer.
        self.assertEqual(self.at("ty.storing_raw_ptr.of_which.none.pub"), 5)

    def test_peel_set_decides_the_population(self) -> None:
        """ThroughSys counts, ThroughVendor and ThroughStd do not.

        The walk descends through the scanned crate and the named `-sys`
        crates and stops everywhere else. ThroughSys is git2-rs's
        `OidArray { raw: git_oidarray }` shape, which a walk stopping at the
        crate boundary would miss; ThroughVendor holds the same pointer behind
        a crate that is neither, and ThroughStd behind a Vec.

        Pinned through the total: 9 admits ThroughSys and excludes the other
        two, and no other combination of the fixture's types gives 9.
        """
        self.assertEqual(self.at("ty.storing_raw_ptr.pub"), 9)
        self.assertEqual(self.at("ty.total.pub"), 15)

    def test_an_unnamed_sys_crate_leaves_the_peel_set(self) -> None:
        """The peel set is named, so omitting `canary-sys` drops ThroughSys.

        The counter reads low for a reason that is not in the code, which is
        why the summary prints the peel set. Asserted here so the naming
        requirement cannot be reverted to discovery without a failure.
        """
        tree = scan.compose(FIXTURE)["counts"]
        self.assertEqual(tree["ty"]["storing_raw_ptr"]["pub"], 8)

    def test_unsafe_cell(self) -> None:
        # Cellular and CellularNested. UnsafeCell is repr(transparent), so a
        # walk that peels transparent wrappers before looking loses it.
        self.assertEqual(self.at("ty.wrapping_unsafe_cell.pub"), 2)

    def test_unsafe_impls(self) -> None:
        self.assertEqual(self.at("ty.impl_trait.of_which.unsafe"), 2)
        self.assertEqual(self.at("ty.impl_trait.of_which.send_sync.send.pub"), 1)
        self.assertEqual(self.at("ty.impl_trait.of_which.send_sync.sync.pub"), 1)

    # ------------------------------------------------------------- fn bodies

    def test_with_unsafe_is_counted_on_the_safe_arm_only(self) -> None:
        """Five: `safe_with_unsafe`, `deref_write`, and the three trait-impl
        methods -- `Owned::drop`, `Viewing::deref`, `Viewing::deref_mut`.
        Not `unsafe_with_unsafe`.

        With `unsafe_op_in_unsafe_fn` denied, every `unsafe fn` doing anything
        raw has a block by construction, so counting it there would measure
        the lint rather than the code.
        """
        self.assertEqual(self.at("fn.safe.of_which.with_unsafe.pub"), 5)

    def test_a_trait_impl_method_reaches_the_fn_family(self) -> None:
        """A safe method of a foreign trait whose body holds unsafe is the
        hazard the counter exists for -- `impl Drop for Foo { fn drop }` that
        frees through FFI, and `Deref::deref` that builds a reference from a
        raw pointer. Three of the five above are those, so a rule that skipped
        trait impls would read 2.
        """
        sites = scan.compose(FIXTURE, seams=["from_raw"],
                             sys_crates=["canary-sys"],
                             sites=["fn.safe.of_which.with_unsafe.pub"])["sites"]
        lines = {l for r in sites["fn.safe.of_which.with_unsafe.pub"]
                 for l in r["lines"]}
        src = (FIXTURE / "canary" / "src" / "lib.rs").read_text().splitlines()
        named = {src[l - 1].strip() for l in lines}
        self.assertIn("fn drop(&mut self) {", named)
        self.assertIn("fn deref(&self) -> &u8 {", named)
        self.assertIn("fn deref_mut(&mut self) -> &mut u8 {", named)

    def test_a_macro_written_method_is_counted_and_marked(self) -> None:
        """`impl_stub_display!(Owned)` writes one `Display::fmt`. It counts
        like any other method -- it is compiled into this crate -- and the
        share says so, which is what lets a reader subtract the boilerplate
        `bitflags!` and `#[derive]` generate.
        """
        # Three: `Display::fmt` from the macro, and `Debug::fmt` plus
        # `Default::default` from `Derived`'s `#[derive]`, which is an
        # expansion like any other.
        self.assertEqual(self.at("fn.total.of_which.macro.pub"), 3)
        self.assertEqual(self.at("fn.total.of_which.macro.priv"), 0)

    def test_deref_split(self) -> None:
        self.assertEqual(self.at("raw_ptr.deref.rd"), 4)
        self.assertEqual(self.at("raw_ptr.deref.wr"), 3)

    def test_a_trait_impls_pointer_positions_go_to_in_impl(self) -> None:
        """`RawSeam::round_trip` takes one and returns one, implemented for
        two types: 4 positions, both directions in one counter.

        None of them reaches `taken` or `returned`. The crate did not choose
        the position -- one trait declaration dictates it in every impl -- so
        counting them there makes the hazard move with how many types
        implement the trait. That is what read 63 of git2-rs' 66 "raw pointers
        returned by a public safe fn": its `Binding` trait, once.
        """
        self.assertEqual(self.at("raw_ptr.in_impl.safe.pub"), 4)
        self.assertEqual(self.at("raw_ptr.in_impl.unsafe.pub"), 0)
        # `taken.safe.pub` is the free and inherent fns only, unchanged by the
        # two impls above.
        self.assertEqual(self.at("raw_ptr.taken.safe.pub"), 8)
        self.assertEqual(self.at("raw_ptr.returned.safe.pub"), 1)

    # ------------------------------------------------------------ type views

    def test_impl_blocks_and_trait_impls_are_separate(self) -> None:
        """An inherent `impl T` is the API the crate wrote for its own type;
        an `impl Tr for T` satisfies someone else's shape. `ty.impl` used to
        merge them."""
        # The workspace's two inherent blocks: `canary::Undeclared` and
        # `canary_vendor::VendorHolder`.
        self.assertEqual(self.at("ty.impl_block.pub"), 2)
        # `RawSeam`, the fixture's own trait, implemented for two types.
        self.assertEqual(self.at("ty.impl_trait.of_which.local.pub"), 2)
        # std's, across the workspace: Drop, Clone, Deref, DerefMut, Send,
        # Sync, the macro-written Display, the vendor crate's Default, and
        # `Derived`'s two derives.
        self.assertEqual(self.at("ty.impl_trait.of_which.std.pub"), 10)

    def test_derived_impls_are_a_share_of_the_trait_impls(self) -> None:
        """`#[derive(Debug, Default)]` on `Derived` writes two impls nobody
        typed. On the real crates that share is most of the `std` arm -- 1171
        of libgit2-bindings' 1960 trait impls and 630 of git2-rs' 1863 -- so a
        reader comparing vocabularies without it is reading how many derives
        each crate spells.
        """
        self.assertEqual(self.at("ty.impl_trait.of_which.derived.pub"), 2)

    def test_generic_types_split_by_parameter_kind(self) -> None:
        """`Borrowed<'a>` over a lifetime, `Generic<T>` over a type. Both hold
        a raw pointer, so both are in the `storing_raw_ptr` share."""
        self.assertEqual(self.at("ty.generic.of_which.lifetime.pub"), 1)
        self.assertEqual(self.at("ty.generic.of_which.storing_raw_ptr.pub"), 1)

    def test_trait_provenance_is_a_share_of_every_type(self) -> None:
        """The denominator `ty.storing_raw_ptr`'s shares lacked: how many
        types speak each vocabulary at all. Shares, not a partition -- `Owned`
        implements std traits AND the fixture's own `RawSeam`."""
        self.assertEqual(self.at("ty.total.pub"), 15)
        self.assertEqual(self.at("ty.total.of_which.local_trait.pub"), 2)
        # `Derived` joins the std-trait share.
        self.assertEqual(self.at("ty.total.of_which.std_trait.pub"), 5)
        self.assertEqual(self.at("ty.total.of_which.no_trait.pub"), 9)
        # 2 + 4 + 9 = 15 over 14 types: `Owned` implements both `Drop` and
        # the fixture's own `RawSeam`, so the arms are shares and a reader
        # must not add them.
        self.assertGreater(
            self.at("ty.total.of_which.local_trait.pub")
            + self.at("ty.total.of_which.std_trait.pub")
            + self.at("ty.total.of_which.no_trait.pub"),
            self.at("ty.total.pub"))

    def test_test_code_reaches_code_tests_and_nothing_else(self) -> None:
        """`unit_tests` holds a pointer-holding struct, a `#[test]` fn that
        takes a raw pointer, an unsafe block and an FFI call -- one of every
        shape a library counter pins. None of them moves.

        Two mechanisms, worth telling apart. In the library build `cfg(test)`
        is off, so rustc strips the module during expansion and the items
        never reach HIR: there is nothing to traverse, rather than a rule that
        skips it. In the `--test` build they are there and the driver does
        walk them -- along with the whole library, which that target
        recompiles -- but only `code.tests.*` is emitted and the rest is
        discarded.
        """
        self.assertEqual(self.at("code.tests.loc.total"), 9)
        # the `#[test]` fn, plus one generated harness `main` per test binary
        # (`canary` and `canary_vendor`).
        self.assertEqual(self.at("code.tests.fn"), 3)
        self.assertEqual(self.at("code.tests.unsafe_block"), 1)
        # `TestHolder` holds a raw pointer and is in neither population.
        self.assertEqual(self.at("ty.total.pub"), 15)
        self.assertEqual(self.at("ty.storing_raw_ptr.pub"), 9)
        # its unsafe block and FFI call are in neither total.
        self.assertEqual(self.at("code.unsafe_block"), 25)
        self.assertEqual(self.at("code.unsafe_call.ffi"), 4)
        self.assertEqual(self.at("code.loc.total"), 136)

    def test_fn_partition_sums_to_total(self) -> None:
        for vis in ("pub", "priv"):
            with self.subTest(vis=vis):
                self.assertEqual(
                    self.at(f"fn.safe.{vis}") + self.at(f"fn.unsafe.{vis}"),
                    self.tree["fn"]["total"][vis])


if __name__ == "__main__":
    unittest.main()
