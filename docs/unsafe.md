# The unsafe surface

> **Historical.** This describes the flat counters, which the counter tree
> of [`schema.md`](schema.md) replaced. It is kept for the reasoning behind
> each rule for the unsafe surface -- including the rules that were
> tried and rejected -- not as a description of what ffimap emits today.

How much unsafety the crate contains, and how much of it crosses the public
API boundary where a caller has to discharge it.

`unsafe_block_code_lines` is the measure of unsafe **volume**: it is the one
that does not move when the code is merely re-divided. `unsafe_blocks` counts
how that volume is split up, which is a function of the crate's policy -- under
a one-operation-per-block lint it approximates the number of unsafe operations,
without one it falls as blocks are merged. So blocks are comparable *within* a
crate over time, and across crates only when both hold the same policy; lines
are comparable either way.

Neither is a score. A wrapper over C must contain unsafe, and folding 600 small
audited blocks into 200 large ones makes the crate worse while improving the
block count. The counters that are categorical are the ones about the **public**
surface -- with the caveat in Seams below.

Visibility and safety are read as [`output.md`](output.md)'s Conventions
section describes.

## Counters

- `code_lines` -- Non-blank, non-comment lines of the crate's own source. The denominator for any rate a reader wants.
- `total_stmts` -- Statements in the crate's bodies.
- `safe_fns_pub` -- Safe functions and methods with a body, reachable from outside the crate.
- `safe_fns_priv` -- Safe functions and methods with a body, not reachable from outside.
- `unsafe_blocks` -- `unsafe { .. }` blocks.
- `unsafe_block_stmts` -- Statements inside `unsafe` blocks. A block holding more than one is doing more than one unsafe thing.
- `unsafe_block_lines` -- Lines spanned by `unsafe` blocks, blanks and comments included.
- `unsafe_block_code_lines` -- Of those, the non-blank, non-comment ones.
- `unsafe_blocks_wrapper_impl` -- Of those, the ones inside an `impl` on a wrapper type.
- `unsafe_blocks_ffi_export` -- Of those, the ones inside the C-ABI gateway (`#[no_mangle]` / `extern "C"` fns).
- `unsafe_fns` -- Every `unsafe fn` the crate defines; the total of the two below.
- `unsafe_fns_pub` -- `unsafe fn`s reachable from outside: the obligations the crate exports to its callers.
- `unsafe_fns_priv` -- `unsafe fn`s the crate keeps to itself.
- `safe_fns_seam_pub` -- Of `safe_fns_pub`, the share that are `--seams` functions.
- `safe_fns_seam_priv` -- Of `safe_fns_priv`, the share that are `--seams` functions.
- `unsafe_fns_seam_pub` -- Of `unsafe_fns_pub`, the share that are `--seams` functions.
- `unsafe_fns_seam_priv` -- Of `unsafe_fns_priv`, the share that are `--seams` functions.
- `unsafe_impls` -- `unsafe impl`s of any trait.
- `unsafe_traits` -- `unsafe trait`s the crate declares.
- `unsafe_send_impl` -- Of those, `unsafe impl Send`: a type opted into moving across threads by assertion.
- `unsafe_sync_impl` -- Of those, `unsafe impl Sync`: a type opted into sharing across threads by assertion.
- `ffi_calls` -- Calls to a foreign item, one declared in an `extern` block. The crate-wide unsafe-FFI-call surface.

## Notes

`unsafe_fns` = `unsafe_fns_pub` + `unsafe_fns_priv`. `safe_fns_*` count
functions and methods **with a body**, on the same terms; a trait method
declared without one is not counted. The crate's own functions are therefore
`fns_pub` = `safe_fns_pub` + `unsafe_fns_pub`, and likewise `fns_priv`, both
given in `derived`.

`unsafe_blocks_wrapper_impl` and `unsafe_blocks_ffi_export` are **subsets** of
`unsafe_blocks`, and `unsafe_send_impl` / `unsafe_sync_impl` subsets of
`unsafe_impls`, so the document nests them under `of_which` and never sums
them into the parent. See [`output.md`](output.md)'s Counter tree.

The `TrivialClone` impl a `#[derive(Clone)]` emits is not counted among
`unsafe_impls`. A negative impl (`impl !Send`) is not unsafe and is not
counted either.

Each `unsafe impl Send` or `Sync` asserts that a value may move to, or be
shared with, another thread. For a type holding a C object that is the C
library's to allow, so check it against the library's thread-safety contract:
a wrong one is a data race reachable from safe code.

The C-ABI gateway (`#[no_mangle]` / `#[export_name]` / `extern "C"` fns) is
counted like any other fn; its unsafe blocks are also counted apart, in
`unsafe_blocks_ffi_export`.

`ffi_calls` resolves on the callee, so it is alias- and re-export-proof and
crate-agnostic: a bindgen `*-sys` binding, `libc` and a local `extern "C"`
block all resolve to the same thing. Calling a foreign item is an unsafe
operation, so this is the crate-wide unsafe-FFI-call surface.

## Seams

A **seam** is the function that converts between a wrapper and its raw pointer
(`raw`, `from_raw`, `as_ptr`, `from_ptr`). Seams are plumbing, not API a caller
reasons about, yet they are functions like any other and land in these
counters -- and only when the crate writes them itself. That made the fn
counters incomparable across crates that site their seams differently, in both
directions:

- a crate whose seams come from a dependency's trait (ffibox's `CRefSeam` /
  `CMutSeam`, whose methods are defaults living in ffibox) contributes none of
  them, because ffimap counts only what the scanned crate defines;
- a crate whose seams are its own public trait (git2-rs's `Binding`, with
  `unsafe fn from_raw`) contributes one per implementing type, and they land in
  `unsafe_fns_pub`, because a public trait's impl methods are publicly
  reachable.

`--seams` resolves it by making the classification **declared** rather than
inferred. With each crate's own names given:

| | total | seam | non-seam |
|---|---|---|---|
| git2-rs `unsafe_fns.pub` | 112 | 89 | **23** |
| libgit2-bindings `unsafe_fns.pub` | 48 | 0 | **48** |

The raw 112 against 48 orders the two crates the opposite way round from the
thing it is meant to measure. ffimap never guesses the names: unset, the seam
counters are zero and every other number is unchanged.
