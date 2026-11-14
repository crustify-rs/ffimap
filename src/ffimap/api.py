"""api.py — a crate's consumer-facing surface per C item, and how it moved.

A crate that stands in for a C library annotates each Rust item that stands in
for a C item with an anchor, a doc line ``Wraps `<kind>::<path>` `` or
``Replaces `<kind>::<path>` ``, and a ``#[doc(alias = "<path>")]``. The anchor
is the only record of which Rust items a C item became, so it is what this
module keys on: `extract` reads one rustdoc JSON document and builds, per C
item, the public surface of the Rust items that stand in for it; `diff` compares
two extracts and classifies each C item as kept, extended, changed, removed or
new. `docs/api.md` describes both documents and every rule.

Pure: it reads documents and returns documents, and runs no build.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from ffimap import contract as ct
from ffimap.rustdoc import Crate, FormatError, kind

# The document this module writes; bumped when its shape or a rule changes, so
# two extracts are compared only under one.
VERSION = 2

ANCHOR = re.compile(r"^(Wraps|Replaces) `([a-z]+)::([^`\s]+)`$")
# A line that tries to be an anchor: the verb followed by a kind-prefixed path,
# in backticks or not. Prose such as "Replaces the name" is not one.
ATTEMPT = re.compile(r"\b(Wraps|Replaces)\s+`?[a-z]+::")
NAME = r"[A-Za-z_][A-Za-z0-9_]*"
PATH = re.compile(rf"^{NAME}(\.{NAME})*$")
ALIAS = re.compile(r'alias\s*(?:=\s*"([^"]*)"|\(([^)]*)\))')
# The kinds the anchor convention names. Another kind is still keyed, as
# written, and reported, since a misspelt kind splits one C item in two.
KINDS = frozenset({"fn", "st", "un", "enm", "fnp", "tdf", "fld", "glb", "mac"})

TYPE_KINDS = ("struct", "enum", "union", "trait", "type_alias")
STATUSES = ("kept", "extended", "changed", "removed", "new")
LIFETIME = re.compile(r"'(?!static\b)[A-Za-z_][A-Za-z0-9_]*")


def _erase_lifetimes(s: str) -> str:
    return LIFETIME.sub("'_", s)


def anchors(docs: str | None) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """The item's anchors as ``(verb, kind, path)``, and its malformed lines.

    An anchor is a doc line of its own, exactly the convention's form. A line
    that tries to be one and is not -- inside a sentence, without backticks,
    with a trailing period, or with a path that is not dot-separated names --
    is returned with the reason instead, and keys nothing.
    """
    good, bad = [], []
    for raw in (docs or "").splitlines():
        line = raw.strip()
        m = ANCHOR.match(line)
        if m:
            verb, k, path = m.groups()
            if not PATH.match(path):
                bad.append((line, "path is not dot-separated names"))
            elif k == "fld" and "." not in path:
                bad.append((line, "fld path names no member"))
            else:
                good.append((verb, k, path))
        elif ATTEMPT.search(line):
            bad.append((line, "not an anchor line"))
    return good, bad


def aliases(item: dict) -> set[str]:
    out: set[str] = set()
    for a in item.get("attrs") or []:
        text = a.get("other") if isinstance(a, dict) else a
        if not isinstance(text, str) or "doc" not in text:
            continue
        for eq, lst in ALIAS.findall(text):
            if eq:
                out.add(eq)
            else:
                out.update(s.strip().strip('"') for s in lst.split(","))
    return out


def _type_ids(node) -> set[str]:
    """Every item a type names by id, its generic arguments included."""
    out: set[str] = set()
    if isinstance(node, dict):
        rp = node.get("resolved_path")
        if isinstance(rp, dict) and rp.get("id") is not None:
            out.add(str(rp["id"]))
        for v in node.values():
            out |= _type_ids(v)
    elif isinstance(node, list):
        for v in node:
            out |= _type_ids(v)
    return out


class _Extractor:
    def __init__(self, crate: Crate, deps: list[Crate] = (),
                 plumbing: frozenset[str] = frozenset({"ffibox"})) -> None:
        self.c = crate
        self.deps = list(deps)
        self.plumbing = frozenset(plumbing)
        self.anchored: dict[str, list[tuple[str, str, str]]] = {}
        self.malformed: list[dict] = []
        self.without_alias: list[dict] = []
        self.unknown_kinds: Counter = Counter()
        for iid, item in crate.index.items():
            if item.get("crate_id") != 0:
                continue
            good, bad = anchors(item.get("docs"))
            for line, why in bad:
                self.malformed.append({"item": self.locator(iid), "line": line,
                                       "reason": why})
            if not good:
                continue
            self.anchored[iid] = good
            al = aliases(item)
            for verb, k, path in good:
                if k not in KINDS:
                    self.unknown_kinds[k] += 1
                # rustdoc rejects an alias equal to its item's name, which
                # already answers a search for it: such an item carries none.
                if path not in al and path != item.get("name"):
                    self.without_alias.append({"item": self.locator(iid),
                                               "anchor": f"{k}::{path}"})

    # -- naming ---------------------------------------------------------

    def locator(self, iid: str) -> str:
        """A stable name for any item, associated ones included.

        A free item is its canonical path; an impl's item is
        ``Ty::name`` or ``<Ty as Trait>::name``; a trait's item, a variant
        and a field are their owner's locator and their name. Lifetime names
        are erased, since renaming one is invisible to a caller.
        """
        c = self.c
        item = c.index[iid]
        parent = c.parent.get(iid)
        name = item.get("name")
        if parent is None:
            return c.item_path(iid)
        p = c.index[parent]
        if kind(p) == "impl":
            owner = _erase_lifetimes(c.impl_owner(p["inner"]["impl"]))
        else:
            owner = self.locator(parent)
        return f"{owner}::{name}"

    def paths(self, iid: str) -> list[str]:
        """The paths a consumer names the item by; an associated item's are its owner's."""
        c = self.c
        if iid in c.public_paths:
            return c.public_paths[iid]
        parent = c.parent.get(iid)
        if parent is None:
            return []
        name = c.index[iid].get("name") or "?"
        p = c.index[parent]
        if kind(p) == "impl":
            im = p["inner"]["impl"]
            owners = c.public_paths.get(_rid(im["for"]) or "", [])
            if im.get("trait"):
                tr = c.path(im["trait"])
                return [f"<{o} as {tr}>::{name}" for o in owners]
            return [f"{o}::{name}" for o in owners]
        return [f"{o}::{name}" for o in self.paths(parent)]

    # -- signatures -----------------------------------------------------

    def sig(self, iid: str, exclude: set[str]) -> dict:
        """The item's normalised signature.

        `exclude` holds the anchored items, which a type's members leave out:
        each is its own C item's stand-in, attributed there and not twice.
        """
        c = self.c
        item = c.index[iid]
        k = kind(item)
        inner = item["inner"][k]
        parent = c.parent.get(iid)
        pinner = c.index[parent]["inner"] if parent else {}
        if k == "function":
            out = {"decl": c.function(inner)}
            if "impl" in pinner:
                out["impl"] = c.impl_header(pinner["impl"])
            if "trait" in pinner:
                out["default"] = bool(inner.get("has_body"))
            return out
        if k in ("struct", "enum", "union"):
            return self.type_sig(iid, exclude)
        if k == "trait":
            return self.trait_sig(iid)
        if k == "type_alias":
            params, where = c.generics(inner["generics"])
            return {"decl": f"type{params} = {c.ty(inner['type'])}{where}"}
        if k == "constant":
            return {"decl": f"const: {c.ty(inner['type'])} = {c.constant(inner['const'])}"}
        if k == "static":
            return {"decl": f"{'unsafe ' if inner.get('is_unsafe') else ''}static "
                            f"{'mut ' if inner.get('is_mutable') else ''}"
                            f": {c.ty(inner['type'])} = {inner.get('expr', '_')}"}
        if k == "assoc_const":
            out = {"decl": f"const: {c.ty(inner['type'])}"
                           + (f" = {inner['value']}" if inner.get("value") is not None else "")}
            if "impl" in pinner:
                out["impl"] = c.impl_header(pinner["impl"])
            return out
        if k == "assoc_type":
            return {"decl": self.assoc_type(inner)}
        if k == "variant":
            return {"decl": self.variant(inner)}
        if k == "struct_field":
            return {"decl": c.ty(inner)}
        if k == "macro":
            return {"decl": "macro_rules!"}
        if k == "proc_macro":
            return {"decl": f"proc_macro {inner.get('kind')}"}
        return {"decl": k}

    def assoc_type(self, inner: dict) -> str:
        c = self.c
        params, where = c.generics(inner.get("generics"))
        s = f"type{params}"
        if inner.get("bounds"):
            s += f": {c.bounds(inner['bounds'])}"
        if inner.get("type") is not None:
            s += f" = {c.ty(inner['type'])}"
        return s + where

    def variant(self, v: dict) -> str:
        c = self.c
        vk = v["kind"]
        if vk == "plain":
            s = "plain"
        elif "tuple" in vk:
            s = "(" + ", ".join(c.ty(c.index[str(f)]["inner"]["struct_field"])
                                if f is not None else "_" for f in vk["tuple"]) + ")"
        else:
            st = vk["struct"]
            fs = [f"{c.index[str(f)]['name']}: {c.ty(c.index[str(f)]['inner']['struct_field'])}"
                  for f in st["fields"]]
            if st.get("has_stripped_fields"):
                fs.append("..")
            s = "{ " + ", ".join(fs) + " }"
        if v.get("discriminant"):
            d = v["discriminant"]
            s += f" = {d.get('value') or d.get('expr')}"
        return s

    def impls_of(self, inner: dict) -> list[dict]:
        return [self.c.index[str(i)]["inner"]["impl"] for i in inner.get("impls") or []
                if str(i) in self.c.index]

    def type_sig(self, iid: str, exclude: set[str]) -> dict:
        """A struct's, enum's or union's surface.

        Its declaration and shape, its public fields or its variants, every
        trait impl rustdoc records for it but the blanket ones (auto traits
        included, as rustdoc synthesises them), and its inherent items that
        stand in for no C item.
        """
        c = self.c
        item = c.index[iid]
        k = kind(item)
        inner = item["inner"][k]
        params, where = c.generics(inner.get("generics"))
        attrs = item.get("attrs") or []
        non_exhaustive = any(a == "non_exhaustive" or (isinstance(a, dict) and (
            "non_exhaustive" in a or "non_exhaustive" in str(a.get("other", ""))))
            for a in attrs)
        decl = f"{'#[non_exhaustive] ' if non_exhaustive else ''}{k}{params}"
        fields: dict[str, str] = {}
        stripped = False
        out: dict = {}
        if k == "struct":
            sk = inner["kind"]
            if sk == "unit":
                decl += " ;"
            elif "tuple" in sk:
                decl += f" ({len(sk['tuple'])})"
                for n, f in enumerate(sk["tuple"]):
                    if f is None:
                        stripped = True
                    else:
                        fields[str(n)] = c.ty(c.index[str(f)]["inner"]["struct_field"])
            else:
                decl += " {}"
                stripped = sk["plain"]["has_stripped_fields"]
                for f in sk["plain"]["fields"]:
                    fi = c.index[str(f)]
                    fields[fi["name"]] = c.ty(fi["inner"]["struct_field"])
        elif k == "union":
            stripped = inner.get("has_stripped_fields", False)
            for f in inner["fields"]:
                fi = c.index[str(f)]
                fields[fi["name"]] = c.ty(fi["inner"]["struct_field"])
        out["decl"] = decl + where
        if k == "enum":
            out["variants"] = {}
            for v in inner["variants"]:
                vi = c.index[str(v)]
                out["variants"][vi["name"]] = self.variant(vi["inner"]["variant"])
            stripped = inner.get("has_stripped_variants", False)
        else:
            out["fields"] = fields
        out["stripped"] = stripped
        out.update(self.impl_surface(inner, exclude))
        return out

    def impl_surface(self, inner: dict, exclude: set[str]) -> dict:
        c = self.c
        impls: dict[str, dict] = {}
        found: list[tuple[str, str, str]] = []
        for im in self.impls_of(inner):
            if im.get("blanket_impl") is not None:
                continue
            if im.get("trait") is None:
                header = c.impl_header(im)
                for x in im["items"]:
                    x = str(x)
                    if x in exclude or x not in c.index:
                        continue
                    found.append((c.index[x].get("name"), header,
                                  self.sig(x, exclude)["decl"]))
                continue
            header = c.impl_header(im)
            names = set(im.get("provided_trait_methods") or [])
            assoc: dict[str, str] = {}
            for x in im["items"]:
                xi = c.index.get(str(x))
                if xi is None:
                    continue
                names.add(xi["name"])
                xk = kind(xi)
                if xk == "assoc_type":
                    assoc[xi["name"]] = self.assoc_type(xi["inner"]["assoc_type"])
                elif xk == "assoc_const":
                    ac = xi["inner"]["assoc_const"]
                    value = ac.get("value")
                    assoc[xi["name"]] = (f"const: {c.ty(ac['type'])}"
                                         + (f" = {value}" if value is not None else ""))
            impls[header] = {"items": sorted(names), "assoc": dict(sorted(assoc.items()))}
        # A name two inherent impls both define is told apart by its impl, for
        # each of them, so the keys do not depend on the order impls come in.
        names = Counter(n for n, _, _ in found)
        members = {(n if names[n] == 1 else f"{n} in {h}"): f"{h} {{ {d} }}"
                   for n, h, d in found}
        return {"impls": dict(sorted(impls.items())), "members": dict(sorted(members.items()))}

    def trait_sig(self, iid: str) -> dict:
        c = self.c
        inner = c.index[iid]["inner"]["trait"]
        params, where = c.generics(inner.get("generics"))
        head = (f"{'unsafe ' if inner.get('is_unsafe') else ''}"
                f"{'auto ' if inner.get('is_auto') else ''}trait{params}")
        if inner.get("bounds"):
            head += f": {c.bounds(inner['bounds'])}"
        required: dict[str, str] = {}
        provided: dict[str, str] = {}
        for x in inner["items"]:
            xi = c.index.get(str(x))
            if xi is None:
                continue
            xk = kind(xi)
            xin = xi["inner"][xk]
            if xk == "function":
                text, has = c.function(xin), xin.get("has_body")
            elif xk == "assoc_const":
                text = f"const: {c.ty(xin['type'])}"
                has = xin.get("value") is not None
                if has:
                    text += f" = {xin['value']}"
            elif xk == "assoc_type":
                text, has = self.assoc_type(xin), xin.get("type") is not None
            else:
                text, has = xk, True
            (provided if has else required)[xi["name"]] = text
        return {"decl": head + where, "required": dict(sorted(required.items())),
                "provided": dict(sorted(provided.items())),
                "dyn_compatible": bool(inner.get("is_dyn_compatible"))}

    # -- the extract ---------------------------------------------------

    def record(self, iid: str, exclude: set[str]) -> dict:
        return {"kind": kind(self.c.index[iid]), "paths": self.paths(iid),
                "sig": self.sig(iid, exclude)}

    def owned_ids(self, iid: str) -> set[str]:
        """The items a type's impls or a trait declare."""
        c = self.c
        item = c.index[iid]
        k = kind(item)
        inner = item["inner"][k]
        if k == "trait":
            return {str(x) for x in inner["items"]}
        out: set[str] = set()
        for im in self.impls_of(inner):
            if im.get("blanket_impl") is None:
                out |= {str(x) for x in im["items"]}
        return out

    def run(self) -> dict:
        c = self.c
        exclude = set(self.anchored)
        items: dict[str, dict] = {}
        by_key_ids: dict[str, list[str]] = {}
        for iid, anchors_ in self.anchored.items():
            for verb, k, path in anchors_:
                by_key_ids.setdefault(f"{k}::{path}", []).append(iid)
        type_keys: dict[str, set[str]] = {}
        for key, ids in by_key_ids.items():
            for iid in ids:
                if kind(c.index[iid]) in TYPE_KINDS:
                    type_keys.setdefault(iid, set()).add(key)

        reachable = set(c.public_paths)
        local_types = sorted(
            (i for i in reachable if c.index[i].get("crate_id") == 0
             and kind(c.index[i]) in TYPE_KINDS and i not in self.anchored), key=int)

        # docs/api.md section 5. Rule 1: a type an associated type ties to an
        # anchored type, either way; rule 2: else a type whose impls or
        # declaration hold stand-ins.
        assoc: dict[str, dict[str, set[str]]] = {}

        def link(tid: str, key: str, via: str) -> None:
            assoc.setdefault(tid, {}).setdefault(key, set()).add(via)

        for aid in type_keys:
            inner = c.index[aid]["inner"][kind(c.index[aid])]
            for im in self.impls_of(inner):
                if im.get("blanket_impl") is not None or im.get("trait") is None:
                    continue
                for x in im["items"]:
                    xi = c.index.get(str(x))
                    if xi and kind(xi) == "assoc_type":
                        rid = _rid(xi["inner"]["assoc_type"].get("type"))
                        if rid in reachable and rid not in self.anchored and \
                                kind(c.index[rid]) in TYPE_KINDS[:4]:
                            for key in type_keys[aid]:
                                link(rid, key, "assoc_type")
        for tid in local_types:
            if kind(c.index[tid]) == "type_alias":
                continue
            inner = c.index[tid]["inner"][kind(c.index[tid])]
            for im in self.impls_of(inner) if kind(c.index[tid]) != "trait" else []:
                if im.get("blanket_impl") is not None or im.get("trait") is None:
                    continue
                for x in im["items"]:
                    xi = c.index.get(str(x))
                    if xi and kind(xi) == "assoc_type":
                        rid = _rid(xi["inner"]["assoc_type"].get("type"))
                        for key in type_keys.get(rid, ()):
                            link(tid, key, "assoc_type")
        for tid in local_types:
            if kind(c.index[tid]) == "type_alias" or tid in assoc:
                continue
            for x in sorted(self.owned_ids(tid) & exclude, key=int):
                for verb, k, path in self.anchored[x]:
                    link(tid, f"{k}::{path}", "owner")
        # Rule 3: an alias goes with the anchored types its target names, else
        # with the types rules 1 and 2 associated.
        for tid in local_types:
            if kind(c.index[tid]) != "type_alias":
                continue
            named = _type_ids(c.index[tid]["inner"]["type_alias"]["type"])
            hits = sorted(named & set(type_keys), key=int)
            if hits:
                for h in hits:
                    for key in type_keys[h]:
                        link(tid, key, "alias")
            else:
                for h in sorted(named & set(assoc), key=int):
                    if kind(c.index[h]) == "type_alias":
                        continue
                    for key in assoc[h]:
                        link(tid, key, "alias")

        for key in sorted(by_key_ids):
            stand: dict[str, dict] = {}
            verbs = set()
            recs = []
            for iid in by_key_ids[key]:
                verb = next(v for v, k, p in self.anchored[iid] if f"{k}::{p}" == key)
                verbs.add(verb)
                rec = self.record(iid, exclude)
                rec["anchor"] = verb
                recs.append((self.locator(iid), json.dumps(rec, sort_keys=True), rec))
            for loc, _, rec in sorted(recs):
                name = loc
                n = 2
                while name in stand:
                    name = f"{loc} #{n}"
                    n += 1
                stand[name] = rec
            items[key] = {"anchor": verbs.pop() if len(verbs) == 1 else "mixed",
                          "stand_ins": stand, "associated": {}}
        for tid in sorted(assoc, key=int):
            rec = self.record(tid, exclude)
            for key, vias in assoc[tid].items():
                r = dict(rec, via=sorted(vias))
                items[key]["associated"][self.locator(tid)] = r
        for key in items:
            items[key]["associated"] = dict(sorted(items[key]["associated"].items()))

        uni = ct.Universe(c, self.deps, self.plumbing, set(self.anchored))
        family = set(type_keys) | {t for t, ks in assoc.items()
                                   if any(v & {"assoc_type", "alias"} for v in ks.values())}
        for key in sorted(items):
            view: dict[str, dict] = {}
            members = list(by_key_ids[key]) + [t for t in sorted(assoc, key=int)
                                                if key in assoc[t]]
            for iid in members:
                ckey, rec = self.contract_record(uni, iid, family, exclude)
                if ckey in view and rec.get("kind") == "method":
                    view[ckey]["sigs"] = sorted(set(view[ckey]["sigs"]) | set(rec["sigs"]))
                else:
                    view.setdefault(ckey, rec)
            items[key]["contract"] = dict(sorted(view.items()))

        unattributed: dict[str, dict] = {}
        for iid in sorted(reachable, key=int):
            item = c.index[iid]
            if item.get("crate_id") != 0 or kind(item) in ("module", "use"):
                continue
            if iid in self.anchored or iid in assoc:
                continue
            loc = self.locator(iid)
            mod = loc.rsplit("::", 1)[0] if "::" in loc else c.name
            unattributed.setdefault(mod, {})[loc] = self.record(iid, exclude)
        unattributed = {m: dict(sorted(v.items())) for m, v in sorted(unattributed.items())}

        return {
            "api": VERSION,
            "source": {"crate": c.name, "crate_version": c.doc.get("crate_version"),
                       "format_version": c.doc["format_version"],
                       "deps": sorted(d.name for d in self.deps),
                       "plumbing": sorted(self.plumbing)},
            "contract_missing_deps": sorted(uni.missing),
            "items": items,
            "unattributed": unattributed,
            "anchors": {
                "malformed": sorted(self.malformed, key=lambda d: (d["item"], d["line"])),
                "unknown_kinds": dict(sorted(self.unknown_kinds.items())),
                "without_alias": sorted(self.without_alias,
                                        key=lambda d: (d["item"], d["anchor"])),
            },
            "coverage": self.coverage(items, assoc, unattributed),
        }

    def contract_record(self, uni: ct.Universe, iid: str, family: set[str],
                        exclude: set[str]) -> tuple[str, dict]:
        """One stand-in's or associated item's entry in its C item's contract view.

        A type has its contract (`contract.py`) under its locator. A method of
        a handle or owner is keyed by its name alone, `method::<name>`, since
        a port moves it between the forms of one type, and its signature is
        normalised as a contract's methods are. Any other function has its
        normalised signature, and anything else its raw one.
        """
        c = self.c
        item = c.index[iid]
        k = kind(item)
        loc = self.locator(iid)
        if k in TYPE_KINDS[:3] + ("type_alias",):
            return loc, self.type_contract(uni, iid, exclude)
        if k == "function":
            parent = c.parent.get(iid)
            im = c.index[parent]["inner"].get("impl") if parent else None
            selfty = uni.lift(0, im["for"]) if im else None
            copy = selfty is not None and uni.holds(selfty, ct.COPY) is True
            _, text, _, _ = uni.signature(0, item, {}, selfty, copy)
            if im is not None and im.get("trait") is None and _rid(im["for"]) in family:
                return f"method::{item['name']}", {"kind": "method", "sigs": [text]}
            rec = {"kind": "fn", "sig": text}
            if im is not None:
                owner = uni.render(selfty)
                if im.get("trait"):
                    owner = f"<{owner} as {uni.render(uni.lift_path(0, im['trait'], {}, None))}>"
                rec["in"] = owner
            return loc, rec
        return loc, {"kind": k, "sig": self.sig(iid, exclude)}

    def type_contract(self, uni: ct.Universe, iid: str, exclude: set[str]) -> dict:
        c = self.c
        item = c.index[iid]
        k = kind(item)
        inner = item["inner"][k]
        params = (inner.get("generics") or {}).get("params", [])
        counts = {"lifetimes": 0, "types": 0, "consts": 0}
        args = []
        for p in params:
            pk = next(iter(p["kind"]))
            if pk == "type" and p["kind"]["type"].get("is_synthetic"):
                continue
            counts[{"lifetime": "lifetimes", "type": "types", "const": "consts"}[pk]] += 1
            args.append(("lt",) if pk == "lifetime" else ("gen", p["name"]))
        rec: dict = {"kind": "type", "generics": counts}
        if k in ("struct", "enum", "union"):
            raw = self.sig(iid, exclude)
            if raw.get("fields"):
                rec["fields"] = raw["fields"]
            if k == "struct" and not raw["stripped"]:
                rec["shape"] = raw["decl"]
            if k == "enum":
                rec["variants"] = raw["variants"]
                rec["non_exhaustive"] = raw["decl"].startswith("#[non_exhaustive]")
        form = ("path", c.item_path(iid), (0, iid), tuple(args))
        rec.update(uni.contract(form))
        return rec

    def coverage(self, items: dict, assoc: dict, unattributed: dict) -> dict:
        """How much of the public surface the anchors reach.

        `public` counts every item a consumer reaches, by role: the crate's
        free items, the items of its types' inherent and trait impls (blanket
        and synthetic ones aside, which no one writes), its traits' items,
        variants and public fields. `anchored` counts those that carry an
        anchor.
        """
        c = self.c
        public: Counter = Counter()
        anchored: Counter = Counter()

        def count(iid: str, role: str) -> None:
            public[role] += 1
            if iid in self.anchored:
                anchored[role] += 1

        seen: set[str] = set()
        for iid in sorted(c.public_paths, key=int):
            item = c.index[iid]
            k = kind(item)
            if item.get("crate_id") != 0 or k in ("module", "use") or iid in seen:
                continue
            seen.add(iid)
            count(iid, k)
            inner = item["inner"][k]
            if k == "trait":
                for x in inner["items"]:
                    if str(x) in c.index:
                        count(str(x), "trait_item")
            if k == "enum":
                for x in inner["variants"]:
                    count(str(x), "variant")
            if k in ("struct", "union"):
                for x in c._children(k, inner):
                    count(str(x), "field")
            if k in ("struct", "enum", "union"):
                for im in self.impls_of(inner):
                    if im.get("blanket_impl") is not None or im.get("is_synthetic"):
                        continue
                    role = "trait_impl_item" if im.get("trait") else "inherent_item"
                    for x in im["items"]:
                        if str(x) in c.index:
                            count(str(x), role)
        kinds = Counter(k.split("::", 1)[0] for k in items)
        return {
            "public": dict(sorted(public.items())),
            "anchored": dict(sorted(anchored.items())),
            "c_items": len(items),
            "c_items_by_kind": dict(sorted(kinds.items())),
            "stand_ins": sum(len(v["stand_ins"]) for v in items.values()),
            "unreachable_stand_ins": sum(1 for v in items.values()
                                         for r in v["stand_ins"].values() if not r["paths"]),
            "associated": len(assoc),
            "unattributed": sum(len(v) for v in unattributed.values()),
        }


