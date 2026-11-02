# The analysis

What produces a document, what it requires, and what each counter is decided
from: the populations the passes walk, the tests that classify a call or a
conversion, and what the analysis cannot see. The counters themselves -- what
each one holds and how a report is built from them -- are
[`schema.md`](schema.md); the ffibox vocabulary is [`ffibox.md`](ffibox.md).

Sections 1 to 8 are how a scan runs; 9 onwards is how each family is decided.

## 1. Determinism, and what it rests on

The document is a pure function of the source tree **under a fixed scanner**.
Two runs over one tree agree byte for byte, so a diff between them is a change
in the crate -- but only if the ffimap commit, the flags and any framework the
crate is built on are the same. A campaign that records a scan should record
those beside it, or a later diff cannot tell a change in the crate from a
change in the scanner.

## 2. The toolchain

A `rustc_private` driver compiles only against the compiler internals it was
written for, so the nightly is pinned by date in
`src/ffimap/driver/rust-toolchain.toml` and both the driver and the scanned
workspace build on it. It needs `rustc-dev` and `llvm-tools`.

## 3. The build

```sh
cargo +<pinned nightly> check --all-targets
```

`check`, not `build`: the driver reports from `after_analysis`, so HIR and
typeck are all it needs, and `--emit=metadata` links nothing. A wrapper's test
binaries link the C library, and a fixture's `extern` declarations may have no
implementation at all, so linking them would make the scan fail where it
otherwise succeeds.

`--all-targets`, not `--tests`: the latter checks the test targets *instead of*
the plain library, and the library's emission is the scan.

The scan needs the workspace to compile. When it does not, `counts` is `null`
and `counts_unavailable` carries the reason; ffimap reports no counts rather
than approximate ones.

## 4. The emission protocol

The driver runs as `RUSTC`, so it sees one invocation per crate per target.
Each prints one line:

```json
{"crate": "<name>", "test": false, "counts": {"<dotted path>": 12}, "sites": {}}
```

Four rules decide what the Python side does with a line.

- **`CARGO_PRIMARY_PACKAGE`.** `after_analysis` returns early without it, so
  only workspace members emit and dependencies are silent. A workspace member
  that another member depends on is built in a dependency unit where it is
  unset, which is why a `-sys` crate inside the scanned workspace emits
  nothing -- and is also dropped by the next rule, so nothing is lost.
- **`-sys` crates are skipped**, by a `*_sys` suffix or by being named in
  `--sys-crates`. Their generated bindings are not the audit subject; their
  types are still walked into, as the peel set.
- **`build_script_build` is skipped.** Under `--all-targets` a build script is
  its own crate, and it builds the crate rather than being part of it. Left
  in, it adds 128 lines to libgit2-bindings' library count.
- **`--test` routes a line to `code.tests`.** Cargo passes it for the lib's
  test target and for each integration test crate, so the driver tells test
  code from the library without inspecting an item. A lib test target
  recompiles the library with `cfg(test)` on, so its figures include the
  library's and are subtracted, keyed on the crate name it shares with the
  non-test emission; an integration crate shares its name with no library, so
  nothing is subtracted from it.

## 5. The flags that change what is counted

Two inputs change the figures and belong with any recorded scan.

