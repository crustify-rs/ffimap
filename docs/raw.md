# Raw and `void` pointers

> **Historical.** This describes the flat counters, which the counter tree
> of [`schema.md`](schema.md) replaced. It is kept for the reasoning behind
> each rule for raw and `void` pointers -- including the rules that were
> tried and rejected -- not as a description of what ffimap emits today.

Where the crate still works in raw pointers: in the types it declares, in the
signatures it exposes, and in the dereferences its bodies perform.

Visibility and safety are read as [`output.md`](output.md)'s Conventions
section describes.

## Counters

- `raw_ptr_as_slice_borrow` -- A slice-like reference a body forms from a raw pointer over a non-C type: `&[T]`, `&str`, `&CStr`.
- `raw_ptr_ty_pub_fields_pub` -- Raw pointer in a public field of a public type: pointer management the API's users inherit.
- `raw_ptr_ty_pub_fields_priv` -- Raw pointer in a private field of a public type: the type's own representation.
- `raw_ptr_ty_priv` -- Raw pointer in a field of a private type.
- `raw_ptr_fn_pub_safe` -- Raw pointer in the signature of a safe public fn: reachable from safe code outside the crate.
- `raw_ptr_fn_pub_unsafe` -- Raw pointer in the signature of a public `unsafe fn`: the caller has taken the obligation.
- `raw_ptr_fn_priv_safe` -- Raw pointer in the signature of a safe private fn.
- `raw_ptr_fn_priv_unsafe` -- Raw pointer in the signature of a private `unsafe fn`.
- `raw_ptr_has_c_type_wrapper` -- Of all those positions, the ones whose pointee is a C type that already has a wrapper.
- `raw_ptr_fn_seam_pub_safe` -- Of `raw_ptr_fn_pub_safe`, the share in a `--seams` function.
- `raw_ptr_fn_seam_pub_unsafe` -- Of `raw_ptr_fn_pub_unsafe`, the share in a `--seams` function.
- `raw_ptr_fn_seam_priv_safe` -- Of `raw_ptr_fn_priv_safe`, the share in a `--seams` function.
- `raw_ptr_fn_seam_priv_unsafe` -- Of `raw_ptr_fn_priv_unsafe`, the share in a `--seams` function.
- `raw_ptr_derefs_rd` -- Dereference `*p` of a raw pointer whose place is read or shared-borrowed.
- `raw_ptr_derefs_wr` -- Dereference `*p` whose place is assigned or mutably borrowed.
- `raw_ptr_derefs_outside_impl` -- Of both, the ones outside any `impl` or trait body.
- `void_ptr_ty_pub_fields_pub` -- `*c_void` in a public field of a public type.
- `void_ptr_ty_pub_fields_priv` -- `*c_void` in a private field of a public type.
- `void_ptr_ty_priv` -- `*c_void` in a field of a private type.
- `void_ptr_fn_pub_safe` -- `*c_void` in the signature of a safe public fn.
- `void_ptr_fn_pub_unsafe` -- `*c_void` in the signature of a public `unsafe fn`.
- `void_ptr_fn_priv_safe` -- `*c_void` in the signature of a safe private fn.
- `void_ptr_fn_priv_unsafe` -- `*c_void` in the signature of a private `unsafe fn`.

## What counts as a position

A **position** is a `*const T` / `*mut T`, a `NonNull<T>` (a `*const T` that is
never null), or an `AtomicPtr<T>` (a `*mut T` behind an atomic), in a
parameter, a return or a field type. Nested ones count: inside references,
generic arguments (`Option<*const T>`), tuples, arrays and slices.

- A pointer to a pointer (`*mut *mut T`) is **one** position.
- Function-pointer types are not entered.
- `PhantomData<*const T>` is a zero-sized marker, not a position.
- Type aliases are resolved, so `type P = *const T` counts.

Every position falls in **exactly one** of the seven `raw_ptr_*` counters, and
a `*c_void` position additionally in the matching `void_ptr_*` one.

