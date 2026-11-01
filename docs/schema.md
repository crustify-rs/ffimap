# Counter schema

The counters ffimap reports, what each one counts, and how it is decided. Every
counter is determined from declarations and single expression nodes: no value is
followed, no cast chain is composed, and no dataflow is performed.

How a scan runs and what it requires is [`scanning.md`](scanning.md); the
`--ffibox` arms and the conventions they read are [`ffibox.md`](ffibox.md).

## 1. The tree

```
raw_ptr.
  taken.{safe,unsafe}.{pub,priv}
  taken.of_which.{seam,void}.{safe,unsafe}.{pub,priv}
  returned.{safe,unsafe}.{pub,priv}
  returned.of_which.{seam,void}.{safe,unsafe}.{pub,priv}
  in_impl.{safe,unsafe}.{pub,priv}
  in_impl.of_which.{seam,void}.{safe,unsafe}.{pub,priv}
  field.{pub,priv}
  field.of_which.void.{pub,priv}
  total.{safe,unsafe}.{pub,priv}
  deref.{rd,wr}
  casted_to.{std,ffibox,local_seam}.{borrow,slice,string,owner,other}

ty.
  storing_raw_ptr.{pub,priv}
  storing_raw_ptr.of_which.{pub,priv}
    impl_drop · impl_clone · has_lifetime
    impl_deref · impl_deref_mut · impl_send_sync
    ffibox                                           --ffibox
    pub_field · none
  field.ffibox.<primitive>.{pub,priv}                --ffibox
  ffibox.ccell.{pub,priv}                            --ffibox
  ffibox.ccell.of_which.no_seam_trait.{pub,priv}     --ffibox

  impl_block.{pub,priv}
  impl_block.of_which.other.{pub,priv}
  impl_block.of_which.ffibox.{layout,ref,mut,locked}.{pub,priv}   --ffibox

  impl_trait.{pub,priv}
  impl_trait.of_which.unsafe
  impl_trait.of_which.derived.{pub,priv}
  impl_trait.of_which.{std,local}.{pub,priv}
  impl_trait.of_which.ffibox.{pub,priv}              --ffibox
  impl_trait.of_which.ffibox.of_which.<trait>.{handwritten,macro}  --ffibox
  impl_trait.of_which.send_sync.{send,sync}.{pub,priv}

  generic.{pub,priv}
  generic.of_which.{lifetime,type}.{pub,priv}
  generic.of_which.storing_raw_ptr.{pub,priv}

  wrapping_unsafe_cell.{pub,priv}
  total.{pub,priv}
  total.of_which.{std_trait,local_trait,no_trait}.{pub,priv}
  total.of_which.ffibox_trait.{pub,priv}             --ffibox

fn.
  safe.{pub,priv}
  safe.of_which.with_unsafe.{pub,priv}
  unsafe.{pub,priv}
  ffibox.{taken,returned}.<primitive>.{pub,priv}     --ffibox
  total.{pub,priv}
  total.of_which.macro.{pub,priv}

code.
  loc.{total,unsafe}
  tests.loc.{total,unsafe}
  tests.{fn,unsafe_block}
  unsafe_block.total
  unsafe_block.of_which.ffi_export
  unsafe_call.{ffi,intrinsic,rust}
```

The counters are the whole of the document's `counts`. There is no second,
flat counter block beside them, and no prose rendering of them: a reader who
wants a rate divides the leaves it names.

`raw_ptr.total` is the denominator, emitted rather than derived: the positions
the crate CHOSE, by safety and visibility. `taken` and `returned` are in it,
`in_impl` is not -- for the reason that family exists, since a reader comparing
crates would otherwise be reading how often a trait is implemented -- and a
`field` counts on the `safe` arm, because reading a field that holds a pointer
takes no `unsafe`, so a public one on a public type is a pointer the interface
hands over without asking for any. `deref` and `casted_to` are body sites, not
positions, and are outside it.

