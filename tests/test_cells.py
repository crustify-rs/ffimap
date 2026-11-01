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

    # ----------------------------------------------------- ty.ffibox.wrapper

    def test_every_borrow_of_the_cell_is_counted_once_per_place(self) -> None:
        """The thirteen `&Widget` mentions of the fixture's public interface.

        Four receivers (`as_ref`, `as_mut`, `peek`, `eq`) and `widest`'s; the
        arguments `eq`, `widest`, `leaked`, `leaked_optional`, `leaked_slice`
        and `Holder::as_ref` take, `borrowed_in_vec`'s through a `Vec`, and
        `widest`'s returned `&Widget`. `leaked_optional` and `leaked_slice`
        prove the walk enters `Option` and a slice.
        """
        self.assertEqual(self.at("ty.ffibox.wrapper.of_which.borrow.pub"), 13)
        self.assertEqual(self.at("ty.ffibox.wrapper.of_which.borrow.priv"), 0)

    def test_the_sanctioned_borrows_are_shares_so_the_rest_subtracts(self) -> None:
        """What the counter is for: `13 - 2 - 2` is the unsanctioned surface.

        The accessors' receivers and the trait impls' stand on ffibox's own
        contract, that a cell value is Rust-owned inline storage. `peek` does
        not, although it takes the same `&self`: the share is a name rule, so
        a conversion the convention did not name stays in the remainder.
        """
        accessor = self.at(
            "ty.ffibox.wrapper.of_which.borrow.of_which.self_in_ref_accessor.pub")
        trait_impl = self.at(
            "ty.ffibox.wrapper.of_which.borrow.of_which.self_in_trait_impl.pub")
        self.assertEqual((accessor, trait_impl), (2, 2))
        self.assertEqual(self.at("ty.ffibox.wrapper.of_which.borrow.pub")
                         - accessor - trait_impl, 9)

    def test_only_the_receiver_of_a_trait_method_is_sanctioned(self) -> None:
        """`eq` and `widest` have one sanctioned borrow each, of five.

        The trait fixes the receiver's shape and nothing else: `eq`'s `other`
        and `widest`'s argument and RETURN are published borrows of C-owned
        memory that the impl chose, and `fn deref(&self) -> &Foo` is the shape
        that makes the distinction worth drawing.
        """
        self.assertEqual(
            self.at("ty.ffibox.wrapper.of_which.borrow.of_which.self_in_trait_impl.pub"),
            2)

    def test_an_accessor_by_name_without_a_receiver_is_not_sanctioned(self) -> None:
        """`Holder::as_ref(w: &Widget)` carries the name and no `self`.

        The contract licenses the mint `define_ctype!` writes, which is a
        method on the cell; a free-standing function of the same name is a
        borrow its author chose.
        """
        self.assertEqual(
            self.at("ty.ffibox.wrapper.of_which.borrow.of_which.self_in_ref_accessor.pub"),
            2)

    def test_a_slice_of_cells_is_a_borrow_and_a_slice_at_one_mention(self) -> None:
        """`&[Widget]` is both, which is why the arms are shares."""
        self.assertEqual(self.at("ty.ffibox.wrapper.of_which.slice.pub"), 1)

    def test_a_std_owner_holds_its_cell_in_storage_of_its_own(self) -> None:
        """`Box<Widget>`, `Vec<Widget>` and the `Vec` nested inside a `CBox`.

        `Option<Widget>` is not a fourth: it allocates nothing and owns no run
        of elements, so the cell sits in the mention's own place and `by_val`
        says it. Admitting the inline wrappers read 34 mentions on
        libgit2-bindings, 31 of them `Result<Foo, Error>` returns.
        """
        self.assertEqual(self.at("ty.ffibox.wrapper.of_which.std_owner.pub"), 3)

    def test_a_std_owner_of_borrows_owns_no_cell(self) -> None:
        """`Vec<&Widget>` is one borrow and no owner.

        The innermost qualifier of each class describes the mention, so the
        reference below the `Vec` clears the owner the `Vec` set. Read off the
        places, since the figure alone cannot say which mention it is.
        """
        wanted = ["ty.ffibox.wrapper.of_which.borrow.pub",
                  "ty.ffibox.wrapper.of_which.std_owner.pub"]
        sites = scan.compose(FIXTURE, ffibox=True, sites=wanted)["sites"]
        src = (FIXTURE / "cells" / "src" / "lib.rs").read_text().splitlines()
        named = {c: {src[ln - 1].strip() for r in sites[c] for ln in r["lines"]}
                 for c in wanted}
        decl = "pub fn borrowed_in_vec(ws: Vec<&Widget>) -> usize {"
        self.assertIn(decl, named["ty.ffibox.wrapper.of_which.borrow.pub"])
        self.assertNotIn(decl, named["ty.ffibox.wrapper.of_which.std_owner.pub"])

    def test_a_field_mention_is_keyed_on_reaching_it(self) -> None:
        """`Holder.w` is public, `PrivateHolder.w` is not."""
        self.assertEqual(self.at("ty.ffibox.wrapper.of_which.field.pub"), 1)
        self.assertEqual(self.at("ty.ffibox.wrapper.of_which.field.priv"), 1)

    def test_the_population_counts_each_mention_once(self) -> None:
        """Seventeen public mentions: 13 borrows, three owners and one field.

        The slice is not an eighteenth: it is the same mention as one of the
        borrows, which is what makes the arms shares rather than a partition.
        A `Widget` taken by value with no qualifier above it -- `by_value`'s
        two, and `maybe`'s `Option` -- is in `by_val` and not here: `wrapper`
        counts the mentions one of its arms describes.
        """
        self.assertEqual(self.at("ty.ffibox.wrapper.pub"), 17)
        self.assertEqual(self.at("ty.ffibox.wrapper.priv"), 1)

    # --------------------------------------------------------- ty.ffibox.ffi

    def test_the_raw_struct_is_keyed_on_the_cells_associated_type(self) -> None:
        """`CCell::C` is the authority: `raw_widget` is counted because
        `Widget` names it, the newtype's own field privately and
        `raw_borrow`'s signature publicly."""
        self.assertEqual(self.at("ty.ffibox.ffi.of_which.borrow.pub"), 1)
        self.assertEqual(self.at("ty.ffibox.ffi.of_which.field.priv"), 1)
        self.assertEqual(self.at("ty.ffibox.ffi.total"), 2)

    # ------------------------------------------------------ ty.ffibox.by_val

    def test_a_cell_held_as_a_value_is_counted_where_it_is_held(self) -> None:
        """`by_value`, `boxed`, `maybe` and `nested_owner` name six, `take` one.

        `field` and `fn_sig` partition the population; `std_owner` cuts across
        and covers three of them, `boxed`'s two and `nested_owner`'s.
        """
        self.assertEqual(self.at("ty.ffibox.by_val.of_which.fn_sig.pub"), 6)
        self.assertEqual(self.at("ty.ffibox.by_val.of_which.fn_sig.priv"), 1)
        self.assertEqual(self.at("ty.ffibox.by_val.of_which.field.pub"), 1)
        self.assertEqual(self.at("ty.ffibox.by_val.of_which.field.priv"), 1)
        self.assertEqual(self.at("ty.ffibox.by_val.of_which.std_owner.pub"), 3)
        self.assertEqual(self.at("ty.ffibox.by_val.total"), 9)

    def test_a_borrowed_cell_is_never_by_value(self) -> None:
        """The thirteen borrows are nowhere in `by_val`, which is the whole
        distinction: `&Widget` is somebody else's storage."""
        self.assertEqual(self.at("ty.ffibox.by_val.total"),
                         self.at("ty.ffibox.by_val.of_which.fn_sig.pub")
                         + self.at("ty.ffibox.by_val.of_which.fn_sig.priv")
                         + self.at("ty.ffibox.by_val.of_which.field.pub")
                         + self.at("ty.ffibox.by_val.of_which.field.priv"))

    # ----------------------------------------------------------- the negatives

    def test_what_ffibox_manages_is_not_the_crates_own_mention(self) -> None:
        """`CBox<Widget>` and `CBorrowedPtr<Widget>` hold the cell behind
        their own pointer, so the walk stops at the primitive.

        Were they counted, every campaign's figures would be dominated by the
        delegation `ty.field.ffibox` and `fn.ffibox` already report: on
        libgit2-bindings the two primitives carried 76 of 80 field mentions
        and 250 of 423 signature mentions.
        """
        self.assertEqual(self.at("ty.ffibox.wrapper.of_which.std_owner.priv"), 0)
        # The primitives, the two raw pointers and `Vec<CBox<Widget>>` would
        # each add a mention; the totals are the hand-derived ones without
        # them.
        self.assertEqual(self.at("ty.ffibox.wrapper.total"), 18)

    def test_a_hazard_nested_below_a_primitive_is_still_seen(self) -> None:
        """`CBox<Vec<Widget>>` against `Vec<CBox<Widget>>`.

        The walk goes THROUGH a pointer-like rather than stopping at it, so a
        `Vec` below one is still a vector holding cells by value, whoever
        manages the vector. The other way round the innermost qualifier is the
        primitive, and nothing is this crate's storage. Stopping at the
        primitive hid the first case; counting the primitive itself as storage
        read 250 of libgit2-bindings' 423 signature mentions.
        """
        sites = scan.compose(
            FIXTURE, ffibox=True,
            sites=["ty.ffibox.by_val.of_which.std_owner.pub"])["sites"]
        lines = [l for r in sites["ty.ffibox.by_val.of_which.std_owner.pub"]
                 for l in r["lines"]]
        src = (FIXTURE / "cells" / "src" / "lib.rs").read_text().splitlines()
        named = sorted({src[l - 1].strip() for l in lines})
        self.assertIn("pub fn nested_owner(_w: CBox<Vec<Widget>>) {}", named)
        self.assertNotIn("pub fn owners_in_vec(_w: Vec<CBox<Widget>>) {}", named)

    def test_a_pointer_to_a_cell_is_not_storage_holding_one(self) -> None:
        """`NonNull<Widget>` and `*mut Widget` are `raw_ptr`'s positions.

        ffibox's lifecycle strategies take `NonNull<Cell>`, so counting it
        would put every `c_drop` in the by-value hazard: on libgit2-bindings
        `NonNull` carried 58 of 173 signature mentions once the primitives
        were out. Were the two counted here the figure would be 8.
        """
        self.assertEqual(self.at("ty.ffibox.by_val.of_which.fn_sig.pub"), 6)

    def test_every_mention_reports_its_place(self) -> None:
        """`--sites` reaches all three families, and a counter's per-file
        counts sum to it.

        Both halves are the point. The families are spelled from a variable in
        the driver (`ty.{tree}.{vis}`), so `test_counters`'s source scrape
        cannot see them and a missing entry in `TREE_SITE_FAMILIES` would make
        them silently unreachable -- how `raw_ptr.field` and `raw_ptr.fn_sig_trait_impl`
        were each unreachable when added. And the sum is what makes the
        remainder readable: the unsanctioned borrows are recovered by taking
        the share's places out of the arm's.
        """
        wanted = ["ty.ffibox.wrapper.of_which.borrow.pub",
                  "ty.ffibox.wrapper.of_which.borrow.of_which.self_in_ref_accessor.pub",
                  "ty.ffibox.ffi.of_which.borrow.pub",
                  "ty.ffibox.by_val.of_which.fn_sig.pub"]
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
