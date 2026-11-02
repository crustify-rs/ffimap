"""`docs/schema.md`'s counter list against the counters the driver registers.

The list is hand-written prose -- one row per counter, with a sentence saying
what it holds -- so nothing but a test keeps it from drifting from the driver.
Both directions are checked: a registered counter no row reaches would be
undocumented, and a row that reaches no counter would describe a counter that
does not exist.

Rows are read off the bullets of section 1, with `{a,b}` expanded into its
leaves and `<trait>` / `<primitive>` taken as a wildcard segment, since those
arms are generated from ffibox's vocabulary rather than spelled out.

Needs the driver, so it skips where cargo and the dated nightly are missing.
"""

import itertools
import re
import shutil
import unittest
from pathlib import Path

from ffimap import measure, scan

DOC = Path(__file__).parents[1] / "docs" / "schema.md"
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


def rows() -> list[str]:
    """The counter paths section 1's bullets name, splits expanded.

    A bullet leads with a backticked path; a row that spells a `{a,b}` split
    stands for one path per member, which is what the driver emits.
    """
    out = []
    section = DOC.read_text().split("## 2. ")[0]
    for line in section.splitlines():
        m = re.match(r"- `([a-z_][\w.{},<>]*)`", line.strip())
        if not m:
            continue
        path = m.group(1)
        groups = re.findall(r"\{([^}]*)\}", path)
        skeleton = re.sub(r"\{[^}]*\}", "{}", path)
        for pick in itertools.product(*(g.split(",") for g in groups)):
            out.append(skeleton.format(*pick))
    return out


def covers(row: str, leaf: str) -> bool:
    """True when `row` names `leaf`, a `<wildcard>` segment matching any name.

    Exact: a row stands for the leaves of its own splits and for nothing
    below them, so a family documented only at the record above it fails
    here rather than passing as covered.
    """
    rs, ls = row.split("."), leaf.split(".")
    if len(rs) != len(ls):
        return False
    return all(r == l or r.startswith("<") for r, l in zip(rs, ls))


def documented(rows: list[str], leaf: str) -> bool:
    """A leaf a row names, or a derived `total` of a record they name.

    Section 1 states once that every partition carries a derived `total`
    rather than spending a bullet on each, so a record's rows document its
    total too.
    """
    if any(covers(row, leaf) for row in rows):
        return True
    if leaf.endswith(".total"):
        record = leaf[: -len(".total")].split(".")
        for row in rows:
            segs = row.split(".")
            if len(segs) >= len(record) and all(
                    r == c or r.startswith("<")
                    for r, c in zip(segs, record)):
                return True
    return False


@unittest.skipUnless(_driver_available(), "needs cargo and the dated nightly")
class SchemaDocTests(unittest.TestCase):
    """The registry of a crate with nothing in it is every counter there is."""

    registry: list[str]
    rows: list[str]

    @classmethod
    def setUpClass(cls) -> None:
        tree = scan.compose(FIXTURES / "empty", ffibox=True,
                            seams=["from_raw"])["counts"]

        def leaves(node: dict, path: str = ""):
            for k, v in node.items():
                name = f"{path}.{k}" if path else k
                if isinstance(v, dict):
                    yield from leaves(v, name)
                else:
                    yield name

        cls.registry = list(leaves(tree))
        cls.rows = rows()

    def test_the_list_is_not_empty(self) -> None:
        """A regex that stops matching would otherwise pass everything."""
        self.assertGreater(len(self.rows), 100)
        self.assertGreater(len(self.registry), 100)

    def test_every_counter_has_a_row(self) -> None:
        for leaf in self.registry:
            with self.subTest(counter=leaf):
                self.assertTrue(
                    documented(self.rows, leaf),
                    f"{leaf} is registered by the driver and documented nowhere")

    def test_every_row_names_a_counter(self) -> None:
        for row in self.rows:
            with self.subTest(row=row):
                self.assertTrue(
                    any(covers(row, leaf) for leaf in self.registry),
                    f"{row} is in schema.md and the driver emits no such counter")