`raw_ptr.total.safe.pub` is therefore the raw pointers a consumer meets
without writing `unsafe`: 5 on libgit2-bindings and 5 on git2-rs. It is not a
sum of the families beside it, the same way `ty.total` is not a sum of its
shares.

A `*c_void` is a raw pointer whose pointee is erased, so it is the `void`
share of the position it sits in, not a family beside it: a reader asking how
many raw pointers a signature carries does not have to add two trees, and one
asking how many are typed subtracts the share. The former top-level
`void_ptr.*` is gone.

`raw_ptr.in_impl` holds the positions in a trait impl's method, both
directions in one counter. The crate did not choose the position there: the
trait fixed the signature, one declaration dictating a position in every impl
of it, and no consumer of the safe API is routed to it -- ffibox's
`CDrop::c_drop(NonNull<T>)` is the strategy that exists so a consumer never
holds a pointer. Mixing them into `taken` or `returned` makes the hazard count
move with how many types a trait is implemented for, which is what read 61 of
git2-rs' 66 pointers "returned by a public safe fn": its `Binding` trait,
once. The direction is dropped with the choice: what is left to say is that
the trait's shape reaches a pointer here.

`ty.impl_block` counts an inherent `impl T` and `ty.impl_trait` an
`impl Tr for T`, which `ty.impl` used to merge. The split is the one the
counters were already asking either side of: a trait impl satisfies someone
else's shape, an inherent block is the API the crate wrote for its own type.
Under `--ffibox` an inherent block is also split by the self type's role in
the convention, since those are different surfaces: the layout type carries
the constructors, its shared handle the getters, its exclusive handle the
setters. On libgit2-bindings: 408 blocks, 100 on layout types, 86 on shared
handles, 103 on exclusive ones, 119 on everything else -- the handles
outnumbering the layout types, which is what a convention routing every field
access through them implies.

`ty.ffibox.ccell` is the layout types, and `of_which.no_seam_trait` those whose
handles implement neither `CRefSeam` nor `CMutSeam`. Those handles sit outside
the generic seam -- `from_ptr`, `from_void_ptr`, `as_ptr`, `as_void_ptr` on the
handle type -- so code generic over a handle has to special-case them. On
libgit2-bindings it reads 32 of 65, exactly the hand-written `CCell` impls: the
macro writes both seams and a hand-written cell gets neither. The trait does
not forbid it -- `impl<'a, 'r: 'a> CRefSeam<'a> for FooRef<'a, 'r>` with
`type Cell = Foo<'r>` compiles -- so it is an omission, not a limit.

The role is read from `CCell`'s own `Ref<'a>` and `Mut<'a>` associated types,
not from the seam trait a type implements. `define_ctype!` generates
`CRefSeam` and `CMutSeam` only for a cell with no parameters of its own; a
lifetime-carrying cell such as `Blob<'r>` hand-writes `CCell` and no seam at
all, so reading the seams missed every hand-written cell's handles -- 49 `*Ref`
and 40 `*Mut` blocks, which landed under `other`. The associated types name
the handles whatever wrote the impl.

`ty.impl_trait.of_which.{std,local,ffibox}` is whose trait it is. A local one
is a shape the crate chose; a std or framework one it adopted. On
libgit2-bindings 1765 std, 193 ffibox, 2 local; on git2-rs 1704 std and 115
local, the latter mostly its own `Binding`.

The `std` arm is that large because of `#[derive]`, not because the crates
implement std by hand: `of_which.derived` is 1171 of libgit2-bindings' 1960
trait impls and 630 of git2-rs' 1863, so the hand-written std impls are 594
and 1074. Without that share a reader comparing vocabularies is reading how
many derives each crate spells. It is the counterpart of
`fn.total.of_which.macro`, and the reason `of_which.unsafe` has always skipped
`TrivialClone`.

