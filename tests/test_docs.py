"""The docs do not say the same thing twice.

Each document owns a part: `schema.md` what each counter holds, `analysis.md`
how a scan runs and what each counter is decided from, `ffibox.md` the
convention the `--ffibox` arms read, `TODO.md` the work that is open. A fact
restated in two of them is two copies to keep current, and the copies drift --
which is how nine figures in the prose came to be stale at once.

Sentences are compared pairwise ACROSS files only. Within a file the
repetition is the format: `schema.md`'s counter list is one row per counter,
and sibling rows of one family read alike on purpose.
"""

import difflib
import itertools
import re
import unittest
from pathlib import Path

DOCS = Path(__file__).parents[1]
FILES = sorted((DOCS / "docs").glob("*.md")) + [
    DOCS / "README.md", DOCS / "examples" / "README.md"]

# Measured at 0.0 duplicated words when the split was made, so a pair at this
# ratio is a new copy rather than a tolerance that was always exceeded.
RATIO = 0.80


def prose(path: Path) -> str:
    """The file's prose: fenced code, tables and headings are not it."""
    out, fence = [], False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            fence = not fence
            continue
        if fence or line.startswith("#") or line.lstrip().startswith("|"):
            continue
        out.append(line)
    return re.sub(r"\s+", " ", "\n".join(out))


def sentences(path: Path) -> list[str]:
    """Sentences worth comparing: a clause of six words says nothing twice."""
    split = re.split(r"(?<=[.:;])\s+(?=[A-Z`\-*])", prose(path))
    return [s for s in (p.strip(" -*") for p in split) if len(s.split()) >= 8]


class CrossDocTests(unittest.TestCase):
    def test_no_sentence_is_restated_in_another_doc(self) -> None:
        sent = {p: sentences(p) for p in FILES}
        for a, b in itertools.combinations(FILES, 2):
            for x in sent[a]:
                for y in sent[b]:
                    # Only a pair of comparable length can be one sentence
                    # rewrapped; a short one inside a long one is a citation.
                    if abs(len(x) - len(y)) > 60:
                        continue
                    m = difflib.SequenceMatcher(None, x, y)
                    # `quick_ratio` is an upper bound and cheap, so it rules
                    # out all but a handful of the pairs before the real
                    # comparison runs on them.
                    if m.quick_ratio() < RATIO:
                        continue
                    r = m.ratio()
                    if r >= RATIO:
                        self.fail(
                            f"{a.name} and {b.name} say the same thing "
                            f"({r:.2f}); one of them should cite the other\n"
                            f"  {a.name}: {x}\n  {b.name}: {y}")

    def test_the_sentences_are_being_read(self) -> None:
        """A prose filter that stopped matching would pass everything."""
        for p in FILES:
            with self.subTest(doc=p.name):
                self.assertGreater(len(sentences(p)), 5)
