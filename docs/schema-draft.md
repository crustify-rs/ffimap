# Counter schema, draft

**Status: draft.** Nothing here is implemented. It is written down so the shape
can be argued with before 125 counters exist, because the schema touches every
counter, both examples, the campaign artifact and the dashboard at once.

The present schema grew family by family, so the position a counter was
observed at is encoded in its name inconsistently -- `_fn_sig_`, `_fn`, `_ty_`,
or nothing -- and six families overlap on the same positions. This draft makes
position the primary axis and collapses those six into one.

## The tree

```
volume .{code_lines, total_stmts, unsafe_block_lines,
         unsafe_block_code_lines, unsafe_block_stmts}

trait  .unsafe

fn.decl.{safe, unsafe}.{pub, priv}                        of_which: seam

fn.sig .ptr
   .by_val                            .{c_layout, rust, generic}          .{pub, priv}
   .borrowed .{scalar, array, string} .{c_layout, c_opaque, rust, generic}.{pub, priv}
              c_layout.{self_on_impl, self_on_accessor, opaque, smells}
              of_which: ffibox, wrapper
   .owned    .{scalar, array, string} .{c_layout, c_opaque, rust, generic}.{pub, priv}
              of_which: ffibox
   .raw                               .{c_layout, c_opaque, rust, generic}.{pub, priv}
              of_which: seam, has_wrapper, unsafe_fn
   .void                                                                  .{pub, priv}
              of_which: unsafe_fn

fn.body
   .unsafe_block                                of_which: wrapper_impl, ffi_export
   .raw_ptr_deref .{rd, wr}                     of_which: outside_impl
   .borrow        .{c_layout, c_opaque, rust, generic}   c_layout of_which: opaque
   .from_raw_ptr  .{array, string}
   .ffi_call

ty .layout_wrapper
   .handle_wrapper
   .drop_impl
   .clone_impl
   .std_value_impl .{pub, priv}                 of_which: derived
   .unsafe_impl    .{send, sync}

ty.fields.ptr
   the modes and partition of `fn.sig.ptr`, without the safety share, and with
   visibility as `.{pub.{pub, priv}, priv}` -- the type's, then the field's.
```

## The axes

**Mode** -- how the position carries access: `by_val` the bytes inline;
`borrowed` a reference; `owned` anything that releases (`Box`, `CBox`, a local
`Drop` type); `raw` a `*const` / `*mut` / `NonNull` / `AtomicPtr`; `void` the
erased pointer.

**Cardinality** -- `scalar`, `array`, `string`, on `borrowed` and `owned` only,
because that is where the ffibox pairs live:

| | scalar | array | string |
|---|---|---|---|
| owned | `CBox` / local `Drop` | `CVec` / `Vec`, `Box<[T]>` | `CStrBox` / `CString` |
| borrowed | `Ref`, `Mut` / handle, `&T` | `CSlice` / `&[T]` | str view / `&CStr` |

**The four-way partition** -- what the carried type is to C:

- `c_layout` -- C reads the bytes as its own type. A layout contract: `repr`,
  field offsets, padding, ABI.
- `c_opaque` -- crosses only as a `*c_void` round trip. C holds the pointer and
  never reads the bytes. Aliasing and lifetime, no layout contract.
- `rust` -- never crosses.
- `generic` -- the referent is a type parameter, so unknown: C memory for some
  instantiations, which a pass reading generic bodies does not see.

`c_layout + c_opaque` is "crosses the FFI boundary", readable as
`total - rust - generic`.

**`c_layout` under `borrowed` partitions again**, by why the borrow exists:

- `self_on_impl` -- `&Self` in an impl of a std trait whose receiver the
  language forces (`Clone`, `PartialEq`, `Hash`, `Deref`, `AsRef`, ...). An API
  design question: should this C type implement that trait at all?
- `self_on_accessor` -- `&self` in an `as_ref` / `as_mut` layout accessor,
  under `--ffibox`. The convention working as intended.
- `opaque` -- the referent is a zero-sized or uninhabited C type, so the
  reference covers no bytes of C's.
- `smells` -- everything else: the signature did not force this borrow.

