"""contract.py — what a consumer may rely on in a handle or an owner.

A C type's handles and owners (`Foo`, `FooRef`, `FooMut`, `FooBox`, `FooArc`,
`FooVal`) take different forms over a migration: pointer wrappers over C's
allocator while the type is wrapped, native references and `Box`es once it is
ported. A consumer relies only on what every form offers -- their methods,
their reborrows (`as_ref`, `as_mut`) and the dereferences the native forms
offer -- so that, not the alias target, is what a landing must keep. This
module computes that **contract** for a type, resolving the methods and trait
impls a form inherits from another crate (ffibox's `CBox`, `CArc`, …) through
that crate's rustdoc JSON when it is given, and from a fixed model of the
standard library's pointer forms. `docs/api.md` section 6 states every rule.

What it cannot resolve it says, under `unresolved`, rather than guessing.
"""
from __future__ import annotations

import re

from ffimap.rustdoc import Crate, kind

# Functions that convert between a wrapper and its raw form: ffimap's seam list
# (the ffimap skill's `--seams`). Not part of any contract.
SEAMS = frozenset({
    "as_ptr", "as_mut_ptr", "as_void_ptr", "from_ptr", "from_void_ptr",
    "from_raw_parts", "into_raw_parts", "from_c", "into_c", "as_c_ptr",
    "from_raw", "as_object"})
REBORROWS = frozenset({"as_ref", "as_mut"})

CLONE, COPY = "core::clone::Clone", "core::marker::Copy"
SEND, SYNC, UNPIN = "core::marker::Send", "core::marker::Sync", "core::marker::Unpin"
UNWIND = "core::panic::unwind_safe::UnwindSafe"
REF_UNWIND = "core::panic::unwind_safe::RefUnwindSafe"
DEBUG, DISPLAY, DEFAULT = "core::fmt::Debug", "core::fmt::Display", "core::default::Default"
CMP = ("core::cmp::PartialEq", "core::cmp::Eq", "core::cmp::PartialOrd",
       "core::cmp::Ord", "core::hash::Hash")
FORWARDED = (DEBUG, DISPLAY) + CMP
# The traits evaluated for a standard pointer form, which has no impl list here.
CONSUMER_TRAITS = (CLONE, COPY, SEND, SYNC, UNPIN, UNWIND, REF_UNWIND, DEFAULT) + FORWARDED
DEREF, DEREF_MUT = "core::ops::deref::Deref", "core::ops::deref::DerefMut"
AS_REF, AS_MUT = "core::convert::AsRef", "core::convert::AsMut"
# Traits that are no part of a contract: drop glue and compiler-internal
# markers no consumer can use, the address (`Pointer` formats it: raw
# access), and the reborrow and dereference machinery, which a contract
# records as reborrows and as the methods reached through it.
EXCLUDED_TRAITS = frozenset({
    "core::ops::drop::Drop", "core::marker::StructuralPartialEq", "core::marker::Freeze",
    "core::marker::UnsafeUnpin", "core::fmt::Pointer", DEREF, DEREF_MUT, AS_REF, AS_MUT,
    "core::borrow::Borrow", "core::borrow::BorrowMut"})
NON_NULL = "core::ptr::non_null::NonNull"
STD_CRATES = ("core", "alloc", "std")
STD_FORMS = {"Box": "box", "Arc": "arc", "Rc": "rc", "Pin": "pin"}
LIFETIME = re.compile(r"'(?!static\b)[A-Za-z_][A-Za-z0-9_]*")


def _and(*vals):
    if any(v is False for v in vals):
        return False
    if any(v is None for v in vals):
        return None
    return True


