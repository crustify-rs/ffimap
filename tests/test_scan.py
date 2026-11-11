from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from ffimap import scan


class ComposeTests(unittest.TestCase):
    def test_compose_scans_the_given_workspace(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "Cargo.toml").write_text("[workspace]\n")
            counts = {"code": {"loc": {"total": 1}}}
            with mock.patch("ffimap.scan.measure.measure",
                            return_value=({}, counts)) as measure, \
                 mock.patch("ffimap.scan.measure.sys_crates",
                            return_value=["foo_sys"]):
                document = scan.compose(workspace)

            measure.assert_called_once_with(workspace, ffibox=False, sys=["foo_sys"],
                                            seams=None, regions=None,
                                            barriers=None, features=None)
            self.assertEqual(document["sys_crates"], ["foo_sys"])
            self.assertEqual(document["crate_path"], str(workspace))
            self.assertEqual(document["counts"], counts)
            # what scanned, so a document cannot drift from its provenance
            self.assertEqual(set(document["scanner"]),
                             {"ffimap", "toolchain", "ffibox", "seams", "regions",
                              "barriers", "features"})

    def test_features_reach_the_build_and_the_record(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "Cargo.toml").write_text("[workspace]\n")
            with mock.patch("ffimap.scan.measure.measure",
                            return_value=({}, {})) as measure, \
                 mock.patch("ffimap.scan.measure.sys_crates", return_value=[]):
                document = scan.compose(workspace, features=["b", "a"])

            self.assertEqual(measure.call_args.kwargs["features"], ["b", "a"])
            self.assertEqual(document["scanner"]["features"], ["a", "b"])

    def test_a_failed_build_gives_no_counts(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with mock.patch("ffimap.scan.measure.measure",
                            side_effect=scan.measure.DriverUnavailable("no build")), \
                 mock.patch("ffimap.scan.measure.sys_crates", return_value=[]), \
                 mock.patch("ffimap.scan.stderr"):
                document = scan.compose(workspace, ffibox=True)

            self.assertIsNone(document["counts"])
            self.assertEqual(document["counts_unavailable"], "no build")
            self.assertNotIn("ffibox", document)
            self.assertNotIn("derived", document)


if __name__ == "__main__":
    unittest.main()