A field counts by its type's visibility and, in a public type, by the field's
own. A signature counts by the function's visibility and its safety. The raw
pointers on the **safe public interface** are `raw_ptr_ty_pub_fields_pub` +
`raw_ptr_fn_pub_safe`, given as `raw_ptr_pub_safe_interface` in `derived`.

The public positions measure the raw-pointer work a consumer of the crate is
left with; the private ones the backend's, which the consumer never sees. A
handle keeping its pointer in a private field behind safe methods therefore
counts only on the backend side, while a `NonNull` or `AtomicPtr` on the
public interface counts like a raw pointer: its API is the pointer's, so using
it is pointer management.

Generated bindings compiled into the crate are skipped: files under the build
script's `OUT_DIR` and files named `bindings.rs`. Bindings in a `-sys` crate
are excluded with that crate.

## Dereferences

`raw_ptr_derefs_rd` and `raw_ptr_derefs_wr` are decided by the operand's type,
so `*` on a `Box`, a reference or a `Deref` impl is not one. Each dereference
falls in one of the two by what is done with the place `*p`, or a field or
index below it: `_wr` when it is assigned (`=`, `op=`) or borrowed mutably
(`&mut`, `&raw mut` / `addr_of_mut!`, a `&mut self` method or `IndexMut`
autoref), `_rd` otherwise, shared borrows and `addr_of!` included.
`*(*p).next = x` is a read of `(*p).next` and a write.

`raw_ptr_derefs_outside_impl` is a **subset** of both, nested under `of_which`
and never summed in.

## Slice borrows

`raw_ptr_as_slice_borrow` counts a reference a body forms from a raw pointer
to a slice-like target over a type that is **not** a C type: `[T]`, `[T; N]`,
`str`, or a standard byte string (`CStr`, `OsStr`, `Path`). `CStr::from_ptr(p)`,
`slice::from_raw_parts(p, n)`, `&*ptr::slice_from_raw_parts(p, n)` and
`&(*p).name` of an array field are each one. A slice of a C type counts in
`c_type_borrow_*` instead, in [`ctypes.md`](ctypes.md).

Each asserts that C neither frees nor changes those bytes for the reference's
lifetime: a C string or buffer C releases or rewrites is a use-after-free or a
write under a shared borrow.

## Reading the numbers

`raw_ptr_has_c_type_wrapper` is a subset of the positions, not a partition of
them, and says "a safe wrapper for this pointee already exists". Read it with
`c_type_layout_wrapper` in [`ctypes.md`](ctypes.md): when the crate has no
wrapper newtypes, zero is vacuous.

The driver cannot tell a pointer to C memory from one to a Rust-owned value,
so a site means "check where this pointer comes from", never "this is wrong".

## Seams

A **seam** is the function that converts between a wrapper and its raw
pointer: `fn raw(&self) -> *mut T`, `unsafe fn from_raw(p: *mut T) -> Self`,
`as_ptr`, `from_ptr`. Its raw pointer is the wrapper's own representation, not
pointer management a consumer of the safe API performs -- but it is a
raw-pointer position like any other, so it lands in these counters and can
dominate them.

`--seams` names them, newline- or comma-separated. ffimap never guesses: with
the flag unset the seam counters are zero and nothing else changes. Each
seam-named function is counted as usual **and** reported as the `of_which.seam`
share of its leaf, so the two are never summed and a reader can take either
view.

Measured on the two libgit2 wrappers, with each crate's own seam names
declared:

| | git2-rs | | | libgit2-bindings | | |
|---|---|---|---|---|---|---|
| | total | seam | non-seam | total | seam | non-seam |
| `raw_ptr_fn.pub.safe` | 66 | 66 | **0** | 5 | 1 | **4** |
| `raw_ptr_fn.pub.unsafe` | 70 | 70 | **0** | 6 | 0 | **6** |

git2-rs's entire public raw-pointer surface is its `Binding` seam, so a
consumer of its safe API faces no raw pointers at all. Read without the split,
66 against 5 says the opposite of the truth.
