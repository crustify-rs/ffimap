import json
from pathlib import Path
import re
import unittest

from ffimap import measure, scan

MAIN_RS = Path(measure.__file__).parent / "driver" / "src" / "main.rs"


def _emission() -> tuple[list[str], list[str]]:
    """The driver's per-crate JSON line: its keys, and the value arguments, in order."""
    src = MAIN_RS.read_text()
    fmt = re.search(r'"\{\{\\"crate\\":\\"\{\}\\",(.*?)\\"sites\\":\{\}\}\}"', src).group(1)
    keys = re.findall(r'\\"(\w+)\\":\{\}', fmt)
    args = src[src.index(fmt):].split("\n", 2)[1]
    values = re.findall(r"\bc\.(\w+)", args)
    return keys, values


def _counts_fields() -> list[str]:
    src = MAIN_RS.read_text()
    body = re.search(r"struct Counts \{(.*?)\n\}", src, re.S).group(1)
    return re.findall(r"^\s*(\w+): u64", body, re.M)


class EmissionTests(unittest.TestCase):
    def test_emitted_keys_match_their_values_in_order(self) -> None:
        keys, values = _emission()
        self.assertEqual(keys, values)

    def test_every_count_is_emitted_and_merged(self) -> None:
        keys, _ = _emission()
        self.assertEqual(set(_counts_fields()), set(keys))
        self.assertEqual(set(measure._COUNTS), set(keys))

    def test_visibility_splits_are_emitted(self) -> None:
        keys, _ = _emission()
        for k in ("unsafe_fns_pub", "unsafe_fns_priv", "safe_fns_pub", "safe_fns_priv",
                  "raw_ptr_fn_pub_safe", "raw_ptr_ty_pub_fields_pub"):
            self.assertIn(k, keys)
            self.assertIn(k, measure.SITE_COUNTERS)

    def test_thread_safety_opt_ins_are_emitted(self) -> None:
        keys, _ = _emission()
        i = keys.index("unsafe_traits")
        names = ["unsafe_send_impl", "unsafe_sync_impl", "c_type_layout_wrapper"]
        self.assertEqual(keys[i + 1:i + 1 + len(names)], names)
        for k in names:
            self.assertIn(k, measure.SITE_COUNTERS)

    def test_c_type_borrows_split_by_position_then_kind(self) -> None:
        keys, _ = _emission()
        i = keys.index("c_type_borrow_fn_sig_sanctioned_pub")
        names = [
            "c_type_borrow_fn_sig_sanctioned_pub", "c_type_borrow_fn_sig_sanctioned_priv",
            "c_type_borrow_fn_sig_non_sanctioned_pub", "c_type_borrow_fn_sig_non_sanctioned_priv",
            "c_type_borrow_fn_sig_opaque_pub", "c_type_borrow_fn_sig_opaque_priv",
            "c_type_borrow_fn_body_non_sanctioned", "c_type_borrow_fn_body_opaque",
            "c_type_borrow_fn_body_generic",
            "c_type_borrow_ty_non_sanctioned_pub_fields_pub",
            "c_type_borrow_ty_non_sanctioned_pub_fields_priv",
            "c_type_borrow_ty_non_sanctioned_priv",
            "c_type_borrow_ty_opaque_pub_fields_pub",
            "c_type_borrow_ty_opaque_pub_fields_priv",
            "c_type_borrow_ty_opaque_priv",
            "raw_ptr_as_slice_borrow",
        ]
        self.assertEqual(keys[i:i + len(names)], names)
        for k in names:
            self.assertIn(k, measure.SITE_COUNTERS)
        self.assertFalse([k for k in keys if k.startswith(("ty_wrapper", "ty_non_wrapper"))])

    def test_absent_position_kind_cells_are_not_emitted(self) -> None:
        """A kind that cannot occur in a position gets no counter at all,
        rather than one that is always 0: sanctioned is a signature-only
        distinction, and `generic` -- a borrow whose referent is a type
        parameter -- is only decidable in a body."""
        keys, _ = _emission()
        for absent in ("c_type_borrow_fn_sig_generic_pub", "c_type_borrow_fn_sig_generic_priv",
                       "c_type_borrow_fn_body_sanctioned",
                       "c_type_borrow_ty_sanctioned_priv",
                       "c_type_borrow_ty_generic_priv"):
            self.assertNotIn(absent, keys)
        # ...and the pre-split names are gone entirely.
        for old in ("c_type_borrow_sanctioned", "c_type_borrow_non_sanctioned",
                    "c_type_borrow_opaque", "c_type_borrow_generic"):
            self.assertNotIn(old, keys)

    def test_redundant_wrapper_counters_are_gone(self) -> None:
        keys, _ = _emission()
        for k in ("deref_impl_on_wrapper", "ty_wrapper_deref_impl", "ty_wrapper_deref_mut_impl",
                  "ty_wrapper_send_impl", "ty_wrapper_sync_impl"):
            self.assertNotIn(k, keys)
        self.assertFalse([k for k in keys if k.startswith("ptr_wrapper")])

    def test_new_counts_sum_across_crates(self) -> None:
        line = lambda crate, n: json.dumps(
            {"crate": crate, "unsafe_blocks": 0, "safe_fns_pub": n, "raw_ptr_fn_pub_safe": n, "sites": {}})
        counts, _, seen, _ = measure._collect_emissions(
            "\n".join([line("a", 2), line("b", 3), line("c_sys", 100)]))
        self.assertEqual(seen, 2)
        self.assertEqual(counts["safe_fns_pub"], 5)
        self.assertEqual(counts["raw_ptr_fn_pub_safe"], 5)


