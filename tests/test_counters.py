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
        names = ["unsafe_send_impl", "unsafe_sync_impl",
                 "ty_wrapper_send_impl", "ty_wrapper_sync_impl",
                 "ptr_wrapper_send_impl", "ptr_wrapper_sync_impl",
                 "ty_wrapper", "ptr_wrapper"]
        self.assertEqual(keys[i + 1:i + 1 + len(names)], names)
        for k in names:
            self.assertIn(k, measure.SITE_COUNTERS)

    def test_deref_impls_split_by_wrapper_kind(self) -> None:
        keys, _ = _emission()
        self.assertNotIn("deref_impl_on_wrapper", keys)
        for kind in ("ty_wrapper", "ptr_wrapper"):
            for k in (f"{kind}_deref_impl", f"{kind}_deref_mut_impl"):
                self.assertIn(k, keys)
                self.assertIn(k, measure.SITE_COUNTERS)

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
            "ffibox": {"fn_sig_ffibox_owner_pub": {"CBox": n}, "drop_impl": {"crate::Owner": 1}},
            "sites": {"fn_sig_ffibox_owner_pub": [{"file": "a.rs", "count": n, "lines": [1]}]}})
        _, sites, seen, ffibox = measure._collect_emissions(
            "\n".join([line("a", 2), line("b", 3), line("c_sys", 100)]))
        # an ffibox line is not a metrics line
        self.assertEqual(seen, 0)
        self.assertEqual(ffibox["fn_sig_ffibox_owner_pub"], {"CBox": 5})
        self.assertEqual(ffibox["drop_impl"], {"crate::Owner": 2})
        self.assertEqual(ffibox["fn_sig_ffibox_handle_priv"], {})
        self.assertEqual(sum(r["count"] for r in sites["fn_sig_ffibox_owner_pub"]), 5)

    def test_record_totals_every_counter(self) -> None:
        rec = scan._ffibox_record({"fn_sig_ffibox_handle_pub": {"Ref": 4, "Mut": 1}})
        self.assertEqual(set(rec["counts"]), set(measure.FFIBOX_COUNTERS))
        self.assertEqual(rec["counts"]["fn_sig_ffibox_handle_pub"], 5)
        self.assertEqual(rec["counts"]["fn_sig_ffibox_owner_pub"], 0)
        self.assertIsNone(scan._ffibox_record(None))

    def test_ffibox_sites_need_the_flag(self) -> None:
        with self.assertRaises(SystemExit) as e:
            scan.site_counters(["fn_sig_ffibox_owner_pub"])
        self.assertIn("--ffibox", str(e.exception))
        self.assertEqual(scan.site_counters(["fn_sig_ffibox_owner_pub"], ffibox=True),
                         ["fn_sig_ffibox_owner_pub"])
        self.assertNotIn("fn_sig_ffibox_owner_pub", scan.site_counters(["all"]))
        self.assertEqual(scan.site_counters(["fn_sig_ffibox_owner_pub:CVal"], ffibox=True),
                         ["fn_sig_ffibox_owner_pub:CVal"])
        with self.assertRaises(SystemExit):
            scan.site_counters(["fn_sig_ffibox_owner_pub:CVal"])
        with self.assertRaises(SystemExit):
            scan.site_counters(["raw_ptr_fn_pub_safe:x"], ffibox=True)
        self.assertIn("fn_sig_ffibox_owner_pub", scan.site_counters(["all"], ffibox=True))


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
    def test_driver_carries_no_seam_names(self) -> None:
        src = MAIN_RS.read_text()
        self.assertNotIn("UM_SEAM_FNS", src)
        self.assertFalse([k for k in measure._COUNTS if k.endswith(("_seam", "_smell"))
                          and not k.startswith("ty_wrapper_borrow")])

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
                  "ty_non_wrapper_borrow_pub_safe", "ty_non_wrapper_borrow_pub_unsafe",
                  "ty_non_wrapper_borrow_priv_safe", "ty_non_wrapper_borrow_priv_unsafe"):
            self.assertIn(k, keys)

    def test_wrapper_value_families_are_emitted(self) -> None:
        keys, _ = _emission()
        for fam in ("by_val", "std_owner"):
            for part in ("fn_sig_pub", "fn_sig_priv", "ty_pub_fields_pub",
                         "ty_pub_fields_priv", "ty_priv"):
                self.assertIn(f"ty_wrapper_{fam}_{part}", keys)
                self.assertIn(f"ty_wrapper_{fam}_{part}", measure.SITE_COUNTERS)

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
