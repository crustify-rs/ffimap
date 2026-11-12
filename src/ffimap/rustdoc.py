"""rustdoc.py — reading a crate's rustdoc JSON.

`cargo rustdoc --lib -- -Z unstable-options --output-format json` writes one
document per crate: an `index` of its items by id, a `paths` table naming each
item it refers to, and a `format_version` that changes whenever the shape
does. This module reads one such document: it refuses a format it was not
written against, renders types and declarations as text, and finds the paths a
consumer reaches each public item by.

Rendering is canonical. A type is named by the path rustdoc's `paths` table
gives its definition, whatever the source spelled, so two documents of one
crate render one declaration the same whatever the imports around it; parameter
names are left out, since a caller never writes them.

Pure Python over the JSON: no rustc driver and no network.
"""
from __future__ import annotations

import json
from pathlib import Path

# The formats this module was written and tested against. Rustdoc's JSON is
# unstable and its `format_version` moves with the shape, so another version is
# refused rather than half read: a renamed field would silently render as
# nothing. nightly-2026-10-07 (the driver's pin) and nightly-2026-10-08 emit 61.
FORMAT_VERSIONS = frozenset({61})


class FormatError(ValueError):
    """The document is not rustdoc JSON of a supported format."""


def load(path: str | Path) -> dict:
    """Read a rustdoc JSON document, refusing an unsupported format."""
    try:
        doc = json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        raise FormatError(f"{path} is not JSON: {e}") from None
    check(doc, str(path))
    return doc


def check(doc: dict, name: str = "document") -> None:
    if not isinstance(doc, dict) or "index" not in doc or "format_version" not in doc:
        raise FormatError(f"{name} is not rustdoc JSON (no `index` or `format_version`)")
    v = doc["format_version"]
    if v not in FORMAT_VERSIONS:
        raise FormatError(
            f"{name} has rustdoc JSON format_version {v}; ffimap reads "
            f"{', '.join(map(str, sorted(FORMAT_VERSIONS)))} -- regenerate it "
            f"with a nightly that emits one of those (nightly-2026-10-07 does)")


def kind(item: dict) -> str:
    """The item's kind: the single key of its `inner`."""
    return next(iter(item["inner"]))