### `smells` overclaims, deliberately

The name is evaluative where the rest of the schema is structural, and it is
not reliable. The two forced cases above are a closed list, and other traits
force `&self` just as much -- `Display`, `Iterator`, `Default`, a
`#[derive(Serialize)]` expansion -- so their borrows land in `smells` while
being exactly as unavoidable. Widening the list moves cells out of `smells`
without anything in the reviewed crate changing. Read it as "no recognised
reason", not as a defect.

## Settled behaviours

**Slots, not positions.** Nesting recurses, so every slot is classified:
`Vec<CBox<Oid>>` emits `owned.array` AND `owned.scalar`, and
`&[CBox<Oid>]` emits `borrowed.array` and `owned.scalar`. The totals therefore
exceed the number of signature positions, `borrowed` and `owned` are not
disjoint over a position, and the ffibox share is a share of slots. Depth
guarded at 8, as the rest of the pass is.

**`from_raw_ptr` sits outside the partition.** A slice-like reference conjured
from a raw pointer -- `CStr::from_ptr(p)`, `slice::from_raw_parts(p, n)` --
has a primitive element type, so provenance says nothing about it, and "came
from a raw pointer" is evidence rather than proof: `Vec::as_ptr` produces one
too. It keeps its cardinality and stays out of `c_layout` / `rust`.

**`c_opaque` undercounts.** The erased set sees only `*c_void` casts in the
scanned crate, so a payload crossing as `*mut T`, with the cast in the `-sys`
crate or nowhere, lands in `rust`. `rust` is not a guarantee of "never
crosses".

**`&[u8]` classifies by element type**, so a byte slice holding text lands in
`array` rather than `string`.

## What it replaces

`raw_ptr_*`, `void_ptr_*`, `c_type_borrow_*`, `non_c_type_borrow_*`,
`c_type_by_val_*`, `c_type_std_owner_*` and the twenty position counters of the
owner / handle record become one `ptr` axis. The `ffibox` record keeps its six
declaration counters, which are the type-level conformance check that `ptr`'s
`of_which: ffibox` complements at position level.

Roughly 125 leaves against 106 today -- close to flat, while collapsing seven
families into two axes.

## Mapping

Every current counter has a home; `{card}` and `{part}` are the cells the new
axes add, which the driver decides per slot rather than inheriting from a name.