def _rid(t) -> str | None:
    """The id a type is a path to, when it is one."""
    if isinstance(t, dict) and isinstance(t.get("resolved_path"), dict):
        i = t["resolved_path"].get("id")
        return None if i is None else str(i)
    return None


def extract(doc: dict, deps: list[dict] = (),
            plumbing: frozenset[str] = frozenset({"ffibox"})) -> dict:
    """The per-C-item surface of one rustdoc JSON document.

    `deps` are the rustdoc JSON documents of crates it depends on, such as
    ffibox's, whose impls the contracts of its handles and owners resolve
    through; `plumbing` names the crates whose wrappers and traits are
    plumbing rather than API.
    """
    return _Extractor(Crate(doc), [Crate(d) for d in deps], plumbing).run()


def as_extract(doc: dict, name: str = "document", deps: list[dict] = (),
               plumbing: frozenset[str] = frozenset({"ffibox"})) -> dict:
    """An extract from either an extract or a rustdoc JSON document."""
    if "index" in doc and "format_version" in doc:
        return extract(doc, deps, plumbing)
    if doc.get("api") != VERSION or "items" not in doc:
        raise FormatError(f"{name} is neither rustdoc JSON nor an api extract "
                          f"of version {VERSION}")
    return doc


# -- diff -------------------------------------------------------------------


