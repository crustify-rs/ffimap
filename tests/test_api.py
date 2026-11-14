"""`ffimap api` over hand-built rustdoc JSON, and over the `api` fixture crate.

The hand-built documents are the smallest rustdoc JSON that carries each case,
written in the shape `format_version` 61 has, so every classification is tested
without a toolchain. `FixtureTests` documents `tests/fixtures/api/` without
and with `--cfg after` (and `--cfg drop_getter`), and its ffibox stand-in, on
the driver's pinned nightly and checks the classification each item's doc
comment states; it skips where that nightly is missing.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ffimap import api, cli, rustdoc

FIXTURE = Path(__file__).parent / "fixtures" / "api"
HEADER = {"is_const": False, "is_unsafe": False, "is_async": False, "abi": "Rust"}
NO_GENERICS = {"params": [], "where_predicates": []}
OPTION = 900


def prim(name):
    return {"primitive": name}


def rp(iid, path, *args):
    a = None
    if args:
        a = {"angle_bracketed": {"args": [{"type": t} for t in args], "constraints": []}}
    return {"resolved_path": {"path": path, "id": iid, "args": a}}


def self_ref(mut=False):
    return {"borrowed_ref": {"lifetime": None, "is_mutable": mut, "type": {"generic": "Self"}}}


class Doc:
    """A rustdoc JSON document under construction, ids handed out in order."""

    def __init__(self, crate="c", start=1):
        self.crate = crate
        self.next = start
        self.root = self.next
        self.next += 1
        self.index = {str(self.root): self._item(self.root, crate, {"module": {
            "is_crate": True, "items": [], "is_stripped": False}})}
        self.paths = {str(self.root): {"crate_id": 0, "path": [crate], "kind": "module"},
                      str(OPTION): {"crate_id": 1, "path": ["core", "option", "Option"],
                                    "kind": "enum"}}

    @staticmethod
    def _item(iid, name, inner, docs=None, attrs=(), vis="public"):
        return {"id": iid, "crate_id": 0, "name": name, "span": None, "visibility": vis,
                "docs": docs, "links": {}, "attrs": list(attrs), "deprecation": None,
                "stability": None, "const_stability": None, "inner": inner}

    def add(self, name, inner, docs=None, alias=(), module=None, path=None, vis="public"):
        iid = self.next
        self.next += 1
        attrs = [{"other": f'#[doc(alias = "{a}")]'} for a in alias]
        self.index[str(iid)] = self._item(iid, name, inner, docs, attrs, vis)
        if module is not False:
            mod = self.root if module is None else module
            self.index[str(mod)]["inner"]["module"]["items"].append(iid)
        if path is not None:
            self.paths[str(iid)] = {"crate_id": 0, "path": path, "kind": next(iter(inner))}
        return iid

    def module(self, name):
        return self.add(name, {"module": {"is_crate": False, "items": [], "is_stripped": False}},
                        path=[self.crate, name])

    def fn(self, name, inputs=(), output=None, docs=None, alias=(), module=None,
           unsafe=False, has_body=True):
        header = dict(HEADER, is_unsafe=unsafe)
        inner = {"function": {"sig": {"inputs": [list(i) for i in inputs], "output": output,
                                      "is_c_variadic": False},
                              "generics": NO_GENERICS, "header": header,
                              "has_body": has_body}}
        vis = "public" if module is not False else "default"
        path = [self.crate, name] if module is None else None
        return self.add(name, inner, docs, alias, module, path=path, vis=vis)

    def struct(self, name, fields=(), docs=None, alias=(), module=None, stripped=False):
        fids = []
        for fname, t in fields:
            fids.append(self.add(fname, {"struct_field": t}, module=False))
        kind = {"plain": {"fields": fids, "has_stripped_fields": stripped}} if fields or \
            stripped else "unit"
        return self.add(name, {"struct": {"kind": kind, "generics": NO_GENERICS,
                                          "impls": []}},
                        docs, alias, module, path=[self.crate, name])

    def enum(self, name, variants, docs=None, alias=(), non_exhaustive=False):
        vids = [self.add(v, {"variant": {"kind": "plain", "discriminant": None}}, module=False,
                         vis="default") for v in variants]
        iid = self.add(name, {"enum": {"generics": NO_GENERICS, "has_stripped_variants": False,
                                       "variants": vids, "impls": []}},
                       docs, alias, path=[self.crate, name])
        if non_exhaustive:
            self.index[str(iid)]["attrs"].append("non_exhaustive")
        return iid

    def alias(self, name, target, docs=None):
        return self.add(name, {"type_alias": {"type": target, "generics": NO_GENERICS}}, docs,
                        path=[self.crate, name])

    def trait(self, name, items):
        return self.add(name, {"trait": {"is_auto": False, "is_unsafe": False,
                                         "is_dyn_compatible": True, "items": list(items),
                                         "generics": NO_GENERICS, "bounds": [],
                                         "implementations": []}},
                        path=[self.crate, name])

    def assoc_type(self, name, ty):
        return self.add(name, {"assoc_type": {"generics": NO_GENERICS, "bounds": [],
                                              "type": ty}}, module=False, vis="default")

    def impl(self, ty_id, items=(), trait=None, synthetic=False, negative=False):
        iid = self.add(None, {"impl": {
            "is_unsafe": False, "generics": NO_GENERICS, "provided_trait_methods": [],
            "trait": trait, "for": rp(ty_id, self.index[str(ty_id)]["name"]),
            "items": list(items), "is_negative": negative, "is_synthetic": synthetic,
            "blanket_impl": None}}, module=False, vis="default")
        inner = self.index[str(ty_id)]["inner"]
        next(iter(inner.values()))["impls"].append(iid)
        return iid

    def doc(self):
        return {"root": self.root, "crate_version": "0.1.0", "includes_private": False,
                "index": self.index, "paths": self.paths, "external_crates": {},
                "target": {}, "format_version": 61}


def auto(name):
    return {"path": name, "id": None, "args": None}


def foo_crate(*, set_ty="i32", param="value", verb="Wraps", send=True, retarget=False,
              debug=False, extra=False, old=True, fresh=False, variants=("A", "B"),
              non_exhaustive=False, provided=False, required=False):
    """A crate with one C type and its functions; each knob is one change."""
    d = Doc()
    foo = d.struct("Foo", docs="A foo.\n\nWraps `st::foo`", alias=["foo"], stripped=True)
    free = d.struct("FooFree")
    holder = d.struct("Holder")
    other = d.struct("Holder2")
    targets = {False: rp(holder, "Holder", rp(foo, "Foo"), rp(free, "FooFree")),
               "option": rp(OPTION, "Option", rp(foo, "Foo")),
               "same": rp(other, "Holder2", rp(foo, "Foo"))}
    d.alias("FooBox", targets[retarget])
    methods = [d.fn("new", output=rp(OPTION, "Option", rp(foo, "Foo")),
                    docs="Wraps `fn::foo_new`", alias=["foo_new"], module=False),
               d.fn("set", inputs=[("self", self_ref(True)), (param, prim(set_ty))],
                    docs=f"{verb} `fn::foo_set`", alias=["foo_set"], module=False)]
    if old:
        methods.append(d.fn("old", inputs=[("self", self_ref())], docs="Wraps `fn::foo_old`",
                            alias=["foo_old"], module=False))
    if fresh:
        methods.append(d.fn("fresh", docs="Wraps `fn::foo_fresh`", alias=["foo_fresh"],
                            module=False))
    if extra:
        methods.append(d.fn("helper", module=False))
    d.impl(foo, methods)
    d.impl(foo, trait=auto("core::marker::Send"), synthetic=True, negative=not send)
    if debug:
        d.impl(foo, [d.fn("fmt", module=False)], trait=auto("core::fmt::Debug"))
    d.impl(free, [d.fn("release", inputs=[("self", self_ref())],
                       docs="Wraps `fn::foo_free`", alias=["foo_free"], module=False)])
    ref = d.struct("FooRef", stripped=True)
    d.impl(ref, [d.assoc_type("Cell", rp(foo, "Foo"))], trait=auto("View"))
    d.enum("Kind", variants, docs="Wraps `enm::kind`", alias=["kind"],
           non_exhaustive=non_exhaustive)
    items = [d.fn("run", inputs=[("self", self_ref())], docs="Wraps `fnp::runner.run`",
                  alias=["runner.run"], module=False, has_body=False)]
    if provided:
        items.append(d.fn("stop", inputs=[("self", self_ref())], module=False))
    if required:
        items.append(d.fn("pause", inputs=[("self", self_ref())], module=False,
                          has_body=False))
    d.trait("Runner", items)
    return d.doc()


def statuses(before, after, **kw):
    out = api.diff(api.extract(before), api.extract(after), **kw)
    return {k: v["status"] for k, v in out["items"].items()}, out


class AnchorTests(unittest.TestCase):
    def test_the_convention_form_parses(self) -> None:
        good, bad = api.anchors("Text.\n\nWraps `fn::git_x`\nReplaces `fld::a.b.c`\n")
        self.assertEqual(good, [("Wraps", "fn", "git_x"), ("Replaces", "fld", "a.b.c")])
        self.assertEqual(bad, [])

    def test_near_misses_are_reported_not_keyed(self) -> None:
        docs = "\n".join([
            "It Wraps `fn::git_x` in a sentence.",
            "Wraps `fn::git_y`.",
            "Wraps fn::git_z",
            "Wraps `fn::a-b`",
            "Wraps `fld::lonely`",
        ])
        good, bad = api.anchors(docs)
        self.assertEqual(good, [])
        self.assertEqual([why for _, why in bad], [
            "not an anchor line", "not an anchor line", "not an anchor line",
            "path is not dot-separated names", "fld path names no member"])

    def test_prose_using_the_verbs_is_not_an_anchor(self) -> None:
        self.assertEqual(api.anchors("Replaces the name, as `git_x` does.\nWraps it."),
                         ([], []))

    def test_aliases_are_read_in_both_spellings(self) -> None:
        item = {"attrs": [{"other": '#[doc(alias = "a")]'},
                          {"other": '#[doc(alias("b", "c"))]'}]}
        self.assertEqual(api.aliases(item), {"a", "b", "c"})


class FormatTests(unittest.TestCase):
    def test_another_format_version_is_refused(self) -> None:
        doc = foo_crate()
        doc["format_version"] = 60
        with self.assertRaisesRegex(rustdoc.FormatError, "format_version 60"):
            api.extract(doc)

    def test_a_non_rustdoc_document_is_refused(self) -> None:
        with self.assertRaises(rustdoc.FormatError):
            api.as_extract({"counts": {}})


class ExtractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.e = api.extract(foo_crate())

    def test_items_are_keyed_by_anchor(self) -> None:
        self.assertEqual(sorted(self.e["items"]), [
            "enm::kind", "fn::foo_free", "fn::foo_new", "fn::foo_old", "fn::foo_set",
            "fnp::runner.run", "st::foo"])
        self.assertEqual(self.e["anchors"],
                         {"malformed": [], "unknown_kinds": {}, "without_alias": []})

    def test_a_method_has_its_receiver_but_no_parameter_names(self) -> None:
        rec = self.e["items"]["fn::foo_set"]["stand_ins"]["c::Foo::set"]
        self.assertEqual(rec["sig"], {"decl": "fn(&mut self, i32)", "impl": "impl c::Foo"})
        self.assertEqual(rec["paths"], ["c::Foo::set"])
        self.assertEqual(rec["anchor"], "Wraps")

    def test_handles_and_owners_are_associated(self) -> None:
        foo = self.e["items"]["st::foo"]
        self.assertEqual({k: v["via"] for k, v in foo["associated"].items()},
                         {"c::FooBox": ["alias"], "c::FooRef": ["assoc_type"]})
        self.assertEqual(foo["associated"]["c::FooBox"]["sig"]["decl"],
                         "type = c::Holder<c::Foo, c::FooFree>")
        # A policy type no alias or associated type ties goes with the
        # stand-ins it holds.
        self.assertEqual(list(self.e["items"]["fn::foo_free"]["associated"]), ["c::FooFree"])

    def test_a_type_lists_auto_traits_and_unanchored_members_only(self) -> None:
        sig = self.e["items"]["st::foo"]["stand_ins"]["c::Foo"]["sig"]
        self.assertEqual(list(sig["impls"]), ["impl core::marker::Send for c::Foo"])
        self.assertEqual(sig["members"], {})

    def test_surface_no_anchor_reaches_is_unattributed(self) -> None:
        self.assertEqual(sorted(self.e["unattributed"]["c"]), ["c::Holder", "c::Holder2"])
        # A trait holding a stand-in goes with it, as a policy type does.
        self.assertEqual(self.e["items"]["fnp::runner.run"]["associated"]["c::Runner"]["via"],
                         ["owner"])

    def test_parameter_names_do_not_move_the_extract(self) -> None:
        self.assertEqual(api.extract(foo_crate(param="other")), self.e)

    def test_renumbering_and_reordering_give_the_same_bytes(self) -> None:
        doc = foo_crate()
        shift = 1000

        def renumber(node):
            if isinstance(node, dict):
                out = {}
                for k, v in node.items():
                    if k in ("id", "root") and isinstance(v, int) and v != OPTION:
                        out[k] = v + shift
                    elif k in ("items", "impls", "variants", "fields") and isinstance(v, list):
                        out[k] = [x + shift if isinstance(x, int) else renumber(x)
                                  for x in reversed(v)]
                    else:
                        out[k] = renumber(v)
                return out
            if isinstance(node, list):
                return [renumber(x) for x in node]
            return node

        moved = renumber(doc)
        moved["index"] = {str(int(k) + shift): v for k, v in reversed(list(moved["index"].items()))}
        moved["paths"] = {(k if int(k) == OPTION else str(int(k) + shift)): v
                          for k, v in moved["paths"].items()}
        dump = lambda e: json.dumps(e, indent=1, sort_keys=True)  # noqa: E731
        self.assertEqual(dump(api.extract(moved)), dump(self.e))

    def test_a_reexport_adds_a_path_but_renders_types_by_the_public_one(self) -> None:
        d = Doc()
        inner = d.module("ffi")
        d.index[str(inner)]["inner"]["module"]["is_stripped"] = True
        # `ffi` is not reachable: the root lists a `pub use ffi::Foo` instead.
        d.index[str(d.root)]["inner"]["module"]["items"].remove(inner)
        foo = d.add("Foo", {"struct": {"kind": "unit", "generics": NO_GENERICS, "impls": []}},
                    "Wraps `st::foo`", ["foo"], module=inner, path=["c", "ffi", "Foo"])
        d.add("Foo", {"use": {"source": "self::ffi::Foo", "name": "Foo", "id": foo,
                              "is_glob": False}})
        d.fn("make", output=rp(foo, "ffi::Foo"), docs="Wraps `fn::make`", alias=["make"])
        e = api.extract(d.doc())
        self.assertEqual(list(e["items"]["st::foo"]["stand_ins"]), ["c::Foo"])
        self.assertEqual(e["items"]["fn::make"]["stand_ins"]["c::make"]["sig"]["decl"],
                         "fn() -> c::Foo")

    def test_coverage_counts_public_and_anchored_items(self) -> None:
        cov = self.e["coverage"]
        self.assertEqual(cov["c_items"], 7)
        self.assertEqual(cov["anchored"], {"enum": 1, "inherent_item": 4, "struct": 1,
                                           "trait_item": 1})
        self.assertEqual(cov["public"]["struct"], 5)


class DiffTests(unittest.TestCase):
    def test_an_extract_against_itself_is_all_kept(self) -> None:
        st, out = statuses(foo_crate(), foo_crate())
        self.assertEqual(set(st.values()), {"kept"})
        self.assertEqual(out["totals"]["kept"], 7)

    def test_a_signature_change_is_changed(self) -> None:
        st, out = statuses(foo_crate(), foo_crate(set_ty="u32"))
        self.assertEqual(st["fn::foo_set"], "changed")
        # A method of a handle is keyed by its name in the contract view.
        self.assertEqual(out["items"]["fn::foo_set"]["changes"], [
            {"item": "method::set", "part": "method", "change": "removed",
             "severity": "changed", "name": "fn(&mut self, i32)"},
            {"item": "method::set", "part": "method", "change": "added",
             "severity": "extended", "name": "fn(&mut self, u32)"}])
        self.assertEqual(st["fn::foo_new"], "kept")
        _, out = statuses(foo_crate(), foo_crate(set_ty="u32"), raw=True)
        self.assertEqual(out["items"]["fn::foo_set"]["changes"], [{
            "item": "c::Foo::set", "part": "decl", "change": "changed",
            "severity": "changed", "before": "fn(&mut self, i32)",
            "after": "fn(&mut self, u32)"}])

    def test_a_lost_auto_trait_is_changed(self) -> None:
        st, out = statuses(foo_crate(), foo_crate(send=False))
        self.assertEqual(st["st::foo"], "changed")
        lost = [c for c in out["items"]["st::foo"]["changes"] if c["change"] == "removed"]
        self.assertEqual((lost[0]["part"], lost[0]["name"]), ("trait", "core::marker::Send"))

    def test_a_new_trait_impl_or_member_is_extended(self) -> None:
        st, out = statuses(foo_crate(), foo_crate(debug=True, extra=True))
        self.assertEqual(st["st::foo"], "extended")
        # An associated function is no part of a contract; the raw view has it.
        self.assertEqual([c["part"] for c in out["items"]["st::foo"]["changes"]], ["trait"])
        _, out = statuses(foo_crate(), foo_crate(debug=True, extra=True), raw=True)
        self.assertEqual(sorted(c["part"] for c in out["items"]["st::foo"]["changes"]),
                         ["impl", "member"])

    def test_a_retarget_that_keeps_the_contract_is_kept(self) -> None:
        st, out = statuses(foo_crate(), foo_crate(retarget="same"))
        self.assertEqual(st["st::foo"], "kept")
        self.assertEqual(out["items"]["st::foo"]["retarget"], [{
            "item": "c::FooBox", "before": "type = c::Holder<c::Foo, c::FooFree>",
            "after": "type = c::Holder2<c::Foo>"}])
        self.assertEqual(out["items"]["st::foo"]["raw_status"], "changed")
        st, _ = statuses(foo_crate(), foo_crate(retarget="same"), raw=True)
        self.assertEqual(st["st::foo"], "changed")

    def test_an_unresolvable_retarget_is_compared_raw(self) -> None:
        st, out = statuses(foo_crate(), foo_crate(retarget="option"))
        self.assertEqual(st["st::foo"], "changed")
        rec = out["items"]["st::foo"]
        self.assertEqual(rec["unresolved"], [
            "c::FooBox: core::option::Option: a standard type no contract models"])
        ch = rec["changes"][0]
        self.assertEqual((ch["item"], ch["part"], ch["after"], ch["view"]),
                         ("c::FooBox", "decl", "type = core::option::Option<c::Foo>", "raw"))

    def test_removed_and_new_items(self) -> None:
        st, _ = statuses(foo_crate(), foo_crate(old=False, fresh=True))
        self.assertEqual((st["fn::foo_old"], st["fn::foo_fresh"]), ("removed", "new"))

    def test_a_wrap_to_port_step_is_recorded(self) -> None:
        st, out = statuses(foo_crate(), foo_crate(verb="Replaces"))
        self.assertEqual(st["fn::foo_set"], "kept")
        self.assertEqual(out["items"]["fn::foo_set"]["anchor"],
                         {"before": "Wraps", "after": "Replaces"})
        self.assertEqual(out["anchor_moves"], {"Wraps->Replaces": 1})

    def test_a_variant_added_to_an_exhaustive_enum_is_changed(self) -> None:
        st, _ = statuses(foo_crate(), foo_crate(variants=("A", "B", "C")))
        self.assertEqual(st["enm::kind"], "changed")
        st, _ = statuses(foo_crate(non_exhaustive=True),
                         foo_crate(non_exhaustive=True, variants=("A", "B", "C")))
        self.assertEqual(st["enm::kind"], "extended")

    def test_a_trait_gains_provided_items_but_not_required_ones(self) -> None:
        st, _ = statuses(foo_crate(), foo_crate(provided=True))
        self.assertEqual(st["fnp::runner.run"], "extended")
        st, _ = statuses(foo_crate(), foo_crate(required=True))
        self.assertEqual(st["fnp::runner.run"], "changed")

    def test_items_restricts_to_a_worklist(self) -> None:
        st, out = statuses(foo_crate(), foo_crate(set_ty="u32"),
                           items=["fn::foo_set", "fn::foo_new", "fn::absent"])
        self.assertEqual(st, {"fn::foo_new": "kept", "fn::foo_set": "changed"})
        self.assertEqual(out["missing"], ["fn::absent"])

    def test_a_relabelled_kind_is_one_item(self) -> None:
        before = foo_crate()
        after = foo_crate()
        for item in after["index"].values():
            if item["docs"] and "`enm::kind`" in item["docs"]:
                item["docs"] = item["docs"].replace("enm::kind", "ty::kind")
        st, out = statuses(before, after)
        self.assertEqual(st["ty::kind"], "kept")
        self.assertNotIn("enm::kind", st)
        self.assertEqual(out["items"]["ty::kind"]["rekeyed"], "enm::kind")
        self.assertEqual(api.extract(after)["anchors"]["unknown_kinds"], {"ty": 1})

    def test_extracts_of_another_version_are_not_compared(self) -> None:
        e = api.extract(foo_crate())
        with self.assertRaises(ValueError):
            api.diff(e, dict(e, api=0))


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.run_api(list(argv))
        return code, out.getvalue()

    def test_extract_and_diff_read_either_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            b, a = Path(tmp, "b.json"), Path(tmp, "a.json")
            b.write_text(json.dumps(foo_crate()))
            a.write_text(json.dumps(foo_crate(set_ty="u32")))
            code, text = self.run_cli("extract", str(b))
            self.assertEqual(code, 0)
            e = Path(tmp, "b.extract.json")
            e.write_text(text)
            code, text = self.run_cli("diff", str(e), str(a), "--format", "text",
                                      "--items", "fn::foo_set,fn::foo_new")
        self.assertEqual(code, 0)
        self.assertEqual(text.splitlines(), [
            "c -> c (rustdoc format 61 -> 61; contract view)",
            "changed  fn::foo_set",
            "    - method::set [method] fn(&mut self, i32)",
            "    + method::set [method] fn(&mut self, u32)",
            "C items: 1 kept, 0 extended, 1 changed, 0 removed, 0 new",
            "unattributed modules: 1 kept, 0 extended, 0 changed, 0 removed, 0 new"])

    def test_an_unsupported_document_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, "old.json")
            p.write_text(json.dumps({"format_version": 40, "index": {}}))
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code, _ = self.run_cli("extract", str(p))
        self.assertEqual(code, 2)
        self.assertIn("format_version 40", err.getvalue())


def _toolchain():
    from ffimap import measure
    return measure._TOOLCHAIN


def _rustdoc_json(target: Path, manifest: Path, name: str, *flags: str) -> dict:
    cmd = ["cargo", f"+{_toolchain()}", "rustdoc", "-q", "--lib",
           "--manifest-path", str(manifest), "--",
           "-Z", "unstable-options", "--output-format", "json", *flags]
    subprocess.run(cmd, check=True, env={**os.environ, "CARGO_TARGET_DIR": str(target)})
    return json.loads((target / "doc" / f"{name}.json").read_text())


def _nightly_available() -> bool:
    if shutil.which("cargo") is None:
        return False
    r = subprocess.run(["cargo", f"+{_toolchain()}", "--version"], capture_output=True)
    return r.returncode == 0


@unittest.skipUnless(_nightly_available(), "needs cargo and the dated nightly")
class FixtureTests(unittest.TestCase):
    """Real rustdoc JSON: the fixture's items state their own classification."""

    @classmethod
    def setUpClass(cls) -> None:
        manifest = FIXTURE / "Cargo.toml"
        with tempfile.TemporaryDirectory() as tmp:
            b = _rustdoc_json(Path(tmp, "b"), manifest, "apifix")
            a = _rustdoc_json(Path(tmp, "a"), manifest, "apifix", "--cfg", "after")
            g = _rustdoc_json(Path(tmp, "g"), manifest, "apifix", "--cfg", "after",
                              "--cfg", "drop_getter")
            stub = _rustdoc_json(Path(tmp, "s"), FIXTURE / "ffibox-stub" / "Cargo.toml",
                                 "ffibox", "--document-private-items")
        cls.before = api.extract(b, [stub])
        after = api.extract(a, [stub])
        cls.out = api.diff(cls.before, after)
        cls.raw = api.diff(cls.before, after, raw=True)
        cls.dropped = api.diff(cls.before, api.extract(g, [stub]))
        cls.nodep = api.diff(api.extract(b), api.extract(a))

    def test_each_item_is_classified_as_its_doc_says(self) -> None:
        self.assertEqual({k: v["status"] for k, v in self.out["items"].items()}, {
            "fld::foo.size": "kept", "fld::pair.a": "kept", "fld::pair.b": "kept",
            "fn::foo_free": "kept", "fn::foo_fresh": "new", "fn::foo_len": "kept",
            "fn::foo_new": "kept", "fn::foo_old": "removed", "fn::foo_set": "changed",
            "fn::no_alias": "kept", "fn::same_name": "kept", "st::cell": "changed",
            "st::foo": "kept",
            "st::point": "extended"})
        self.assertEqual(self.out["items"]["fn::foo_len"]["anchor"],
                         {"before": "Wraps", "after": "Replaces"})

    def test_the_port_layout_step_keeps_the_contract(self) -> None:
        foo = self.out["items"]["st::foo"]
        self.assertEqual([r["item"] for r in foo["retarget"]], [
            "apifix::foo::Foo", "apifix::foo::FooBox", "apifix::foo::FooMut",
            "apifix::foo::FooRef"])
        self.assertEqual(foo["raw_status"], "changed")
        self.assertEqual(self.raw["items"]["st::foo"]["status"], "changed")
        # The getters moved from the handles to `impl Foo`.
        self.assertEqual(self.raw["items"]["fld::foo.size"]["status"], "changed")
        contract = self.before["items"]["st::foo"]["contract"]["apifix::foo::FooBox"]
        self.assertEqual(contract["reborrows"], {
            "as_mut": ["apifix::foo::FooMut<'_>"], "as_ref": ["apifix::foo::FooRef<'_>"]})
        self.assertEqual(contract["methods"], {"id": "fn(&self) -> u32"})

    def test_a_dropped_getter_is_changed(self) -> None:
        foo = self.dropped["items"]["st::foo"]
        self.assertEqual(foo["status"], "changed")
        self.assertEqual(sorted((c["item"], c["name"]) for c in foo["changes"]), [
            ("apifix::foo::Foo", "id"), ("apifix::foo::FooBox", "id"),
            ("apifix::foo::FooMut", "id"), ("apifix::foo::FooRef", "id")])

    def test_without_ffiboxs_json_the_owner_is_unresolved(self) -> None:
        foo = self.nodep["items"]["st::foo"]
        self.assertEqual(foo["status"], "changed")
        self.assertEqual(foo["unresolved"], [
            "apifix::foo::FooBox: ffibox::CBox: no rustdoc JSON for its crate"])
        self.assertEqual({c.get("view") for c in foo["changes"]}, {"raw"})

    def test_the_lost_auto_traits_are_named(self) -> None:
        lost = sorted(c["name"] for c in self.out["items"]["st::cell"]["changes"]
                      if c["change"] == "removed")
        self.assertEqual(lost, ["core::marker::Send", "core::marker::Sync"])

    def test_the_unattributed_drop_is_reported(self) -> None:
        mod = self.out["unattributed"]["modules"]["apifix"]
        self.assertEqual(mod["changes"], [{
            "item": "apifix::Loose", "part": "impl", "change": "removed",
            "severity": "changed", "name": "impl core::ops::drop::Drop for apifix::Loose"}])

    def test_anchor_defects_are_reported(self) -> None:
        self.assertEqual(self.before["anchors"]["malformed"][0]["item"], "apifix::bad_anchor")
        self.assertEqual(self.before["anchors"]["without_alias"],
                         [{"anchor": "fn::no_alias", "item": "apifix::lacks_alias"}])
        self.assertEqual(self.before["items"]["st::foo"]["associated"]["apifix::foo::FooRef"]
                         ["via"], ["assoc_type"])


if __name__ == "__main__":
    unittest.main()
