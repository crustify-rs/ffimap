# TODO

## References into C memory the counters miss

Two ways to form a Rust reference into memory C may write go uncounted
(see Known limitations in [output.md](output.md)):

- **Fields of other types.** `c_type_borrow_non_sanctioned` follows the
  whole place back to a raw-pointer deref, but counts only a reference whose
  type holds a C type, so `&(*p).len` or
  `&mut (*p).a[i].b` of a C scalar counts nowhere.
- **Autoref on a field.** `(*p).field.method()` with a `&self` method borrows
  the field implicitly. Count `Adjust::Borrow` adjustments on raw-based places,
  as `c_type_borrow_non_sanctioned` already does for whole wrappers.

## The C-type pass has two open admission questions

The pass decides by provenance ([ctypes.md](ctypes.md)'s Which types are C's).
Two of its rules are still inferences rather than recorded facts:

- **Pointer fields are followed unconditionally.** A field held by value is
  admitted only if its own type has a layout C can describe; a field holding
  `*mut T` admits `T` regardless. C holding a pointer does not say it
  dereferences it, and `T` may be a `repr(Rust)` type C could not read. There
  were 21 such insertions on libgit2-bindings, unexamined; the same repr test
  applies, with its own blast radius to measure.
- **`is_c_type` is circular.** It is `is_type_wrapper || is_c_accessible`, and
  `is_type_wrapper` resolves through `embedded_c` to `is_c_accessible` again.
  For a local type the first term is wholly redundant, since the fixpoint's
  layout rule already admits any local `repr(C)` / `transparent` struct holding
  a reachable type by value. Its only real contribution is a *foreign* layout
  newtype, which that rule skips because it is restricted to local types.
  Making the layout rule crate-agnostic collapses `is_c_type` to
  `is_c_accessible` and leaves `is_type_wrapper` a classification output rather
  than an admission input.

## The erased class is computed and discarded

`compute_c_visible` returns `(accessible, erased)`; the second is the types
whose only tie to C is a `*c_void` round trip. Nothing reads it --
`is_c_visible` carries `#[allow(dead_code)]` -- because a payload handed to C
is not a C type and must not be classified as one. It is worth reporting on its
own: a Rust payload crossing as `void *` is an FFI smell, and on git2-rs the
class is the whole `TreeWalkCbData` / `StashCbData` / `RemoteCallbacks` family.
Either give it a counter or drop the computation.

## Handles with a companion field are unclassified

`structural_wrapper`'s handle arm needs `#[repr(transparent)]` and a single
non-zero-sized pointer field, so ffibox's
`#[repr(C)] struct CBox<T, D> { ptr: NonNull<T>, policy: D }` is neither handle
nor layout newtype, and nor is anything built on `AtomicPtr`. Widening it --
strip every layer, and if a pointer at a C type remains it is a handle -- gives
`c_type_handle_wrapper` as a sibling of `c_type_layout_wrapper`, and lets
`scan_structural` stop discarding the kind it already computed, which today
puts handles and layout newtypes into one `Wrappers` map that `is_wrapper` and
`wrapped_c` both read without distinguishing them.

## Per-type counters have no visibility split

The counters that count a TYPE rather than a position are still single
numbers, although the driver already has the type's effective visibility in
scope at each site (`exported`, as `count_raw_ptr_fields` uses it):

- `unsafe_send_impl`, `unsafe_sync_impl` -- a public type asserting `Send` is a
  different fact from a private one, and under
  [`specs/testing.md`](https://github.com/crustify-rs/crustify) each needs a
  synchronization or immutability proof and a TSan obligation. libgit2-bindings
  has 73 + 71 of them, undifferentiated.
- `drop_impl`, `clone_impl` -- a hand-written lifecycle on a public type is
  part of the contract; on a private one it is an implementation detail.
- `c_type_layout_wrapper` -- how much of the C surface has a safe layout
  newtype, split by whether that newtype is reachable.

Each becomes a `{total, pub, priv}` record, folded by the existing
`_PARTITION` spec in `measure.py`. `code_lines`, `total_stmts` and the
`unsafe_block_*lines` totals take no split: they are not per-type or
per-position.

## The FFmpeg example predates the counter tree

[`examples/ffmpeg-bindings/ffimap.json`](../examples/ffmpeg-bindings/ffimap.json)
carries the flat `counts` schema and the pre-split `c_type_borrow_*` counters.
The libgit2-bindings and git2-rs documents have been regenerated; this one
cannot be: `ffmpeg-bindings` at `crustify/devel` does not compile against
the ffibox it pins (`/opt/venv/share/ffibox`, commit `203b1a0`) -- 684
`no method named as_ptr/as_mut_ptr` errors on the `define_ctype!` handles, on
both the workspace's own 1.99.0 and ffimap's nightly, with the stock compiler
as well as the driver. The generated code expects those as inherent methods on
the `*Ref` / `*Mut` handles, while `203b1a0` has them on the `CRefSeam` /
`CMutSeam` traits. Until that is resolved, `ffimap` reports
`counts_unavailable` for that workspace, so the committed document is the only
record of it.

## Seam classification is declared, not detected

`--seams` takes the names (`UM_SEAM_FNS` to the driver) and reports them as the
`of_which.seam` share of `safe_fns`, `unsafe_fns` and `raw_ptr_fn`. That was
chosen over a structural predicate -- "a fn relating only `Self` and `*T`" --
because the classification is then explicit per scan and visible in the
invocation, and cannot silently misclassify a one-pointer API that happens to
look like a seam. `tests/test_counters.py` asserts the driver hardcodes no
names.

Still open:

- the seam share is reported for fn-signature counters only. `unsafe_blocks`
  and `raw_ptr_derefs` inside seam bodies are still counted undifferentiated,
  so a crate with many seams still reads as having more unsafe than one whose
  seams live in a dependency.
- `raw_ptr_has_c_type_wrapper` has no seam split, and on libgit2 72.5% of it is
  seam constructors and projections with a further 23.2% `extern "C"` callback
  slots whose signature C fixes -- leaving about 6 positions that mean what the
  counter claims. It wants the same `of_which` treatment, plus an `abi_fixed`
  share.
- nothing marks the *escape hatch* distinction, which is what a reader really
  wants: git2-rs documents `Binding` in prose ("do consider contributing to the
  git2 project") but does not mark it `#[doc(hidden)]`, and libgit2-bindings
  uses no `doc(hidden)` at all, so there is no machine-readable signal.

