"""diff.py — what changed between two documents of one crate.

A document is read most usefully against the one before it: which counters a
change moved, and where the new increments are. That is the feedback an agent
checks its own change with, so it is computed here once rather than by every
reader, and the same way for all of them.

Pure: it reads two documents and returns a third, and runs no scan.
"""
from __future__ import annotations


def leaves(node: dict | None, path: str = "") -> dict[str, int]:
    """Every leaf of a counter tree, by its dotted path."""
    out: dict[str, int] = {}
    for k, v in (node or {}).items():
        name = f"{path}.{k}" if path else k
        if isinstance(v, dict):
            out.update(leaves(v, name))
        else:
            out[name] = v
    return out


def _site_lines(rows: list[dict]) -> dict[str, tuple[int, set[int]]]:
    return {r["file"]: (r["count"], set(r["lines"])) for r in rows}


def diff(before: dict, after: dict) -> dict:
    """The difference between two documents, as a document.

    `scanner` holds both scanners when they differ, since a counter that moved
    under a different scanner may have moved for the scanner's sake; `null`
    when they agree. `counts` holds every leaf whose value differs, with its
    value before and after and the change, a leaf only one side has reading
    0 on the other. `sites` holds, for every counter both documents list
    sites for, the files whose increments changed, with the lines added and
    removed; a counter whose sites did not change is left out.
    """
    for name, doc in (("before", before), ("after", after)):
        if doc.get("counts") is None:
            raise ValueError(f"the {name} document has no counts: "
                             f"{doc.get('counts_unavailable')}")
    b, a = leaves(before["counts"]), leaves(after["counts"])
    counts = {
        k: {"before": b.get(k, 0), "after": a.get(k, 0),
            "delta": a.get(k, 0) - b.get(k, 0)}
        for k in sorted(set(b) | set(a))
        if b.get(k, 0) != a.get(k, 0)
    }
    sites: dict[str, list[dict]] = {}
    for k in sorted(set(before.get("sites") or {}) & set(after.get("sites") or {})):
        sb = _site_lines(before["sites"][k])
        sa = _site_lines(after["sites"][k])
        rows = []
        for f in sorted(set(sb) | set(sa)):
            nb, lb = sb.get(f, (0, set()))
            na, la = sa.get(f, (0, set()))
            if nb == na and lb == la:
                continue
            rows.append({"file": f, "delta": na - nb,
                         "added": sorted(la - lb), "removed": sorted(lb - la)})
        if rows:
            sites[k] = rows
    scanner = (None if before.get("scanner") == after.get("scanner")
               else {"before": before.get("scanner"), "after": after.get("scanner")})
    return {"scanner": scanner, "counts": counts, "sites": sites}
