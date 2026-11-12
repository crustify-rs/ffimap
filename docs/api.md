# API stability per C item

`ffimap api` measures a promise a C-to-Rust migration makes to its Rust
consumers: once a C item has a safe Rust API, wrapping it, porting it and its
later stages leave that API alone. It reads the crate's rustdoc JSON, finds the
Rust items that stand in for each C item through their anchors, and records
their consumer-facing surface twice: raw, as the signatures stand, and as the
**contract** a consumer may rely on whatever form a handle or an owner takes.
Two such records, one at the item's first landing and one after a later
landing, say whether the contract was kept, extended or changed. This document is what the two documents hold and every
rule behind them. The scan's counters are [`schema.md`](schema.md)'s and have
nothing to do with it.

## 1. Input

```sh
cargo +nightly-2026-10-07 rustdoc -p CRATE --lib -- -Z unstable-options --output-format json
(cd ffibox && cargo +nightly-2026-10-07 rustdoc --lib -- -Z unstable-options \
    --output-format json --document-private-items)
ffimap api extract target/doc/CRATE.json --dep ffibox/target/doc/ffibox.json > before.json
```

`--dep` gives the rustdoc JSON of a crate the measured one depends on, and is
repeatable. The contracts of handles and owners that are aliases into ffibox
(`CBox`, `CArc`, `CVal`, …) need ffibox's, since the reborrows and trait impls
those forms inherit live there; it is made with `--document-private-items`
because the bounds rustdoc synthesises for ffibox's auto-trait impls name its
private fields' types. Without it those contracts are unresolved, as section 6
describes. The measure is pure Python over the JSON. It does not use the driver, so the
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

## 6. The contract view

A handle or an owner changes form over a migration: `FooRef` is a pointer
wrapper while `Foo` is wrapped and `&'a Foo` once it is ported, `FooBox` an
ffibox `CBox` and then a `Box`. A consumer relies only on what every form
offers, as `binding-types` states: their methods, their reborrows (`as_ref`,
`as_mut`) and the dereferences the native forms offer. The **contract** of a
type is that, and it, not the raw record, decides a C item's status.

Every C item has a `contract` view: one entry per stand-in or associated item.

- **A type** (`Foo`, `FooRef`, `FooMut`, `FooBox`, `FooArc`, `FooVal`, a
  policy type, an enum) has its contract under its locator:
  - `generics`: how many lifetimes, types and constants it takes;
  - `fields` (public ones), `shape` (only when a consumer can build it, no
    field hidden), `variants` and `non_exhaustive`;
  - `methods`: every method a consumer can call on it, by name, over every
    route: on the form itself, through its dereferences (`&self` methods
    through `Deref`, `&mut self` ones too through `DerefMut`) and on what its
    reborrows return. The route is not recorded, and the first found names a
    method;
  - `reborrows`: what `as_ref` and `as_mut` return. One returning the form's
    own type adds nothing and is left out;
  - `traits`: the traits it implements that a consumer can use, with their
    arguments;
  - `derefs`: targets reached through a dereference that the contract does
    not look inside (a slice, `str`, a primitive, a standard type), whose
    methods are the standard library's.
- **A method of a handle or owner** is keyed `method::<name>`, without its
  owner, since a port moves it from `FooRef` to `impl Foo`, and holds its
  normalised signatures.
- **Any other function** has its normalised signature; anything else its raw
  record.

Signatures in a contract are normalised so that each form reads the same: a
type equal to the target of one of the crate's public aliases is written as the
alias, so `&'a Foo` reads `FooRef<'_>` once `FooRef<'a> = &'a Foo`; lifetimes
are erased; `Self` is the type the method is called on; a projection such as
`<Foo as CCell>::Ref<'_>` is resolved through `Foo`'s impl; parameter names
are dropped; and a `self` receiver of a `Copy` type is `&self`.

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
given with `--dep`, answers from its impls in that crate's JSON: an impl
applies when its self type matches the form, and its bounds are checked
against the impl lists rustdoc records (which list the blanket impls that
apply), so `impl<T: Send, D: Send> Send for CBox<T, D>` holds for `CBox<Foo,
FooFree>` exactly when `Foo` and `FooFree` are `Send`. A standard pointer form
answers from a fixed model: `&T` and `&mut T` dereference to `T`, `Box<T>`
too, with `as_ref`/`as_mut`, `Arc<T>` and `Rc<T>` shared, `Pin<P>` as `P`,
and each implements `Clone`, `Copy`, `Send`, `Sync`, `Unpin`, `UnwindSafe`,
`RefUnwindSafe`, `Default`, `Debug`, `Display`, `PartialEq`, `Eq`,
`PartialOrd`, `Ord` and `Hash` under the standard library's conditions on
`T`; `NonNull` and `PhantomData` are modelled for the bounds they appear in.