def _change(item: str, part: str, change: str, severity: str, **kw) -> dict:
    return dict({"item": item, "part": part, "change": change, "severity": severity}, **kw)


def _dict_changes(item: str, part: str, b: dict, a: dict, added: str = "extended") -> list[dict]:
    """Keys lost or rewritten are changes; keys gained are `added`'s severity."""
    out = []
    for k in sorted(set(b) | set(a)):
        if k not in a:
            out.append(_change(item, part, "removed", "changed", name=k, before=b[k]))
        elif k not in b:
            out.append(_change(item, part, "added", added, name=k, after=a[k]))
        elif b[k] != a[k]:
            out.append(_change(item, part, "changed", "changed", name=k,
                               before=b[k], after=a[k]))
    return out


def compare_record(loc: str, b: dict, a: dict) -> list[dict]:
    """How one stand-in, or one associated item, moved.

    A path, an impl, an impl's item or associated type, a member, a provided
    trait item or a variant of a non-exhaustive enum gained is an addition;
    anything lost or rewritten, a required trait item gained, and a field or a
    variant gained where a consumer could match or build every one, is a
    change.
    """
    out = []
    if b["kind"] != a["kind"]:
        return [_change(loc, "kind", "changed", "changed", before=b["kind"], after=a["kind"])]
    pb, pa = set(b["paths"]), set(a["paths"])
    for p in sorted(pb - pa):
        out.append(_change(loc, "path", "removed", "changed", name=p))
    for p in sorted(pa - pb):
        out.append(_change(loc, "path", "added", "extended", name=p))
    sb, sa = b["sig"], a["sig"]
    for part in ("decl", "impl", "default", "stripped", "dyn_compatible"):
        if sb.get(part) != sa.get(part):
            out.append(_change(loc, part, "changed", "changed",
                               before=sb.get(part), after=sa.get(part)))
    if "fields" in sb or "fields" in sa:
        grow = "extended" if sb.get("stripped") else "changed"
        out += _dict_changes(loc, "field", sb.get("fields", {}), sa.get("fields", {}), grow)
    if "variants" in sb or "variants" in sa:
        grow = "extended" if "#[non_exhaustive]" in sb.get("decl", "") else "changed"
        out += _dict_changes(loc, "variant", sb.get("variants", {}), sa.get("variants", {}), grow)
    if "members" in sb or "members" in sa:
        out += _dict_changes(loc, "member", sb.get("members", {}), sa.get("members", {}))
    if "required" in sb or "required" in sa:
        rb, ra = sb.get("required", {}), sa.get("required", {})
        vb, va = sb.get("provided", {}), sa.get("provided", {})
        for k in sorted(set(rb) | set(ra) | set(vb) | set(va)):
            before = rb.get(k, vb.get(k))
            after = ra.get(k, va.get(k))
            if before is None:
                out.append(_change(loc, "trait_item", "added",
                                   "extended" if k in va else "changed", name=k, after=after))
            elif after is None:
                out.append(_change(loc, "trait_item", "removed", "changed", name=k, before=before))
            elif before != after or (k in vb and k in ra):
                out.append(_change(loc, "trait_item", "changed", "changed", name=k,
                                   before=before, after=after))
            elif k in rb and k in va:
                out.append(_change(loc, "trait_item", "changed", "extended", name=k,
                                   before="required", after="provided"))
    if "impls" in sb or "impls" in sa:
        ib, ia = sb.get("impls", {}), sa.get("impls", {})
        for h in sorted(set(ib) | set(ia)):
            if h not in ia:
                out.append(_change(loc, "impl", "removed", "changed", name=h))
            elif h not in ib:
                out.append(_change(loc, "impl", "added", "extended", name=h))
            else:
                xb, xa = set(ib[h]["items"]), set(ia[h]["items"])
                for n in sorted(xb - xa):
                    out.append(_change(loc, "impl_item", "removed", "changed", name=f"{h} :: {n}"))
                for n in sorted(xa - xb):
                    out.append(_change(loc, "impl_item", "added", "extended", name=f"{h} :: {n}"))
                for ch in _dict_changes(loc, "impl_assoc", ib[h]["assoc"], ia[h]["assoc"]):
                    # An item gained or lost is reported once, as an item.
                    if ch["change"] != "changed" and ch["name"] in xb ^ xa:
                        continue
                    ch["name"] = f"{h} :: {ch['name']}"
                    out.append(ch)
    return out


