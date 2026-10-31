import json
from pathlib import Path
import re
import unittest
from tempfile import TemporaryDirectory
from unittest import mock

from ffimap import measure, scan

MAIN_RS = Path(measure.__file__).parent / "driver" / "src" / "main.rs"


def _mirrored() -> list[str]:
    """The tree keys `mirror_into_tree` fills from `Counts`, in order."""
    src = MAIN_RS.read_text()
    body = re.search(r"fn mirror_into_tree.*?\n\}", src, re.S).group(0)
    return re.findall(r'\("([\w.]+)", c\.(?:\w+)\)', body)


def _counts_fields() -> list[str]:
    src = MAIN_RS.read_text()
    body = re.search(r"struct Counts \{(.*?)\n\}", src, re.S).group(1)
    return re.findall(r"^\s*(\w+): u64", body, re.M)


class EmissionTests(unittest.TestCase):
    def test_the_line_carries_the_tree_and_the_sites(self) -> None:
        """One shape, two members. A flat counter block beside the tree would
        be a second answer to every question the tree answers."""
        src = MAIN_RS.read_text()
        fmt = next(f for f in re.findall(r'"(\{\{\\"crate\\".*?\}\})"', src)
                   if "counts" in f)
        self.assertEqual(re.findall(r'\\"(\w+)\\":', fmt),
                         ["crate", "counts", "sites"])

    def test_every_counts_field_reaches_the_tree(self) -> None:
        """`Counts` holds only what is accumulated while walking and then
        mirrored; a field that reaches no tree key counts into nothing."""
        self.assertEqual(len(_mirrored()), len(_counts_fields()))


class MergeTests(unittest.TestCase):
    def test_tree_counters_sum_across_crates(self) -> None:
        line = lambda crate, n: json.dumps(
            {"crate": crate, "counts": {"fn.safe.pub": n, "raw_ptr.taken.safe.pub": n},
             "sites": {}})
        _, seen, counts = measure._collect_emissions(
            "\n".join([line("a", 2), line("b", 3), line("c_sys", 100)]))
        self.assertEqual(seen, 2)
        self.assertEqual(counts["fn.safe.pub"], 5)
        self.assertEqual(counts["raw_ptr.taken.safe.pub"], 5)



class SiteFamilyTests(unittest.TestCase):
    def test_every_counter_family_the_driver_emits_takes_sites(self) -> None:
        """`--sites` validates a dotted path against the prefix and the family
        under it. A family the driver emits but the table omits is rejected,
        which is how `raw_ptr.field` and `raw_ptr.in_impl` were unreachable
        when each was added.
        """
        src = MAIN_RS.read_text()
        emitted: set[tuple[str, str]] = set()
        for m in re.finditer(r'"((?:raw_ptr|void_ptr|ty|fn|code)\.[\w.{}]+)"', src):
            head, _, rest = m.group(1).partition(".")
            fam = rest.partition(".")[0]
            if fam and not fam.startswith("{"):
                emitted.add((head, fam))
        for head, fam in sorted(emitted):
            with self.subTest(counter=f"{head}.{fam}"):
                self.assertIn(fam, measure.TREE_SITE_FAMILIES[head])
                self.assertTrue(measure.is_tree_counter(f"{head}.{fam}.x"))