| now | becomes |
|---|---|
| `code_lines` | `volume.code_lines` |
| `total_stmts` | `volume.total_stmts` |
| `safe_fns_pub` | `fn.decl.safe.pub` |
| `safe_fns_priv` | `fn.decl.safe.priv` |
| `unsafe_blocks` | `fn.body.unsafe_block` |
| `unsafe_block_stmts` | `volume.unsafe_block_stmts` |
| `unsafe_block_lines` | `volume.unsafe_block_lines` |
| `unsafe_block_code_lines` | `volume.unsafe_block_code_lines` |
| `unsafe_blocks_wrapper_impl` | `fn.body.unsafe_block.of_which.wrapper_impl` |
| `unsafe_blocks_ffi_export` | `fn.body.unsafe_block.of_which.ffi_export` |
| `unsafe_fns` | `fn.decl.unsafe` |
| `unsafe_fns_pub` | `fn.decl.unsafe.pub` |
| `unsafe_fns_priv` | `fn.decl.unsafe.priv` |
| `unsafe_impls` | `ty.unsafe_impl` |
| `unsafe_traits` | `trait.unsafe` |
| `unsafe_send_impl` | `ty.unsafe_impl.send` |
| `unsafe_sync_impl` | `ty.unsafe_impl.sync` |
| `c_type_layout_wrapper` | `ty.layout_wrapper` |
| `c_type_borrow_fn_sig_sanctioned_pub` | `fn.sig.ptr.borrowed.{card}.c_layout.self_on_impl|self_on_accessor.pub` |
| `c_type_borrow_fn_sig_sanctioned_priv` | `fn.sig.ptr.borrowed.{card}.c_layout.self_on_impl|self_on_accessor.priv` |
| `c_type_borrow_fn_sig_non_sanctioned_pub` | `fn.sig.ptr.borrowed.{card}.c_layout.smells.pub` |
| `c_type_borrow_fn_sig_non_sanctioned_priv` | `fn.sig.ptr.borrowed.{card}.c_layout.smells.priv` |
| `c_type_borrow_fn_sig_opaque_pub` | `fn.sig.ptr.borrowed.{card}.c_layout.opaque.pub` |
| `c_type_borrow_fn_sig_opaque_priv` | `fn.sig.ptr.borrowed.{card}.c_layout.opaque.priv` |
| `c_type_borrow_fn_body_non_sanctioned` | `fn.body.borrow.c_layout` |
| `c_type_borrow_fn_body_opaque` | `fn.body.borrow.c_layout.of_which.opaque` |
| `c_type_borrow_fn_body_generic` | `fn.body.borrow.generic` |
| `c_type_borrow_ty_non_sanctioned_pub_fields_pub` | `ty.fields.ptr.borrowed.{card}.c_layout.smells.pub.pub` |
| `c_type_borrow_ty_non_sanctioned_pub_fields_priv` | `ty.fields.ptr.borrowed.{card}.c_layout.smells.pub.priv` |
| `c_type_borrow_ty_non_sanctioned_priv` | `ty.fields.ptr.borrowed.{card}.c_layout.smells.priv` |
| `c_type_borrow_ty_opaque_pub_fields_pub` | `ty.fields.ptr.borrowed.{card}.c_layout.opaque.pub.pub` |
| `c_type_borrow_ty_opaque_pub_fields_priv` | `ty.fields.ptr.borrowed.{card}.c_layout.opaque.pub.priv` |
| `c_type_borrow_ty_opaque_priv` | `ty.fields.ptr.borrowed.{card}.c_layout.opaque.priv` |
| `raw_ptr_as_slice_borrow` | `fn.body.from_raw_ptr.{array,string}  (split by formed type)` |
| `c_type_by_val_fn_sig_pub` | `fn.sig.ptr.by_val.c_layout.pub` |
| `c_type_by_val_fn_sig_priv` | `fn.sig.ptr.by_val.c_layout.priv` |
| `c_type_by_val_ty_pub_fields_pub` | `ty.fields.ptr.by_val.c_layout.pub.pub` |
| `c_type_by_val_ty_pub_fields_priv` | `ty.fields.ptr.by_val.c_layout.pub.priv` |
| `c_type_by_val_ty_priv` | `ty.fields.ptr.by_val.c_layout.priv` |
| `c_type_std_owner_fn_sig_pub` | `fn.sig.ptr.owned.{card}.c_layout.pub  (of_which.ffibox=0 for std)` |
| `c_type_std_owner_fn_sig_priv` | `fn.sig.ptr.owned.{card}.c_layout.priv  (of_which.ffibox=0 for std)` |
| `c_type_std_owner_ty_pub_fields_pub` | `ty.fields.ptr.owned.{card}.c_layout.pub.pub` |
| `c_type_std_owner_ty_pub_fields_priv` | `ty.fields.ptr.owned.{card}.c_layout.pub.priv` |
| `c_type_std_owner_ty_priv` | `ty.fields.ptr.owned.{card}.c_layout.priv` |
| `non_c_type_borrow_pub_safe` | `fn.sig.ptr.borrowed.{card}.rust.pub` |
| `non_c_type_borrow_pub_unsafe` | `fn.sig.ptr.borrowed.{card}.rust.pub` |
| `non_c_type_borrow_priv_safe` | `fn.sig.ptr.borrowed.{card}.rust.priv` |
| `non_c_type_borrow_priv_unsafe` | `fn.sig.ptr.borrowed.{card}.rust.priv` |
| `raw_ptr_ty_pub_fields_pub` | `ty.fields.ptr.raw.{part}.pub.pub` |
| `raw_ptr_ty_pub_fields_priv` | `ty.fields.ptr.raw.{part}.pub.priv` |
| `raw_ptr_ty_priv` | `ty.fields.ptr.raw.{part}.priv` |
| `raw_ptr_fn_pub_safe` | `fn.sig.ptr.raw.{part}.pub` |
| `raw_ptr_fn_pub_unsafe` | `fn.sig.ptr.raw.{part}.pub (+of_which.unsafe_fn)` |
| `raw_ptr_fn_priv_safe` | `fn.sig.ptr.raw.{part}.priv` |
| `raw_ptr_fn_priv_unsafe` | `fn.sig.ptr.raw.{part}.priv (+of_which.unsafe_fn)` |
| `raw_ptr_has_c_type_wrapper` | `fn.sig.ptr.raw.of_which.has_wrapper + ty.fields.ptr.raw.of_which.has_wrapper  (SPLITS)` |
| `safe_fns_seam_pub` | `fn.decl.safe.pub.of_which.seam` |
| `safe_fns_seam_priv` | `fn.decl.safe.priv.of_which.seam` |
| `unsafe_fns_seam_pub` | `fn.decl.unsafe.pub.of_which.seam` |
| `unsafe_fns_seam_priv` | `fn.decl.unsafe.priv.of_which.seam` |
| `raw_ptr_fn_seam_pub_safe` | `fn.sig.ptr.raw.{part}.pub.of_which.seam` |
| `raw_ptr_fn_seam_pub_unsafe` | `fn.sig.ptr.raw.{part}.pub.of_which.seam` |
| `raw_ptr_fn_seam_priv_safe` | `fn.sig.ptr.raw.{part}.priv.of_which.seam` |
| `raw_ptr_fn_seam_priv_unsafe` | `fn.sig.ptr.raw.{part}.priv.of_which.seam` |
| `raw_ptr_derefs_rd` | `fn.body.raw_ptr_deref.rd` |
| `raw_ptr_derefs_wr` | `fn.body.raw_ptr_deref.wr` |
| `raw_ptr_derefs_outside_impl` | `fn.body.raw_ptr_deref.of_which.outside_impl` |
| `void_ptr_ty_pub_fields_pub` | `ty.fields.ptr.void.pub.pub` |
| `void_ptr_ty_pub_fields_priv` | `ty.fields.ptr.void.pub.priv` |
| `void_ptr_ty_priv` | `ty.fields.ptr.void.priv` |
| `void_ptr_fn_pub_safe` | `fn.sig.ptr.void.pub` |
| `void_ptr_fn_pub_unsafe` | `fn.sig.ptr.void.pub (+of_which.unsafe_fn)` |
| `void_ptr_fn_priv_safe` | `fn.sig.ptr.void.priv` |
| `void_ptr_fn_priv_unsafe` | `fn.sig.ptr.void.priv (+of_which.unsafe_fn)` |
| `drop_impl` | `ty.drop_impl` |
| `clone_impl` | `ty.clone_impl` |
| `c_type_std_value_impl_pub` | `ty.std_value_impl.pub` |
| `c_type_std_value_impl_priv` | `ty.std_value_impl.priv` |
| `c_type_std_value_impl_derived` | `ty.std_value_impl.of_which.derived` |
| `ffi_calls` | `fn.body.ffi_call` |

The twenty `fn_sig_*` and `ty_*` counters of the owner / handle record map onto
`ptr.{owned,borrowed}` with `of_which: ffibox` set or clear. `raw_ptr_has_c_type_wrapper`
is the one counter that splits: it spans both positions today and has no single
home, which the backlog already records as wanting `of_which` treatment.

## Prerequisites

`handle_wrapper` is the repr-agnostic handle test from
[TODO.md](TODO.md): `owned` and `borrowed` cannot be told apart for
`#[repr(C)] struct CBox<T, D> { ptr: NonNull<T>, policy: D }` without it, so it
lands inside this work rather than before it.

## How it should be landed

NOT as a pure rename, and not in one commit. The schema adds information --
cardinality, `c_opaque` on every mode, the four-way split under `c_layout` --
and recursing into nested slots changes every total on purpose. No sum is
preserved, so there is no multiset invariant to assert.

Instead, emit the new counters BESIDE the old ones first, on one driver, and
compare them on both examples. Every delta then has to be explained by one of
the deliberate changes above or it is a bug. The old counters come out only
once each new number is accounted for. That is the only verification available
when the output is meant to change.