def compare_set(part: str, b: dict, a: dict) -> list[dict]:
    """A set of records by locator: lost is a change, gained an addition."""
    out = []
    for loc in sorted(set(b) | set(a)):
        if loc not in a:
            out.append(_change(loc, part, "removed", "changed"))
        elif loc not in b:
            out.append(_change(loc, part, "added", "extended"))
        else:
            out += compare_record(loc, b[loc], a[loc])
    return out


def _status(changes: list[dict]) -> str:
    if any(c["severity"] == "changed" for c in changes):
        return "changed"
    return "extended" if changes else "kept"


def _rekeys(bi: dict, ai: dict) -> dict[str, str]:
    """C items whose anchor kind alone changed: removed key -> new key.

    A key gone and a key come that share the path are one C item relabelled,
    as when a kind the convention renamed is rewritten, provided the path
    picks out one of each; otherwise both stand as removed and new.
    """
    gone: dict[str, list[str]] = {}
    came: dict[str, list[str]] = {}
    for k in set(bi) - set(ai):
        gone.setdefault(k.split("::", 1)[1], []).append(k)
    for k in set(ai) - set(bi):
        came.setdefault(k.split("::", 1)[1], []).append(k)
    return {gone[p][0]: came[p][0] for p in gone
            if len(gone[p]) == 1 and len(came.get(p, [])) == 1}


