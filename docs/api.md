# API stability per C item

`ffimap api` measures a promise a C-to-Rust migration makes to its Rust
consumers: once a C item has a safe Rust API, wrapping it, porting it and its
later stages leave that API alone. It reads the crate's rustdoc JSON, finds the
Rust items that stand in for each C item through their anchors, and records
their consumer-facing surface; two such records, one at the item's first
landing and one after a later landing, say whether the surface was kept,
extended or changed. This document is what the two documents hold and every
rule behind them. The scan's counters are [`schema.md`](schema.md)'s and have
nothing to do with it.

## 1. Input

```sh
cargo +nightly-2026-10-07 rustdoc -p CRATE --lib -- -Z unstable-options --output-format json
ffimap api extract target/doc/CRATE.json > before.json
```

The measure is pure Python over that JSON. It does not use the driver, so the
crate need not build on the driver's nightly, only document on one whose JSON
format it reads.

Rustdoc's JSON is unstable: each nightly writes a `format_version`, and the
shape moves with it. `ffimap api` reads **format 61**, which
nightly-2026-10-07 (the driver's pin) and nightly-2026-10-08 emit, and refuses
any other with an error naming the version it found. Support for a new format
is added by checking the fields `src/ffimap/rustdoc.py` reads against it and
adding it to `FORMAT_VERSIONS`.

## 2. C items and their stand-ins

A C item is keyed by its anchor's `<kind>::<path>`: `fn::git_mailmap_new`,
`st::git_mailmap`, `fld::git_buf.ptr`. An anchor is a doc-comment line of its
own, exactly ``Wraps `<kind>::<path>` `` or ``Replaces `<kind>::<path>` ``,
where the path is names separated by dots and a `fld` path names a member. Every
public item of the crate that carries one is a **stand-in** of that C item, and
an item carrying several (the accessor of two members) is a stand-in of each.

What the extract reports about the anchors themselves, under `anchors`:

- `malformed`: a line that tries to be an anchor and is not one -- the verb and
  a `kind::` path inside a sentence, with a trailing period, without backticks,
  or with a path that is not names. It keys nothing.
- `unknown_kinds`: anchors whose kind is not one of the convention's (`fn`,
  `st`, `un`, `enm`, `fnp`, `tdf`, `fld`, `glb`, `mac`), counted by kind. They
  are keyed as written.
- `without_alias`: anchors on an item with no `#[doc(alias)]` naming the
  anchor's path.

## 3. Locators and paths

Each stand-in is named by a **locator**, which is how one landing's record is
matched with the next's:

| item | locator |
|---|---|
| a free item | its canonical path |
| an item of an inherent impl | `Ty::name` |
| an item of a trait impl | `<Ty as Trait<Args>>::name` |
| a trait's item, a variant, a field | its owner's locator `::name` |

Lifetime names in a locator are erased to `'_`.

A **canonical path** is the path a consumer names an item by. For an item of
the crate it is the path rustdoc's `paths` table gives its definition when that
path is public, else the shortest public path it is re-exported at, the first
in order among equals. An item defined in a private module and re-exported from
its parent is named by the parent's path, and a port that moves the definition
into the parent changes nothing. An item of another crate is named by its
definition's path in the `paths` table, `ffibox::refs::CBox` for instance,
because this document does not record that crate's re-exports.

Every type in a signature is rendered by its canonical path, never by what the
source wrote, so an import or a reordering of the source gives the same bytes.

A record's `paths` lists every public path the item is reached by, from the
crate root through public modules and `pub use`, globs included. An associated
item's are its owner's paths with its name appended.

## 4. Signatures

Each stand-in's `sig` is normalised text by kind:

- **functions and methods**: `decl` holds `const`, `async`, `unsafe`, the ABI,
  generics, the receiver (`self`, `&self`, `&'a mut self`, `self: Box<Self>`),
  the parameter types and return type, and where-clauses. A method also has
  the `impl` header it is declared in, generics and trait included, and a
  trait's method has `default`, whether it has a body. Parameter names are
  left out.