Every sub-classification of the same impls sits under `of_which`, nested where
it refines another share: `of_which.ffibox.of_which.<trait>` is the ffibox
impls by trait. That is not cosmetic. `ty.impl` used to carry an emitted
`total`, which protected it; splitting it into `{pub,priv}` let `nest_ptr`
derive the total from every child, and the two sub-classifications beside it
pushed `impl_trait.total` to 2297 against the 1960 impls there are. It is 1960
now, and `impl_block` 408 + `impl_trait` 1960 = 2368, the old merged figure.

`ty.total.of_which.{std_trait,local_trait,ffibox_trait,no_trait}` asks the
same of TYPES rather than impls, and is the denominator the
`ty.storing_raw_ptr` shares lacked: that family says 29 of the pointer
holders implement a std trait, and this says 317 types do. Shares, not a
partition -- a type may implement std's `Drop`, ffibox's `CDrop` and one of
the crate's own traits -- with `no_trait` the residual.

The cross-tabulation is recorded once, in `ty.storing_raw_ptr.of_which`, which
is the finer direction: it separates `impl_drop` from `impl_clone` from
`impl_send_sync`, which a single `std` arm would collapse.

`ty.generic` is the types carrying a generic parameter, by kind. A lifetime
ties the type to something it borrows; a type parameter makes it a family
rather than one layout, so each instantiation is a separate question about C's
bytes. A type may carry both, so these are shares. On libgit2-bindings 199 of
374 are generic, 195 over a lifetime and 5 over a type, and 23 of them hold a
raw pointer.

`raw_ptr.field.pub` is one reachability question -- can a consumer of
the crate touch the field -- so it is the type being exported AND the field
being exported, rather than two levels a reader has to combine.

`fn.total` and `code.unsafe_call` totals are derived from their partitions.

`code.tests` is the test code, and every other counter is the library without
it. `cargo build` enables no `cfg(test)` and builds nothing under `tests/`, so
the test code was invisible rather than excluded by a rule -- on
libgit2-bindings 92693 lines against the library's 16081, and 4909 fns against
2755. The scan runs `cargo check --all-targets` and the driver tells a test target
apart by the `--test` cargo passes it, reporting it under `code.tests` so that
no library counter moves. `check` rather than `build`: the driver reports from
`after_analysis`, so HIR and typeck are all it needs, and `--emit=metadata`
does not link -- a test binary links the C library, and declarations with no
implementation at all would make the scan fail where it used to succeed.

The exclusion is two mechanisms, not one rule. In the library build `cfg(test)`
is off, so rustc strips those items during expansion and they never reach HIR:
there is nothing to traverse. In the `--test` build they are there and the
driver does walk them -- along with the whole library, which a lib test target
recompiles -- but only `code.tests.*` is emitted and the library-shaped
counters are computed and discarded. So a test's own types, signatures and
conversions are nowhere: a type that holds a raw pointer inside
`#[cfg(test)]` is in no `ty` population, and its unsafe blocks and FFI calls
are in no `code` total.

Only the quantities that mean the same thing for a test as for a library are
there: its size, its fns and its unsafe. The rest of the tree asks what a
crate's API hands its consumers, which a test harness has none of.

A lib's test target recompiles the library with `cfg(test)` on, so its figures
include the library's; they are subtracted, keyed on the crate name it shares
with the non-test emission. An integration test crate shares its name with no
library, so nothing is subtracted from it, and a build script is skipped --
under `--all-targets` it is its own crate, and it builds the crate rather than
being part of it. `code.tests.fn` carries one generated harness `main` per test
binary.

`fn.*` counts every function the crate defines, the methods of its trait impls
included. A method implementing another crate's trait is still this crate's
code: that crate fixed the signature's shape, not what the body does, and
`impl Drop for Foo { fn drop }` is where a wrapper's unsafe free lives -- the
one case `fn.safe.of_which.with_unsafe` exists for. A foreign *declaration*,
an item in an `extern` block, is excluded by having no body to walk.

