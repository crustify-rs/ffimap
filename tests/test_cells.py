"""The cell counters `--ffibox` turns on, over a fixture hand-derived item by item.

`tests/fixtures/cells/` is a crate built on a stub named `ffibox`, since the
driver recognises the vocabulary by crate name. Every expectation below is read
off the annotations in its `lib.rs`, and the negatives carry as much weight as
the positives: a mention ffibox manages, or one that is a raw pointer, must not
land in these counters at all.

Needs the driver, so it skips where cargo and the dated nightly are missing.
"""

import shutil
import unittest
from pathlib import Path

from ffimap import measure, scan

FIXTURE = Path(__file__).parent / "fixtures" / "cells"
W = "ty.ffibox.wrapper.as"


def _driver_available() -> bool:
    """cargo on the PATH and the driver buildable, as in test_canary.

    Kept local rather than imported: `tests` is not a package, so a
    cross-module import works under one runner and not the other.
    """
    if shutil.which("cargo") is None:
        return False
    try:
        measure._driver_bin()
    except Exception:
        return False
    return True


@unittest.skipUnless(_driver_available(), "needs cargo and the dated nightly")
class CellCounterTests(unittest.TestCase):
    """The fixture is scanned once, with the flag the counters are gated on."""

    tree: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = scan.compose(FIXTURE, ffibox=True)["counts"]

    def at(self, path: str) -> int:
        """A leaf by its dotted path, 0 where the counter did not fire."""
        node = self.tree
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return 0
            node = node[part]
        return node if isinstance(node, int) else node.get("total", 0)

    # ------------------------------------------- the convention's own traits

    def test_a_lifecycle_traits_pointer_position_carries_its_trait(self) -> None:
        """`CDrop::c_drop(NonNull<raw_widget>)` and `CNew::c_new() -> NonNull<_>`.

        Two positions in `raw_ptr.fn_sig_trait_impl`, and the `ffibox` arm
        says whose shape put them there -- the whole point of the arm, since
        the family's bare figure reads the same whether a crate's trait-impl
        pointers are a convention's lifecycle strategies or its own plumbing.
        """
        self.assertEqual(self.at("raw_ptr.fn_sig_trait_impl.total"), 2)
        self.assertEqual(
            self.at("raw_ptr.fn_sig_trait_impl.of_which.ffibox.unsafe.pub"), 1)
        self.assertEqual(
            self.at("raw_ptr.fn_sig_trait_impl.of_which.ffibox.safe.pub"), 1)
        self.assertEqual(
            self.at("raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.CDrop"), 1)
        self.assertEqual(
            self.at("raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.CNew"), 1)

    def test_a_trait_that_names_no_pointer_is_a_registered_zero(self) -> None:
        """`CCell` is implemented for `Widget` and declares associated types
        only, and the fixture's own `Widest` takes `&Widget`. Both leaves read
        0 rather than going missing, so a document says which contracts reach
        a raw pointer and which do not."""
        self.assertEqual(
            self.at("raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.CCell"), 0)
        self.assertEqual(
            self.at("raw_ptr.fn_sig_trait_impl.of_which.local.total"), 0)

    # ----------------------------------------------------- ty.ffibox.wrapper

    def test_wrapper_counts_the_cell_types(self) -> None:
        """`Widget` is the fixture's one `CCell`, and its handles implement
        no seam."""
        self.assertEqual(self.at("ty.ffibox.wrapper.pub"), 1)
        self.assertEqual(self.at("ty.ffibox.wrapper.of_which.no_seam_trait.pub"), 1)
        self.assertEqual(self.at("ty.ffibox.wrapper.total"), 1)

    def test_the_mentions_are_never_summed_into_the_types(self) -> None:
        """`as` counts places, the record above it types: 31 mentions of one
        cell, and the cell count stays 1."""
        self.assertEqual(self.at("ty.ffibox.wrapper.as.total"), 31)
        self.assertEqual(self.tree["ty"]["ffibox"]["wrapper"]["total"], 1)

    # ------------------------------------------------- ty.ffibox.wrapper.as

    # The innermost holder above each mention, by place, read off the
    # fixture's annotations.
    AS = {
        "borrowed.std": {"fn_sig.pub": 15, "field.pub": 1},
        "borrowed.ffibox": {"fn_sig.pub": 1},
        "owned.std": {"fn_sig.pub": 3, "field.priv": 1},
        "owned.ffibox": {"fn_sig.pub": 4},
        "by_val": {"fn_sig.pub": 3, "fn_sig.priv": 1, "field.pub": 1, "field.priv": 1},
    }

    def test_every_mention_is_in_one_arm_by_its_innermost_holder(self) -> None:
        """The arms partition the mentions, and `field` and `fn_sig` each arm.

        `borrowed.std` is every `&Widget`: the receivers of `as_ref`, `as_mut`,
        `peek`, `eq`, `as_ref` the trait method and `widest`, the arguments
        `eq`, `widest`, `leaked`, `leaked_optional`, `leaked_slice`,
        `borrowed_in_vec` and `Holder::as_ref` take, the returns of `widest`
        and `AsRef::as_ref`, and `Lens.w`. `owned.ffibox` is `in_ffibox_owner`,
        `owners_in_vec`, `opened` and `peeked`, whose reference is to the
        `CBox` and not to the cell.
        """
        for arm, places in self.AS.items():
            for place in ["fn_sig.pub", "fn_sig.priv", "field.pub", "field.priv"]:
                at, vis = place.split(".")
                with self.subTest(arm=arm, place=place):
                    self.assertEqual(self.at(f"{W}.{arm}.of_which.{at}.{vis}"),
                                     places.get(place, 0))
            with self.subTest(arm=arm):
                self.assertEqual(self.at(f"{W}.{arm}.total"), sum(places.values()))
        self.assertEqual(self.at(f"{W}.total"),
                         sum(sum(p.values()) for p in self.AS.values()))

    def test_the_sanctioned_borrows_are_shares_so_the_rest_subtracts(self) -> None:
        """What the counter is for: `16 - 2 - 3` is the unsanctioned surface.

        The accessors' receivers and the trait impls' stand on ffibox's own
        contract, that a cell value is Rust-owned inline storage. `peek` does
        not, although it takes the same `&self`: the share is a name rule, so
        a conversion the convention did not name stays in the remainder.
        """
        accessor = self.at(f"{W}.borrowed.std.of_which.self_in_ref_accessor.pub")
        trait_impl = self.at(f"{W}.borrowed.std.of_which.self_in_trait_impl.pub")
        self.assertEqual((accessor, trait_impl), (2, 3))
        self.assertEqual(self.at(f"{W}.borrowed.std.pub") - accessor - trait_impl, 11)

    def test_only_the_receiver_of_a_trait_method_is_sanctioned(self) -> None:
        """`eq`, `as_ref` and `widest` have one sanctioned borrow each, of
        seven.

        The trait fixes the receiver's shape and nothing else: `eq`'s `other`,
        `widest`'s argument and the RETURNS of `widest` and `AsRef::as_ref` are
        published borrows of C-owned memory that the impl chose.
        """
        self.assertEqual(self.at(f"{W}.borrowed.std.of_which.self_in_trait_impl.pub"), 3)

    def test_a_ref_forming_receiver_is_its_own_share(self) -> None:
        """`AsRef::as_ref` is the one receiver of a std trait whose method
        returns a reference the impl chose; `PartialEq` and the local `Widest`
        are not std's ref-forming traits."""
        self.assertEqual(
            self.at(f"{W}.borrowed.std.of_which.self_in_trait_impl.of_which.ref_forming.pub"),
            1)

    def test_an_accessor_by_name_without_a_receiver_is_not_sanctioned(self) -> None:
        """`Holder::as_ref(w: &Widget)` carries the name and no `self`, and the
        trait method `AsRef::as_ref` is not in an inherent impl.

        The contract licenses the mint `define_ctype!` writes, which is an
        inherent method on the cell; a free-standing function of the same name
        is a borrow its author chose.
        """
        self.assertEqual(self.at(f"{W}.borrowed.std.of_which.self_in_ref_accessor.pub"), 2)

    def test_a_std_owner_of_borrows_owns_no_cell(self) -> None:
        """`Vec<&Widget>` is one borrow and no owner: the innermost holder
        describes the mention. Read off the places, since the figure alone
        cannot say which mention it is."""
        wanted = [f"{W}.borrowed.std.pub", f"{W}.owned.std.pub"]
        sites = scan.compose(FIXTURE, ffibox=True, sites=wanted)["sites"]
        src = (FIXTURE / "cells" / "src" / "lib.rs").read_text().splitlines()
        named = {c: {src[ln - 1].strip() for r in sites[c] for ln in r["lines"]}
                 for c in wanted}
        decl = "pub fn borrowed_in_vec(ws: Vec<&Widget>) -> usize {"
        self.assertIn(decl, named[f"{W}.borrowed.std.pub"])
        self.assertNotIn(decl, named[f"{W}.owned.std.pub"])

    def test_a_hazard_nested_below_a_primitive_is_still_seen(self) -> None:
        """`CBox<Vec<Widget>>` against `Vec<CBox<Widget>>`.

        The walk goes THROUGH a primitive rather than stopping at it, so a
        `Vec` below one is still a vector holding cells by value, whoever
        manages the vector, and the other way round the primitive is the
        holder.
        """
        wanted = [f"{W}.owned.std.pub", f"{W}.owned.ffibox.pub"]
        sites = scan.compose(FIXTURE, ffibox=True, sites=wanted)["sites"]
        src = (FIXTURE / "cells" / "src" / "lib.rs").read_text().splitlines()
        named = {c: {src[ln - 1].strip() for r in sites[c] for ln in r["lines"]}
                 for c in wanted}
        self.assertIn("pub fn nested_owner(_w: CBox<Vec<Widget>>) {}",
                      named[f"{W}.owned.std.pub"])
        self.assertIn("pub fn owners_in_vec(_w: Vec<CBox<Widget>>) {}",
                      named[f"{W}.owned.ffibox.pub"])

    # --------------------------------------------------------- ty.ffibox.ffi

    def test_the_raw_struct_is_keyed_on_the_cells_associated_type(self) -> None:
        """`CCell::C` is the authority: `raw_widget` is counted because
        `Widget` names it, the newtype's own field privately and
        `raw_borrow`'s signature publicly. `ffi` holds mentions only."""
        self.assertEqual(self.at("ty.ffibox.ffi.as.borrowed.std.of_which.fn_sig.pub"), 1)
        self.assertEqual(self.at("ty.ffibox.ffi.as.by_val.of_which.field.priv"), 1)
        self.assertEqual(self.at("ty.ffibox.ffi.as.total"), 2)
        self.assertNotIn("total", self.tree["ty"]["ffibox"]["ffi"])

    # ------------------------------------------------------- ty.impl_trait

    def test_std_and_ffibox_impls_are_partitioned_by_trait(self) -> None:
        """`PartialEq` is `other`, `AsRef` `ref_forming`, `Drop for Holder`
        `drop`; `CCell` is `layout`, `CDrop` and `CNew` `policy`."""
        it = "ty.impl_trait.of_which"
        self.assertEqual(
            {arm: self.at(f"{it}.std.{arm}.pub")
             for arm in ["drop", "clone", "send", "sync", "ref_forming", "other"]},
            {"drop": 1, "clone": 0, "send": 0, "sync": 0, "ref_forming": 1, "other": 1})
        self.assertEqual(self.at(f"{it}.std.total"), 3)
        self.assertEqual(self.at(f"{it}.ffibox.layout.pub"), 1)
        self.assertEqual(self.at(f"{it}.ffibox.policy.pub"), 2)
        self.assertEqual(self.at(f"{it}.ffibox.policy.of_which.CDrop.handwritten"), 1)
        self.assertEqual(self.at(f"{it}.ffibox.total"), 3)

    # ---------------------------------------------------------------- fn.sig

    def test_a_primitive_counts_wherever_the_signature_holds_it(self) -> None:
        """Bare, inside a `Result` or an `Option`, behind a reference, and
        above or below a std owner: `in_ffibox_owner`, `nested_owner`,
        `owners_in_vec` and `peeked` take a `CBox`, `in_ffibox_borrow` a
        `CBorrowedPtr`, and `opened` returns a `Result<CBox<_>, _>`.
        `called_back`'s fn pointer is not entered.
        """
        sig = self.tree["fn"]["sig"]["of_which"]["ffibox"]
        self.assertEqual(self.at("fn.sig.of_which.ffibox.arg.CBox.pub"), 4)
        self.assertEqual(self.at("fn.sig.of_which.ffibox.arg.CBorrowedPtr.pub"), 1)
        self.assertEqual(self.at("fn.sig.of_which.ffibox.ret.CBox.pub"), 1)
        self.assertEqual(sig["total"], 6)

    # ----------------------------------------------------------- the negatives

    def test_a_pointer_to_a_cell_is_no_holder(self) -> None:
        """`NonNull<Widget>`, `*mut Widget`, the strategies' `NonNull<raw_widget>`
        and the handles' raw pointers are `raw_ptr`'s positions, `PhantomData`
        holds nothing, and `called_back`'s fn pointer is not entered: none is
        in the arms, whose sum is the hand-derived 31 without them."""
        self.assertEqual(self.at(f"{W}.total"), 31)
        self.assertEqual(self.at("ty.ffibox.ffi.as.total"), 2)

    def test_every_mention_reports_its_place(self) -> None:
        """`--sites` reaches both trees, and a counter's per-file counts sum
        to it.

        Both halves are the point. The families are spelled from a variable in
        the driver (`ty.{tree}.{vis}`), so `test_counters`'s source scrape
        cannot see them and a missing entry in `TREE_SITE_FAMILIES` would make
        them silently unreachable -- how `raw_ptr.field` and `raw_ptr.fn_sig_trait_impl`
        were each unreachable when added. And the sum is what makes the
        remainder readable: the unsanctioned borrows are recovered by taking
        the share's places out of the arm's.
        """
        wanted = [f"{W}.borrowed.std.pub",
                  f"{W}.borrowed.std.of_which.self_in_ref_accessor.pub",
                  "ty.ffibox.ffi.as.borrowed.std.pub",
                  f"{W}.by_val.of_which.fn_sig.pub"]
        sites = scan.compose(FIXTURE, ffibox=True, sites=wanted)["sites"]
        for counter in wanted:
            with self.subTest(counter=counter):
                rows = sites[counter]
                self.assertTrue(rows, "no places reported")
                self.assertEqual(sum(r["count"] for r in rows), self.at(counter))

    def test_the_counters_are_gated_on_the_flag(self) -> None:
        """Without `--ffibox` there is no `CCell` to read, so the arms are
        absent rather than zero -- the rule every ffibox arm follows."""
        self.assertNotIn("ffibox", scan.compose(FIXTURE)["counts"]["ty"])


if __name__ == "__main__":
    unittest.main()