class Crate:
    """One rustdoc document, with the lookups rendering needs."""

    def __init__(self, doc: dict) -> None:
        check(doc)
        self.doc = doc
        self.index: dict[str, dict] = doc["index"]
        self.paths: dict[str, dict] = doc["paths"]
        self.root = str(doc["root"])
        self.name = self.index[self.root]["name"]
        self.parent: dict[str, str] = {}
        for iid, item in self.index.items():
            inner = item["inner"][kind(item)]
            if not isinstance(inner, dict):
                continue
            for child in self._children(kind(item), inner):
                self.parent.setdefault(str(child), iid)
        self.public_paths = self._walk()
        self._canon: dict[str, str | None] = {}

    # -- structure ---------------------------------------------------------

    @staticmethod
    def _children(k: str, inner: dict) -> list:
        if k in ("impl", "trait"):
            return list(inner.get("items") or [])
        if k == "enum":
            return list(inner.get("variants") or [])
        if k == "union":
            return list(inner.get("fields") or [])
        if k == "struct":
            sk = inner["kind"]
            if isinstance(sk, dict) and "plain" in sk:
                return list(sk["plain"]["fields"])
            if isinstance(sk, dict) and "tuple" in sk:
                return [f for f in sk["tuple"] if f is not None]
        if k == "variant":
            vk = inner["kind"]
            if isinstance(vk, dict) and "struct" in vk:
                return list(vk["struct"]["fields"])
            if isinstance(vk, dict) and "tuple" in vk:
                return [f for f in vk["tuple"] if f is not None]
        return []

    def get(self, iid) -> dict | None:
        return self.index.get(str(iid))

    def _walk(self) -> dict[str, list[str]]:
        """Every path a consumer names each item by, from the crate root.

        Follows public modules and `pub use` re-exports, globs included. Rustdoc
        has already inlined the re-exports of items it does not document
        elsewhere, so what is left as a `use` points at an item that has a
        path of its own as well.
        """
        out: dict[str, set[str]] = {}
        seen: set[tuple[str, str]] = set()

        def visit(mid: str, prefix: str) -> None:
            if (mid, prefix) in seen:
                return
            seen.add((mid, prefix))
            mod = self.get(mid)
            if mod is None or kind(mod) != "module":
                return
            for child in mod["inner"]["module"]["items"]:
                item = self.get(child)
                if item is None:
                    continue
                k = kind(item)
                if k == "use":
                    use = item["inner"]["use"]
                    target = use.get("id")
                    if target is None or self.get(target) is None:
                        continue
                    if use.get("is_glob"):
                        visit(str(target), prefix)
                        continue
                    name, tid = use["name"], str(target)
                else:
                    name, tid = item.get("name"), str(child)
                if not name:
                    continue
                path = f"{prefix}::{name}"
                out.setdefault(tid, set()).add(path)
                if kind(self.index[tid]) == "module":
                    visit(tid, path)

        visit(self.root, self.name)
        return {k: sorted(v) for k, v in out.items()}

    def canonical(self, iid) -> str | None:
        """The path an item is rendered by: the one a consumer names it by.

        For an item of this crate that is the path rustdoc's `paths` table
        gives its definition when a consumer can name it there, else the
        shortest path it is re-exported at (the first in order among equals),
        so that moving a definition behind an unchanged re-export, as a port
        moves an item out of a private module, renders the same. For another
        crate's item, whose re-exports this document does not record, it is
        the `paths` table's.
        """
        iid = str(iid)
        cached = self._canon.get(iid)
        if cached is not None or iid in self._canon:
            return cached
        entry = self.paths.get(iid)
        defined = "::".join(entry["path"]) if entry else None
        public = self.public_paths.get(iid)
        if public and defined not in public:
            defined = min(public, key=lambda p: (p.count("::"), p))
        self._canon[iid] = defined
        return defined

    def item_path(self, iid) -> str:
        """The item's canonical path, else its name."""
        iid = str(iid)
        c = self.canonical(iid)
        if c:
            return c
        item = self.get(iid)
        return (item or {}).get("name") or f"#{iid}"

    # -- types ---------------------------------------------------------------

    def path(self, p: dict) -> str:
        """A `Path` (a resolved type or a trait), canonically named, with args."""
        name = self.canonical(p.get("id")) if p.get("id") is not None else None
        return (name or p["path"]) + self.args(p.get("args"))

    def args(self, a: dict | None) -> str:
        if not a:
            return ""
        if "angle_bracketed" in a:
            ab = a["angle_bracketed"]
            parts = [self.generic_arg(x) for x in ab["args"]]
            parts += [self.constraint(c) for c in ab["constraints"]]
            return f"<{', '.join(parts)}>" if parts else ""
        if "parenthesized" in a:
            pz = a["parenthesized"]
            out = f"({', '.join(self.ty(t) for t in pz['inputs'])})"
            if pz.get("output") is not None:
                out += f" -> {self.ty(pz['output'])}"
            return out
        if "return_type_notation" in a or a == "return_type_notation":
            return "(..)"
        raise FormatError(f"unknown generic args {sorted(a)}")

    def generic_arg(self, g) -> str:
        if g == "infer":
            return "_"
        if "lifetime" in g:
            return g["lifetime"]
        if "type" in g:
            return self.ty(g["type"])
        if "const" in g:
            return self.constant(g["const"])
        raise FormatError(f"unknown generic arg {g}")

    def constraint(self, c: dict) -> str:
        head = c["name"] + self.args(c.get("args"))
        b = c["binding"]
        if "equality" in b:
            return f"{head} = {self.term(b['equality'])}"
        return f"{head}: {self.bounds(b['constraint'])}"

    def term(self, t: dict) -> str:
        if "type" in t:
            return self.ty(t["type"])
        return self.constant(t["constant"])

    @staticmethod
    def constant(c: dict) -> str:
        v = c.get("value")
        return v if v is not None else c.get("expr", "_")

    def bounds(self, bs: list) -> str:
        return " + ".join(self.bound(b) for b in bs)

    def bound(self, b) -> str:
        if "trait_bound" in b:
            tb = b["trait_bound"]
            mod = {"none": "", "maybe": "?", "maybe_const": "[const] "}.get(
                tb.get("modifier", "none"), "")
            return mod + self.hrtb(tb.get("generic_params")) + self.path(tb["trait"])
        if "outlives" in b:
            return b["outlives"]
        if "use" in b:
            caps = []
            for c in b["use"]:
                caps.append(c if isinstance(c, str) else next(iter(c.values())))
            return f"use<{', '.join(caps)}>"
        raise FormatError(f"unknown bound {b}")

    def hrtb(self, params: list | None) -> str:
        if not params:
            return ""
        return f"for<{', '.join(self.param(p) for p in params)}> "

    def ty(self, t) -> str:
        if t is None:
            return "()"
        if "resolved_path" in t:
            return self.path(t["resolved_path"])
        if "generic" in t:
            return t["generic"]
        if "primitive" in t:
            return t["primitive"]
        if "borrowed_ref" in t:
            r = t["borrowed_ref"]
            lt = f"{r['lifetime']} " if r.get("lifetime") else ""
            return f"&{lt}{'mut ' if r['is_mutable'] else ''}{self.ty(r['type'])}"
        if "raw_pointer" in t:
            r = t["raw_pointer"]
            return f"*{'mut' if r['is_mutable'] else 'const'} {self.ty(r['type'])}"
        if "tuple" in t:
            items = [self.ty(x) for x in t["tuple"]]
            return f"({items[0]},)" if len(items) == 1 else f"({', '.join(items)})"
        if "slice" in t:
            return f"[{self.ty(t['slice'])}]"
        if "array" in t:
            return f"[{self.ty(t['array']['type'])}; {t['array']['len']}]"
        if "function_pointer" in t:
            fp = t["function_pointer"]
            return (self.hrtb(fp.get("generic_params")) + self.header(fp["header"])
                    + "fn" + self.sig(fp["sig"]))
        if "dyn_trait" in t:
            dt = t["dyn_trait"]
            parts = [self.hrtb(p.get("generic_params")) + self.path(p["trait"])
                     for p in dt["traits"]]
            if dt.get("lifetime"):
                parts.append(dt["lifetime"])
            return "dyn " + " + ".join(parts)
        if "impl_trait" in t:
            return "impl " + self.bounds(t["impl_trait"])
        if "qualified_path" in t:
            q = t["qualified_path"]
            self_ty = self.ty(q["self_type"])
            base = (f"<{self_ty} as {self.path(q['trait'])}>" if q.get("trait")
                    else self_ty)
            return f"{base}::{q['name']}{self.args(q.get('args'))}"
        if "pat" in t:
            p = t["pat"]
            return f"{self.ty(p['type'])} is {p.get('__pat_unstable_do_not_use', '_')}"
        if t == "infer" or "infer" in t:
            return "_"
        raise FormatError(f"unknown type {sorted(t) if isinstance(t, dict) else t}")

    # -- declarations ------------------------------------------------------

    def param(self, p: dict) -> str:
        k = p["kind"]
        if "lifetime" in k:
            out = k["lifetime"].get("outlives") or []
            return p["name"] + (f": {' + '.join(out)}" if out else "")
        if "type" in k:
            tk = k["type"]
            s = p["name"]
            if tk.get("bounds"):
                s += f": {self.bounds(tk['bounds'])}"
            if tk.get("default") is not None:
                s += f" = {self.ty(tk['default'])}"
            return s
        if "const" in k:
            ck = k["const"]
            s = f"const {p['name']}: {self.ty(ck['type'])}"
            if ck.get("default") is not None:
                s += f" = {ck['default']}"
            return s
        raise FormatError(f"unknown generic param {p}")

    def generics(self, g: dict | None) -> tuple[str, str]:
        """``<params>`` and `` where …`` of a declaration, either may be empty.

        A synthetic param is an `impl Trait` argument, already rendered in place.
        """
        if not g:
            return "", ""
        params = [self.param(p) for p in g.get("params", [])
                  if not p["kind"].get("type", {}).get("is_synthetic")]
        preds = [self.predicate(w) for w in g.get("where_predicates", [])]
        return ((f"<{', '.join(params)}>" if params else ""),
                (f" where {', '.join(preds)}" if preds else ""))

    def predicate(self, w: dict) -> str:
        if "bound_predicate" in w:
            bp = w["bound_predicate"]
            return (self.hrtb(bp.get("generic_params")) + self.ty(bp["type"])
                    + ": " + self.bounds(bp["bounds"]))
        if "lifetime_predicate" in w:
            lp = w["lifetime_predicate"]
            return f"{lp['lifetime']}: {' + '.join(lp['outlives'])}"
        if "eq_predicate" in w:
            ep = w["eq_predicate"]
            return f"{self.ty(ep['lhs'])} == {self.term(ep['rhs'])}"
        raise FormatError(f"unknown where predicate {sorted(w)}")

    @staticmethod
    def header(h: dict) -> str:
        out = ""
        if h.get("is_const"):
            out += "const "
        if h.get("is_async"):
            out += "async "
        if h.get("is_unsafe"):
            out += "unsafe "
        abi = h.get("abi", "Rust")
        if abi != "Rust":
            if isinstance(abi, dict):
                name, val = next(iter(abi.items()))
                if name == "Other":
                    name = str(val).strip('"')
                elif isinstance(val, dict) and val.get("unwind"):
                    name += "-unwind"
            else:
                name = str(abi)
            out += f'extern "{name}" '
        return out

    def receiver(self, t) -> str:
        """The `self` parameter as written: `self`, `&self`, `&'a mut self`, …"""
        if t == {"generic": "Self"}:
            return "self"
        if "borrowed_ref" in t and t["borrowed_ref"]["type"] == {"generic": "Self"}:
            r = t["borrowed_ref"]
            lt = f"{r['lifetime']} " if r.get("lifetime") else ""
            return f"&{lt}{'mut ' if r['is_mutable'] else ''}self"
        return f"self: {self.ty(t)}"

    def sig(self, s: dict) -> str:
        """``(types…) -> out`` with parameter names dropped, `self` kept."""
        ins = []
        for name, t in s["inputs"]:
            ins.append(self.receiver(t) if name == "self" else self.ty(t))
        if s.get("is_c_variadic"):
            ins.append("...")
        out = f"({', '.join(ins)})"
        if s.get("output") is not None:
            out += f" -> {self.ty(s['output'])}"
        return out

    def function(self, f: dict) -> str:
        params, where = self.generics(f["generics"])
        return f"{self.header(f['header'])}fn{params}{self.sig(f['sig'])}{where}"

    def impl_header(self, im: dict) -> str:
        params, where = self.generics(im["generics"])
        out = f"{'unsafe ' if im.get('is_unsafe') else ''}impl{params} "
        if im.get("trait"):
            out += f"{'!' if im.get('is_negative') else ''}{self.path(im['trait'])} for "
        return out + self.ty(im["for"]) + where

    def impl_owner(self, im: dict) -> str:
        """The locator prefix of an impl's items: ``Ty`` or ``<Ty as Trait>``."""
        for_ = self.ty(im["for"])
        if im.get("trait"):
            return f"<{for_} as {self.path(im['trait'])}>"
        return for_
