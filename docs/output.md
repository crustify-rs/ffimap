# The ffimap document

What `ffimap --json` emits: the shape of the document, the conventions every
counter is read under, and where each counter is described.

## Availability

The scan requires:

- the dated nightly pinned in `src/ffimap/driver/rust-toolchain.toml`
  (a `rustc_private` driver builds only against the compiler internals it was
  written for), with `rustc-dev` and `llvm-tools`;
- successful `cargo metadata`;
- a workspace that builds under the nightly driver, including its native
  dependencies.

When measurement cannot run, `counts` is `null` and `counts_unavailable`
contains the failure. The tool does not substitute approximate results.

Generated `-sys` binding crates are excluded from the aggregate because they
are not the wrapper being audited.

## Document shape

- `crate_path`: audited Cargo workspace.
- `counts`: aggregate compiled-code metrics, as a tree (see Counter tree), or
  `null`.
- `counts_unavailable`: failure text when counts are unavailable.
- `derived`: sums calculated from counts.
- `sites`: present when `--sites` names counters; see Counter sites.
- `ffibox`: the owner and handle surface, always present; see that document.
  `null` when there are no counts.

### Counter tree

`counts` is a tree, one record per counter family, so that a family's total is
in the document rather than reconstructed by a consumer who has to know which
names belong together. The counter names the sections below describe are its
**leaves**; a family groups them by the distinctions the names encode --
visibility (`pub` / `priv`), safety (`safe` / `unsafe`), and, for a public
type, the visibility of the field (`pub.fields.pub` / `pub.fields.priv`).

```json
"raw_ptr_fn":  {"total": 217, "pub":  {"total": 11,  "safe": 5,  "unsafe": 6},
                              "priv": {"total": 206, "safe": 75, "unsafe": 131}},
"raw_ptr_ty":  {"total": 5, "pub": {"total": 3, "fields": {"pub": 0, "priv": 3, "total": 3}},
                            "priv": 2},
"unsafe_blocks": {"total": 1894, "of_which": {"wrapper_impl": 1478, "ffi_export": 88}}
```

Every node carries a `total`, and there are two kinds of child, which the flat
names could not tell apart:

- a **partition** -- disjoint children that sum to the node's `total`;
- an **`of_which`** record -- children that re-count some of the node's own
  occurrences from another angle, and so are **never** summed into it.
  `unsafe_blocks_wrapper_impl` is a subset of `unsafe_blocks`,
  `unsafe_send_impl` is "of `unsafe_impls`", `raw_ptr_derefs_outside_impl` is
  "of both" `rd` and `wr`.

A counter with no family stays a number at the top level. `sites` and the
`--ffibox` `by` breakdowns are keyed by the flat **leaf** name, since a site
list and a breakdown belong to one leaf rather than to a family.

Unsafe-block totals provide context only. A C wrapper must contain unsafe code,
and combining many small unsafe blocks into fewer large ones improves the count
without improving the code.

## Conventions

Every counter measures what the scanned crate itself defines: its types, its
fns and its methods. Items of other crates are never counted (ffibox's `CBox`,
`CArc` and their methods, std's), and neither are methods implementing another
crate's trait (`Clone`, `Drop`, ffibox's `CDrop`, ..), whose signature that
crate fixed. "pub" is rustc's effective visibility, reachable from outside the
crate: a `pub` item in a private module is not, unless it is re-exported, and a
`pub(crate)` item (such as the constructors `define_ctype!` emits) is private.

## The counters

Each counter is described, with the others of its area, in:

| document | covers |
|---|---|
| [`unsafe.md`](unsafe.md) | the unsafe surface: `unsafe` blocks, fns, impls and traits, and FFI calls |
| [`raw.md`](raw.md) | raw and `void` pointers: positions, dereferences, slice borrows |
| [`ctypes.md`](ctypes.md) | C types: which types are C's, wrappers, borrows into C memory, C values held by value, hand-written `Drop` / `Clone` |
| [`ffibox.md`](ffibox.md) | the owner and handle record |

### Derived

`type P = *const T` counts as a raw pointer.

The derived fields are sums over `counts`, never ratios: a ratio moves when
either term moves, so it reads as a change in the crate when only the
denominator changed. `unsafe_fns_pub / unsafe_fns` rises when private unsafe
fns are *deleted*. Every count is in `counts`; a consumer that wants a rate
divides its own.

- `fns_pub` / `fns_priv`: `safe_fns_pub + unsafe_fns_pub`, likewise `_priv`.
- `raw_ptr_pub`: `raw_ptr_ty_pub_fields_pub + raw_ptr_ty_pub_fields_priv +
  raw_ptr_fn_pub_safe + raw_ptr_fn_pub_unsafe`.
- `raw_ptr_pub_safe_interface`: `raw_ptr_ty_pub_fields_pub + raw_ptr_fn_pub_safe`.

## Counter sites

`--sites COUNTER [COUNTER ...]` (or `--sites all`) adds a `sites` record beside
`counts`, with one list per named counter: where that counter's increments are
in the source, as `[{"file": .., "count": N, "lines": [..]}]` per file. `count`
is the number of increments in that file, so a counter's per-file counts sum to
its value in `counts`; `lines` are the distinct lines they fell on, sorted. A
signature position (raw/void pointer, `unsafe fn`, `c_type_borrow_*`) is
sited at its function's signature line; a block, dereference, projection,
reference or call at the expression. A site inside macro output
(`define_ctype!`, `#[derive]`) is the line in the measured crate that invoked
the macro. Only counters that count source locations take `--sites`: the line
and statement totals (`code_lines`, `total_stmts`, `unsafe_block_*lines`,
`unsafe_block_stmts`) have none.

## Known limitations

- **References into C memory the counters miss.** A reference to a field of C
  memory whose type is neither a C type nor slice-like (`&(*p).len`, a C
  scalar), and an autoref
  on such a field (`(*p).field.method()` with `&self`), are counted by no
  counter, since `c_type_borrow_*` only cover C types. See
  [TODO.md](TODO.md).
- **Generic code.** Each generic body is read once, generically. A reference
  to a type parameter counts in `c_type_borrow.fn_body.generic`, whatever `T` turns
  out to be; a `*mut T` counts as a raw-pointer position but never as a
  `void_ptr_*` one or with a wrapper, and a generic type holding a `T` by
  value is not a `c_type_by_val_*` position.
- **Signatures and fields only for pointer positions.** Raw-pointer, `c_void`
  and `c_type_borrow_*` signature counters read the parameter and return
  types of functions with bodies; raw-pointer and `c_void` positions also
  include struct and union fields. Raw pointers in locals, casts, closure parameters, enum variants and
  statics are not positions, and a trait method
  declared without a default body is not counted.
- **Pointer origin.** No counter can tell C-owned memory from Rust-owned memory
  behind a pointer. C reachability is a property of a TYPE, not of a value: a
  `Copy` value of a C-reachable type held in Rust memory (`git2::Oid`) is
  checked like one C owns, and a pointer C only reads during a call counts
  like one it retains.
- **C reachability it cannot see.** The C-type pass decides by provenance, so
  what the compiler records bounds what it can decide. It over-admits where a
  Rust tail carries `#[repr(C)]` anyway, where a pointer field is followed
  whatever it points at, and where a binding's declaration has drifted from the
  C it mirrors; it under-admits where a variadic hides its argument type, where
  generics are left uninstantiated, and where erasure or an integer round trip
  breaks the chain. [`ctypes.md`](ctypes.md)'s Limitations section splits them
  into over- and under-admission, with the measurements.
