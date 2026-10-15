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
            with mock.patch("ffimap.scan.measure.measure",
                            return_value=({"code_lines": 1}, {}, None)) as measure, \
                 mock.patch("ffimap.scan.measure.sys_crates",
                            return_value=["foo_sys"]):
                document = scan.compose(workspace)

            measure.assert_called_once_with(workspace, ffibox=False, sys=["foo_sys"])
            self.assertEqual(document["sys_crates"], ["foo_sys"])
            self.assertEqual(document["crate_path"], str(workspace))

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
            self.assertIsNone(document["ffibox"])
            self.assertEqual(document["derived"], {})


if __name__ == "__main__":
    unittest.main()