- **structs, enums and unions**: `decl` holds the generics, the shape (`;`,
  `(n)`, `{}`) and `#[non_exhaustive]`. `fields` maps each public field to its
  type, and `variants` each variant to its shape and discriminant.
  `stripped` says whether rustdoc hid private fields or variants. `impls` maps
  the header of every trait impl rustdoc records for the type to its items
  (those it defines and the trait's provided ones it inherits) and its
  associated types and constants; the auto-trait impls rustdoc synthesises
  (`Send`, `Sync`, `Unpin`, `UnwindSafe`, `RefUnwindSafe`, and `Freeze` and
  `UnsafeUnpin` where the nightly records them), negative ones as `!Send`, are
  included, and blanket impls are not, since they follow from the type's other
  impls. `members` holds the items of its inherent impls that stand in for no
  C item, each with its impl header.
- **traits**: `decl` with generics, supertraits and `unsafe`; `required` and
  `provided` items, each with its declaration; `dyn_compatible`.
- **type aliases**: `decl` holds the whole target, `type = ffibox::refs::CBox<…>`.
- **constants and statics**: type and value; **associated constants and types**:
  their declaration and, in an impl, its header; **variants** and **fields**:
  their shape or type; a `macro_rules!` macro only its kind, since its body is
  not an interface.

A trait impl's methods are recorded by name only: their signatures are the
trait's, recorded where the trait is.

## 5. Handles and owners

The types a consumer reaches a C type through -- `FooRef`, `FooMut`, `FooBox`,
`FooArc`, `FooVal` and a policy type such as `FooFree` -- are not always
annotated. An unannotated public struct, enum, union or trait of the crate is
**associated** with C items by rule 1, else by rule 2, and a type alias by rule
3; `via` says which rule tied it:

1. `assoc_type`: a trait impl of the type sets an associated type to an
   anchored type, or a trait impl of an anchored type sets one to it.
   `impl CRefSeam for MailmapRef { type Cell = Mailmap; }` and
   `impl CCell for Mailmap { type Ref<'a> = MailmapRef<'a>; }` both tie
   `MailmapRef` to `st::git_mailmap`.
2. `owner`: the type's impls, or the trait's declaration, hold stand-ins; it is
   associated with their C items. A policy type whose `CDrop::c_drop` wraps
   `fn::git_mailmap_free` goes with that item.
3. `alias`: a type alias whose target names an anchored type, by id anywhere in
   the target, goes with that type's C items: `MailmapBox = CBox<Mailmap,
   MailmapFree>` with `st::git_mailmap`. A target naming none goes with the
   items of the types it names that rules 1 and 2 associated.

An associated item is recorded under each of its C items with the record a
stand-in has, and a C item's surface is its stand-ins and its associated items
together.

## 6. The unattributed surface

A public item of the crate that is neither a stand-in nor associated is
**unattributed**. It is recorded by the Rust module of its canonical path,
under `unattributed`, with the same records, and compared the same way, so a
change to it is reported though no C item owns it.

## 7. Coverage

`coverage` counts how far the anchors reach. `public` counts the crate's
reachable items by role: free items by kind, `inherent_item` and
`trait_impl_item` for the items of a type's impls (blanket and synthesised
impls aside), `trait_item`, `variant` and `field`. `anchored` counts those that
carry an anchor. `c_items` and `c_items_by_kind` count the keys, `stand_ins`
the records, `associated` and `unattributed` the items those sections hold.

## 8. The extract

```json
{
 "api": 1,
 "source": {"crate": "libgit2", "crate_version": "0.1.0", "format_version": 61},
 "items": {
  "st::git_mailmap": {
   "anchor": "Wraps",
   "stand_ins": {"libgit2::…::Mailmap": {"anchor": "Wraps", "kind": "struct",
                                         "paths": ["libgit2::…::Mailmap"], "sig": {…}}},
   "associated": {"libgit2::…::MailmapBox": {"kind": "type_alias", "via": ["alias"],
                                             "paths": […], "sig": {…}}}
  }
 },
 "unattributed": {"libgit2::…::odb": {"libgit2::…::OdbDataStrVec": {…}}},
 "anchors": {"malformed": [], "unknown_kinds": {}, "without_alias": []},
 "coverage": {…}
}
```

An item's `anchor` is its stand-ins' verb, or `mixed` when they differ.
`api` is the extract's own version, bumped when a rule or the shape changes,
and two extracts of different versions are not compared. Keys are sorted and
the JSON is indented by one, so one document gives one byte sequence.

## 9. The diff

`ffimap api diff BEFORE AFTER` takes two extracts, or two rustdoc JSON
documents it extracts first, and classifies every C item:

| status | when |
|---|---|
| `kept` | every record is identical |
| `extended` | only additions |
| `changed` | anything lost or rewritten |
| `removed` | the key is gone |
| `new` | the key first appears |

What counts as an addition and what as a change:

| addition (`extended`) | change (`changed`) |
|---|---|
| a stand-in or an associated item | a stand-in or an associated item lost, or its kind changed |
| a public path | a public path lost |
| a trait impl, auto traits included | a trait impl lost, auto traits included (`Send` becoming `!Send` is both) |
| an item or associated type in a trait impl | one lost, or an associated type retargeted |
| an inherent member no anchor claims | a member lost or rewritten |
| a provided trait item, or a required one made provided | a required trait item, or any trait item lost or rewritten |
| a field of a struct with private fields | a field of one without, or any field lost or retyped |
| a variant of a `#[non_exhaustive]` enum | a variant of an exhaustive enum, or any variant lost or rewritten |
| | a `decl` or `impl` header rewritten: a signature, an alias target, a constant's value |

An item whose anchor verb moved records it as `anchor: {before, after}`, and
`anchor_moves` counts the moves, so a wrap-to-port step reads `Wraps->Replaces`
whatever the status. A key gone and a key come with the same path, one of each,
are one C item whose anchor kind was relabelled: it is compared as one and
records `rekeyed` with its old key.

The JSON form, the default, holds `totals`, `anchor_moves`, `rekeyed`, every C
item's `status` with its `changes`, and `unattributed` with its own totals by
module. Each change names the record's locator, the `part` that moved (`decl`,
`impl`, `impl_item`, `member`, `path`, …), whether it was `added`, `removed`
or `changed`, its `severity` (`extended` or `changed`), and the values before
and after. `--format text` prints the items that are neither kept nor new,
with one line per change, then the totals.

`--items` restricts the C items to a list of keys, a batch's worklist, and
lists those found in neither document under `missing`. The unattributed
surface is reported whatever it holds, since no worklist names it.

## 10. What the measure cannot see

- **What no anchor reaches.** An unannotated type that no rule of section 5
  ties to an anchored one is attributed to its module, not to a C item.
- **Behaviour.** A signature that stays while what the function does changes
  reads as kept.
- **Renamed generics.** Generic parameter names are kept in declarations, so
  renaming `T` or a lifetime reads as changed, except in locators, where
  lifetimes are erased.
- **Another crate's re-exports.** A dependency that moves a definition behind
  an unchanged re-export renders differently, since this document has only the
  definition's path.
- **Semver nuance.** A change is anything lost or rewritten, whether or not a
  consumer could tell: a bound loosened, a where-clause reordered or an alias
  retargeted to an identical type all read as changed.
- **Trait-impl method signatures.** They are the trait's; a change to an
  unanchored, unattributed trait is reported under its module only.
- **Hidden items.** Rustdoc leaves `#[doc(hidden)]` items and private ones out
  of its JSON, so neither they nor anchors on them are seen.