def compare_contract(loc: str, b: dict, a: dict) -> list[dict]:
    """How one entry of a contract view moved; additions extend it."""
    if b.get("kind") != a.get("kind"):
        return [_change(loc, "kind", "changed", "changed", before=b.get("kind"),
                        after=a.get("kind"))]
    out = []
    if b["kind"] == "method":
        sb, sa = set(b["sigs"]), set(a["sigs"])
        for x in sorted(sb - sa):
            out.append(_change(loc, "method", "removed", "changed", name=x))
        for x in sorted(sa - sb):
            out.append(_change(loc, "method", "added", "extended", name=x))
        return out
    if b["kind"] not in ("type", "fn"):
        return compare_record(loc, {"kind": b["kind"], "paths": [], "sig": b["sig"]},
                              {"kind": a["kind"], "paths": [], "sig": a["sig"]})
    if b["kind"] == "fn":
        for part in ("sig", "in"):
            if b.get(part) != a.get(part):
                out.append(_change(loc, part, "changed", "changed", before=b.get(part),
                                   after=a.get(part)))
        return out
    for part in ("generics", "shape", "non_exhaustive"):
        if b.get(part) != a.get(part):
            out.append(_change(loc, part, "changed", "changed", before=b.get(part),
                               after=a.get(part)))
    out += _dict_changes(loc, "field", b.get("fields", {}), a.get("fields", {}),
                         "changed" if "shape" in b else "extended")
    if "variants" in b or "variants" in a:
        out += _dict_changes(loc, "variant", b.get("variants", {}), a.get("variants", {}),
                             "extended" if b.get("non_exhaustive") else "changed")
    out += _dict_changes(loc, "method", b.get("methods", {}), a.get("methods", {}))
    out += _dict_changes(loc, "reborrow", b.get("reborrows", {}), a.get("reborrows", {}))
    for part in ("traits", "derefs"):
        xb, xa = set(b.get(part, [])), set(a.get(part, []))
        for x in sorted(xb - xa):
            out.append(_change(loc, part[:-1], "removed", "changed", name=x))
        for x in sorted(xa - xb):
            out.append(_change(loc, part[:-1], "added", "extended", name=x))
    return out