Counting them makes the family sensitive to boilerplate a macro wrote:
`#[derive]`, `bitflags!`, ffibox's `define_ctype!`. On libgit2-bindings that is
802 of 2755 and on git2-rs 2350 of 3977, most of the latter from `bitflags!`.
It is counted anyway -- what a macro emitted is compiled into the crate and
runs like a hand-written method, the grounds `code.unsafe_block` already
stands on -- and `fn.total.of_which.macro` carries the share, so a reader
after the hand-written total subtracts it.

### 1.1 Vocabularies

The `<trait>` and `<primitive>` arms are generated from ffibox's vocabulary,
which [`ffibox.md`](ffibox.md) lists. They are present only under `--ffibox`,
absent rather than zero without it.

### 1.2 Partitions and shares

A `partition` node's children are disjoint and sum to it; an `of_which` node's
children are subsets that overlap and are never summed. `nest_ptr` derives
every partition `total` bottom-up and skips `of_which` when summing, so no sum
is written by the driver and none can disagree with its parts.

`ty.storing_raw_ptr.of_which` is a share family, not a partition: a type may
implement both `Drop` and `Clone`. `none` is the residual, the types matching
no declaration share.

The first six shares read std traits, so a crate that declares its lifecycle
through a framework instead -- ffibox's `CDrop`, `CDispose`, `CDupClone` --
said something none of them can see. `ffibox` is that statement, counted
beside them, so the residual means what it says: on libgit2-bindings `none`
read 12 of 41 while 8 of those 12 were `define_ctype!` layout newtypes whose
release and clone sit on ffibox traits and whose lifetimes sit on their
handles. It reads 4 now, against git2-rs' 15 of 97, which is the direction
every other share points. `no_ffibox_trait` is gone with it: it was the exact
complement of this share, 13 against 28 of 41.

`pub_field` is not a declaration and does not rescue a type from the residual
-- it is the opposite, an access the type does not govern.

An `of_which` node therefore carries no `total` of its own -- summing two
shares is not a quantity -- while each share keeps the total of its own
`{pub,priv}` partition.

## 2. The peel set

A type stores a raw pointer when the walk over its fields reaches one. The walk
descends through types defined in the scanned crate and in the `-sys` crates
named on the command line, and stops at every other crate, the standard library
included.

The rule is deliberately narrow, and it decides what the counter means. A
pointer inside `Vec` is the standard library's to manage, not the crate's. A
pointer inside an ffibox owner is ffibox's, so a type holding a `CBox` is not a
`ty.storing_raw_ptr` -- it appears under `ty.field.ffibox` instead. The
population is therefore the types that manage a pointer themselves, and
delegation is counted separately rather than silently folded in.

The set is named, by `--sys-crates`, and never discovered. A Cargo `links`
key and a `*-sys` name both over-report: `prettyplease` sets `links` to detect
duplicate versions of itself, and bindgen's `clang_sys` matches the name, yet
neither is any part of the scanned crate's C surface. Discovery put both in the
peel set of libgit2-bindings and had their `#[repr(C)]` types taken for C's,
which contradicts a rule whose whole value is being narrow.

A `-sys` crate left unnamed therefore drops its types out of the walk, and the
counter reads low for a reason that is not in the code. The document's
`sys_crates` field records the set it ran with, so the omission is readable
beside the figures it explains.

## 3. Calls

### 3.1 Classifying a call

The callee's signature is read from the type of the callee expression, which
carries an ABI and a safety whether or not the callee resolves to an item:

```rust
match typeck.expr_ty_adjusted(callee).kind() {
    ty::FnDef(did, args) => { /* tcx.fn_sig(did).instantiate(..) */ }
    ty::FnPtr(_, hdr)    => { /* hdr.abi(), hdr.safety */ }
    _ => None,                       // Fn-trait call, not a direct call
}
```

A `MethodCall` has no callee expression; its `DefId` comes from
`typeck.type_dependent_def_id` and takes the `FnDef` path.

