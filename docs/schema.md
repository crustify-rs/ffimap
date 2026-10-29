# Counter schema

The counters ffimap reports, what each one counts, and how it is decided. Every
counter is determined from declarations and single expression nodes: no value is
followed, no cast chain is composed, and no dataflow is performed.

## 1. The tree

```
raw_ptr.
  taken.{safe,unsafe}.{pub,priv}
  taken.of_which.seam.{safe,unsafe}.{pub,priv}
  returned.{safe,unsafe}.{pub,priv}
  returned.of_which.seam.{safe,unsafe}.{pub,priv}
  deref.{rd,wr}
  casted_to.{std,ffibox,local_seam}.{borrow,slice,string,owner,other}

void_ptr.
  taken.{safe,unsafe}.{pub,priv}
  taken.of_which.seam.{safe,unsafe}.{pub,priv}
  returned.{safe,unsafe}.{pub,priv}
  returned.of_which.seam.{safe,unsafe}.{pub,priv}

ty.
  storing_raw_ptr.{pub,priv}
  storing_raw_ptr.of_which.{pub,priv}
    impl_drop · impl_clone · has_lifetime
    impl_deref · impl_deref_mut · impl_send_sync
    pub_field · none
    no_ffibox_trait                                  --ffibox
  field.ffibox.<primitive>.{pub,priv}                --ffibox
  impl.total
  impl.of_which.unsafe
  impl.ffibox.<trait>.{handwritten,macro}            --ffibox
  impl.send_sync.{send,sync}.{pub,priv}
  wrapping_unsafe_cell.{pub,priv}
  total.{pub,priv}

fn.
  safe.{pub,priv}
  safe.of_which.with_unsafe.{pub,priv}
  unsafe.{pub,priv}
  ffibox.{taken,returned}.<primitive>.{pub,priv}     --ffibox
  total.{pub,priv}

code.
  loc.{total,unsafe}
  unsafe_block
  unsafe_call.{ffi,intrinsic,rust}
```

`fn.total` and `code.unsafe_call` totals are derived from their partitions.

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
children are subsets that overlap and are never summed. `measure.py` enforces
both with `_PARTITION` and `_OF_WHICH`, and `_totals` cross-checks the sums.

`ty.storing_raw_ptr.of_which` is a share family, not a partition: a type may
implement both `Drop` and `Clone`. `none` is the residual, the types matching no
other share.

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

A `-sys` crate left unnamed drops its types out of the walk, and the counter
reads low for a reason that is not in the code. This is not diagnosed: most
crates that stop the walk do so legitimately, so a warning would be noise.

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

`ty.impl.ffibox.<trait>.{handwritten,macro}` splits each impl by whether it was
generated. ffibox ships `define_ctype!` and the `impl_c*!` family
(`impl_cdrop!`, `impl_cdupclone!`, `impl_cdispose!`, `impl_clendrop!`,
`impl_clenclone!`, `impl_crefclone!`, `impl_cguarded!`), so an impl either
carries expansion context or was typed out, and `Span::from_expansion()` decides
it exactly.

`macro` is a reserved word; the driver's enum variant is spelled otherwise while
the emitted key stays `macro`.

## 6. Deliberate asymmetries

`ty.impl.ffibox` splits `{handwritten,macro}` but not `{pub,priv}`: whether a
generator was used does not vary with visibility, and the split would cost 68
cells for nothing.

`ty.impl.send_sync` splits `{pub,priv}` but not by origin: asserting `Send` on a
public type is a claim to consumers, on a private one it is internal
bookkeeping.

`fn.safe.of_which.with_unsafe` is counted on the safe arm only. With
`unsafe_op_in_unsafe_fn` denied, every `unsafe fn` doing anything raw has a
block by construction, so counting it there would measure the lint.

## 7. Retired counters

The whole `c_type_*` family -- `borrow`, `by_val`, `std_owner`,
`std_value_impl`, `layout_wrapper` -- with `non_c_type_borrow_*` and
`raw_ptr_has_c_type_wrapper`. The C-reachability pass that fed them is kept: it
no longer has a counter, but the peel set and the `-sys` vocabulary still use
it.

Also retired: `raw_ptr_as_slice_borrow` into `casted_to`, `drop_impl` and
`clone_impl` into `ty.storing_raw_ptr.of_which`, `raw_ptr_derefs_outside_impl`,
`unsafe_traits`, `total_stmts`, `unsafe_block_stmts`.

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

`code.unsafe_call.ffi` counts calls through function pointers, which earlier
versions keyed on `is_foreign_item` and missed. Figures measured before this
change undercount and are not comparable.