def _raw_record(item: dict, loc: str) -> dict | None:
    return item["stand_ins"].get(loc) or item["associated"].get(loc)


def compare_view(b: dict, a: dict) -> tuple[list[dict], list[str], list[dict]]:
    """A C item's contract changes, what could not be resolved, and retargets.

    An entry whose contract is unresolved on either side is compared on its
    raw record instead, and those changes carry ``view: raw``. A type whose
    raw record moved while its contract did not is a retarget.
    """
    vb, va = b["contract"], a["contract"]
    changes: list[dict] = []
    unresolved: list[str] = []
    retargets: list[dict] = []
    for loc in sorted(set(vb) | set(va)):
        if loc not in va:
            changes.append(_change(loc, "contract", "removed", "changed"))
            continue
        if loc not in vb:
            changes.append(_change(loc, "contract", "added", "extended"))
            continue
        x, y = vb[loc], va[loc]
        if x.get("unresolved") or y.get("unresolved"):
            unresolved += [f"{loc}: {u}" for u in x.get("unresolved", []) + y.get("unresolved", [])]
            rb, ra = _raw_record(b, loc), _raw_record(a, loc)
            raw = compare_record(loc, rb, ra) if rb and ra else (
                [] if x == y else [_change(loc, "contract", "changed", "changed")])
            changes += [dict(ch, view="raw") for ch in raw]
            continue
        moved = compare_contract(loc, x, y)
        changes += moved
        rb, ra = _raw_record(b, loc), _raw_record(a, loc)
        if not moved and x.get("kind") == "type" and rb and ra and \
                (rb["sig"].get("decl"), rb["kind"]) != (ra["sig"].get("decl"), ra["kind"]):
            retargets.append({"item": loc, "before": rb["sig"].get("decl"),
                              "after": ra["sig"].get("decl")})
    return changes, sorted(set(unresolved)), retargets


