# Counter schema

This document describes the counters that ffimap reports: what each one holds,
how a record is shaped, and how a report is built from them. ffimap determines
every counter from declarations and single expression nodes. It follows no
value, composes no cast chain and performs no dataflow.

[`analysis.md`](analysis.md) describes what each counter is decided from, and
how a scan runs. [`ffibox.md`](ffibox.md) describes the ffibox vocabulary that
the `<trait>` and `<primitive>` arms are generated from.

## 1. The counters

Each row below is one counter, named by its dotted path into the document's
`counts`. A `{a,b}` in a path is a split that the counter carries:
`raw_ptr.field.{pub,priv}` is two leaves. Every row's leaves are integers.
Each partition also carries a `total`, which is derived from the partition's
children unless the driver emits it. So `raw_ptr.field.total` exists, and
`raw_ptr.field.pub + raw_ptr.field.priv` equals it. The `of_which` rows are
shares of the row above them and are never summed
([2.1](#21-partitions-and-shares)).

The counters are the whole of the document's `counts`. There is no second,
flat counter block beside them, and no prose rendering of them. If you want a
rate, divide the leaves that it names.

Some names mean the same thing across the tree. `unsafe` and `safe` are the
safety of the *function* that the position or site is in. `pub` and `priv` say
whether a consumer of the crate can reach the item, and `void` marks a pointer
whose pointee is erased (`*c_void`).

Some rows are present only with a flag:

- A row that names `ffibox`, a `<trait>` or a `<primitive>` is present only
  under `--ffibox`.
- An `of_which.seam` row is present only with `--seams`.
- A `region` or `outside_regions` row is present only with `--regions`.

Without its flag, such a row is absent rather than zero
([2.3](#23-zero-and-absent)).

A row ends with the property that it bears on. [goals.md](goals.md) names
these properties: safety, soundness, ergonomics and idiomaticity.

### 1.1 `raw_ptr`

The raw pointers that the crate declares in its signatures and types, and what
its bodies do with them.

- `raw_ptr.total.{safe,unsafe}.{pub,priv}` -- the denominator: every
  raw-pointer position that the crate CHOSE, which is `fn_sig_arg` plus
  `fn_sig_ret` plus `field`. The driver emits it and does not derive it, so it
  is not a sum of the families beside it
  ([analysis 9.2](analysis.md#92-what-raw_ptrtotal-admits)).
- `raw_ptr.fn_sig_arg.{safe,unsafe}.{pub,priv}` -- raw pointers that an
  argument of a signature takes. Taking is the hazard: a safe fn that takes a
  raw pointer lets a caller pass anything, with no `unsafe` at the call site.
- `raw_ptr.fn_sig_arg.of_which.void.{safe,unsafe}.{pub,priv}` -- of those, the
  erased ones. To get the typed ones, subtract this share from `fn_sig_arg`.
- `raw_ptr.fn_sig_arg.of_which.seam.{safe,unsafe}.{pub,priv}` -- of those, the
  ones in a function that `--seams` declared to be nothing but a conversion
  between a wrapper and its raw pointer.
- `raw_ptr.fn_sig_ret.{safe,unsafe}.{pub,priv}` -- raw pointers that a
  signature returns. The caller must still write `unsafe` before a returned
  pointer means anything, which is why this counter is apart from
  `fn_sig_arg`.
- `raw_ptr.fn_sig_ret.of_which.void.{safe,unsafe}.{pub,priv}` -- of those, the
  erased ones, as for `fn_sig_arg`.
- `raw_ptr.fn_sig_ret.of_which.seam.{safe,unsafe}.{pub,priv}` -- of those, the
  ones in a seam, as for `fn_sig_arg`.
- `raw_ptr.fn_sig_trait_impl.{safe,unsafe}.{pub,priv}` -- positions in a trait
  impl's method. Both directions share one counter, because a trait
  declaration fixed the signature, so the crate did not choose the position.
  Mixed into `fn_sig_arg` and `fn_sig_ret`, these positions would make those
  figures move with how many types a trait is implemented for
  ([analysis 9.3](analysis.md#93-positions-a-trait-fixed)).
- `raw_ptr.fn_sig_trait_impl.of_which.void.{safe,unsafe}.{pub,priv}` -- of
  those, the erased ones, as for `fn_sig_arg`.
- `raw_ptr.fn_sig_trait_impl.of_which.seam.{safe,unsafe}.{pub,priv}` -- of
  those, the ones in a seam, as for `fn_sig_arg`.
- `raw_ptr.fn_sig_trait_impl.of_which.std.{safe,unsafe}.{pub,priv}` -- of
  those, the ones that a standard-library trait fixed.
- `raw_ptr.fn_sig_trait_impl.of_which.local.{safe,unsafe}.{pub,priv}` -- the
  ones fixed by a trait that the crate declared itself.
- `raw_ptr.fn_sig_trait_impl.of_which.ffibox.{safe,unsafe}.{pub,priv}` -- the
  ones that an ffibox contract fixed. For a crate built on the convention,
  these are its lifecycle strategies.
- `raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.<trait>` -- the ffibox
  ones by trait, over the whole vocabulary, so that a document says which
  contracts reach a raw pointer and which do not. This row has no safety or
  visibility split, because a trait method's safety and visibility are the
  trait declaration's ([2.5](#25-deliberate-asymmetries)).
- `raw_ptr.field.{pub,priv}` -- struct and union fields declared with a raw
  pointer. `pub` is one reachability question, not two levels that you have
  to combine: the type is exported AND the field is exported.
- `raw_ptr.field.of_which.void.{pub,priv}` -- of those, the erased ones.
- `raw_ptr.deref.{rd,wr}` -- dereference sites in bodies, by whether the place
  is read or written. These are sites, not positions, so they are outside
  `raw_ptr.total`.
- `raw_ptr.casted_to.std.{owner,string,borrow,slice,other}` -- a raw pointer
  converted into a standard-library shape, by the shape it became: an owner
  (`Box`, `Vec`, `Rc`, `Arc`), a string (`CStr`, `CString`, `String`), a
  borrow or a slice. `other` is a shape that the table does not know. For
  `std`, the table knows every shape, so nothing lands in `other`
  ([analysis 11.3](analysis.md#113-other)).
- `raw_ptr.casted_to.ffibox.{owner,string,borrow,slice}` -- a raw pointer
  adopted into an ffibox primitive, by the primitive's group. There is no
  `other` arm, because every primitive maps to a shape.
- `raw_ptr.casted_to.local_seam.{owner,string,borrow,slice,other}` -- a raw
  pointer converted through a function that `--seams` named, by the seam's
  return type. `other` is a seam that returns a bespoke handle.
- `raw_ptr.surrendered.std.{owner,string}` -- the other direction: a value
  that Rust owns, turned into a raw pointer by a standard-library call such as
  `Box::into_raw` or `CString::into_raw`, by the shape the value had. These
  are the values that C is then trusted to give back to the allocator that
  made them (soundness).
- `raw_ptr.surrendered.ffibox.<shape>` -- the same through an ffibox
  primitive's `into_raw`, `into_c` or `into_raw_parts`, by the primitive's
  shape, as `casted_to.ffibox` reads it (soundness).

### 1.2 `ty`

The types the crate defines, by what they hold and what they declare about it.

- `ty.total.{pub,priv}` -- every type that the crate defines. The driver emits
  it, and it is the denominator that its shares are read against.
- `ty.total.of_which.std_trait.{pub,priv}` -- of those, the types that
  implement a standard-library trait.
- `ty.total.of_which.local_trait.{pub,priv}` -- the types that implement a
  trait that the crate declared itself.
- `ty.total.of_which.ffibox_trait.{pub,priv}` -- the types that implement an
  ffibox contract.
- `ty.total.of_which.no_trait.{pub,priv}` -- the residual: the types that
  implement no trait at all.
- `ty.total.of_which.macro.{pub,priv}` -- the types that a macro wrote, such
  as `bitflags!`'s. Subtract this share for the hand-written types, as for
  `fn.total`.
- `ty.total.of_which.{repr_c,repr_transparent}.{pub,priv}` -- the types whose
  layout is C's (`#[repr(C)]`) or exactly another type's
  (`#[repr(transparent)]`). These are the layouts that the crate shares with C
  (soundness).
- `ty.total.of_which.std_impl.<trait>.{pub,priv}` -- the types that implement
  one of a fixed list of std traits that a Rust consumer expects of a value,
  by trait. The list is `Debug`, `Display`, `Error`, `Clone`, `Default`,
  `PartialEq`, `Eq`, `Hash`, `Iterator` and `From`. An impl counts whether it
  is derived or written (idiomaticity).
- `ty.storing_raw_ptr.{pub,priv}` -- types whose fields reach a raw pointer
  within the peel set ([analysis 9.1](analysis.md#91-the-peel-set)), so these
  are the types that manage a raw pointer themselves instead of delegating to
  `Vec` or to an ffibox owner.
- `ty.storing_raw_ptr.of_which.impl_drop.{pub,priv}` -- of those, the ones that
  implement `Drop`: they free memory that Rust did not allocate.
- `ty.storing_raw_ptr.of_which.impl_clone.{pub,priv}` -- the ones that
  implement `Clone`. A shallow clone duplicates the pointer and, with `Drop`,
  double-frees it.
- `ty.storing_raw_ptr.of_which.{impl_deref,impl_deref_mut}.{pub,priv}` -- the
  ones that hand out a reference derived from the pointer implicitly, at every
  call site.
- `ty.storing_raw_ptr.of_which.impl_send_sync.{pub,priv}` -- the ones that
  assert thread safety for memory that no type system checked.
- `ty.storing_raw_ptr.of_which.has_lifetime.{pub,priv}` -- the ones that tie
  the pointer to a lifetime parameter.
- `ty.storing_raw_ptr.of_which.ffibox.{pub,priv}` -- the ones that declare
  their lifecycle through an ffibox contract, which none of the std shares can
  see.
- `ty.storing_raw_ptr.of_which.pub_field.{pub,priv}` -- the ones that publish
  the pointer as a public field. This is not a declaration: it is an access
  that the type does not govern.
- `ty.storing_raw_ptr.of_which.none.{pub,priv}` -- the residual: the types
  that store a pointer and declare nothing about it, in any vocabulary.
- `ty.wrapping_unsafe_cell.{pub,priv}` -- types that hold an `UnsafeCell`,
  which is the one way to hold a value that C may write while Rust holds a
  shared reference to it.
- `ty.impl_block.{pub,priv}` -- inherent `impl T` blocks: the API that the
  crate wrote for its own type.
- `ty.impl_block.of_which.ffibox.{layout,ref,mut,locked}.{pub,priv}` -- of
  those, the blocks on a cell (a type that implements `CCell`) and on each of
  its handles. These are different surfaces: the layout type carries the
  constructors, the shared handle carries the getters, and the exclusive
  handle carries the setters.
- `ty.impl_block.of_which.other.{pub,priv}` -- the blocks on everything else.
- `ty.impl_trait.{pub,priv}` -- `impl Tr for T` blocks: satisfying someone
  else's shape.
- `ty.impl_trait.of_which.unsafe` -- of those, the `unsafe impl`s, which assert
  what the compiler cannot check. `TrivialClone`, which `#[derive(Clone)]`
  emits, is skipped.
- `ty.impl_trait.of_which.derived.{pub,priv}` -- the ones that a `#[derive]`
  wrote. Nobody typed them, and they are most of the `std` arm.
- `ty.impl_trait.of_which.std.drop.{pub,priv}` -- the impls of a
  standard-library trait, by trait. This arm is `Drop`, which runs code when
  an object is released.
- `ty.impl_trait.of_which.std.clone.{pub,priv}` -- `Clone`, which duplicates
  an object.
- `ty.impl_trait.of_which.std.send.{pub,priv}` -- `Send`, the claim that an
  object may move to another thread.
- `ty.impl_trait.of_which.std.sync.{pub,priv}` -- `Sync`, the claim that an
  object may be shared between threads.
- `ty.impl_trait.of_which.std.ref_forming.{pub,priv}` -- `Deref`, `DerefMut`,
  `AsRef`, `AsMut`, `Borrow`, `BorrowMut`, `Index` and `IndexMut`. The method
  of each returns a reference of a type that the impl chose.
- `ty.impl_trait.of_which.std.other.{pub,priv}` -- every other std trait:
  `Debug`, `PartialEq`, `Copy` and the rest.
- `ty.impl_trait.of_which.local.{pub,priv}` -- the impls of a trait that the
  crate declared itself: a shape that it chose, not one that it adopted.
- `ty.impl_trait.of_which.ffibox.layout.{pub,priv}` -- the impls of an ffibox
  trait that states a cell's layout, or how the cell is reached and locked.
  These are the layout, seam and guard groups of
  [ffibox.md](ffibox.md#1-the-vocabulary).
- `ty.impl_trait.of_which.ffibox.layout.of_which.<trait>.{handwritten,macro}` --
  the `layout` impls by trait. The split is by whether a generator wrote the
  impl, not by visibility ([2.5](#25-deliberate-asymmetries)).
- `ty.impl_trait.of_which.ffibox.policy.{pub,priv}` -- the impls of a lifecycle
  policy: the allocate, release and clone groups.
- `ty.impl_trait.of_which.ffibox.policy.of_which.<trait>.{handwritten,macro}` --
  the `policy` impls by trait, with the same split.
- `ty.generic.{pub,priv}` -- types that carry a generic parameter.
- `ty.generic.of_which.{lifetime,type}.{pub,priv}` -- of those, by kind of
  parameter. A lifetime ties the type to something that it borrows. A type
  parameter makes the type a family, not one layout, so each instantiation is
  a separate question about C's bytes. A type may carry both.
- `ty.generic.of_which.storing_raw_ptr.{pub,priv}` -- the generic types that
  hold a raw pointer.
- `ty.field.ffibox.<primitive>.{pub,priv}` -- fields that hold an ffibox
  primitive, by primitive. This is the delegation that `ty.storing_raw_ptr`
  deliberately does not count as the crate's own pointer.
- `ty.ffibox.wrapper.{pub,priv}` -- the cell types: those that implement
  `CCell`.
- `ty.ffibox.wrapper.of_which.no_seam_trait.{pub,priv}` -- of those, the cells
  whose handles implement neither seam. Code that is generic over a handle has
  to special-case them.
- `ty.ffibox.wrapper.as.borrowed.std.{pub,priv}` -- the records under `as`
  count MENTIONS of a cell in the crate's declarations, by what holds the
  cell. A cell named in twenty signatures is twenty mentions. This arm is the
  mentions behind a reference, which the convention says should be a handle
  instead.
- `ty.ffibox.wrapper.as.borrowed.std.of_which.{field,fn_sig}.{pub,priv}` -- of
  those, by where they sit: in a field's type, or in a signature's. These two
  shares partition each arm of `as`.
- `ty.ffibox.wrapper.as.borrowed.std.of_which.self_in_ref_accessor.{pub,priv}`
  -- of the references, the ones that are the receiver of an `as_ref` /
  `as_mut` accessor, which ffibox's contract licenses.
- `ty.ffibox.wrapper.as.borrowed.std.of_which.self_in_trait_impl.{pub,priv}` --
  of the references, the ones that are the receiver of a trait impl's method.
  The trait fixed the receiver's shape, and the crate did not. The references
  in neither this share nor `self_in_ref_accessor` are the unsanctioned
  surface.
- `ty.ffibox.wrapper.as.borrowed.std.of_which.self_in_trait_impl.of_which.ref_forming.{pub,priv}`
  -- of those, the receivers of a `ref_forming` std trait's method, which
  returns a reference that the impl chose.
- `ty.ffibox.wrapper.as.borrowed.ffibox.{pub,priv}` -- the mentions held by an
  ffibox borrow: `CBorrowedPtr`, `CSlice`, `CSliceMut`, `CGuardedRef`,
  `CGuard`.
- `ty.ffibox.wrapper.as.borrowed.ffibox.of_which.{field,fn_sig}.{pub,priv}` --
  of those, by where they sit.
- `ty.ffibox.wrapper.as.owned.std.{pub,priv}` -- the mentions held by a
  standard-library owner of its own storage (`Box`, `Vec`, a map).
- `ty.ffibox.wrapper.as.owned.std.of_which.{field,fn_sig}.{pub,priv}` -- of
  those, by where they sit.
- `ty.ffibox.wrapper.as.owned.ffibox.{pub,priv}` -- the mentions held by an
  ffibox owner: `CBox`, `CArc`, `CVec`, `CVal`.
- `ty.ffibox.wrapper.as.owned.ffibox.of_which.{field,fn_sig}.{pub,priv}` --
  of those, by where they sit.
- `ty.ffibox.wrapper.as.by_val.{pub,priv}` -- the mentions with nothing above
  them: the cell's bytes sit in the mention's own place.
- `ty.ffibox.wrapper.as.by_val.of_which.{field,fn_sig}.{pub,priv}` -- of
  those, by where they sit.
- `ty.ffibox.wrapper.fields.total` -- the crate's fns annotated as accessors
  of a C member. The annotation is a
  `#[doc(alias = "<root>.<member>{.<member>}")]` whose member path resolves
  through the structs and unions that the crates named by `--sys-crates`
  declare. The path starts from a struct, a union or a type alias of one. The
  count is once per alias and fn, so a getter and a setter of one member are
  two. The path names only what has a name:
  - bindgen's `__bindgen_anon_<n>` members are looked through;
  - a member that bindgen escapes with a trailing `_` matches its C name;
  - a bitfield resolves through the getter that bindgen declares for it; and
  - an array member continues into its element type.

  Only names are resolved, never layouts. The counter counts fns, not cells,
  so it is never summed into `ty.ffibox.wrapper`. It has no `{pub,priv}`
  split, like `ty.ffibox.sys`.
- `ty.ffibox.wrapper.fields.of_which.unique` -- the distinct member paths that
  those fns name.
- `ty.ffibox.sys.total` -- the structs that the crates named by `--sys-crates`
  declare: the C aggregates that the bindings expose. It has no `{pub,priv}`
  split, because they are another crate's types.
- `ty.ffibox.sys.of_which.raw_ptr_in_sys.total` -- of those, the ones that a
  `-sys` declaration puts behind a raw pointer. The declaration is a
  function's signature, a field, a callback typedef's parameters, or a member
  of a union that a pointer reaches.
- `ty.ffibox.sys.of_which.raw_ptr_in_sys.of_which.used` -- of those, the ones
  that the crate's compiled code names: in a declaration, or as the type of
  any expression or binding in a body.
- `ty.ffibox.sys.of_which.raw_ptr_in_sys.of_which.wrapped` -- of the
  `raw_ptr_in_sys` ones, the ones that a cell's `CCell::C` names.
- `ty.ffibox.sys.as.borrowed.std.{pub,priv}` -- the same mentions as
  `wrapper.as`'s, but of the raw struct that a cell covers, its `CCell::C`.
  This is the C layout named where the wrapper could have been.
- `ty.ffibox.sys.as.borrowed.std.of_which.{field,fn_sig}.{pub,priv}` -- as for
  `wrapper.as`.
- `ty.ffibox.sys.as.borrowed.std.of_which.{self_in_ref_accessor,self_in_trait_impl}.{pub,priv}`
  -- as for `wrapper.as`.
- `ty.ffibox.sys.as.borrowed.std.of_which.self_in_trait_impl.of_which.ref_forming.{pub,priv}`
  -- as for `wrapper.as`.
- `ty.ffibox.sys.as.borrowed.ffibox.{pub,priv}` -- as for `wrapper.as`.
- `ty.ffibox.sys.as.borrowed.ffibox.of_which.{field,fn_sig}.{pub,priv}` -- as
  for `wrapper.as`.
- `ty.ffibox.sys.as.owned.std.{pub,priv}` -- as for `wrapper.as`.
- `ty.ffibox.sys.as.owned.std.of_which.{field,fn_sig}.{pub,priv}` -- as for
  `wrapper.as`.
- `ty.ffibox.sys.as.owned.ffibox.{pub,priv}` -- as for `wrapper.as`.
- `ty.ffibox.sys.as.owned.ffibox.of_which.{field,fn_sig}.{pub,priv}` -- as for
  `wrapper.as`.
- `ty.ffibox.sys.as.by_val.{pub,priv}` -- as for `wrapper.as`.
- `ty.ffibox.sys.as.by_val.of_which.{field,fn_sig}.{pub,priv}` -- as for
  `wrapper.as`.

### 1.3 `fn`

Every function the crate defines, the methods of its trait impls included
([analysis 9.4](analysis.md#94-functions-and-methods)).

- `fn.total.{pub,priv}` -- the denominator, emitted: every function with a body.
- `fn.total.of_which.macro.{pub,priv}` -- of those, the ones that a macro
  wrote. Subtract this share for the hand-written total.
- `fn.safe.{pub,priv}` -- the safe ones.
- `fn.safe.of_which.with_unsafe.{pub,priv}` -- of those, the ones whose body
  contains an `unsafe` block: a safe fn that discharges an obligation
  internally. Counted on the safe arm only
  ([2.5](#25-deliberate-asymmetries)).
- `fn.unsafe.{pub,priv}` -- the `unsafe fn`s. `fn.unsafe.pub` is the unsafe
  surface that a consumer meets.
- `fn.unsafe.of_which.in_trait_impl.std.{pub,priv}` -- of those, the methods
  of a trait impl, whose `unsafe` the trait's declaration fixed and the impl
  cannot drop. This arm is the methods of a standard-library trait's impl.
- `fn.unsafe.of_which.in_trait_impl.local.{pub,priv}` -- the methods of an
  impl of a trait that the crate declared itself. The crate put the `unsafe`
  there one level up.
- `fn.unsafe.of_which.in_trait_impl.ffibox.{pub,priv}` -- the methods of an
  impl of an ffibox contract, such as `CDrop::c_drop`.
- `fn.unsafe.of_which.in_trait_impl.other.{pub,priv}` -- the methods of an
  impl of any other crate's trait.
- `fn.unsafe.of_which.seam.{pub,priv}` -- the `unsafe fn`s that `--seams`
  names, which adopt a raw pointer by design. A seam may also be a trait's
  method, so this share overlaps `in_trait_impl`.
- `fn.unsafe.of_which.other.{pub,priv}` -- the residual: the `unsafe fn`s that
  are neither a trait impl's method nor a seam. This is the `unsafe` that the
  crate chose with nothing requiring it.
- `fn.unsafe.of_which.outside_regions.{pub,priv}` -- the `unsafe fn`s outside
  every module that `--regions` named: the unsafe API that the crate did not
  confine (safety).
- `fn.extern_abi.{pub,priv}` -- the fns that the crate defines with a foreign
  ABI (`extern "C"`). C reaches them by symbol or by fn pointer (soundness).
- `fn.extern_abi.of_which.exported.{pub,priv}` -- of those, the ones that
  carry a C symbol name (`#[no_mangle]`, `#[export_name]`).
- `fn.extern_abi.of_which.macro.{pub,priv}` -- the ones that a macro wrote.
- `fn.extern_abi.of_which.catches_unwind.{pub,priv}` -- the ones whose body
  calls `std::panic::catch_unwind`, a fn that `--barriers` named, or, under
  `--ffibox`, ffibox's `callback::barrier`. Such a call stops a panic before
  it unwinds into C. To read the rest, subtract this share (soundness).
- `fn.extern_abi.of_which.raw_ptr_sig.{pub,priv}` -- the ones whose signature
  holds a raw pointer.
- `fn.extern_abi.of_which.ffibox_sig.{pub,priv}` -- the ones whose signature
  holds an ffibox primitive: an owner or a handle in place of a pointer.
- `fn.extern_abi.of_which.ffibox_macro.{pub,priv}` -- the ones that an ffibox
  macro wrote, such as its `export_*!` lifecycle exports.
- `fn.sig.of_which.c_type.{arg,ret}.{pub,priv}` -- mentions of C's types in
  the signatures that the crate chose, with a trait impl's methods left out.
  A mention is one of C's scalar names (`c_int`, `c_char`, and `libc`'s) or a
  foreign-ABI fn pointer. The scalar names are read from the signature as
  written, since typeck erases them. These mentions are what a consumer of a
  Rust API handles in C's terms (ergonomics).
- `fn.sig.of_which.result.ret.{pub,priv}` -- the fns that return a `Result`,
  with trait impls' methods left out. A `Result` states failure in Rust's
  vocabulary, not in C's status codes (idiomaticity).
- `fn.sig.of_which.ffibox.{arg,ret}.<primitive>.{pub,priv}` -- mentions of an
  ffibox primitive in a signature, by position and by primitive. The mentions
  inside a `Result`, an `Option` or a reference are included
  ([analysis 9.4](analysis.md#94-functions-and-methods)). The counter says
  whether the vocabulary actually crosses the interface.
- `fn.ffibox.sys.total` -- the fns that the crates named by `--sys-crates`
  declare, and the fns of the scanned crate's own modules that `--sys-crates`
  names as `crate::<path>`. These are the C functions that the bindings
  expose, macro shims included. It has no `{pub,priv}` split, because they are
  another crate's.
- `fn.ffibox.sys.of_which.used` -- of those, the ones that the crate's
  compiled code names, by calling one or by coercing it to a pointer.
- `fn.ffibox.wrapper.{non_trait,other_trait}` -- the crate's fns annotated as
  wrappers of a C function. The annotation is a `#[doc(alias)]` that names a
  fn of the `-sys` crates. The count is once per alias and fn, so the variants
  that a C function is forked into count once each. By where the annotated
  fn sits, the arm is `non_trait` (a free fn or an inherent method) or
  `other_trait` (the method of a trait that is no ffibox policy). It has no
  `{pub,priv}` split, like `fn.ffibox.sys`.
- `fn.ffibox.wrapper.policy.<trait>` -- the annotated fns that are the method
  of an ffibox lifecycle policy, such as `CDrop::c_drop`, by trait. The
  policies are the allocate, release and clone groups of
  [ffibox.md](ffibox.md#1-the-vocabulary).
- `fn.ffibox.wrapper.of_which.unique` -- the distinct C functions that the
  annotated fns name.

### 1.4 `static`

The statics that the crate defines. An `extern` block's declarations are C's.

- `static.total.{pub,priv}` -- every static that the crate defines. The driver
  emits it, and it is the denominator that its shares are read against.
- `static.of_which.mut.{pub,priv}` -- the `static mut`s: shared mutable state
  that no borrow checks (soundness).
- `static.of_which.exported.{pub,priv}` -- the ones that carry a C symbol
  name, which C reads by that name (soundness).

### 1.5 `code`

The size of the crate and what its bodies do. These are the denominators that
the rest is read against.

- `code.loc.total` -- lines of code, from the compiled crate: the union of HIR
  definition spans, with blanks and comments excluded. Items that `cfg`
  removed are therefore not in the denominator.
- `code.loc.unsafe` -- of those, the lines inside an `unsafe` block, filtered
  the same way so that the two are comparable.
- `code.unsafe_block.total` -- `unsafe` blocks, however many lines each holds.
- `code.unsafe_block.of_which.ffi_export` -- of those, the ones inside a fn
  that is the C-ABI boundary: a fn with a foreign ABI or a C symbol name, or a
  closure inside one
  ([analysis 9.7](analysis.md#97-regions-and-the-c-abi-boundary)).
- `code.unsafe_block.of_which.region.<region>` -- the ones inside a module
  that `--regions` named, or inside a module nested in one, by the name of the
  innermost such module (safety).
- `code.unsafe_block.of_which.outside_regions` -- the ones inside no such
  module, another crate's macro expansions included: the unsafe that the crate
  did not confine (safety).
- `code.unsafe_call.ffi` -- unsafe calls whose callee carries a foreign ABI:
  the real crossings. They are counted by the callee's type, not by its
  declaration site, so calls through a stored function pointer are included
  ([analysis 10](analysis.md#10-calls)).
- `code.unsafe_call.rust` -- unsafe calls to a Rust-ABI function, the crate's
  own `unsafe fn`s and the standard library's unsafe constructors alike.
- `code.unsafe_call.intrinsic` -- unsafe calls to a compiler intrinsic,
  `transmute` among them.
- `code.fn_ptr.extern_abi.{local,foreign,other}` -- a fn with a foreign ABI
  turned into a fn pointer, by coercion or by an `as` cast: how C is handed a
  callback. The arm says what the fn is: one that the crate defines (`local`),
  a C fn that an `extern` block declares (`foreign`), or another crate's
  (`other`) (soundness).
- `code.fn_ptr.extern_abi.ffibox` -- under `--ffibox`, the calls that hand C an
  ffibox trampoline or release routine as a fn pointer (`trampoline`,
  `release_fn`, `release_fn_of`).
- `code.call.ffibox.{status,barrier}` -- under `--ffibox`, the calls to
  ffibox's status conventions, which turn a C status into a `Result`, and the
  calls to its panic barrier. Read them against `code.unsafe_call.ffi`
  (idiomaticity, soundness).
- `code.tests.loc.{total,unsafe}` -- the same two line counts as `code.loc`'s,
  for the test code. No other counter includes the test code
  ([analysis 9.6](analysis.md#96-test-code)).
- `code.tests.unsafe_block` -- `unsafe` blocks in the test code.
- `code.tests.fn` -- functions in the test code, including one generated
  harness `main` per test binary.

## 2. The shape of a record

### 2.1 Partitions and shares

A partition's children are disjoint and sum to it. An `of_which` node's
children are subsets that overlap, and they are never summed. `nest_ptr`
derives every partition `total` bottom-up and skips `of_which` when it sums.
So the driver writes no sum, and no sum can disagree with its parts.

`ty.storing_raw_ptr.of_which` is a share family. A type may implement both
`Drop` and `Clone`, so the family's arms overlap, and only the record itself
is a population. An `of_which` node therefore carries no `total` of its own,
because the sum of two shares is not a quantity. Each share still keeps the
total of its own `{pub,priv}` partition. A share may refine another share, and
then it nests under it: `fn_sig_trait_impl.of_which.ffibox.of_which.<trait>`
is the ffibox positions by trait.

One child is of another unit: `as` holds the mentions of the types that its
parent counts. `ty.ffibox.wrapper` is the cell types, and
`ty.ffibox.wrapper.as` is the places where they are named. So `as` is never
summed into the parent either. It is a record with a total of its own, which
its arms partition. The same holds for `ty.ffibox.wrapper.fields`, the fns
annotated as field accessors on those cells.

Where a residual is wanted, it is emitted as a share named for it, such as
`ty.storing_raw_ptr.of_which.none` and `ty.total.of_which.no_trait`. You do
not have to subtract to get it.

### 2.2 Namespaces

Three kinds of node carry no derived `total`:

- an `of_which` node, as above;
- a node that already carries an emitted `total`, which is how the
  denominators `raw_ptr.total`, `ty.total` and `code.loc.total` survive a
  derivation that would otherwise take their name; and
- a NAMESPACE: a node whose children are families, not the parts of one
  quantity.

A top-level prefix is always a namespace. For example, `raw_ptr.fn_sig_arg`
counts signature positions and `raw_ptr.deref` counts body sites, so their sum
means nothing. Four more nodes are namespaces a level down:

- `ty.ffibox` holds two type counts: the cells (`wrapper`) and the `-sys`
  crates' types (`sys`), each with its mentions under `as`.
- `code.tests` holds four separate measurements of the test build: its lines,
  its unsafe lines (a subset of its lines), its unsafe blocks and its fns.
  Their sum read 103840 on libgit2-bindings, a figure with no unit at all.
- `fn.sig` holds what a signature carries, in mentions: a fn that takes two
  `CBox` is two mentions. So `fn.sig` is a share of no count of fns, and
  `fn.total` beside it is the denominator that you divide by. Its own arms do
  carry totals: `fn.sig.of_which.ffibox` is `arg` plus `ret`, which are
  disjoint.
- `fn.ffibox` holds two fn counts, as `ty.ffibox` holds two type counts: the
  crate's annotated wrappers (`wrapper`) and the `-sys` crates' fns (`sys`).

`nest_ptr` declares the namespaces in `NAMESPACES` and does not infer them,
since no shape distinguishes a namespace from a partition.
`raw_ptr.fn_sig_arg`'s `{safe,unsafe}` children are records with their own
totals too, and summing those is exactly right.

### 2.3 Zero, and absent

The document holds every counter that the invocation's flags turn on, and a
counter that never fired is at `0`. With one document in hand, you cannot tell
an absent counter from one that the schema does not have. For example, no
`owned.std` under `ty.ffibox.wrapper.as` could mean "no cell is held in a std
collection" or "that arm was never written". The schema is also too long to
hold in the head. So the driver registers every path that it can emit before
the passes run, and the passes count up from there.

What is absent is what the flags did not turn on: the ffibox arms without
`--ffibox`, and the `of_which.seam` shares without `--seams`. That absence is
a different statement, and a deliberate one. A `0` there would say that the
scan looked and found none, when it did not look.

The registry is in the driver, beside the passes. It iterates the same
vocabulary lists that the passes do, so the trait and primitive arms cannot
drift from it. `RegistryTests` reads the registry off a scan of
`tests/fixtures/empty/`, a crate with nothing in it, whose every counter is
therefore 0. The test then holds the other fixtures' fired counters to the
registry.

### 2.4 The order of a record

A record's children are written in a declared order, most salient first:

1. the record's own `total`;
2. the splits that the record is cut by (`unsafe` before `safe`, `pub` before
   `priv`);
3. its families;
4. its shares and arms; and
5. `of_which` last, since a share is read against the partition that it cuts
   across.

The prefixes come in this document's order: `raw_ptr`, `ty`, `fn`, `code`.

The driver emits a sorted map, so the alternative is alphabetical: `fn` would
read `{safe, sig, total, unsafe}`, with the denominator in the middle.

A name that the order does not hold comes after every name that it does hold,
alphabetically. That is where the primitive arms land, such as `CArc`,
`CBorrowedPtr` and `CBox`. So a primitive added to ffibox needs no change to
the order and still reads predictably. The trait arms are declared, in the
order in which [`ffibox.md`](ffibox.md) gives the vocabulary. A breakdown by
trait therefore reads as the lifecycle that it describes, not alphabetically.

`measure.KEY_ORDER` is one table for every level, since a name that earns an
early rank in one record earns it in the others: `unsafe` is early as
`fn.unsafe`, as `code.loc.unsafe` and as the unsafe trait impls. `fn` is the
one name that the table cannot place for every record, because `fn` is a
prefix as well as one of `code.tests`'s measurements. It is ranked for
`code.tests`. A type count's `as` comes after its `of_which`, since the
mentions are read once the types are.

### 2.5 Deliberate asymmetries

This section lists each split that is not carried where you might expect it,
and says why.

`ty.impl_trait.of_which.ffibox.{layout,policy}.of_which.<trait>` splits
`{handwritten,macro}` but not `{pub,priv}`, because whether a generator was
used does not vary with visibility, and the split would cost a cell per trait
for nothing.

`raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.<trait>` splits by neither
safety nor visibility. A trait method's safety and visibility are the trait
declaration's: one spelling dictates every impl. So the split would restate
the parent, cell by cell. The parent `ffibox` arm carries both splits, since
the mix of traits that a crate implements does move them.

`fn.safe.of_which.with_unsafe` is counted on the safe arm only. With
`unsafe_op_in_unsafe_fn` denied, every `unsafe fn` that does anything raw has
a block by construction, so counting it there would measure the lint.

`raw_ptr.fn_sig_trait_impl` carries no direction, while `fn_sig_arg` and
`fn_sig_ret` are separate counters. The direction says what the crate chose to
do with the pointer, and in a trait impl the crate chose neither.

## 3. Building a report

A report is leaves divided and subtracted, named by their paths. Three rules
make the arithmetic sound:

- You may sum a partition. You may not sum an `of_which`, and you may never
  sum an `as` with the types above it. Two shares of one record overlap, so
  `ty.storing_raw_ptr.of_which.impl_drop + impl_clone` is not a quantity,
  while `pub + priv` is the record.
- A rate stays inside one record, or between a record and the denominator
  emitted for it: `fn.unsafe.pub / fn.total.pub`, `code.loc.unsafe /
  code.loc.total`, `ty.storing_raw_ptr.pub / ty.total.pub`. Dividing across
  prefixes mixes grains: signature positions divided by lines of code says
  nothing.
- A share is read against the record that it cuts, and the remainder is a
  subtraction: `wrapper.as.borrowed.std.pub` less its two sanctioned shares is
  the convention's unsanctioned surface.

### 3.1 The readings worth taking

Each reading below names the leaves it is made of. The figures are not here.
A reading of one crate is in [`analysis.md`](analysis.md), where it is the
evidence for a rule. A reading of several crates is in
[`examples/README.md`](../examples/README.md), where three real documents are
tabulated side by side. A figure copied into this document would be a second
copy to keep current, and the counters are what this document is for.

**How much of the bindings has a cell.** Take this reading under `--ffibox`
with the `-sys` crates named.
`ty.ffibox.sys.of_which.raw_ptr_in_sys.of_which.wrapped` against
`raw_ptr_in_sys` is the share of the C types the bindings hand around by
pointer that the crate has given a cell. `used` against `raw_ptr_in_sys` is
the share that the crate touches at all. So the gap between the two shares is
the C that the crate touches without a cell
([ffibox.md](ffibox.md#8-where-the-declarations-mention-a-cell)). Against
`ty.ffibox.sys.total`, `wrapped` reads low by construction, since a by-value
struct needs no cell.

**How much of the C functions has a wrapper.** Take this reading under
`--ffibox` with the `-sys` crates named. `fn.ffibox.wrapper.of_which.unique`
against `fn.ffibox.sys.total` is the share of the C functions the bindings
declare that the crate annotates a wrapper for.
`fn.ffibox.sys.of_which.used` against `fn.ffibox.sys.total` is the share that
the crate calls at all. The annotation is the only record of what a wrapper
wraps, so an unannotated wrapper reads as none. The alias is the one that the
conventions of Crustify require; Crustify is the agent harness that uses
ffimap. `fn.ffibox.wrapper.total` against `unique` is how many variants a
wrapped function was forked into on average.

**Which `unsafe fn`s nothing required.** `fn.unsafe.of_which.other` is the
unsafe surface that the crate chose: no trait declared the method unsafe, and
no seam adopts a pointer through it. Read it against `fn.unsafe`, and read its
`pub` leaf against `fn.unsafe.pub`. Do not subtract `in_trait_impl` and `seam`
instead, because those two overlap.

**What a consumer meets without writing `unsafe`.**
`raw_ptr.total.safe.pub` is the raw pointers on the safe public interface.
`fn.unsafe.pub` against `fn.total.pub` is the public unsafe surface.
`raw_ptr.field.pub` is the pointers that a public field hands over with no
`unsafe` at all.

**How much unsafe, and where it sits.** `code.loc.unsafe / code.loc.total` is
the density, and `code.unsafe_block.total` is the number of blocks. Read both,
since folding small blocks into large ones moves one and not the other.
`code.unsafe_block.of_which.ffi_export` subtracts the gateways that a port
campaign generated; a port campaign is a Crustify project that reimplements C
code in Rust. The `code.unsafe_call` arms say what the unsafe is for: `ffi` is the
boundary, `rust` is the standard library's constructors and the crate's own
helpers, and `intrinsic` is `transmute` and its siblings.

**What the crate wrote, as opposed to what a macro did.** Subtract
`fn.total.of_which.macro` from `fn.total`, and
`ty.impl_trait.of_which.derived` from `ty.impl_trait`. A comparison of two
crates without those shares is partly a comparison of how much boilerplate
each spells.

**What the crate declares about the pointers it manages.**
`ty.storing_raw_ptr.of_which.none` against `ty.storing_raw_ptr` is the types
that hold a pointer and say nothing about it. The other shares, such as
`impl_drop`, `impl_clone` and `ffibox`, say what the rest declared.
`pub_field` is the opposite of a declaration.

**Whether a convention is kept.** Take these readings under `--ffibox`:

- `ty.ffibox.wrapper.as.borrowed.std` less `self_in_ref_accessor` and
  `self_in_trait_impl` is the bare `&Foo` surface that the convention says
  should be a handle.
- `as.owned.std` and `as.by_val` against `as.owned.ffibox` say how much of a
  cell's storage the crate holds itself, not through ffibox's owners.
- `ty.ffibox.wrapper.of_which.no_seam_trait` is the cells that a generic
  handle has to special-case.
- `fn.sig.of_which.ffibox` says whether the vocabulary reaches the interface
  at all.

**What the trait impls do.** `ty.impl_trait.of_which.std`'s arms say which of
the crate's adopted traits act on what it wraps: `drop` and `clone` run its
lifecycle, `send` and `sync` are claims about threads, and `ref_forming` can
hand out a reference to it. Under `--ffibox`, `ty.impl_trait.of_which.ffibox`'s
`layout` and `policy` say how much of the convention is the cells' layout and
how much is their lifecycle.

**Whose shape the pointers in trait impls are.** Read `fn_sig_trait_impl`
through its `of_which` arms, never bare. One crate's positions are a
convention's lifecycle strategies, another's are its own private helpers, and
a third's are one local conversion trait. The bare figure is the same for all
three.

**The test code, beside the library and never added to it.**
`code.tests.loc.total` against `code.loc.total` is how much of the tree is
tests. The `code.tests` arms are the only counters that include the test code.

A report of several crates is a table of leaves, one row per crate, with the
denominator beside every share.

### 3.2 What a comparison requires

The document is a pure function of the source tree under a fixed scanner, so
two figures are comparable only when the scanner and the flags match:

- the ffimap commit;
- the toolchain;
- `--sys-crates`, which decides what `ty.storing_raw_ptr` admits;
- `--seams`, which decides what the `seam` shares and `casted_to.local_seam`
  can see; and
- any framework that the crate is built on.

The `scanner` and `sys_crates` fields carry all of it, which is why they are
in the document and not beside it. `scanner.ffimap` names one scanner only as
a commit, bare or with the hash of its uncommitted changes. Every copy of
ffimap outside a checkout of its own records a package version instead. So
`ffimap diff` reports two such documents as under scanners not known to be the
same ([analysis 1](analysis.md#1-determinism-and-what-it-rests-on)).

A counter added or a rule corrected moves figures too. The ones already known
to be incomparable across versions are named in
[analysis 12](analysis.md#12-what-the-analysis-cannot-see).

### 3.3 No target values

ffimap has no target values, and this is the place that says so. Absolute
counts are not comparable across crates of different size, and lower is not
automatically better. A wrapper over C must contain unsafe, and folding 600
small audited blocks into 200 large ones improves the number while it makes
the crate worse. If you want a rate, divide the leaves that it names.

Finding what is worth looking at is the opposite kind of work. It belongs to a
reviewer who reads the code, forms suspicions and defends them. `none` and
`no_seam_trait` name an absence, not a defect.