`is_foreign_item` is not used. It is a property of the declaration site, while
the ABI is part of the function's type and so survives being stored in a field
or passed as an argument. That is what admits calls through function pointers,
which have no item to ask -- invoking a stored `extern "C"` callback among them.

### 3.2 `code.unsafe_call`

Safety decides whether a call counts, ABI decides which arm it lands in.

| signature | arm |
|---|---|
| `safety == Safe` | not counted |
| `tcx.intrinsic(did).is_some()` | `intrinsic` |
| `abi != Rust` | `ffi` |
| otherwise | `rust` |

Safety gates membership because an `extern "C" fn` *defined in Rust* is safe to
call: a port campaign's `ffi_export` gateways have a C ABI but cross no boundary
and discharge no obligation. Foreign declarations keep their `Unsafe` safety, so
the real crossings still land in `ffi`.

Intrinsics are tested with `tcx.intrinsic`, not by ABI: current rustc marks them
`#[rustc_intrinsic]` with the Rust ABI, so an ABI test would file `transmute`
under `rust`.

## 4. `raw_ptr.casted_to`

Two axes: whose vocabulary the conversion belongs to, and what shape the pointer
became. Conversions are recognised by name, never inferred from types, because
a type rule cannot show that the output derives from the pointer input.

| arm | names from | shape from |
|---|---|---|
| `std` | the (krate, type, method) table below | the table |
| `ffibox` | `<primitive>` x the adoption methods | the primitive's group |
| `local_seam` | `--seams` / `UM_SEAM_FNS` | the seam's return type |

A declared seam needs no derivation proof: the declaration states the function
is a conversion, and only its shape is read from the return type.

### 4.1 The std table

```
borrow   <*const T>::as_ref   <*mut T>::as_mut   NonNull::as_ref   NonNull::as_mut
slice    slice::from_raw_parts    slice::from_raw_parts_mut
         slice::from_ptr_range    slice::from_mut_ptr_range
string   CStr::from_ptr   CString::from_raw   String::from_raw_parts
owner    Box::from_raw   Vec::from_raw_parts   Rc::from_raw   Arc::from_raw
```

Matching is on (crate, type, method), gated on `did.krate` being `core`,
`alloc` or `std`, so a custom `Box::from_raw` cannot collide.

`CString` and `String` are `string` rather than `owner`: the bucket records what
shape the pointer became, and the C-string boundary is the distinction worth
keeping.

Two syntactic forms carry no call and are counted as `std.borrow`:

```
AddrOf(Ref, Not, Unary(Deref, p))    where p is a raw pointer
AddrOf(Ref, Mut, Unary(Deref, p))
```

### 4.2 The ffibox table

Derived from ffibox's adoption methods crossed with its primitives, as
[`ffibox.md`](ffibox.md) describes.

### 4.3 `other`

For `local_seam` it holds a seam returning a bespoke handle. For `std` and
`ffibox` it is structurally zero, every name in those tables mapping to a known
shape, so a nonzero reading means the name table and the shape classifier have
drifted apart.

## 5. Deliberate asymmetries

`ty.impl_trait.ffibox` splits `{handwritten,macro}` but not `{pub,priv}`: whether a
generator was used does not vary with visibility, and the split would cost 68
cells for nothing.

`ty.impl_trait.send_sync` splits `{pub,priv}` but not by origin: asserting `Send` on a
public type is a claim to consumers, on a private one it is internal
bookkeeping.

`fn.safe.of_which.with_unsafe` is counted on the safe arm only. With
`unsafe_op_in_unsafe_fn` denied, every `unsafe fn` doing anything raw has a
block by construction, so counting it there would measure the lint.

## 6. Retired counters

The counters the tree replaced are gone, not kept beside it. A second answer
to a question the tree answers is a liability: the two drift, and a reader has
no way to tell which one is current.