**Unresolved.** A contract that needs what is not there -- a type of a crate
whose JSON was not given, a standard type the model does not cover, a bound
that cannot be decided, such as one on the free parameter of a generic alias
-- lists it under `unresolved`, and that entry is compared on its raw record
instead (section 10). `contract_missing_deps` names the crates whose JSON
would have resolved more.

## 7. The unattributed surface

A public item of the crate that is neither a stand-in nor associated is
**unattributed**. It is recorded by the Rust module of its canonical path,
under `unattributed`, with the same records, and compared the same way, so a
change to it is reported though no C item owns it.

## 8. Coverage

`coverage` counts how far the anchors reach. `public` counts the crate's
reachable items by role: free items by kind, `inherent_item` and
`trait_impl_item` for the items of a type's impls (blanket and synthesised
impls aside), `trait_item`, `variant` and `field`. `anchored` counts those that
carry an anchor. `c_items` and `c_items_by_kind` count the keys, `stand_ins`
the records, `associated` and `unattributed` the items those sections hold.

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

An item's `anchor` is its stand-ins' verb, or `mixed` when they differ.
`api` is the extract's own version, bumped when a rule or the shape changes,
and two extracts of different versions are not compared. Keys are sorted and
the JSON is indented by one, so one document gives one byte sequence.

## 10. The diff

`ffimap api diff BEFORE AFTER` takes two extracts, or two rustdoc JSON
documents it extracts first (with the same `--dep` and `--plumbing`), and
classifies every C item by its contract view:

| status | when |
|---|---|
| `kept` | every entry is identical |
| `extended` | only additions |
| `changed` | anything lost or rewritten |
| `removed` | the key is gone |
| `new` | the key first appears |

In the contract view an entry gained, a method, a reborrow, a trait, a
dereference target, a signature beside a method's others, a field of a type
with hidden fields or a variant of a `#[non_exhaustive]` enum is an addition;
an entry, a method, a reborrow, a trait or a signature lost or rewritten, a
generics count changed, and a field or variant gained where a consumer could
build or match every one, is a change. A type whose raw record moved while its
contract did not is a **retarget**: the item records `retarget` with the raw
declarations before and after, and stays kept. `raw_status` says when the raw
view would have classified the item otherwise.

`--raw` classifies by the raw records instead, and an unresolved contract entry
is compared on its raw record; the raw rules, where an addition and a change
are:

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

The JSON form, the default, holds the `view` that decided, `totals`,
`anchor_moves`, `rekeyed`, `retargeted`, `unresolved`, every C item's `status`
with its `changes`, `raw_status`, `retarget` and `unresolved`, and
`unattributed` with its own totals by module, always on raw records. Each
change names the entry's locator, the `part` that moved (`method`, `trait`,
`reborrow`, `decl`, `impl`, `member`, `path`, …), whether it was `added`,
`removed` or `changed`, its `severity` (`extended` or `changed`), the values
before and after, and `view: raw` when an unresolved entry was compared raw. `--format text` prints the items that are neither kept nor new,
with one line per change, then the totals.

`--items` restricts the C items to a list of keys, a batch's worklist, and
lists those found in neither document under `missing`. The unattributed
surface is reported whatever it holds, since no worklist names it.

## 11. What the measure cannot see

- **What no anchor reaches.** An unannotated type that no rule of section 5
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
  an unchanged re-export renders differently, since this document has only the
  definition's path.
- **Semver nuance.** A change is anything lost or rewritten, whether or not a
  consumer could tell: a bound loosened or a where-clause reordered reads as
  changed. A contract's impl bounds are checked against impl lists only, one
  impl at a time, with no inference beyond what rustdoc recorded.
- **Trait-impl method signatures.** They are the trait's; a change to an
  unanchored, unattributed trait is reported under its module only.
- **Hidden items.** Rustdoc leaves `#[doc(hidden)]` items and private ones out
  of its JSON, so neither they nor anchors on them are seen.