class FfiboxTests(unittest.TestCase):
    def test_counters_match_the_driver_in_order(self) -> None:
        src = MAIN_RS.read_text()
        body = re.search(r"const FFIBOX_COUNTERS: &\[&str\] = &\[(.*?)\];", src, re.S).group(1)
        self.assertEqual(tuple(re.findall(r'"(\w+)"', body)), measure.FFIBOX_COUNTERS)

    def test_breakdowns_merge_across_crates_and_skip_sys(self) -> None:
        line = lambda crate, n: json.dumps({
            "crate": crate,
            "ffibox": {"fn_sig_ffibox_owner_pub": {"CBox": n}, "ffibox_impl_manual": {"CDrop": 1}},
            "sites": {"fn_sig_ffibox_owner_pub": [{"file": "a.rs", "count": n, "lines": [1]}]}})
        _, sites, seen, ffibox = measure._collect_emissions(
            "\n".join([line("a", 2), line("b", 3), line("c_sys", 100)]))
        # an ffibox line is not a metrics line
        self.assertEqual(seen, 0)
        self.assertEqual(ffibox["fn_sig_ffibox_owner_pub"], {"CBox": 5})
        self.assertEqual(ffibox["ffibox_impl_manual"], {"CDrop": 2})
        self.assertEqual(ffibox["fn_sig_ffibox_handle_priv"], {})
        self.assertEqual(sum(r["count"] for r in sites["fn_sig_ffibox_owner_pub"]), 5)

    def test_record_totals_every_counter(self) -> None:
        rec = scan._ffibox_record({"fn_sig_ffibox_handle_pub": {"Ref": 4, "Mut": 1}})
        # `counts` is the tree; every counter is still there, as a leaf.
        self.assertEqual(set(measure.flatten_ffibox(rec["counts"])),
                         set(measure.FFIBOX_COUNTERS))
        self.assertEqual(rec["counts"]["fn_sig"]["ffibox"]["handle"]["pub"], 5)
        self.assertEqual(rec["counts"]["fn_sig"]["ffibox"]["owner"]["pub"], 0)
        # `by` stays keyed by the flat leaf name: a breakdown belongs to a leaf.
        self.assertEqual(rec["by"]["fn_sig_ffibox_handle_pub"], {"Mut": 1, "Ref": 4})
        self.assertIsNone(scan._ffibox_record(None))

    def test_owner_handle_sites_need_no_flag(self) -> None:
        # The owner / handle record is always measured: its `non_ffibox` half
        # counts what the crate wrote itself, which holds with or without
        # ffibox, so its site counters take no flag.
        self.assertEqual(scan.site_counters(["fn_sig_ffibox_owner_pub"]),
                         ["fn_sig_ffibox_owner_pub"])
        self.assertEqual(scan.site_counters(["fn_sig_non_ffibox_handle_pub"]),
                         ["fn_sig_non_ffibox_handle_pub"])
        self.assertIn("fn_sig_ffibox_owner_pub", scan.site_counters(["all"]))
        # <counter>:<key> selects one key of a breakdown.
        self.assertEqual(scan.site_counters(["fn_sig_ffibox_owner_pub:CVal"]),
                         ["fn_sig_ffibox_owner_pub:CVal"])
        # A plain counter has no breakdown, so it takes no key.
        with self.assertRaises(SystemExit):
            scan.site_counters(["raw_ptr_fn_pub_safe:x"])
        with self.assertRaises(SystemExit):
            scan.site_counters(["no_such_counter"])