class SysCrateTests(unittest.TestCase):
    def test_emissions_of_sys_crates_are_skipped_by_name_or_links(self) -> None:
        line = lambda crate: json.dumps(
            {"crate": crate, "counts": {"code.unsafe_block.total": 1}, "sites": {}})
        _, seen, counts = measure._collect_emissions(
            "\n".join([line("safe"), line("ffmpeg_sys_the_third"), line("x_sys")]),
            {"ffmpeg_sys_the_third"})
        self.assertEqual(seen, 1)
        self.assertEqual(counts["code.unsafe_block.total"], 1)

    def test_sys_crates_are_exactly_the_named_ones(self) -> None:
        self.assertEqual(
            measure.sys_crates(["libgit2-sys", "libc", "libgit2_sys"]),
            ["libc", "libgit2_sys"])
        self.assertEqual(measure.sys_crates(None), [])

    def test_sys_crates_are_never_discovered(self) -> None:
        """A Cargo `links` key and a `*-sys` name both over-report, so the peel
        set is named and nothing is read from the build graph: `prettyplease`
        sets `links` to detect duplicate versions of itself, and bindgen's
        `clang_sys` matches the name, yet neither is part of the scanned
        crate's C surface. See docs/schema.md, The peel set."""
        from unittest import mock
        with mock.patch("ffimap.measure.subprocess.run") as run:
            self.assertEqual(measure.sys_crates(["libc"]), ["libc"])
        run.assert_not_called()


class PartitionTests(unittest.TestCase):
    def test_driver_hardcodes_no_seam_names(self) -> None:
        """The `local_seam` arm comes from `--seams`, never from the driver.

        The driver reads the names out of `UM_SEAM_FNS`. If it carried a list
        of its own, a crate's own conversions would stop being the user's to
        declare and start being a guess that differs per codebase.

        ffibox's vocabulary is the one exception, and it is not one of these:
        `FFIBOX_ADOPTERS` and `FFIBOX_PRIMITIVES` name a specific crate's
        published API, they are gated on `--ffibox`, and they feed the
        `casted_to.ffibox` arm, which is a different arm precisely so that
        ffibox's conversions are never counted as the crate's own.
        """
        src = MAIN_RS.read_text()
        self.assertIn("UM_SEAM_FNS", src)
        # Scan the `const ... : &[&str]` name lists, not the whole file: the
        # driver legitimately contains strings like "raw" as counter keys, and
        # grepping the source for them tests spelling rather than behaviour.
        # The ffibox vocabulary lists are excluded, per the docstring.
        lists = re.findall(
            r"const\s+(\w+)\s*:\s*&\[(?:&str|\(&str, &str\))\]\s*=\s*&\[(.*?)\];",
            src, re.S)
        declared = {
            n
            for name, body in lists
            if not name.startswith("FFIBOX_")
            for n in re.findall(r'"([^"]+)"', body)
        }
        self.assertLessEqual(
            declared & {"from_raw", "as_ptr", "from_ptr", "as_mut_ptr", "raw"},
            set(), f"driver hardcodes seam names: {declared}")

    def test_local_seam_arm_is_reached_only_through_is_seam_fn(self) -> None:
        """The guard above is about lists; this one is about the code path.

        A driver could stop hardcoding names and still bump `local_seam` from
        some other predicate. The arm must be reached from `is_seam_fn` and
        nothing else, so that an empty `--seams` yields an empty arm.
        """
        src = MAIN_RS.read_text()
        for m in re.finditer(r'bump_casted_to\("local_seam"', src):
            window = src[max(0, m.start() - 400):m.start()]
            self.assertIn(
                "is_seam_fn", window,
                "a local_seam bump is not guarded by is_seam_fn")

    def test_seam_counters_are_subsets_not_partitions(self) -> None:
        """A seam is counted in its own counter AND in the base one, so the
        two must never be summed: the document hangs them off `of_which`."""
        src = MAIN_RS.read_text()
        self.assertIn('format!("raw_ptr.{pos}.of_which.seam.{safety}.{vis}")', src)
        tree = measure.nest_ptr({"raw_ptr.taken.safe.pub": 10,
                                 "raw_ptr.taken.of_which.seam.safe.pub": 7})
        taken = tree["raw_ptr"]["taken"]
        self.assertEqual(taken["safe"], {"pub": 10, "total": 10})
        self.assertEqual(taken["of_which"]["seam"]["safe"], {"pub": 7, "total": 7})
        self.assertEqual(taken["total"], 10)   # not 17


if __name__ == "__main__":
    unittest.main()