def diff(before: dict, after: dict, items: list[str] | None = None,
         raw: bool = False) -> dict:
    """Each C item's classification between two extracts.

    The contract view decides each status, and `raw_status` says when the raw
    records would have decided otherwise; with `raw`, the raw records decide,
    as the signatures of the stand-ins and associated items as they stand.
    `items`, when given, restricts the C items to those keys, and those found
    in neither extract are listed under `missing`. The surface no anchor
    reaches is compared by Rust module, under `unattributed`, whatever
    `items` holds.
    """
    if before.get("api") != after.get("api"):
        raise ValueError(f"extracts of api versions {before.get('api')} and "
                         f"{after.get('api')} are not comparable")
    bi, ai = before["items"], after["items"]
    rekeyed = _rekeys(bi, ai)
    old_key = {new: old for old, new in rekeyed.items()}
    keys = sorted((set(bi) - set(rekeyed)) | set(ai))
    missing: list[str] = []
    if items is not None:
        want = set(items)
        missing = sorted(want - set(keys) - set(rekeyed))
        keys = [k for k in keys if k in want or old_key.get(k) in want]
    out_items: dict[str, dict] = {}
    totals = Counter({s: 0 for s in STATUSES})
    moves: Counter = Counter()
    for key in keys:
        bkey = old_key.get(key, key)
        if key not in ai:
            rec = {"status": "removed"}
        elif bkey not in bi:
            rec = {"status": "new"}
        else:
            b, a = bi[bkey], ai[key]
            raw_changes = (compare_set("stand_in", b["stand_ins"], a["stand_ins"])
                           + compare_set("associated", b["associated"], a["associated"]))
            if raw:
                changes, unresolved, retargets = raw_changes, [], []
            else:
                changes, unresolved, retargets = compare_view(b, a)
            rec = {"status": _status(changes)}
            if changes:
                rec["changes"] = changes
            if not raw and _status(raw_changes) != rec["status"]:
                rec["raw_status"] = _status(raw_changes)
            if retargets:
                rec["retarget"] = retargets
            if unresolved:
                rec["unresolved"] = unresolved
            if b["anchor"] != a["anchor"]:
                rec["anchor"] = {"before": b["anchor"], "after": a["anchor"]}
                moves[f"{b['anchor']}->{a['anchor']}"] += 1
            if bkey != key:
                rec["rekeyed"] = bkey
        totals[rec["status"]] += 1
        out_items[key] = rec

    ub, ua = before.get("unattributed", {}), after.get("unattributed", {})
    mods: dict[str, dict] = {}
    utotals = Counter({s: 0 for s in STATUSES})
    for m in sorted(set(ub) | set(ua)):
        if m not in ua:
            rec = {"status": "removed"}
        elif m not in ub:
            rec = {"status": "new"}
        else:
            changes = compare_set("item", ub[m], ua[m])
            rec = {"status": _status(changes)}
            if changes:
                rec["changes"] = changes
        utotals[rec["status"]] += 1
        mods[m] = rec
    out = {
        "api": before.get("api"),
        "view": "raw" if raw else "contract",
        "before": before["source"],
        "after": after["source"],
        "totals": dict(totals),
        "anchor_moves": dict(sorted(moves.items())),
        "rekeyed": sum(1 for r in out_items.values() if "rekeyed" in r),
        "retargeted": sum(1 for r in out_items.values() if "retarget" in r),
        "unresolved": sum(1 for r in out_items.values() if "unresolved" in r),
        "items": out_items,
        "unattributed": {"totals": dict(utotals), "modules": mods},
    }
    if items is not None:
        out["missing"] = missing
    return out