class SysCrateTests(unittest.TestCase):
    def test_emissions_of_sys_crates_are_skipped_by_name_or_links(self) -> None:
        line = lambda crate: json.dumps({"crate": crate, "unsafe_blocks": 1, "sites": {}})
        counts, _, seen, _ = measure._collect_emissions(
            "\n".join([line("safe"), line("ffmpeg_sys_the_third"), line("x_sys")]),
            {"ffmpeg_sys_the_third"})
        self.assertEqual(seen, 1)
        self.assertEqual(counts["unsafe_blocks"], 1)

    def test_sys_crates_reads_links_keys(self) -> None:
        from unittest import mock
        meta = {"packages": [
            {"name": "libgit2-sys", "links": "git2",
             "targets": [{"name": "libgit2_sys", "kind": ["lib"]}]},
            {"name": "pcre2-sys", "links": None,
             "targets": [{"name": "pcre2_sys", "kind": ["lib"]}]},
            {"name": "git2", "links": None, "targets": [{"name": "git2", "kind": ["lib"]}]}]}
        done = mock.Mock(returncode=0, stdout=json.dumps(meta))
        with mock.patch("ffimap.measure.subprocess.run", return_value=done):
            self.assertEqual(measure.sys_crates(Path("."), ["libc"]), ["libc", "libgit2_sys", "pcre2_sys"])


class PartitionTests(unittest.TestCase):
    def test_driver_hardcodes_no_seam_names(self) -> None:
        """Seam names come from `--seams`, never from the driver.

        The driver reads them out of `UM_SEAM_FNS`; it must not carry a list
        of its own, or the classification stops being the user's to declare
        and starts being a guess that differs per codebase.
        """
        src = MAIN_RS.read_text()
        self.assertIn("UM_SEAM_FNS", src)
        for guess in ('"from_raw"', '"as_ptr"', '"from_ptr"', '"as_mut_ptr"', '"raw"'):
            self.assertNotIn(guess, src, f"driver hardcodes the seam name {guess}")

    def test_seam_counters_are_subsets_not_partitions(self) -> None:
        """A seam is counted in its own counter AND in the base one, so the
        two must never be summed: the document hangs them off `of_which`."""
        for leaf, parent in (("safe_fns_seam_pub", ("safe_fns", "pub")),
                             ("unsafe_fns_seam_priv", ("unsafe_fns", "priv")),
                             ("raw_ptr_fn_seam_pub_safe", ("raw_ptr_fn", "pub", "safe"))):
            self.assertIn(leaf, measure._COUNTS)
            self.assertIn(leaf, measure.SITE_COUNTERS)
            self.assertEqual(measure._OF_WHICH[leaf], (parent, "seam"))
        tree = measure.nest_counts({"safe_fns_pub": 10, "safe_fns_priv": 0,
                                    "safe_fns_seam_pub": 7})
        self.assertEqual(tree["safe_fns"]["pub"], {"total": 10, "of_which": {"seam": 7}})
        self.assertEqual(tree["safe_fns"]["total"], 10)   # not 17

    def test_raw_and_void_partitions_are_emitted(self) -> None:
        keys, _ = _emission()
        parts = ("ty_pub_fields_pub", "ty_pub_fields_priv", "ty_priv", "fn_pub_safe", "fn_pub_unsafe",
                 "fn_priv_safe", "fn_priv_unsafe")
        for k in ("raw_ptr", "raw_ptr_args", "raw_ptr_rets", "raw_ptr_fields", "void_ptr"):
            self.assertNotIn(k, keys)
        for fam in ("raw_ptr", "void_ptr"):
            for part in parts:
                self.assertIn(f"{fam}_{part}", keys)
                self.assertIn(f"{fam}_{part}", measure.SITE_COUNTERS)
        for k in ("unsafe_fns", "unsafe_fns_pub", "unsafe_fns_priv",
                  "non_c_type_borrow_pub_safe", "non_c_type_borrow_pub_unsafe",
                  "non_c_type_borrow_priv_safe", "non_c_type_borrow_priv_unsafe"):
            self.assertIn(k, keys)

    def test_wrapper_value_families_are_emitted(self) -> None:
        keys, _ = _emission()
        for fam in ("by_val", "std_owner"):
            for part in ("fn_sig_pub", "fn_sig_priv", "ty_pub_fields_pub",
                         "ty_pub_fields_priv", "ty_priv"):
                self.assertIn(f"c_type_{fam}_{part}", keys)
                self.assertIn(f"c_type_{fam}_{part}", measure.SITE_COUNTERS)

    def test_ffibox_fn_and_ty_families_mirror(self) -> None:
        kinds = [k[len("fn_sig_"):-len("_pub")] for k in measure.FFIBOX_COUNTERS
                 if k.startswith("fn_sig_") and k.endswith("_pub")]
        self.assertEqual(kinds, ["ffibox_owner", "ffibox_handle", "non_ffibox_owner",
                                 "non_ffibox_handle"])
        for k in kinds:
            for name in (f"fn_sig_{k}_priv", f"ty_pub_fields_pub_{k}",
                         f"ty_pub_fields_priv_{k}", f"ty_priv_{k}"):
                self.assertIn(name, measure.FFIBOX_COUNTERS)
        self.assertFalse([k for k in measure.FFIBOX_COUNTERS
                          if "_sig_" in k and not k.startswith("fn_sig_") or k.endswith("_seam")])


if __name__ == "__main__":
    unittest.main()
