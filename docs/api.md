# API stability per C item

`ffimap api` measures a promise that a C-to-Rust migration makes to its Rust
consumers: once a C item has a safe Rust API, wrapping the item, porting it
and the later stages of its migration leave that API alone. Wrapping an item
gives it a safe Rust view over the C code. Porting an item replaces the C code
with a native Rust translation.

`ffimap api` reads the crate's rustdoc JSON. It finds the Rust items that
stand in for each C item through their anchors: doc-comment lines of
crustify's convention, which
[section 2](#2-c-items-and-their-stand-ins) defines. It records the
consumer-facing surface of those items twice:

- raw, as the signatures stand; and
- as the **contract**: what a consumer may rely on, whatever form a handle or
  an owner takes. [Section 5](#5-handles-and-owners) describes handles and
  owners, and [section 6](#6-the-contract-view) describes the contract.

Two such records say whether the contract was kept, extended or changed: one
taken at the item's first landing, and one taken after a later landing, where
a landing is a change as it is merged into the crate.

This document describes what the two documents hold, the extract and the
diff, and every rule behind them. The counters of a scan are
[`schema.md`](schema.md)'s, and they are unrelated to `ffimap api`.

## 1. Input

```sh
cargo +nightly-2026-10-07 rustdoc -p CRATE --lib -- -Z unstable-options --output-format json
(cd ffibox && cargo +nightly-2026-10-07 rustdoc --lib -- -Z unstable-options \
    --output-format json --document-private-items)
ffimap api extract target/doc/CRATE.json --dep ffibox/target/doc/ffibox.json > before.json
```

`--dep` gives the rustdoc JSON of a crate that the measured crate depends on.
The option is repeatable.

The contracts of the handles and owners that are aliases into ffibox (`CBox`,
`CArc`, `CVal`, …) need ffibox's JSON, since the reborrows (`as_ref`, `as_mut`)
and the trait impls that those forms inherit live in ffibox. Make ffibox's JSON
with `--document-private-items`, because the bounds that rustdoc synthesises
for ffibox's auto-trait impls name the types of its private fields. Without
ffibox's JSON, those contracts are unresolved, as section 6 describes.

The measure is pure Python over the JSON. It does not use the rustc driver
that a scan runs through. So the crate need not build on the driver's nightly:
it only needs to document on a nightly whose JSON format `ffimap api` reads.

Rustdoc's JSON is unstable: each nightly writes a `format_version`, and the
shape moves with it. `ffimap api` reads **format 61**, which
nightly-2026-10-07 (the driver's pin) and nightly-2026-10-08 emit. It refuses
any other format with an error that names the version it found. To add support
for a new format, check the fields that `src/ffimap/rustdoc.py` reads against
it, and add it to `FORMAT_VERSIONS`.

## 2. C items and their stand-ins

A C item is keyed by its anchor's `<kind>::<path>`: `fn::git_mailmap_new`,
`st::git_mailmap`, `fld::git_buf.ptr`.

An **anchor** is a doc-comment line of its own that reads exactly
``Wraps `<kind>::<path>` `` or ``Replaces `<kind>::<path>` ``. In crustify's
convention, an item's anchor reads `Wraps` while the item wraps the C item,
and `Replaces` once the item is its native Rust translation.
The path is names separated by dots, and a `fld` path names a member. An item
that carries an anchor is **anchored**.

Every public item of the crate that carries an anchor is a **stand-in** of
that anchor's C item. An item that carries several anchors, such as the
accessor of two members, is a stand-in of each of their C items.

The extract reports the following about the anchors themselves, under
`anchors`:

- `malformed`: the lines that try to be an anchor and are not one. Such a line
  has the verb and a `kind::` path, but it sits inside a sentence, has a
  trailing period, lacks the backticks, or has a path that is not names. A
  malformed line keys nothing.
- `unknown_kinds`: the anchors whose kind is not one of the convention's
  (`fn`, `st`, `un`, `enm`, `fnp`, `tdf`, `fld`, `glb`, `mac`), counted by
  kind. They are keyed as written.
- `without_alias`: the anchors on an item that has no `#[doc(alias)]` naming
  the anchor's path. An item whose own name is the anchor's path is left out,
  for two reasons: rustdoc rejects an alias equal to its item's name, and the
  name already answers a search for it.

## 3. Locators and paths

Each stand-in is named by a **locator**. The diff matches one landing's record
with the next landing's record by locator:

| item | locator |
|---|---|
| a free item | its canonical path |
| an item of an inherent impl | `Ty::name` |
| an item of a trait impl | `<Ty as Trait<Args>>::name` |
| a trait's item, a variant, a field | its owner's locator `::name` |

Lifetime names in a locator are erased to `'_`.

A **canonical path** is the path that a consumer names an item by:

- **An item of the crate.** When the path that rustdoc's `paths` table gives
  the item's definition is public, the canonical path is that path. Otherwise
  it is the shortest public path the item is re-exported at, and among equally
  short paths, the first in order. So an item that is defined in a private
  module and re-exported from the module's parent is named by the parent's
  path, and a port that moves the definition into the parent changes nothing.
- **An item of another crate.** The canonical path is its definition's path
  in the `paths` table, `ffibox::refs::CBox` for instance, because the
  measured crate's rustdoc JSON does not record that crate's re-exports.

Every type in a signature is rendered by its canonical path, never by what the
source wrote. So an import or a reordering of the source gives the same bytes.

A record's `paths` lists every public path the item is reached by, from the
crate root through public modules and `pub use`, globs included. An item that
has an owner (an item of an impl or of a trait, a variant, a field) has its
owner's paths with its name appended.

## 4. Signatures

Each stand-in's `sig` is normalised text. What it holds depends on the item's
kind:

- **functions and methods**: `decl` holds `const`, `async`, `unsafe`, the ABI,
  the generics, the receiver (`self`, `&self`, `&'a mut self`,
  `self: Box<Self>`), the parameter types, the return type and the
  where-clauses. Parameter names are left out. A method also has `impl`: the
  header of the impl it is declared in, generics and trait included. A trait's
  method has `default`, which says whether the method has a body.
- **structs, enums and unions**:
  - `decl` holds the generics, the shape (`;`, `(n)`, `{}`) and
    `#[non_exhaustive]`.
  - `fields` maps each public field to its type, and `variants` maps each
    variant to its shape and discriminant.
  - `stripped` says whether rustdoc hid private fields or variants.
  - `impls` maps the header of every trait impl that rustdoc records for the
    type to the impl's items and to its associated types and constants. The
    items are those the impl defines and the trait's provided ones that it
    inherits. The auto-trait impls that rustdoc synthesises (`Send`, `Sync`,
    `Unpin`, `UnwindSafe`, `RefUnwindSafe`, and `Freeze` and `UnsafeUnpin`
    where the nightly records them) are included, negative ones as `!Send`.
    Blanket impls are not included, since they follow from the type's other
    impls.
  - `members` holds the items of the type's inherent impls that stand in for
    no C item, each with its impl header.
- **traits**: `decl` holds the generics, the supertraits and `unsafe`.
  `required` and `provided` hold the trait's items, each with its declaration.
  `dyn_compatible` says whether the trait is dyn-compatible.
- **type aliases**: `decl` holds the whole target, `type = ffibox::refs::CBox<…>`.
- **constants and statics**: their type and value.
- **associated constants and types**: their declaration and, in an impl, the
  impl's header.
- **variants** and **fields**: their shape or type.
- **`macro_rules!` macros**: only the kind, since a macro's body is not an
  interface.

A trait impl's methods are recorded by name only. Their signatures are the
trait's, and those are recorded where the trait is.

## 5. Handles and owners

A consumer reaches a C type through `FooRef`, `FooMut`, `FooBox`, `FooArc`,
`FooVal` and a policy type such as `FooFree`. These types
are not always anchored. An unanchored public struct, enum, union or trait of
the crate is **associated** with C items by rule 1, or else by rule 2. An
unanchored public type alias is associated by rule 3. The record's `via` says
which rule tied the item:

1. `assoc_type`: a trait impl of the type sets an associated type to an
   anchored type, or a trait impl of an anchored type sets an associated type
   to the type.
   `impl CRefSeam for MailmapRef { type Cell = Mailmap; }` and
   `impl CCell for Mailmap { type Ref<'a> = MailmapRef<'a>; }` both tie
   `MailmapRef` to `st::git_mailmap`.
2. `owner`: the type's impls, or the trait's declaration, hold stand-ins. The
   type or trait is associated with the C items of those stand-ins. A policy
   type whose `CDrop::c_drop` wraps `fn::git_mailmap_free` goes with that
   item.
3. `alias`: a type alias whose target names an anchored type goes with that
   type's C items. The anchored type is found by id, anywhere in the target:
   `MailmapBox = CBox<Mailmap, MailmapFree>` goes with `st::git_mailmap`. An
   alias whose target names no anchored type goes with the C items of the
   types it names that rules 1 and 2 associated.

An associated item is recorded under each of its C items, with the record a
stand-in has. A C item's surface is its stand-ins and its associated items
together.

## 6. The contract view

A handle or an owner changes form over a migration:

- `FooRef` is a pointer wrapper while `Foo` is wrapped, and `&'a Foo` once
  `Foo` is ported.
- `FooBox` is an ffibox `CBox`, and then a `Box`.

A consumer relies only on what every form offers, as crustify's
`binding-types` skill states: the forms' methods, their reborrows (`as_ref`,
`as_mut`) and the dereferences that the native forms offer. That is the
**contract** of a type. The contract, not the raw record, decides a C item's
status.

Every C item has a `contract` view, with one entry per stand-in or associated
item.

- **A type** (`Foo`, `FooRef`, `FooMut`, `FooBox`, `FooArc`, `FooVal`, a
  policy type, an enum) has its contract under its locator:
  - `generics`: how many lifetimes, types and constants it takes;
  - `fields` (public ones), `shape` (only when a consumer can build it, no
    field hidden), `variants` and `non_exhaustive`;
  - `methods`: every method a consumer can call on it, by name, over every
    route: on the form itself, through its dereferences (`&self` methods
    through `Deref`, `&mut self` ones too through `DerefMut`) and on what its
    reborrows return. The route is not recorded. When several routes reach a
    method of one name, the first route found gives the entry;
  - `reborrows`: what `as_ref` and `as_mut` return. A reborrow that returns
    the form's own type adds nothing and is left out;
  - `traits`: the traits it implements that a consumer can use, with their
    arguments;
  - `derefs`: the targets reached through a dereference that the contract
    does not look inside (a slice, `str`, a primitive, a standard type). The
    methods of such a target are the standard library's.
- **A method of a handle or owner** is keyed `method::<name>`, without its
  owner, since a port moves it from `FooRef` to `impl Foo`. The entry holds
  the method's normalised signatures.
- **Any other function** has its normalised signature. Anything else has its
  raw record.

Signatures in a contract are normalised so that each form reads the same:

- A type equal to the target of one of the crate's public aliases is written
  as the alias. So `&'a Foo` reads `FooRef<'_>` once `FooRef<'a> = &'a Foo`.
- Lifetimes are erased.
- `Self` is the type the method is called on.
- A projection such as `<Foo as CCell>::Ref<'_>` is resolved through `Foo`'s
  impl.
- Parameter names are dropped.
- A `self` receiver of a `Copy` type is `&self`.

**What is no part of a contract:**

| left out | why |
|---|---|
| functions without a `self` receiver | reached through a type path, which a change of form changes |
| the seams `as_ptr`, `as_mut_ptr`, `as_void_ptr`, `from_ptr`, `from_void_ptr`, `from_raw_parts`, `into_raw_parts`, `from_c`, `into_c`, `as_c_ptr`, `from_raw`, `as_object` | the conversion between a wrapper and its raw form, ffimap's seam list |
| a method with a raw pointer or `NonNull` in its signature | raw access |
| `unsafe` methods | they exist because a form wraps C; an anchored one is its own C item's |
| anchored methods | each is its own C item's stand-in, compared there |
| every method of a plumbing crate's type (`--plumbing`, ffibox by default) but `as_ref` and `as_mut` | what one form offers beyond the native ones, such as `try_clone` or `policy` |
| the traits of a plumbing crate (`CCell`, `CDrop`, `CRefSeam`, …) | plumbing |
| `Drop`, `StructuralPartialEq`, `Freeze`, `UnsafeUnpin` | no consumer can use them |
| `Pointer` | it formats the address: raw access |
| `Deref`, `DerefMut`, `AsRef`, `AsMut`, `Borrow`, `BorrowMut` | recorded as dereferences and reborrows, and through the methods they reach |
| blanket impls | they follow from the others |

**Where a form's surface comes from.** A type of the crate, or of a crate
given with `--dep`, answers from its impls in that crate's JSON. An impl
applies when its self type matches the form. The impl's bounds are checked
against the impl lists that rustdoc records, which list the blanket impls
that apply. So `impl<T: Send, D: Send> Send for CBox<T, D>` holds for
`CBox<Foo, FooFree>` exactly when `Foo` and `FooFree` are `Send`.

A standard pointer form answers from a fixed model:

- `&T` and `&mut T` dereference to `T`.
- `Box<T>` dereferences to `T` too, and has `as_ref`/`as_mut`.
- `Arc<T>` and `Rc<T>` dereference to `T` for shared access only, and have
  `as_ref`.
- `Pin<P>` answers as `P`.
- Each of these forms implements `Clone`, `Copy`, `Send`, `Sync`, `Unpin`,
  `UnwindSafe`, `RefUnwindSafe`, `Default`, `Debug`, `Display`, `PartialEq`,
  `Eq`, `PartialOrd`, `Ord` and `Hash` under the standard library's
  conditions on `T`.
- `NonNull` and `PhantomData` are modelled for the bounds they appear in.

**Unresolved.** A contract can need something that is not there:

- a type of a crate whose JSON was not given;
- a standard type that the model does not cover; or
- a bound that cannot be decided, such as a bound on the free parameter of a
  generic alias.

The contract lists each such thing under `unresolved`, and that entry is
compared on its raw record instead (section 10). `contract_missing_deps`
names the crates whose JSON would have resolved more.

## 7. The unattributed surface

A public item of the crate that is neither a stand-in nor associated is
**unattributed**. It is recorded under `unattributed`, by the Rust module of
its canonical path, with the same records. It is compared the same way, so a
change to it is reported though no C item owns it.

## 8. Coverage

`coverage` counts how far the anchors reach:

- `public` counts the crate's reachable items by role: free items by kind,
  `inherent_item` and `trait_impl_item` for the items of a type's impls
  (blanket and synthesised impls aside), `trait_item`, `variant` and `field`.
- `anchored` counts those items that carry an anchor.
- `c_items` and `c_items_by_kind` count the keys.
- `stand_ins` counts the records.
- `associated` and `unattributed` count the items that those sections hold.

## 9. The extract

```json
{
 "api": 2,
 "source": {"crate": "libgit2", "crate_version": "0.1.0", "format_version": 61,
            "deps": ["ffibox"], "plumbing": ["ffibox"]},
 "items": {
  "st::git_mailmap": {
   "anchor": "Wraps",
   "stand_ins": {"libgit2::…::Mailmap": {"anchor": "Wraps", "kind": "struct",
                                         "paths": ["libgit2::…::Mailmap"], "sig": {…}}},
   "associated": {"libgit2::…::MailmapBox": {"kind": "type_alias", "via": ["alias"],
                                             "paths": […], "sig": {…}}},
   "contract": {"libgit2::…::MailmapBox": {"kind": "type", "generics": {…},
                                           "methods": {…}, "reborrows": {…},
                                           "traits": […]}, …}
  }
 },
 "contract_missing_deps": [],
 "unattributed": {"libgit2::…::odb": {"libgit2::…::OdbDataStrVec": {…}}},
 "anchors": {"malformed": [], "unknown_kinds": {}, "without_alias": []},
 "coverage": {…}
}
```

An item's `anchor` is the verb of its stand-ins, or `mixed` when their verbs
differ. `api` is the extract's own version. It is bumped when a rule or the
shape changes, and two extracts of different versions are not compared. Keys
are sorted and the JSON is indented by one, so one document gives one byte
sequence.

## 10. The diff

`ffimap api diff BEFORE AFTER` compares two extracts. You can give it two
rustdoc JSON documents instead, and it extracts them first. For that
extraction it accepts the same `--dep` and `--plumbing` options as
`ffimap api extract`, and it applies them to both documents. The command
classifies every C item by its contract view:

| status | when |
|---|---|
| `kept` | every entry is identical |
| `extended` | only additions |
| `changed` | anything lost or rewritten |
| `removed` | the key is gone |
| `new` | the key first appears |

In the contract view, each of these is an addition:

- an entry gained;
- a method, a reborrow, a trait or a dereference target gained;
- a signature gained beside a method's others;
- a field gained by a type with hidden fields; and
- a variant gained by a `#[non_exhaustive]` enum.

Each of these is a change:

- an entry, a method, a reborrow, a trait or a signature lost or rewritten;
- a generics count changed; and
- a field or a variant gained where a consumer could build or match every
  one.

A type whose raw record moved while its contract did not is a **retarget**:
the item records `retarget` with the raw declarations before and after, and
stays kept. When the raw view would have classified the item otherwise,
`raw_status` says how.

`--raw` classifies by the raw records instead. Without `--raw`, an unresolved
contract entry is also compared on its raw record. The raw rules say what is
an addition and what is a change:

| addition (`extended`) | change (`changed`) |
|---|---|
| a stand-in or an associated item gained | a stand-in or an associated item lost, or its kind changed |
| a public path gained | a public path lost |
| a trait impl gained, auto traits included | a trait impl lost, auto traits included (`Send` becoming `!Send` is both) |
| an item or associated type gained in a trait impl | one lost, or an associated type retargeted |
| an inherent member gained that no anchor claims | a member lost or rewritten |
| a provided trait item gained, or a required one made provided | a required trait item gained, or any trait item lost or rewritten |
| a field gained by a struct with private fields | a field gained by a struct without private fields, or any field lost or retyped |
| a variant gained by a `#[non_exhaustive]` enum | a variant gained by an exhaustive enum, or any variant lost or rewritten |
| | a `decl` or `impl` header rewritten: a signature, an alias target, a constant's value |

An item whose anchor verb moved records the move as `anchor: {before, after}`,
and `anchor_moves` counts the moves. So a wrap-to-port step reads
`Wraps->Replaces` whatever the status.

A key that is gone and a key that has come, with the same path and one of
each, are one C item whose anchor kind was relabelled. The diff compares it as
one item, and the item records `rekeyed` with its old key.

The JSON form is the default. It holds:

- the `view` that decided;
- `totals`, `anchor_moves`, `rekeyed`, `retargeted` and `unresolved`;
- every C item's `status` with its `changes`, `raw_status`, `retarget` and
  `unresolved`; and
- `unattributed` with its own totals by module, always on raw records.

Each change names:

- the entry's locator;
- the `part` that moved (`method`, `trait`, `reborrow`, `decl`, `impl`,
  `member`, `path`, …);
- whether it was `added`, `removed` or `changed`;
- its `severity` (`extended` or `changed`);
- the values before and after; and
- `view: raw` when an unresolved entry was compared raw.

`--format text` prints the items that are neither kept nor new, with one line
per change, then the totals.

`--items` restricts the C items to a list of keys, such as a worklist: the C
items that one batch of the migration's work covers. The diff lists the keys
found in neither document under `missing`. The unattributed surface is
reported whatever the list holds, since no worklist names it.

## 11. What the measure cannot see

- **What no anchor reaches.** An unanchored type that no rule of section 5
  ties to an anchored one is attributed to its module, not to a C item.
- **The route to a method.** A contract flattens methods over dereferences
  and reborrows, so a method callable directly on one form and only through
  `as_ref()` on another reads the same.
- **Lifetimes in contracts.** They are erased, so a getter returning a borrow
  of the handle and one returning a borrow of its target read the same.
- **Standard types beyond the model.** A form that is an `Option`, a `Vec` or
  any standard type other than the pointer forms is unresolved, and so is a
  bound on a generic alias's free parameter.
- **Behaviour.** A signature that stays while what the function does changes
  reads as kept.
- **Renamed generics.** Generic parameter names are kept in declarations, so
  renaming `T` or a lifetime reads as changed, except in locators, where
  lifetimes are erased.
- **Another crate's re-exports.** A dependency that moves a definition behind
  an unchanged re-export renders differently, since the measured crate's
  rustdoc JSON has only the definition's path.
- **Semver nuance.** A change is anything lost or rewritten, whether or not a
  consumer could tell: a bound loosened or a where-clause reordered reads as
  changed. A contract's impl bounds are checked against impl lists only, one
  impl at a time, with no inference beyond what rustdoc recorded.
- **Trait-impl method signatures.** They are the trait's; a change to an
  unanchored, unattributed trait is reported under its module only.
- **Hidden items.** Rustdoc leaves `#[doc(hidden)]` items and private ones out
  of its JSON, so neither they nor anchors on them are seen.
