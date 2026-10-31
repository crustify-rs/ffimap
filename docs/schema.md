# Counter schema

The counters ffimap reports, what each one counts, and how it is decided. Every
counter is determined from declarations and single expression nodes: no value is
followed, no cast chain is composed, and no dataflow is performed.

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

  impl_block.{pub,priv}
  impl_block.of_which.other.{pub,priv}
  impl_block.of_which.ffibox.{layout,ref,mut,locked}.{pub,priv}   --ffibox

  impl_trait.{pub,priv}
  impl_trait.of_which.unsafe
  impl_trait.of_which.{std,local}.{pub,priv}
  impl_trait.of_which.ffibox.{pub,priv}              --ffibox
  impl_trait.ffibox.<trait>.{handwritten,macro}      --ffibox
  impl_trait.send_sync.{send,sync}.{pub,priv}

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
the convention, read from the seam trait it implements -- `CCell` the layout
type, `CRefSeam` its shared handle, `CMutSeam` its exclusive one,
`CLockedSeam` its locked one -- since those are three different surfaces. On
libgit2-bindings: 408 blocks, 100 on layout types, 37 on shared handles, 63 on
exclusive ones, 208 on everything else.

`ty.impl_trait.of_which.{std,local,ffibox}` is whose trait it is. A local one
is a shape the crate chose; a std or framework one it adopted. On
libgit2-bindings 1765 std, 193 ffibox, 2 local; on git2-rs 1704 std and 115
local, the latter mostly its own `Binding`.

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

```
<trait>      layout    CCell · CPlainElem · CZeroable
             allocate  CAlloc · CAllocZeroed · CNew
             release   CDrop · CDispose · CLenDrop
             clone     CDupClone · CRefClone · CLenClone
             seam      CRefSeam · CMutSeam · CLockedSeam
             guard     CGuarded · CGuardedAll · LockScope

<primitive>  owner     CBox · CArc · CStrBox · CVec · CVal
             borrow    CBorrowedPtr · CSlice · CSliceMut
             guard     CGuardedRef · CGuard
```

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

Derived, not hand-written: the adoption methods are `from_raw`, `from_raw_with`,
`from_ptr`, `from_c`, `from_c_with`, `from_raw_parts`, `from_raw_parts_with`,
`from_raw_parts_or_empty` and `from_raw_parts_or_empty_with`, crossed with the
`<primitive>` vocabulary and bucketed by the primitive's group -- `CStrBox` to
`string`, the other owners to `owner`, `CBorrowedPtr` to `borrow`, `CSlice` and
`CSliceMut` to `slice`.

`as_ref`, `as_slice`, `as_c_str` and `as_bytes` are excluded: they take `&self`
on an owner, so they are owner-to-borrow, not raw-to-borrow. `as_ptr`,
`as_mut_ptr`, `as_c_ptr` and `as_elem_ptr` run the other direction.

### 4.3 `other`

For `local_seam` it holds a seam returning a bespoke handle. For `std` and
`ffibox` it is structurally zero, every name in those tables mapping to a known
shape, so a nonzero reading means the name table and the shape classifier have
drifted apart.

## 5. ffibox impls

`ty.impl_trait.ffibox.<trait>.{handwritten,macro}` splits each impl by whether it was
generated. ffibox ships `define_ctype!` and the `impl_c*!` family
(`impl_cdrop!`, `impl_cdupclone!`, `impl_cdispose!`, `impl_clendrop!`,
`impl_clenclone!`, `impl_crefclone!`, `impl_cguarded!`), so an impl either
carries expansion context or was typed out, and `Span::from_expansion()` decides
it exactly.

`macro` is a reserved word; the driver's enum variant is spelled otherwise while
the emitted key stays `macro`.

## 6. Deliberate asymmetries

`ty.impl_trait.ffibox` splits `{handwritten,macro}` but not `{pub,priv}`: whether a
generator was used does not vary with visibility, and the split would cost 68
cells for nothing.

`ty.impl_trait.send_sync` splits `{pub,priv}` but not by origin: asserting `Send` on a
public type is a claim to consumers, on a private one it is internal
bookkeeping.

`fn.safe.of_which.with_unsafe` is counted on the safe arm only. With
`unsafe_op_in_unsafe_fn` denied, every `unsafe fn` doing anything raw has a
block by construction, so counting it there would measure the lint.

## 7. Retired counters

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

## 8. Sites

`--sites` takes a tree counter as its dotted path, validated against the
prefix and the family under it rather than against a list of every leaf. The
leaves are open on purpose: the ffibox arms are generated from a vocabulary of
17 traits and 10 primitives, so an exhaustive list would be a second copy of
this document and would drift from the driver's.

`all` means the owner / handle counters, which are the only closed list left.
Enumerating every leaf of the tree is a different request, and nothing needs it
yet.

## 9. Limitations

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
