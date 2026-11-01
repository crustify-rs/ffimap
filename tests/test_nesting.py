"""The counter tree `nest_ptr` builds, and the ffibox record's.

The driver emits dotted keys; `nest_ptr` folds them into records and derives
every `total`. What it must get right is which parents get one: an `of_which`
node holds overlapping shares, so its children must never be summed, and a
top-level prefix mixes grains, so summing across it means nothing.
"""
import unittest

from ffimap import measure


class NestPtrTests(unittest.TestCase):
    def test_partition_totals_sum_their_children(self) -> None:
        tree = measure.nest_ptr({
            "raw_ptr.taken.safe.pub": 1, "raw_ptr.taken.safe.priv": 2,
            "raw_ptr.taken.unsafe.pub": 4, "raw_ptr.taken.unsafe.priv": 8,
        })
        self.assertEqual(tree["raw_ptr"]["taken"]["safe"]["total"], 3)
        self.assertEqual(tree["raw_ptr"]["taken"]["unsafe"]["total"], 12)
        self.assertEqual(tree["raw_ptr"]["taken"]["total"], 15)

    def test_a_top_level_prefix_gets_no_total(self) -> None:
        """`raw_ptr.taken` counts signature positions and `raw_ptr.deref`
        counts body sites; their sum is not a quantity."""
        tree = measure.nest_ptr({"raw_ptr.taken.safe.pub": 1, "raw_ptr.deref.rd": 2})
        self.assertNotIn("total", tree["raw_ptr"])
        self.assertNotIn("total", tree)

    def test_of_which_is_never_summed_and_gets_no_total(self) -> None:
        tree = measure.nest_ptr({
            "code.unsafe_block.total": 100,
            "code.unsafe_block.of_which.ffi_export": 5,
        })
        self.assertEqual(tree["code"]["unsafe_block"]["total"], 100)
        self.assertEqual(tree["code"]["unsafe_block"]["of_which"], {"ffi_export": 5})

    def test_a_share_keeps_its_own_partition_total(self) -> None:
        """Summing two different shares is meaningless, but the `pub` / `priv`
        split inside ONE share is a partition and does have a total."""
        tree = measure.nest_ptr({
            "ty.storing_raw_ptr.pub": 9,
            "ty.storing_raw_ptr.of_which.impl_drop.pub": 2,
            "ty.storing_raw_ptr.of_which.impl_drop.priv": 1,
            "ty.storing_raw_ptr.of_which.impl_clone.pub": 4,
        })
        of_which = tree["ty"]["storing_raw_ptr"]["of_which"]
        self.assertEqual(of_which["impl_drop"]["total"], 3)
        self.assertNotIn("total", of_which)
        self.assertEqual(tree["ty"]["storing_raw_ptr"]["total"], 9)

    def test_an_emitted_total_is_not_overwritten_by_a_sum(self) -> None:
        """`ty.total` is the denominator the driver emits -- every type the
        crate declares -- and it occupies the name a derived sum would take.
        It must survive beside `ty.storing_raw_ptr`, which is one of its
        subsets, not a sibling to add to it."""
        tree = measure.nest_ptr({"ty.total.pub": 300, "ty.total.priv": 74,
                                 "ty.storing_raw_ptr.pub": 9})
        self.assertEqual(tree["ty"]["total"], {"pub": 300, "priv": 74, "total": 374})
        self.assertEqual(tree["ty"]["storing_raw_ptr"], {"pub": 9, "total": 9})

    def test_a_namespace_node_gets_no_derived_total(self) -> None:
        """`ty.ffibox` is a namespace of families, not a counter.

        It holds a type population (`ccell` counts types) beside records of
        mentions (`wrapper` and `by_val` count places, and overlap each other:
        a cell held in a field is in both). Summing them mixes grains exactly
        as summing across a top-level prefix would, so no total is written
        there -- while every family under it keeps its own.
        """
        tree = measure.nest_ptr({
            "ty.ffibox.ccell.pub": 32,
            "ty.ffibox.wrapper.pub": 161,
            "ty.ffibox.wrapper.of_which.borrow.pub": 161,
            "ty.ffibox.by_val.pub": 109,
        })
        ffibox = tree["ty"]["ffibox"]
        self.assertNotIn("total", ffibox)
        self.assertEqual(ffibox["ccell"]["total"], 32)
        self.assertEqual(ffibox["wrapper"]["total"], 161)
        self.assertEqual(ffibox["by_val"]["total"], 109)
        # The namespace is declared, not inferred: `ty` itself is the
        # top-level case of the same rule.
        self.assertIn(("ty", "ffibox"), measure.NAMESPACES)
        self.assertNotIn("total", tree["ty"])

    def test_a_leaf_and_a_prefix_cannot_share_a_name(self) -> None:
        with self.assertRaises(ValueError):
            measure.nest_ptr({"code.unsafe_block": 1, "code.unsafe_block.of_which.x": 1})
        with self.assertRaises(ValueError):
            measure.nest_ptr({"code.unsafe_block.of_which.x": 1, "code.unsafe_block": 1})


if __name__ == "__main__":
    unittest.main()
