from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from ffimap import measure, scan


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


@unittest.skipUnless(measure.driver_prerequisites(), "needs cargo and the dated nightly")
class DriverManifestTests(unittest.TestCase):
    def test_the_driver_is_its_own_workspace_under_another(self) -> None:
        """A copy of the driver below a directory that holds a Cargo workspace,
        as a copy inside a scanned tree is, still resolves: without its own
        `[workspace]` table cargo refuses a package the outer one does not
        list, and the driver suites once skipped on that."""
        import shutil
        import subprocess
        with TemporaryDirectory() as tmp:
            outer = Path(tmp)
            (outer / "Cargo.toml").write_text("[workspace]\nmembers = []\n")
            copy = outer / "nested" / "driver"
            shutil.copytree(measure._DRIVER_CRATE, copy,
                            ignore=shutil.ignore_patterns("target"))
            r = subprocess.run(["cargo", f"+{measure._TOOLCHAIN}", "metadata", "--no-deps",
                                "--format-version", "1"], cwd=copy, capture_output=True,
                               text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


class DriverSuiteSkipTests(unittest.TestCase):
    """The suites that need the driver skip without the toolchain, and fail,
    not skip, where the toolchain is there and the driver does not build."""

    SUITES = ("test_canary", "test_cells", "test_interop", "test_registry",
              "test_schema_doc")

    def load(self, name: str) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            f"_probe_{name}", Path(__file__).with_name(f"{name}.py"))
        spec.loader.exec_module(importlib.util.module_from_spec(spec))

    def test_every_driver_suite_is_listed(self) -> None:
        using = sorted(p.stem for p in Path(__file__).parent.glob("test_*.py")
                       if p != Path(__file__) and "def _driver_available()" in p.read_text())
        self.assertEqual(using, sorted(self.SUITES))

    def test_a_driver_that_does_not_build_fails_each_suite(self) -> None:
        broken = measure.DriverUnavailable("driver build failed")
        for name in self.SUITES:
            with self.subTest(name), \
                    mock.patch.object(measure, "driver_prerequisites", return_value=True), \
                    mock.patch.object(measure, "_driver_bin", side_effect=broken):
                with self.assertRaises(measure.DriverUnavailable):
                    self.load(name)

    def test_a_host_without_the_toolchain_skips_each_suite(self) -> None:
        for name in self.SUITES:
            with self.subTest(name), \
                    mock.patch.object(measure, "driver_prerequisites", return_value=False), \
                    mock.patch.object(measure, "_driver_bin",
                                      side_effect=AssertionError("built without the toolchain")):
                self.load(name)



if __name__ == "__main__":
    unittest.main()