# -- text -------------------------------------------------------------------


def _line(c: dict) -> str:
    mark = {"added": "+", "removed": "-", "changed": "~"}[c["change"]]
    if c["severity"] == "extended" and c["change"] == "changed":
        mark = "+"
    s = f"    {mark} {c['item']}"
    if c.get("view") == "raw":
        s += " (raw)"
    if c["part"] not in ("stand_in", "associated", "item"):
        s += f" [{c['part']}]"
    if "name" in c:
        s += f" {c['name']}"
    if c["change"] == "changed" and ("before" in c or "after" in c):
        s += f": {c.get('before')} -> {c.get('after')}"
    elif c["change"] == "added" and c["part"] in ("stand_in", "associated", "item"):
        s += " (added)"
    elif c["change"] == "removed" and c["part"] in ("stand_in", "associated", "item"):
        s += " (removed)"
    return s


def render_text(d: dict) -> str:
    """The short form: what is not kept or new, with its changes, and totals."""
    out = [f"{d['before']['crate']} -> {d['after']['crate']} "
           f"(rustdoc format {d['before']['format_version']} -> {d['after']['format_version']}; "
           f"{d.get('view', 'contract')} view)"]
    for key, rec in d["items"].items():
        st = rec["status"]
        move = rec.get("anchor")
        if st in ("kept", "new") and not move:
            continue
        head = f"{st:<9}{key}"
        if "rekeyed" in rec:
            head += f"  (was {rec['rekeyed']})"
        if "raw_status" in rec:
            head += f"  (raw: {rec['raw_status']})"
        if move:
            head += f"  ({move['before']} -> {move['after']})"
        out.append(head)
        out += [_line(c) for c in rec.get("changes", [])]
        out += [f"    unresolved: {u}" for u in rec.get("unresolved", [])]
    for m, rec in d["unattributed"]["modules"].items():
        if rec["status"] in ("kept", "new"):
            continue
        out.append(f"{rec['status']:<9}{m}  (unattributed)")
        out += [_line(c) for c in rec.get("changes", [])]
    t = d["totals"]
    out.append("C items: " + ", ".join(f"{t[s]} {s}" for s in STATUSES))
    if d["anchor_moves"]:
        out.append("anchors: " + ", ".join(f"{n} {k}" for k, n in d["anchor_moves"].items()))
    if d["rekeyed"]:
        out.append(f"rekeyed: {d['rekeyed']} (anchor kind relabelled, same path)")
    if d.get("retargeted"):
        out.append(f"retargeted: {d['retargeted']} (a type's form moved, its contract kept)")
    if d.get("unresolved"):
        out.append(f"unresolved: {d['unresolved']} (compared on raw records where unresolved)")
    u = d["unattributed"]["totals"]
    out.append("unattributed modules: " + ", ".join(f"{u[s]} {s}" for s in STATUSES))
    if d.get("missing"):
        out.append("not in either extract: " + ", ".join(d["missing"]))
    return "\n".join(out) + "\n"
