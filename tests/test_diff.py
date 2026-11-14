"""`ffimap diff` over hand-built documents: no driver needed."""

import unittest

from ffimap import diff


# A `scanner.ffimap` that names one scanner: a commit.
COMMIT = "a" * 40


def doc(counts, sites=None, scanner=None):
    d = {"counts": counts, "scanner": scanner or {"ffimap": COMMIT}}
    if sites is not None:
        d["sites"] = sites
    return d


class DiffTests(unittest.TestCase):
    def test_a_document_against_itself_is_empty(self) -> None:
        d = doc({"fn": {"unsafe": {"pub": 2, "priv": 0}}},
                {"fn.unsafe.pub": [{"file": "a.rs", "count": 2, "lines": [3, 9]}]})
        self.assertEqual(diff.diff(d, d), {"scanner": None, "counts": {}, "sites": {}})

    def test_moved_counters_carry_before_after_and_delta(self) -> None:
        a = doc({"fn": {"unsafe": {"pub": 2, "priv": 1}}})
        b = doc({"fn": {"unsafe": {"pub": 3, "priv": 1}}, "static": {"total": {"pub": 1}}})
        out = diff.diff(a, b)["counts"]
        self.assertEqual(out["fn.unsafe.pub"], {"before": 2, "after": 3, "delta": 1})
        # A leaf only one side has reads 0 on the other.
        self.assertEqual(out["static.total.pub"], {"before": 0, "after": 1, "delta": 1})
        self.assertNotIn("fn.unsafe.priv", out)

    def test_sites_name_the_lines_added_and_removed(self) -> None:
        k = "raw_ptr.deref.wr"
        a = doc({"x": 1}, {k: [{"file": "a.rs", "count": 1, "lines": [4]}]})
        b = doc({"x": 1}, {k: [{"file": "a.rs", "count": 2, "lines": [4, 7]},
                               {"file": "b.rs", "count": 1, "lines": [1]}]})
        self.assertEqual(diff.diff(a, b)["sites"][k], [
            {"file": "a.rs", "delta": 1, "added": [7], "removed": []},
            {"file": "b.rs", "delta": 1, "added": [1], "removed": []},
        ])

    def test_scanners_that_name_none_are_never_the_same(self) -> None:
        """A package version, or `unknown`, is what every copy that is no
        checkout of its own records: two documents that agree on it are
        reported, not passed as scanned alike. A commit, bare or with the
        hash of its uncommitted changes, names one scanner."""
        for rev in ("0.1.0", "unknown", COMMIT + "+dirty"):
            a = doc({}, scanner={"ffimap": rev})
            self.assertEqual(diff.diff(a, a)["scanner"],
                             {"before": {"ffimap": rev}, "after": {"ffimap": rev}}, rev)
        for rev in (COMMIT, COMMIT + "+dirty." + "b" * 12):
            a = doc({}, scanner={"ffimap": rev})
            self.assertIsNone(diff.diff(a, a)["scanner"], rev)

    def test_a_scanner_change_is_reported(self) -> None:
        a, b = doc({}, scanner={"ffimap": "1"}), doc({}, scanner={"ffimap": "2"})
        self.assertEqual(diff.diff(a, b)["scanner"],
                         {"before": {"ffimap": "1"}, "after": {"ffimap": "2"}})

    def test_a_document_without_counts_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            diff.diff({"counts": None, "counts_unavailable": "no build"}, doc({}))