class Universe:
    """The crate measured and the dependency crates whose JSON was given."""

    def __init__(self, main: Crate, deps: list[Crate], plumbing: frozenset[str],
                 anchored: set[str]) -> None:
        self.crates = [main] + list(deps)
        self.plumbing = plumbing
        self.anchored = anchored          # ids of main's anchored items
        self.by_path: dict[str, tuple[int, str]] = {}
        for ci, c in enumerate(self.crates):
            for iid, entry in c.paths.items():
                if entry.get("crate_id") == 0 and iid in c.index:
                    self.by_path.setdefault("::".join(entry["path"]), (ci, iid))
        self.patterns = self._patterns()
        self._direct: dict[str, dict] = {}
        self.missing: set[str] = set()   # foreign crates no JSON was given for

    # -- types as trees ------------------------------------------------------

    def lift(self, ci: int, t, subst: dict | None = None, selfty=None):
        """A rustdoc type as a crate-independent tree, generics substituted."""
        c = self.crates[ci]
        subst = subst or {}
        if t is None:
            return ("tuple", ())
        if "resolved_path" in t:
            return self.lift_path(ci, t["resolved_path"], subst, selfty)
        if "generic" in t:
            g = t["generic"]
            if g == "Self" and selfty is not None:
                return selfty
            return subst.get(g, ("gen", g))
        if "primitive" in t:
            return ("prim", t["primitive"])
        if "borrowed_ref" in t:
            r = t["borrowed_ref"]
            return ("ref", r["is_mutable"], self.lift(ci, r["type"], subst, selfty))
        if "raw_pointer" in t:
            r = t["raw_pointer"]
            return ("ptr", r["is_mutable"], self.lift(ci, r["type"], subst, selfty))
        if "tuple" in t:
            return ("tuple", tuple(self.lift(ci, x, subst, selfty) for x in t["tuple"]))
        if "slice" in t:
            return ("slice", self.lift(ci, t["slice"], subst, selfty))
        if "array" in t:
            return ("array", self.lift(ci, t["array"]["type"], subst, selfty), t["array"]["len"])
        if "qualified_path" in t:
            q = t["qualified_path"]
            trait = self.lift_path(ci, q["trait"], subst, selfty) if q.get("trait") else None
            return ("proj", self.lift(ci, q["self_type"], subst, selfty), trait, q["name"],
                    self.lift_args(ci, q.get("args"), subst, selfty))
        return ("text", LIFETIME.sub("'_", c.ty(t)))

    def lift_path(self, ci: int, p: dict, subst, selfty):
        c = self.crates[ci]
        iid = p.get("id")
        canon = (c.canonical(iid) if iid is not None else None) or p["path"]
        entry = c.paths.get(str(iid)) if iid is not None else None
        if entry is not None and entry.get("crate_id") == 0 and str(iid) in c.index:
            ref = (ci, str(iid))
        else:
            ref = self.by_path.get(canon)
        return ("path", canon, ref, self.lift_args(ci, p.get("args"), subst, selfty))

    def lift_args(self, ci: int, a, subst, selfty) -> tuple:
        if not a or "angle_bracketed" not in a:
            if a and "parenthesized" in a:
                return (("text", LIFETIME.sub("'_", self.crates[ci].args(a))),)
            return ()
        out = []
        for g in a["angle_bracketed"]["args"]:
            if g == "infer":
                out.append(("text", "_"))
            elif "lifetime" in g:
                out.append(("lt",))
            elif "type" in g:
                out.append(self.lift(ci, g["type"], subst, selfty))
            else:
                out.append(("text", self.crates[ci].generic_arg(g)))
        for con in a["angle_bracketed"]["constraints"]:
            out.append(("text", LIFETIME.sub("'_", self.crates[ci].constraint(con))))
        return tuple(out)

    def subst(self, t, b: dict):
        tag = t[0]
        if tag == "gen":
            return b.get(t[1], t)
        if tag == "path":
            return ("path", t[1], t[2], tuple(self.subst(a, b) for a in t[3]))
        if tag in ("ref", "ptr"):
            return (tag, t[1], self.subst(t[2], b))
        if tag == "tuple":
            return ("tuple", tuple(self.subst(x, b) for x in t[1]))
        if tag == "slice":
            return ("slice", self.subst(t[1], b))
        if tag == "array":
            return ("array", self.subst(t[1], b), t[2])
        if tag == "proj":
            return ("proj", self.subst(t[1], b), t[2] and self.subst(t[2], b), t[3],
                    tuple(self.subst(a, b) for a in t[4]))
        return t

    def match(self, pat, t, vars_: frozenset, b: dict | None = None) -> dict | None:
        """Bindings of `vars_` that make `pat` equal `t`, lifetimes ignored."""
        b = {} if b is None else b
        if pat[0] == "gen" and pat[1] in vars_:
            if pat[1] in b:
                return b if b[pat[1]] == t else None
            b[pat[1]] = t
            return b
        if pat[0] != t[0]:
            return None
        tag = pat[0]
        if tag == "path":
            if pat[1] != t[1]:
                return None
            pa = [a for a in pat[3] if a[0] != "lt"]
            ta = [a for a in t[3] if a[0] != "lt"]
            if len(pa) != len(ta):
                return None
            for x, y in zip(pa, ta):
                if self.match(x, y, vars_, b) is None:
                    return None
            return b
        if tag in ("ref", "ptr"):
            return self.match(pat[2], t[2], vars_, b) if pat[1] == t[1] else None
        if tag == "tuple":
            if len(pat[1]) != len(t[1]):
                return None
            for x, y in zip(pat[1], t[1]):
                if self.match(x, y, vars_, b) is None:
                    return None
            return b
        if tag in ("slice",):
            return self.match(pat[1], t[1], vars_, b)
        if tag == "array":
            return self.match(pat[1], t[1], vars_, b) if pat[2] == t[2] else None
        return b if pat == t else None

    # -- rendering, with handle aliases normalised ---------------------------

    def _patterns(self) -> list:
        """The crate's public aliases: a type equal to a target reads as the alias."""
        c = self.crates[0]
        out = []
        for iid in sorted(c.public_paths, key=int):
            item = c.index[iid]
            if item.get("crate_id") != 0 or kind(item) != "type_alias":
                continue
            ta = item["inner"]["type_alias"]
            params = ta["generics"]["params"]
            target = self.lift(0, ta["type"])
            if target[0] == "gen":
                continue
            vars_ = frozenset(p["name"] for p in params if "lifetime" not in p["kind"])
            out.append((c.item_path(iid), params, vars_, target))
        return sorted(out, key=lambda x: x[0])

    def render(self, t, norm: bool = True) -> str:
        if norm:
            for name, params, vars_, pat in self.patterns:
                b = self.match(pat, t, vars_)
                if b is None:
                    continue
                args = []
                for p in params:
                    if "lifetime" in p["kind"]:
                        args.append("'_")
                    elif p["name"] in b:
                        args.append(self.render(b[p["name"]]))
                    else:
                        args.append("_")
                return name + (f"<{', '.join(args)}>" if args else "")
        tag = t[0]
        if tag == "path":
            args = [self.render_arg(a, norm) for a in t[3]]
            return t[1] + (f"<{', '.join(args)}>" if args else "")
        if tag == "gen":
            return t[1]
        if tag == "prim":
            return t[1]
        if tag == "ref":
            return f"&{'mut ' if t[1] else ''}{self.render(t[2], norm)}"
        if tag == "ptr":
            return f"*{'mut' if t[1] else 'const'} {self.render(t[2], norm)}"
        if tag == "tuple":
            items = [self.render(x, norm) for x in t[1]]
            return f"({items[0]},)" if len(items) == 1 else f"({', '.join(items)})"
        if tag == "slice":
            return f"[{self.render(t[1], norm)}]"
        if tag == "array":
            return f"[{self.render(t[1], norm)}; {t[2]}]"
        if tag == "proj":
            base = self.render(t[1], norm)
            if t[2] is not None:
                base = f"<{base} as {self.render(t[2], norm)}>"
            args = [self.render_arg(a, norm) for a in t[4]]
            return f"{base}::{t[3]}" + (f"<{', '.join(args)}>" if args else "")
        if tag == "lt":
            return "'_"
        return t[1]

    def render_arg(self, a, norm: bool) -> str:
        return "'_" if a[0] == "lt" else self.render(a, norm)

    # -- resolution ----------------------------------------------------------

    def item(self, ref):
        ci, iid = ref
        return self.crates[ci].index[iid]

    def expand(self, t, depth: int = 0):
        """Follow type aliases and projections to what they name."""
        if depth > 8:
            return t
        if t[0] == "path" and t[2] is not None:
            item = self.item(t[2])
            if kind(item) == "type_alias":
                ta = item["inner"]["type_alias"]
                params = [p for p in ta["generics"]["params"] if "lifetime" not in p["kind"]]
                args = [a for a in t[3] if a[0] != "lt"]
                b = {p["name"]: a for p, a in zip(params, args)}
                return self.expand(self.lift(t[2][0], ta["type"], b), depth + 1)
        if t[0] == "proj":
            r = self.project(t, depth)
            if r is not None:
                return self.expand(r, depth + 1)
        return t

    def resolve(self, t, depth: int = 0):
        """Resolve every projection inside `t` that can be."""
        if depth > 8:
            return t
        tag = t[0]
        if tag == "proj":
            r = self.project(t, depth)
            return self.resolve(r, depth + 1) if r is not None else t
        if tag == "path":
            return ("path", t[1], t[2], tuple(self.resolve(a, depth) for a in t[3]))
        if tag in ("ref", "ptr"):
            return (tag, t[1], self.resolve(t[2], depth))
        if tag == "tuple":
            return ("tuple", tuple(self.resolve(x, depth) for x in t[1]))
        if tag == "slice":
            return ("slice", self.resolve(t[1], depth))
        if tag == "array":
            return ("array", self.resolve(t[1], depth), t[2])
        return t

    def impls(self, ref) -> list[tuple[int, dict]]:
        ci, iid = ref
        item = self.crates[ci].index[iid]
        inner = item["inner"][kind(item)]
        if not isinstance(inner, dict):
            return []
        out = []
        for i in inner.get("impls") or []:
            im = self.crates[ci].index.get(str(i))
            if im is not None:
                out.append((ci, im["inner"]["impl"]))
        return out

    def impl_match(self, ci: int, im: dict, t) -> dict | None:
        params = im["generics"]["params"]
        vars_ = frozenset(p["name"] for p in params if "lifetime" not in p["kind"])
        return self.match(self.lift(ci, im["for"]), t, vars_)

    def trait_name(self, ci: int, p: dict) -> str:
        c = self.crates[ci]
        iid = p.get("id")
        return (c.canonical(iid) if iid is not None else None) or p["path"]

    def project(self, t, depth: int):
        """``<Ty as Trait>::Name`` resolved through Ty's impl of Trait."""
        _, self_ty, trait, name, _ = t
        if trait is None:
            return None
        base = self.expand(self_ty, depth + 1)
        if base[0] != "path" or base[2] is None or kind(self.item(base[2])) not in (
                "struct", "enum", "union"):
            return None
        for ci, im in self.impls(base[2]):
            if not im.get("trait") or im.get("is_negative"):
                continue
            if self.trait_name(ci, im["trait"]) != trait[1]:
                continue
            b = self.impl_match(ci, im, base)
            if b is None:
                continue
            for x in im["items"]:
                xi = self.crates[ci].index.get(str(x))
                if xi and xi["name"] == name and kind(xi) == "assoc_type":
                    return self.lift(ci, xi["inner"]["assoc_type"]["type"], b, base)
        return None

    # -- trait evaluation -----------------------------------------------------

    def bounds_hold(self, ci: int, generics: dict, b: dict, depth: int):
        """Whether an impl's bounds hold under bindings `b`: True, False or None."""
        results = []
        for p in generics.get("params", []):
            tk = p["kind"].get("type")
            if not tk or p["name"] not in b:
                continue
            for bound in tk.get("bounds") or []:
                tb = bound.get("trait_bound")
                if tb and tb.get("modifier", "none") == "none":
                    results.append(self.holds(b[p["name"]], self.trait_name(ci, tb["trait"]),
                                              depth + 1))
        for w in generics.get("where_predicates", []):
            bp = w.get("bound_predicate")
            if not bp:
                continue
            subject = self.subst(self.lift(ci, bp["type"]), b)
            for bound in bp["bounds"]:
                tb = bound.get("trait_bound")
                if tb and tb.get("modifier", "none") == "none":
                    results.append(self.holds(subject, self.trait_name(ci, tb["trait"]),
                                              depth + 1))
        return _and(*results)

    def holds(self, t, trait: str, depth: int = 0):
        """Whether `t` implements `trait`: True, False, or None when unknown.

        A nominal type answers from its own impl list, in which rustdoc has
        already listed the blanket impls that apply; the standard pointer
        forms and the primitives from a fixed model.
        """
        if depth > 8:
            return None
        t = self.expand(t)
        if t[0] == "ref":
            return self._std_holds("ref_mut" if t[1] else "ref", t[2], trait, depth)
        if t[0] == "prim":
            if trait in (SEND, SYNC, UNPIN, UNWIND, REF_UNWIND, DEBUG):
                return True
            if trait in (COPY, CLONE, DEFAULT) + CMP:
                return t[1] not in ("str",) and (trait not in ("core::cmp::Eq", "core::cmp::Ord",
                                                               "core::hash::Hash")
                                                 or t[1] not in ("f32", "f64"))
            return None
        if t[0] == "tuple" and not t[1]:
            return True if trait != DISPLAY else False
        if t[0] != "path":
            return None
        form = self.std_form(t)
        if form is None and t[2] is None and t[1].split("::")[0] in STD_CRATES:
            form = {"NonNull": "non_null", "PhantomData": "phantom"}.get(t[1].split("::")[-1])
        if form is not None:
            args = [a for a in t[3] if a[0] != "lt"]
            if not args:
                return None
            return self._std_holds(form, args[0], trait, depth)
        if t[2] is None:
            self._note_missing(t)
            return None
        if kind(self.item(t[2])) not in ("struct", "enum", "union"):
            return None
        unknown = False
        for ci, im in self.impls(t[2]):
            if not im.get("trait") or self.trait_name(ci, im["trait"]) != trait:
                continue
            b = self.impl_match(ci, im, t)
            if b is None:
                continue
            if im.get("is_negative"):
                return False
            r = self.bounds_hold(ci, im["generics"], b, depth)
            if r is True:
                return True
            if r is None:
                unknown = True
        return None if unknown else False

    def _std_holds(self, form: str, inner, trait: str, depth: int):
        h = lambda tr: self.holds(inner, tr, depth + 1)  # noqa: E731
        if form == "ref":
            table = {CLONE: True, COPY: True, SEND: h(SYNC), SYNC: h(SYNC), UNPIN: True,
                     UNWIND: h(REF_UNWIND), REF_UNWIND: h(REF_UNWIND), DEFAULT: False}
        elif form == "ref_mut":
            table = {CLONE: False, COPY: False, SEND: h(SEND), SYNC: h(SYNC), UNPIN: True,
                     UNWIND: False, REF_UNWIND: h(REF_UNWIND), DEFAULT: False}
        elif form == "box":
            table = {CLONE: h(CLONE), COPY: False, SEND: h(SEND), SYNC: h(SYNC), UNPIN: True,
                     UNWIND: h(UNWIND), REF_UNWIND: h(REF_UNWIND), DEFAULT: h(DEFAULT)}
        elif form in ("arc", "rc"):
            both = _and(h(SEND), h(SYNC)) if form == "arc" else False
            table = {CLONE: True, COPY: False, SEND: both, SYNC: both, UNPIN: True,
                     UNWIND: h(REF_UNWIND), REF_UNWIND: h(REF_UNWIND), DEFAULT: h(DEFAULT)}
        elif form == "pin":
            return self.holds(inner, trait, depth + 1)
        elif form == "non_null":
            table = {CLONE: True, COPY: True, SEND: False, SYNC: False, UNPIN: True,
                     UNWIND: h(REF_UNWIND), REF_UNWIND: h(REF_UNWIND), DEBUG: True,
                     DEFAULT: False}
        elif form == "phantom":
            table = {CLONE: True, COPY: True, SEND: h(SEND), SYNC: h(SYNC), UNPIN: h(UNPIN),
                     UNWIND: h(UNWIND), REF_UNWIND: h(REF_UNWIND), DEBUG: True,
                     DEFAULT: True}
            if trait in CMP:
                return True
        else:
            return None
        if trait in table:
            return table[trait]
        if trait in FORWARDED:
            return h(trait)
        return None

    def std_form(self, t) -> str | None:
        if t[0] != "path":
            return None
        parts = t[1].split("::")
        if parts[0] in STD_CRATES and parts[-1] in STD_FORMS and t[2] is None:
            return STD_FORMS[parts[-1]]
        return None

    def _note_missing(self, t) -> None:
        crate = t[1].split("::")[0]
        if crate not in STD_CRATES and crate != self.crates[0].name:
            self.missing.add(crate)

    # -- the direct surface of a form ------------------------------------------

    def direct(self, t) -> dict:
        """What a form offers by itself: its methods, reborrows, derefs, traits.

        `methods` and `reborrows` map a name to ``(receiver, text)`` and
        ``(receiver, [targets])``; `derefs` lists ``(target, exclusive)``.
        """
        key = self.render(t, norm=False)
        if key in self._direct:
            return self._direct[key]
        out = {"methods": {}, "reborrows": {}, "derefs": [], "traits": set(),
               "unresolved": set(), "unresolved_traits": set()}
        self._direct[key] = out
        e = self.expand(t)
        if e[0] == "ref":
            out["derefs"].append((e[2], e[1]))
            self._std_traits("ref_mut" if e[1] else "ref", e[2], out)
            return out
        form = self.std_form(e)
        if form is not None:
            args = [a for a in e[3] if a[0] != "lt"]
            if not args:
                out["unresolved"].add(f"{e[1]} without a type argument")
                return out
            inner = args[0]
            if form == "pin":
                target = self.expand(inner)
                pointee = target[2] if target[0] == "ref" else (
                    [a for a in target[3] if a[0] != "lt"][0]
                    if self.std_form(target) and len(target[3]) else None)
                if pointee is None:
                    out["unresolved"].add(f"Pin of {self.render(inner)}")
                    return out
                mut = self.holds(pointee, UNPIN) is True and (
                    target[0] != "ref" or target[1]) and self.std_form(target) != "arc"
                out["derefs"].append((pointee, mut))
            else:
                out["derefs"].append((inner, form == "box"))
                out["reborrows"]["as_ref"] = ("ref", [("ref", False, inner)])
                if form == "box":
                    out["reborrows"]["as_mut"] = ("mut", [("ref", True, inner)])
            self._std_traits(form, inner, out)
            return out
        if e[0] != "path":
            out["unresolved"].add(self.render(e, norm=False))
            return out
        if e[2] is None:
            self._note_missing(e)
            if e[1].split("::")[0] in STD_CRATES:
                out["unresolved"].add(f"{e[1]}: a standard type no contract models")
            else:
                out["unresolved"].add(f"{e[1]}: no rustdoc JSON for its crate")
            return out
        if kind(self.item(e[2])) not in ("struct", "enum", "union"):
            out["unresolved"].add(self.render(e, norm=False))
            return out
        plumbing = e[2][0] != 0 and self.crates[e[2][0]].name in self.plumbing
        copy = self.holds(e, COPY) is True
        for ci, im in self.impls(e[2]):
            if im.get("blanket_impl") is not None or im.get("is_negative"):
                continue
            b = self.impl_match(ci, im, e)
            if b is None:
                continue
            ok = self.bounds_hold(ci, im["generics"], b, 0)
            if ok is False:
                continue
            if im.get("trait") is None:
                if ok is None:
                    out["unresolved"].add(f"bounds of {self.crates[ci].impl_header(im)}")
                self._inherent(ci, im, b, e, copy, plumbing, out)
                continue
            name = self.trait_name(ci, im["trait"])
            if name == DEREF or name == DEREF_MUT:
                if name == DEREF:
                    for x in im["items"]:
                        xi = self.crates[ci].index.get(str(x))
                        if xi and xi["name"] == "Target" and kind(xi) == "assoc_type":
                            tgt = self.resolve(self.lift(ci, xi["inner"]["assoc_type"]["type"],
                                                         b, e))
                            out["derefs"].append((tgt, False))
                else:
                    out["deref_mut"] = True
                continue
            if name in (AS_REF, AS_MUT):
                args = [a for a in self.lift_args(ci, im["trait"].get("args"), b, e)
                        if a[0] != "lt"]
                if args:
                    which, mut = ("as_ref", False) if name == AS_REF else ("as_mut", True)
                    recv, targets = out["reborrows"].get(which, ("mut" if mut else "ref", []))
                    out["reborrows"][which] = (recv, targets + [("ref", mut, args[0])])
                continue
            if name in EXCLUDED_TRAITS or name.split("::")[0] in self.plumbing:
                continue
            if ok is None:
                out["unresolved_traits"].add(f"bounds of {self.crates[ci].impl_header(im)}")
                continue
            args = self.lift_args(ci, im["trait"].get("args"), b, e)
            text = name + (f"<{', '.join(self.render_arg(self.resolve(a), True) for a in args)}>"
                           if args else "")
            out["traits"].add(text)
        if out.pop("deref_mut", False):
            out["derefs"] = [(tgt, True) for tgt, _ in out["derefs"]]
        return out

    def _std_traits(self, form: str, inner, out: dict) -> None:
        for tr in CONSUMER_TRAITS:
            r = self._std_holds(form, inner, tr, 0)
            if r is True:
                out["traits"].add(tr)
            elif r is None:
                out["unresolved_traits"].add(f"{tr} of {form} {self.render(inner)}")

    def _inherent(self, ci: int, im: dict, b: dict, selfty, copy: bool, plumbing: bool,
                  out: dict) -> None:
        c = self.crates[ci]
        for x in im["items"]:
            xi = c.index.get(str(x))
            if xi is None or kind(xi) != "function" or xi.get("visibility") != "public":
                continue
            name = xi["name"]
            if ci == 0 and str(x) in self.anchored:
                continue
            if plumbing and name not in REBORROWS:
                continue
            m = self.method(ci, xi, b, selfty, copy)
            if m is None:
                continue
            recv, text, ret = m
            if name in REBORROWS:
                out["reborrows"].setdefault(name, (recv, [ret]))
            else:
                out["methods"].setdefault(name, (recv, text))

    def method(self, ci: int, xi: dict, b: dict, selfty, copy: bool):
        """A method's receiver class, normalised text and return type, or None.

        None when it is no part of a contract: no `self`, `unsafe`, a seam, or
        a raw pointer or `NonNull` in its signature (raw access).
        """
        f = xi["inner"]["function"]
        inputs = f["sig"]["inputs"]
        if not inputs or inputs[0][0] != "self" or f["header"].get("is_unsafe"):
            return None
        if xi["name"] in SEAMS:
            return None
        recv, text, params, ret = self.signature(ci, xi, b, selfty, copy)
        if any(self._raw(p) for p in params + [ret]):
            return None
        return recv, text, ret

    def signature(self, ci: int, xi: dict, b: dict, selfty, copy: bool):
        """Any function's receiver class, normalised text, parameters and return."""
        c = self.crates[ci]
        f = xi["inner"]["function"]
        inputs = f["sig"]["inputs"]
        has_self = bool(inputs) and inputs[0][0] == "self"
        rt = inputs[0][1] if has_self else None
        if not has_self:
            recv = None
        elif rt == {"generic": "Self"}:
            recv = "ref" if copy else "value"
        elif "borrowed_ref" in rt and rt["borrowed_ref"]["type"] == {"generic": "Self"}:
            recv = "mut" if rt["borrowed_ref"]["is_mutable"] else "ref"
        else:
            recv = "other"
        rest = inputs[1:] if has_self else inputs
        params = [self.resolve(self.lift(ci, t, b, selfty)) for _, t in rest]
        ret = self.resolve(self.lift(ci, f["sig"]["output"], b, selfty))
        if recv == "other":
            recv_text = f"self: {self.render(self.resolve(self.lift(ci, rt, b, selfty)))}"
        else:
            recv_text = {"ref": "&self", "mut": "&mut self", "value": "self"}.get(recv)
        gp, where = c.generics(f["generics"])
        args = ([recv_text] if recv_text else []) + [self.render(p) for p in params]
        text = (c.header(f["header"]) + "fn" + LIFETIME.sub("'_", gp)
                + "(" + ", ".join(args) + ")"
                + ("" if f["sig"]["output"] is None else f" -> {self.render(ret)}")
                + LIFETIME.sub("'_", where))
        return recv, text, params, ret

        if rt == {"generic": "Self"}:
            recv = "ref" if copy else "value"
        elif "borrowed_ref" in rt and rt["borrowed_ref"]["type"] == {"generic": "Self"}:
            recv = "mut" if rt["borrowed_ref"]["is_mutable"] else "ref"
        else:
            recv = "other"

    def _raw(self, t) -> bool:
        tag = t[0]
        if tag == "ptr":
            return True
        if tag == "path":
            return t[1] == NON_NULL or any(self._raw(a) for a in t[3] if a[0] != "lt")
        if tag == "ref":
            return self._raw(t[2])
        if tag == "tuple":
            return any(self._raw(x) for x in t[1])
        if tag in ("slice", "array"):
            return self._raw(t[1])
        return False

    # -- the contract ----------------------------------------------------------

    def contract(self, t) -> dict:
        """The methods, reborrows and traits a consumer may rely on in form `t`.

        Methods are flattened over every route a consumer can call one by:
        on the form itself, through its dereferences (`&self` methods through
        `Deref`, `&mut self` ones too through `DerefMut`) and on what its
        reborrows return; the first route found names a method. A reborrow
        returning the form's own type adds nothing and is left out.
        """
        allowed = {"value": {"ref", "mut", "value", "other"}, "exclusive": {"ref", "mut"},
                   "shared": {"ref"}}
        methods: dict[str, str] = {}
        reborrows: dict[str, list[str]] = {}
        unresolved: set[str] = set()
        opaque: set[str] = set()
        seen = set()
        level = [(t, "value")]
        while level:
            nxt = []
            for form, mode in level:
                key = (self.render(form, norm=False), mode)
                if key in seen:
                    continue
                seen.add(key)
                if form is not t and self.opaque(form):
                    if mode != "value":
                        opaque.add(self.render(form))
                    continue
                d = self.direct(form)
                unresolved |= d["unresolved"]
                for name, (recv, text) in sorted(d["methods"].items()):
                    if recv in allowed[mode]:
                        methods.setdefault(name, text)
                for name, (recv, targets) in sorted(d["reborrows"].items()):
                    if recv not in allowed[mode]:
                        continue
                    if name not in reborrows:
                        reborrows[name] = sorted(self.render(x) for x in targets)
                    for x in targets:
                        nxt.append((x, "value"))
                for tgt, mut in d["derefs"]:
                    if mut and mode != "shared":
                        nxt.append((tgt, "exclusive"))
                    else:
                        nxt.append((tgt, "shared"))
            level = sorted(nxt, key=lambda x: (self.render(x[0], norm=False), x[1]))
        own = self.render(t)
        reborrows = {k: v for k, v in reborrows.items() if v != [own]}
        top = self.direct(t)
        traits = sorted(top["traits"])
        # Only the form's own traits are its contract's, so only their
        # unknowns make it unresolved.
        unresolved |= top["unresolved_traits"]
        out = {"methods": dict(sorted(methods.items())),
               "reborrows": dict(sorted(reborrows.items())), "traits": traits}
        if opaque:
            out["derefs"] = sorted(opaque)
        if unresolved:
            out["unresolved"] = sorted(unresolved)
        return out

    def opaque(self, t) -> bool:
        """A target this module does not look inside: a slice, `str`, a
        primitive, or a standard type that is not a pointer form. Reaching one
        through a dereference is recorded as such; its own methods are the
        standard library's."""
        e = self.expand(t)
        if e[0] in ("slice", "array", "prim", "tuple"):
            return True
        return e[0] == "path" and e[2] is None and self.std_form(e) is None and \
            e[1].split("::")[0] in STD_CRATES