The whole `c_type_*` family -- `borrow`, `by_val`, `std_owner`,
`std_value_impl`, `layout_wrapper` -- with `non_c_type_borrow_*`,
`raw_ptr_has_c_type_wrapper`, `raw_ptr_as_slice_borrow` (into `casted_to`),
`drop_impl` and `clone_impl` (into `ty.storing_raw_ptr.of_which`),
`raw_ptr_derefs_outside_impl`, `unsafe_traits`, `total_stmts`,
`unsafe_block_stmts` and `unsafe_blocks_wrapper_impl`.

Then the rest of the flat block, each into the tree counter that measures the
same thing: `code_lines` and `unsafe_block_code_lines` into `code.loc.*`,
`unsafe_blocks` into `code.unsafe_block.total`, `unsafe_blocks_ffi_export`
into its `of_which`, `safe_fns_*` and `unsafe_fns_*` into `fn.{safe,unsafe}.*`
with their seam shares, `unsafe_impls` into `ty.impl_trait.of_which.unsafe`,
`unsafe_{send,sync}_impl` into `ty.impl_trait.send_sync.*`, `raw_ptr_derefs_{rd,wr}`
into `raw_ptr.deref.*`, and `{raw,void}_ptr_ty_*` into
`{raw,void}_ptr.field.*`.

Three of them were not equivalents, and the tree's reading is the one kept:

- `ffi_calls` used `is_foreign_item`, a property of the declaration site, so it
  missed every call made through a function pointer -- 27 of 557 on
  libgit2-bindings. `code.unsafe_call.ffi` classifies by the callee's ABI,
  which is part of its type and survives being stored in a field.
- `raw_ptr_fn_*` counted a `*c_void` position in both the `raw_ptr` and the
  `void_ptr` family, two unrelated top-level totals, so adding them
  double-counted and reading either alone under-counted. The tree counts the
  position once, in `raw_ptr`, and labels the erased ones as its `void` share.
- `unsafe_block_lines` was the raw brace-to-brace span, blanks and comments
  included, so it was not comparable with the `code_lines` denominator.
  `code.loc.unsafe` applies the same filter to both.

Last, the owner / handle record: the second emission line and its 24 counters
(`fn_sig_{ffibox,non_ffibox}_{owner,handle}_*`, the `ty_*` variants,
`ffibox_impl_*`, `ffibox_define_ctype_*`, `ffibox_ccell_not_layout`,
`ffibox_layout_not_ccell`). `ty.field.ffibox`, `ty.impl_trait.ffibox` and
`fn.ffibox` cover the vocabulary it measured, by primitive and by trait rather
than by the owner / handle pair, and they split an impl by whether a macro
wrote it.

Two of its readings have no replacement, and go rather than being kept:

- the `non_ffibox` half, the owners and handles the crate wrote itself, found
  by shape rather than by type. `ty.storing_raw_ptr` and its shares answer the
  question the shape test was standing in for -- which types manage a pointer,
  and what they declare about it -- without a wrapper taxonomy.
- `ffibox_ccell_not_layout` and `ffibox_layout_not_ccell`, which checked a
  declared `CCell` against the structural layout test. That is a consistency
  check on ffibox's own use, not a measure of the crate's unsafety, and it was
  the last reader of the reachability pass.

With it goes the pass itself: `compute_c_visible`, `is_c_accessible`,
`structural_wrapper`, `embedded_c`, `is_type_wrapper`, `holds_c_pointer`,
`CastCollector` and the erased-type machinery. The peel set never used it --
membership is the scanned crate or the named `-sys` crates -- so the tree is
unchanged by its removal.

## 7. Sites

`--sites` reports where a counter's increments are, by its dotted path. The
validation, and why a macro-generated item reports its macro's call site, are
[`scanning.md`](scanning.md)'s.

## 8. Limitations

`raw_ptr.casted_to` is a filter, not a partition. A crate that hand-rolls a
conversion and does not declare it in `--seams` is invisible, not filed under
`other`. This bites hardest in an audit, where the seam list starts empty: a low
`local_seam` there means nothing was declared, not that nothing was hand-rolled.
The seam list is established once per campaign and recorded, so that every
batch's scan reads the same one -- a list inferred per batch would make
`local_seam` a measure of which agent looked harder.

