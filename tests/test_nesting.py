"""The `counts` tree and its inverse.

The nesting spec in `measure.py` is two tables that have to agree: one folds
the driver's flat counters into the tree, the other reads them back. A
round-trip over every counter the driver emits keeps them honest, and is the
test that would have caught `unsafe_blocks` being both a family total and an
`of_which` parent.
"""
import unittest

from ffimap import measure


def _one_of_each() -> dict:
    """Every counter the driver emits, with a distinct value so that a leaf
    landing in the wrong slot changes the round trip.

    `unsafe_fns` is a flat counter that must equal its two children, and
    `nest_counts` enforces that, so the fixture satisfies it rather than
    tripping the cross-check.
    """
    flat = {name: i + 1 for i, name in enumerate(measure._COUNTS)}
    flat["unsafe_fns"] = flat["unsafe_fns_pub"] + flat["unsafe_fns_priv"]
    return flat


class NestCountsTests(unittest.TestCase):
    def test_round_trip_is_exact_over_every_counter(self) -> None:
        flat = _one_of_each()
        self.assertEqual(measure.flatten_counts(measure.nest_counts(flat)), flat)

    def test_every_counter_is_placed(self) -> None:
        tree = measure.nest_counts(_one_of_each())
        self.assertEqual(set(measure.flatten_counts(tree)), set(measure._COUNTS))

    def test_partition_totals_sum_their_children(self) -> None:
        tree = measure.nest_counts({
            "raw_ptr_fn_pub_safe": 1, "raw_ptr_fn_pub_unsafe": 2,
            "raw_ptr_fn_priv_safe": 4, "raw_ptr_fn_priv_unsafe": 8,
        })
        self.assertEqual(tree["raw_ptr_fn"]["pub"]["total"], 3)
        self.assertEqual(tree["raw_ptr_fn"]["priv"]["total"], 12)
        self.assertEqual(tree["raw_ptr_fn"]["total"], 15)

    def test_of_which_subsets_are_not_summed_into_the_total(self) -> None:
        # unsafe_blocks_wrapper_impl re-counts blocks unsafe_blocks already
        # counted, so the total stays the emitted number.
        tree = measure.nest_counts({
            "unsafe_blocks": 100,
            "unsafe_blocks_wrapper_impl": 90,
            "unsafe_blocks_ffi_export": 5,
        })
        self.assertEqual(tree["unsafe_blocks"]["total"], 100)
        self.assertEqual(tree["unsafe_blocks"]["of_which"],
                         {"wrapper_impl": 90, "ffi_export": 5})

    def test_a_public_type_splits_its_fields_by_visibility(self) -> None:
        tree = measure.nest_counts({
            "raw_ptr_ty_pub_fields_pub": 1, "raw_ptr_ty_pub_fields_priv": 2,
            "raw_ptr_ty_priv": 4,
        })
        self.assertEqual(tree["raw_ptr_ty"]["pub"]["fields"], {"pub": 1, "priv": 2, "total": 3})
        self.assertEqual(tree["raw_ptr_ty"]["priv"], 4)
        self.assertEqual(tree["raw_ptr_ty"]["total"], 7)

    def test_a_flat_parent_total_must_match_its_children(self) -> None:
        with self.assertRaises(AssertionError):
            measure.nest_counts({"unsafe_fns": 99, "unsafe_fns_pub": 1,
                                 "unsafe_fns_priv": 1})


class NestFfiboxTests(unittest.TestCase):
    def test_round_trip_is_exact_over_every_counter(self) -> None:
        flat = {name: i + 1 for i, name in enumerate(measure.FFIBOX_COUNTERS)}
        self.assertEqual(measure.flatten_ffibox(measure.nest_ffibox(flat)), flat)

    def test_handles_and_owners_split_by_framework_then_visibility(self) -> None:
        tree = measure.nest_ffibox({
            "fn_sig_ffibox_handle_pub": 1, "fn_sig_ffibox_handle_priv": 2,
            "fn_sig_non_ffibox_handle_pub": 4, "fn_sig_non_ffibox_handle_priv": 8,
        })
        self.assertEqual(tree["fn_sig"]["ffibox"]["handle"], {"pub": 1, "priv": 2, "total": 3})
        self.assertEqual(tree["fn_sig"]["non_ffibox"]["handle"]["total"], 12)
        self.assertEqual(tree["fn_sig"]["total"], 15)


if __name__ == "__main__":
    unittest.main()
