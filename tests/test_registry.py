"""Every counter the driver can emit is in the document, at zero if it never fired.

A document is read on its own, so an absent counter cannot be told from one
the schema does not have. `register_counters` in the driver puts every path
its flags turn on into the tally at 0; what is still absent is what the flags
did NOT turn on, which is a different statement and a deliberate one.

The registry is read off a crate with nothing in it: a scan of
`tests/fixtures/empty/` is exactly what was registered. The other fixtures are
then held to it, so a counter that fires without being registered fails here.

Needs the driver, so it skips where cargo and the dated nightly are missing.
"""

import shutil
import unittest
from pathlib import Path

from ffimap import measure, scan

FIXTURES = Path(__file__).parent / "fixtures"


def _driver_available() -> bool:
    """cargo on the PATH and the driver buildable, as in test_canary."""
    if shutil.which("cargo") is None:
        return False
    try:
        measure._driver_bin()
    except Exception:
        return False
    return True


def flat(tree: dict, path: str = "") -> dict:
    """The tree's leaves by dotted path, derived totals included."""
    out = {}
    for k, v in tree.items():
        name = f"{path}.{k}" if path else k
        if isinstance(v, dict):
            out.update(flat(v, name))
        else:
            out[name] = v
    return out


@unittest.skipUnless(_driver_available(), "needs cargo and the dated nightly")
class RegistryTests(unittest.TestCase):
    """Scanned once per flag combination the fixtures use."""

    plain: dict
    ffibox: dict

    @classmethod
    def setUpClass(cls) -> None:
        empty = FIXTURES / "empty"
        cls.plain = flat(scan.compose(empty, seams=["from_raw"])["counts"])
        cls.ffibox = flat(scan.compose(empty, ffibox=True)["counts"])

    def test_the_registry_is_every_counter_at_zero(self) -> None:
        """A crate with nothing in it fires nothing, so every leaf reads 0.

        But one. `code.tests.fn` reads 1 on a crate with no functions at all,
        because the lib's test target carries the harness `main` that rustc
        generates for it, and the subtraction of the library's own fns does
        not reach it. The fixture is what exposed it; see `docs/TODO.md`.
        """
        self.assertGreater(len(self.plain), 60)
        nonzero = {k: v for k, v in self.plain.items() if v}
        self.assertEqual(nonzero, {"code.tests.fn": 1})

    def test_a_counter_that_fires_was_registered(self) -> None:
        """The direction that matters: an arm added to a pass and not to the
        registry would go out as an absence on every crate that never hits
        it, which is the thing this change exists to remove.
        """
        for name, fixture, doc in (
            ("canary", scan.compose(FIXTURES / "canary", seams=["from_raw"],
                                    sys_crates=["canary-sys"]), self.plain),
            ("cells", scan.compose(FIXTURES / "cells", ffibox=True), self.ffibox),
        ):
            for counter, value in sorted(flat(fixture["counts"]).items()):
                if value:
                    with self.subTest(fixture=name, counter=counter):
                        self.assertIn(counter, doc)

    def test_the_ffibox_arms_are_absent_without_the_flag(self) -> None:
        """Absent, not zero: the scan did not look, and a 0 would say it
        looked and found none. The same holds for the seam shares, which are
        registered only when `--seams` names something."""
        self.assertNotIn("ty.ffibox.ccell.pub", self.plain)
        self.assertNotIn("fn.ffibox.taken.CBox.pub", self.plain)
        self.assertIn("ty.ffibox.ccell.pub", self.ffibox)
        self.assertIn("raw_ptr.taken.of_which.seam.safe.pub", self.plain)
        self.assertNotIn("raw_ptr.taken.of_which.seam.safe.pub", self.ffibox)

    def test_a_namespace_still_carries_no_total(self) -> None:
        """Registering zeros must not give one a derived total of 0 either."""
        tree = scan.compose(FIXTURES / "empty", ffibox=True)["counts"]
        self.assertNotIn("total", tree["ty"]["ffibox"])
        self.assertNotIn("total", tree["code"]["tests"])


if __name__ == "__main__":
    unittest.main()