`ty.storing_raw_ptr` reads what the peel set admits, so its population moves
with the `-sys` crates named. Figures from different invocations are comparable
only with the same list.

`code.unsafe_call.rust` is dominated by the standard library. On the canary
fixture it reads 13, of which 1 is a call to the crate's own `unsafe fn` and
12 are std's unsafe constructors -- `Box::from_raw` and its siblings, the same
calls `casted_to` already classifies. Splitting the arm into own-crate and
dependency would separate "wrote unsafe helpers" from "used std's unsafe API";
until it is split, the arm is not a measure of the crate's own unsafety.

`code.unsafe_call.ffi` counts calls through function pointers, which earlier
versions keyed on `is_foreign_item` and missed. Figures measured before this
change undercount and are not comparable.

### 8.1 No target values

ffimap has none, and this is the place that says so. Absolute counts are not
comparable across crates of different size, and lower is not automatically
better: a wrapper over C must contain unsafe, and folding 600 small audited
blocks into 200 large ones improves the number while making the crate worse.
A reader who wants a rate divides the leaves it names.

Finding what is worth looking at is the opposite kind of work, and belongs to
a reviewer who reads the code, forms suspicions and defends them. `none` and
`no_seam_trait` name an absence, not a defect.

### 8.2 Rules that were tried and rejected

Kept because the reasoning is the useful part, and a counter that looks
obvious often fails for a reason worth recording.

- **A cast between two named types as evidence of C ownership.** Reading one
  would mean composing casts from unrelated program points into a chain,
  symmetrically, which says nothing about who owns the bytes. Measured on
  libgit2-bindings (12 such casts) and git2-rs (42), it admitted no type that
  declarations and containment did not already reach.
- **A C-reachability pass behind the counters.** `compute_c_visible` and
  `structural_wrapper` classified every type by whether C reads its bytes, and
  fed the whole `c_type_*` family. The pass is what was wrong with it, not the
  question: deciding the population by inference over seeds and a closure took
  some 300 lines whose own false positives were untestable, and nothing else
  in the tree depended on it.

  The question was sound and the signal was good. On libgit2-bindings
  `c_type_borrow` split 137 sanctioned, 7 non-sanctioned, 22 opaque and 4
  generic -- a residual of 7 out of 170, which is a finding rather than a
  census. An earlier revision of this section cited 660 and called it
  undiscriminating; that figure was a sum across the counter's position x kind
  x visibility leaves with `sanctioned` included, and the claim was wrong.
  Under `--ffibox` the population is in the type system -- a type that
  implements `CCell` -- so it can be asked again without the pass.
- **Layout newtypes as a counter.** `c_type_layout_wrapper` read 71 on
  libgit2-bindings and 3 on git2-rs, which separates the two crates' binding
  *styles* rather than their soundness; `ty.storing_raw_ptr` does that more
  directly. Reviving it would revive the whole reachability pass for one
  number.
- **Owner and handle detection by shape.** `holds_c_pointer` found
  hand-written owners and handles structurally, independent of any framework.
  `ty.storing_raw_ptr` and its declaration shares answer what the shape test
  was standing in for -- which types manage a pointer, and what they declare
  about it -- without a wrapper taxonomy.
- **Classifying a handle by the seam trait it implements.** It misses every
  hand-written cell, since `define_ctype!` generates the seams only for a cell
  with no parameters of its own. `CCell`'s associated types are the authority
  (see [`ffibox.md`](ffibox.md)).
- **Excluding trait-impl methods from `fn.*`.** The justification was that
  another crate fixed the signature, but a foreign *declaration* has no body
  and never reaches the walk, so the rule only ever excluded the crate's own
  code -- including `impl Drop for Foo { fn drop }`, the one shape
  `fn.safe.of_which.with_unsafe` exists to find.