`--sys-crates` is the peel set, which decides what `ty.storing_raw_ptr` means
(see [The peel set](#91-the-peel-set)). It is named, never
discovered: a Cargo `links` key and a `*-sys` name both over-report --
`prettyplease` carries a `links` key to detect duplicate versions of itself,
and bindgen's `clang_sys` matches the name, so discovery puts both in
libgit2-bindings' peel set and takes their `#[repr(C)]` types for C's. An unnamed `-sys` crate drops out of the walk and
the counter reads low for a reason that is not in the code, so the document
records the set it ran with in `sys_crates`.

`--seams` names the functions that only convert between a wrapper and its raw
pointer. It is established once per campaign and recorded, so every batch's
scan reads the same list: a list inferred per batch would make
`casted_to.local_seam` a measure of which agent looked harder.

## 6. The cache

A scan measures nothing if cargo serves the build from cache, so the source
roots of every workspace member are touched to a strictly future mtime first.
`time.time()` alone is not enough: two scans less than a filesystem tick apart
leave the mtime unchanged, the second is served from cache, and the document
would report a crate that was never analysed. The collector counts the crates
that emitted and raises when none did.

## 7. Sites

`--sites` takes a counter's dotted path and adds a `sites` record beside
`counts`, one list per counter, each entry a file with a count and its lines.
Paths are validated against the prefix and the family under it, not against a
list of leaves, because the ffibox arms are generated from a vocabulary. There
is no `all`: enumerating every leaf is a different request.

The path must reach a LEAF. One that stops at a family or at an `of_which` arm
validates and then reads empty, since the lookup is keyed by leaf:
`--sites ty.ffibox.wrapper.of_which.borrow.pub`, not the arm above it.

Every counter that counts a PLACE has sites, keyed by the same dotted path
`--sites` names. The line and statement counters have none -- `code.loc`,
`code.loc.unsafe` and the `code.tests` figures, whose increment is a line, so
their sites would be the file's own lines. Nothing else reads empty: a counter
whose places went in under another name would be indistinguishable from one
that has none, which is what `code.unsafe_block` and `raw_ptr.deref` did while
their sites carried the `Counts` field name they are tallied in.

A site for a macro-generated item reports the macro's **call site**, since that
is where the item's span points. A `define_ctype!(` or `impl_cdrop!(` line
among the sites of a type or impl counter is that, not a miscount.

## 8. The document

| field | contents |
|---|---|
| `crate_path` | the scanned workspace |
| `sys_crates` | the peel set it ran with |
| `scanner` | what scanned: `ffimap` (its commit, or its version outside a checkout), `toolchain`, `ffibox`, `seams` |
| `counts` | the counter tree, or `null` |
| `counts_unavailable` | why `counts` is `null`, otherwise `null` |
| `sites` | with `--sites` only |

`scanner` is section 1's determinism caveat made machine-readable. A counter
added, a rule corrected or a different framework underneath all move the
figures, so a document that did not say what produced it could not be diffed
against another: a reader could not tell a change in the crate from a change
in the scanner. The scan records itself rather than relying on a file beside
it, which can drift from the scan it describes.

The document is the only output: there is no prose rendering of the counters,
which would be a second description of the schema in a place no test reads.

What `counts` holds is decided by the flags: a counter they turn on is always
there, at `0` when it never fired, and what is absent is what they did not turn
on. Within a record the children are written in a declared order rather than
sorted. Both rules are [`schema.md`](schema.md)'s Zero, and absent and The
order of a record.

## 9. The populations

### 9.1 The peel set

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

The set is named, by `--sys-crates`, and never discovered, for the reason
[the flags](#5-the-flags-that-change-what-is-counted) give. A `-sys` crate left
unnamed drops its types out of the walk, and the counter reads low for a reason
that is not in the code; the document's `sys_crates` field records the set it
ran with, so the omission is readable beside the figures it explains.

### 9.2 What `raw_ptr.total` admits

The denominator is emitted rather than derived: the positions the crate CHOSE,
by safety and visibility. `fn_sig_arg` and `fn_sig_ret` are in it,
`fn_sig_trait_impl` is not -- for the reason that family exists, since a reader
comparing crates would otherwise be reading how often a trait is implemented --
and a `field` counts on the `safe` arm, because reading a field that holds a
pointer takes no `unsafe`, so a public one on a public type is a pointer the
interface hands over without asking for any. `deref` and `casted_to` are body
sites, not positions, and are outside it.

A `*c_void` is a raw pointer whose pointee is erased, so it is the `void` share
of the position it sits in, not a family beside it: a reader asking how many
raw pointers a signature carries does not have to add two trees, and one asking
how many are typed subtracts the share.

`raw_ptr.field.pub` is one reachability question -- can a consumer of the crate
touch the field -- so it is the type being exported AND the field being
exported, rather than two levels a reader has to combine.

### 9.3 Positions a trait fixed

`raw_ptr.fn_sig_trait_impl` holds the positions in a trait impl's method, both
directions in one counter. The three position names say where the position IS
-- an argument of a signature, its return, or a signature a trait fixed --
rather than what the fn does with the pointer, so that a reader need not know
which names are a signature's while `field` is a type's and `deref` a body's.

The crate did not choose the position there: the trait fixed the signature, one
declaration dictating a position in every impl of it, and no consumer of the
safe API is routed to it -- ffibox's `CDrop::c_drop(NonNull<T>)` is the
strategy that exists so a consumer never holds a pointer. A family mixing them
into `fn_sig_arg` or `fn_sig_ret` would move with how many types a trait is
implemented for: 61 of git2-rs' 66 raw pointers returned by a public safe fn
are its one `Binding` trait's. The direction is dropped with the choice: what
is left to say is that the trait's shape reaches a pointer here.

Which is why the family carries whose trait it was, in the same three arms as
`ty.impl_trait.of_which`: `std` for one the crate adopted, `local` for one it
declared itself, `ffibox` for the convention's, and the ffibox arm broken down
by trait. Without them the figure is a number with no reading -- on
libgit2-bindings all 64 of its positions are ffibox lifecycle strategies
(`CDrop` 36, `CDupClone` 8, `CDispose` and `CNew` and `CRefClone` 5 each,
`CLenClone` 2, `CAlloc`, `CAllocZeroed` and `CLenDrop` 1 each), on
ffmpeg-bindings 67 of 93 are, the other 26 being private helper traits of its
own (`into_void`, `to_c`, an element-adoption pair), and on git2-rs all 134 are
its one local `Binding` trait, 125 of them seams. The same count, three
different things.

`std` is zero on all three, and that is a reading too: std's traits do not put
a raw pointer in a signature -- `Drop::drop` takes `&mut self` and
`Deref::deref` returns a reference -- so a nonzero `std` arm would be a
`From<*mut T>`-shaped conversion worth looking at.

The per-trait leaves are the closed vocabulary [`ffibox.md`](ffibox.md) lists,
so a trait ffibox adds and the vocabulary does not have is in the `ffibox` arm
and in no leaf below it; the three `whose` arms leave the same hole for a
fourth crate's trait, exactly as `ty.impl_trait.of_which` does.

### 9.4 Functions and methods

`fn.*` counts every function the crate defines, the methods of its trait impls
included. A method implementing another crate's trait is still this crate's
code: that crate fixed the signature's shape, not what the body does, and
`impl Drop for Foo { fn drop }` is where a wrapper's unsafe free lives -- the
one case `fn.safe.of_which.with_unsafe` exists for. A foreign *declaration*,
an item in an `extern` block, is excluded by having no body to walk.

Counting them makes the family sensitive to boilerplate a macro wrote:
`#[derive]`, `bitflags!`, ffibox's `define_ctype!`. On libgit2-bindings that is
802 of 2755 and on git2-rs 2452 of 4134, most of the latter from `bitflags!`.
It is counted anyway -- what a macro emitted is compiled into the crate and
runs like a hand-written method, the grounds `code.unsafe_block` already
stands on -- and `fn.total.of_which.macro` carries the share, so a reader
after the hand-written total subtracts it.

`fn.sig.of_which.ffibox` reads every type a value of an argument or the return
holds or borrows, the type itself first: through the generic arguments of an
ADT, a reference's pointee, and the elements of a tuple, array or slice. That
is the walk `raw_ptr.fn_sig_arg` and `fn_sig_ret` find their pointers by, so
the two families agree on what a signature carries. It does not enter a raw
pointer, `NonNull` or `AtomicPtr`, which are positions of `raw_ptr`'s;
`PhantomData`, which holds nothing; a fn pointer, whose parameters are the
callback's interface; a trait object or an opaque type, whose bounds say what
a hidden type does rather than what it holds; or a named type's fields, which
are counted where the type is defined. Aliases are no step: the walk reads the
types typeck resolved, so a constructor returning `Result<Repository, Error>`,
with `type Repository = CBox<git_repository>`, is a `CBox` mention. A method's
receiver is not read, since its impl fixed the type.

### 9.5 Types and impls

`ty.impl_block` counts an inherent `impl T` and `ty.impl_trait` an
`impl Tr for T`. The split is the one the counters ask either side of: a trait
impl satisfies someone else's shape, an inherent block is the API the crate
wrote for its own type. Under `--ffibox` an inherent block is also split by the
self type's role in the convention, which [`ffibox.md`](ffibox.md) decides.

`ty.impl_trait.of_which.{std,local,ffibox}` is whose trait it is. A local one
is a shape the crate chose; a std or framework one it adopted. On
libgit2-bindings 1765 std, 257 ffibox, 2 local; on git2-rs 1713 std and 115
local, the latter mostly its own `Binding`.

The `std` arm is that large because of `#[derive]`, not because the crates
implement std by hand: `of_which.derived` is 1171 of libgit2-bindings' 2024
trait impls and 683 of git2-rs' 1916, so the hand-written std impls are 594
and 1030. Without that share a reader comparing vocabularies is reading how
many derives each crate spells. It is the counterpart of
`fn.total.of_which.macro`, and the reason `of_which.unsafe` skips
`TrivialClone`, the marker `#[derive(Clone)]` emits as an `unsafe impl`: on
libgit2-bindings it is 206 of 477, so counting it would make the counter mostly
derive expansions.

Every sub-classification of the same impls sits under `of_which`, nested where
it refines another share, so that the derived total stays the population: a
classification counted as a family beside `impl_trait` would be added into it,
and the record would exceed the impls there are.

`ty.total.of_which.{std_trait,local_trait,ffibox_trait,no_trait}` asks the
same of TYPES rather than impls, and is the denominator the
`ty.storing_raw_ptr` shares are read against: that family says 3 of
libgit2-bindings' 41 pointer holders implement `Drop`, and this says 317 of its
374 types implement a std trait at all. Shares, not a partition -- a type may
implement std's `Drop`, ffibox's `CDrop` and one of the crate's own traits --
with `no_trait` the residual. The cross-tabulation is recorded once, in
`ty.storing_raw_ptr.of_which`, which is the finer direction: it separates
`impl_drop` from `impl_clone` from `impl_send_sync`, which a single `std` arm
would collapse.

`ty.storing_raw_ptr.of_which`'s first six shares read std traits, so a crate
that declares its lifecycle through a framework says something none of them can
see. The `ffibox` share is that statement, and
[`ffibox.md`](ffibox.md#7-why-ffibox-is-a-declaration-share) is why it belongs
beside them. `pub_field` is not a declaration and does not rescue a type from
the residual -- it is the opposite, an access the type does not govern.

`ty.generic`'s arms are shares, a type being able to carry both kinds of
parameter at once. On libgit2-bindings 199 of 374 types are generic, 195 over a
lifetime and 5 over a type, and 23 of them hold a raw pointer.

### 9.6 Test code

`code.tests` is the test code, and every other counter is the library without
it. `cargo build` enables no `cfg(test)` and builds nothing under `tests/`, so
the test code was invisible rather than excluded by a rule -- on
libgit2-bindings 92693 lines against the library's 16081, and 4909 fns against
2755.

The exclusion is two mechanisms, not one rule. In the library build `cfg(test)`
is off, so rustc strips those items during expansion and they never reach HIR:
there is nothing to traverse. In the `--test` build they are there and the
driver does walk them -- along with the whole library, which a lib test target
recompiles -- but only `code.tests.*` is emitted and the library-shaped
counters are computed and discarded. So a test's own types, signatures and
conversions are nowhere: a type that holds a raw pointer inside `#[cfg(test)]`
is in no `ty` population, and its unsafe blocks and FFI calls are in no `code`
total.

Only the quantities that mean the same thing for a test as for a library are
there: its size, its fns and its unsafe. The rest of the tree asks what a
crate's API hands its consumers, which a test harness has none of.

A lib's test target recompiles the library with `cfg(test)` on, so its figures
include the library's; they are subtracted, keyed on the crate name it shares
with the non-test emission. An integration test crate shares its name with no
library, so nothing is subtracted from it, and a build script is skipped --
under `--all-targets` it is its own crate, and it builds the crate rather than
being part of it.

## 10. Calls

### 10.1 Classifying a call

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

### 10.2 `code.unsafe_call`

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

## 11. `raw_ptr.casted_to`

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

### 11.1 The std table

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

### 11.2 The ffibox table

Derived from ffibox's adoption methods crossed with its primitives, as
[`ffibox.md`](ffibox.md) describes.

### 11.3 `other`

`std.other` and `ffibox.other` are structurally zero, every name in those
tables mapping to a known shape, so a nonzero reading means the name table and
the shape classifier have drifted apart. `local_seam.other` is a real arm: a
declared seam's shape is read from its return type, which may be a handle
neither table knows.

## 12. What the analysis cannot see

`raw_ptr.casted_to` is a filter, not a partition. A crate that hand-rolls a
conversion and does not declare it in `--seams` is invisible, not filed under
`other`. This bites hardest in an audit, where the seam list starts empty: a low
`local_seam` there means nothing was declared, not that nothing was
hand-rolled.

`ty.storing_raw_ptr` reads what the peel set admits, so its population moves
with the `-sys` crates named. Figures from different invocations are comparable
only with the same list.

`code.unsafe_call.rust` is dominated by the standard library. On the canary
fixture it reads 13, of which 1 is a call to the crate's own `unsafe fn` and
12 are std's unsafe constructors -- `Box::from_raw` and its siblings, the same
calls `casted_to` already classifies. The arm is therefore not a measure of the
crate's own unsafety ([`TODO.md`](TODO.md) carries the split that would make it
one).
