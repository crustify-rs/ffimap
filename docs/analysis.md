# The analysis

This document says what produces a scan's document, what the scan requires,
and what each counter is decided from: the populations the passes walk, the
tests that classify a call or a conversion, and what the analysis cannot see.
[`schema.md`](schema.md) describes the counters themselves: what each one
holds and how a report is built from them. [`ffibox.md`](ffibox.md) describes
the ffibox vocabulary.

Sections 1 to 8 say how a scan runs. Sections 9 onwards say how each family is
decided.

## 1. Determinism, and what it rests on

The document is a pure function of the source tree **under a fixed scanner**.
Two runs over one tree agree byte for byte, so a diff between them is a change
in the crate. That holds only if the ffimap commit, the flags and any
framework the crate is built on are the same. When you record a scan, record
those three beside it. Otherwise a later diff cannot tell a change in the
crate from a change in the scanner.

## 2. The toolchain

A `rustc_private` driver compiles only against the compiler internals it was
written for. So the nightly is pinned by date in
`src/ffimap/driver/rust-toolchain.toml`, and both the driver and the scanned
workspace build on it. The driver needs the nightly's `rustc-dev` and
`llvm-tools` components.

## 3. The build

```sh
cargo +<pinned nightly> check --all-targets
```

The build is `check`, not `build`. The driver reports from `after_analysis`,
so HIR and typeck are all it needs, and `--emit=metadata` links nothing.
Linking would make the scan fail where it otherwise succeeds: a wrapper's test
binaries link the C library, and a fixture's `extern` declarations may have no
implementation at all.

The build passes `--all-targets`, not `--tests`. `--tests` checks the test
targets *instead of* the plain library, and the library's emission is the
scan.

The scan needs the workspace to compile. When the workspace does not compile,
`counts` is `null` and `counts_unavailable` carries the reason. In that case
ffimap reports no counts rather than approximate ones.

## 4. The emission protocol

The driver runs as `RUSTC`, so it sees one invocation per crate per target.
Each invocation prints one line:

```json
{"crate": "<name>", "test": false, "counts": {"<dotted path>": 12}, "sites": {}}
```

Four rules decide what the Python side does with a line.

- **`CARGO_PRIMARY_PACKAGE`.** Without this variable, `after_analysis` returns
  early, so only workspace members emit and dependencies are silent. A
  workspace member that another member depends on is built in a dependency
  unit, where the variable is unset. That is why a `-sys` crate inside the
  scanned workspace emits nothing. The next rule drops such a crate too, so
  nothing is lost.
- **`-sys` crates are skipped.** A crate is skipped when its name has a
  `*_sys` suffix or when `--sys-crates` names it. The generated bindings of a
  `-sys` crate are not the audit subject. Its types are still walked into, as
  [the peel set](#91-the-peel-set).
- **Bindings that are a module of the scanned crate.** You name such a module
  to `--sys-crates` by its path, `crate::<path>`. When a module is named, its
  own items, and the items of the modules below it:
  - join the `-sys` inventory (`ty.ffibox.sys`, `fn.ffibox.sys`, and what the
    wrapper counters resolve against), as a named crate's items do; and
  - drop out of every other counter, as a named crate's items do, which are
    another crate's and are never scanned.

  They drop out because the bindings' own derives, impls and declarations are
  not the crate's code, and do not count as uses of the types they declare. A named crate gives
  the items a dependent can reach. A named module gives every item it defines,
  private ones included. A module that is left unnamed is the crate's own
  code, except in the counters that skip a file that is named `bindings.rs` or
  written to `OUT_DIR`.
- **`build_script_build` is skipped.** Under `--all-targets` a build script is
  its own crate. It builds the crate; it is not part of the crate. If it were
  left in, it would add 128 lines to libgit2-bindings' library count.
- **`--test` routes a line to `code.tests`.** Cargo passes `--test` for the
  lib's test target and for each integration test crate, so the driver tells
  test code from the library without inspecting an item. A lib test target
  recompiles the library with `cfg(test)` on, so its figures include the
  library's. The library's figures are subtracted, keyed on the crate name
  that the test target shares with the non-test emission. An integration test
  crate shares its name with no library, so nothing is subtracted from it.

## 5. The flags that change what is counted

Four inputs change the figures and belong with any recorded scan.

`--sys-crates` is the peel set, which decides what `ty.storing_raw_ptr` means
(see [The peel set](#91-the-peel-set)). The set is named, never discovered,
because a Cargo `links` key and a `*-sys` name both over-report.
`prettyplease` carries a `links` key to detect duplicate versions of itself,
and bindgen's `clang_sys` matches the name. So discovery puts both in
libgit2-bindings' peel set and takes their `#[repr(C)]` types for C's. When a
`-sys` crate is left unnamed, it drops out of the walk and the counter reads
low for a reason that is not in the code. So the document records the set it
ran with in `sys_crates`.

`--seams` names the functions that only convert between a wrapper and its raw
pointer. The list is established once per campaign and recorded, so that every
batch's scan reads the same list. Here a campaign is one project of
Crustify, the agent harness that uses ffimap: it wraps a C library in Rust,
ports C code to Rust, or audits an existing Rust crate. A batch is one unit
of a campaign's work, and one coding agent carries it out. A list inferred per batch would make
`casted_to.local_seam` a measure of which agent looked harder.

`--barriers` names the crate's own panic barriers: the helpers that a callback
calls in place of `catch_unwind`. They are named for the reason `--seams`
names its seams.

`--regions` names the modules that a crate confines a kind of code to, such as
its unsafe FFI. Which modules those are is the crate's design, not a fact the
compiler states. So they are named, and they are recorded in the document's
`scanner` as the seams are. See
[Regions](#97-regions-and-the-c-abi-boundary).

`--features` names the Cargo features that the scanned build enables beside
its defaults. Code that a feature gates is compiled, and so counted, only when
the feature is named. An example is an export gateway that stays behind a
feature of its own until it is linked. Code behind an unnamed feature reads as
no code at all. The set is recorded in `features`, and two scans are compared
only when it is the same.

## 6. The cache

A scan measures nothing if cargo serves the build from cache. So ffimap first
touches the source roots of every workspace member to a strictly future mtime.
`time.time()` alone is not enough. Two scans less than a filesystem tick apart
leave the mtime unchanged. The second scan is then served from cache, and the
document would report a crate that was never analysed. The collector counts
the crates that emitted and raises an error when none did.

## 7. Sites

`--sites` takes a counter's dotted path and adds a `sites` record beside
`counts`. The record holds one list per counter, and each entry of a list is a
file with a count and its lines. Paths are validated against the prefix and
the family under it, not against a list of leaves, because the ffibox arms are
generated from a vocabulary. There is no `all`: enumerating every leaf is a
different request.

The path must reach a LEAF. A path that stops at a family or at an `of_which`
arm validates and then reads empty, because the lookup is keyed by leaf. Write
`--sites ty.ffibox.wrapper.as.borrowed.std.pub`, not the arm above it.

Every counter that counts a PLACE has sites, keyed by the same dotted path
that `--sites` names. The line and statement counters have none: `code.loc`,
`code.loc.unsafe` and the `code.tests` figures. Their increment is a line, so
their sites would be the file's own lines.

No other counter reads empty. A counter whose places were recorded under
another name could not be told from a counter that has none.
`code.unsafe_block` and `raw_ptr.deref` were in that state while their sites
carried the name of the `Counts` field they are tallied in.

A site for a macro-generated item reports the macro's **call site**, because
that is where the item's span points. A `define_ctype!(` or `impl_cdrop!(`
line among the sites of a type or impl counter is such a call site, not a
miscount.

## 8. The document

| field | contents |
|---|---|
| `crate_path` | the scanned workspace |
| `sys_crates` | the peel set it ran with |
| `scanner` | what scanned: `ffimap`, `toolchain`, `ffibox`, `seams`, `regions`, `barriers`, `features`. `ffimap` is its commit, with `+dirty.<hash of the changes>` where tracked changes are not committed. Outside a checkout of its own, it is ffimap's version, which names no one scanner |
| `counts` | the counter tree, or `null` |
| `counts_unavailable` | why `counts` is `null`, otherwise `null` |
| `sites` | with `--sites` only |

`scanner` makes section 1's determinism caveat machine-readable. A counter
added, a rule corrected or a different framework underneath all move the
figures. So a document that did not say what produced it could not be diffed
against another: a reader could not tell a change in the crate from a change
in the scanner. The scan records itself and does not rely on a file beside it,
because such a file can drift from the scan it describes.

The document is the only output. There is no prose rendering of the counters:
it would be a second description of the schema, in a place no test reads.

The flags decide what `counts` holds: a counter that they turn on is always
there, at `0` when it never fired. A counter that is absent is one that the
flags did not turn on. Within a record, the children are written in a declared
order, not sorted. Both rules are [`schema.md`](schema.md)'s Zero, and absent
and The order of a record.

## 9. The populations

### 9.1 The peel set

A type stores a raw pointer when the walk over its fields reaches one. The
walk descends through the types defined in the scanned crate and in the `-sys`
crates named on the command line. It stops at every other crate, the standard
library included.

The rule is deliberately narrow, and it decides what the counter means. A
pointer inside `Vec` is the standard library's to manage, not the crate's. A
pointer inside an ffibox owner is ffibox's, so a type that holds a `CBox` is
not a `ty.storing_raw_ptr`. It appears under `ty.field.ffibox` instead. The
population is therefore the types that manage a pointer themselves. Delegation
is counted separately and is not silently folded in.

The set is named by `--sys-crates` and never discovered, for the reason
[the flags](#5-the-flags-that-change-what-is-counted) give. A `-sys` crate
that is left unnamed drops its types out of the walk, and the counter reads
low for a reason that is not in the code. The document's `sys_crates` field
records the set it ran with, so the omission is readable beside the figures it
explains.

### 9.2 What `raw_ptr.total` admits

The denominator is emitted, not derived. It holds the positions the crate
CHOSE, by safety and visibility:

- `fn_sig_arg` and `fn_sig_ret` are in it.
- `fn_sig_trait_impl` is not, for the reason that family exists: a reader who
  compares crates would otherwise be reading how often a trait is implemented.
- A `field` counts on the `safe` arm. Reading a field that holds a pointer
  takes no `unsafe`, so a public field on a public type is a pointer that the
  interface hands over without asking for any.
- `deref` and `casted_to` are body sites, not positions, and are outside it.

A `*c_void` is a raw pointer whose pointee is erased, so it is the `void`
share of the position it sits in, not a family beside it. A reader who asks
how many raw pointers a signature carries does not have to add two trees, and
a reader who asks how many are typed subtracts the share.

`raw_ptr.field.pub` is one reachability question: can a consumer of the crate
touch the field? So it is the type being exported AND the field being
exported, not two levels that a reader has to combine.

### 9.3 Positions a trait fixed

`raw_ptr.fn_sig_trait_impl` holds the positions in a trait impl's method, both
directions in one counter. The three position names say where the position IS:
an argument of a signature, its return, or a signature a trait fixed. They do
not say what the fn does with the pointer. This way a reader need not know
which names are a signature's, while `field` is a type's and `deref` is a
body's.

The crate did not choose the position there. The trait fixed the signature:
one declaration dictates a position in every impl of it. And no consumer of
the safe API is routed to it: ffibox's `CDrop::c_drop(NonNull<T>)` is the
strategy that exists so that a consumer never holds a pointer. A family that
mixed these positions into `fn_sig_arg` or `fn_sig_ret` would move with how
many types a trait is implemented for: 61 of git2-rs' 66 raw pointers returned
by a public safe fn are its one `Binding` trait's. The direction is dropped
with the choice. What is left to say is that the trait's shape reaches a
pointer here.

For that reason the family carries whose trait it was, in the same three arms
as `ty.impl_trait.of_which`: `std` for a trait the crate adopted, `local` for
one it declared itself, and `ffibox` for the convention's. The `ffibox` arm is
broken down by trait. Without the arms, the figure is a number with no
reading:

- On libgit2-bindings, all 64 of its positions are ffibox lifecycle strategies
  (`CDrop` 36, `CDupClone` 8, `CDispose` and `CNew` and `CRefClone` 5 each,
  `CLenClone` 2, `CAlloc`, `CAllocZeroed` and `CLenDrop` 1 each).
- On ffmpeg-bindings, 67 of 93 are. The other 26 are private helper traits of
  its own (`into_void`, `to_c`, an element-adoption pair).
- On git2-rs, all 134 are its one local `Binding` trait, and 125 of them are
  seams.

The same count is three different things.

`std` is zero on all three, and that is a reading too. std's traits do not put
a raw pointer in a signature, since `Drop::drop` takes `&mut self` and
`Deref::deref` returns a reference. So a nonzero `std` arm would be a
`From<*mut T>`-shaped conversion worth looking at.

The per-trait leaves are the closed vocabulary that [`ffibox.md`](ffibox.md)
lists, so a trait that ffibox adds and the vocabulary does not have is in the
`ffibox` arm and in no leaf below it. The three `whose` arms leave the same
hole for a fourth crate's trait, exactly as `ty.impl_trait.of_which` does.

### 9.4 Functions and methods

`fn.*` counts every function the crate defines, the methods of its trait impls
included. A method that implements another crate's trait is still this crate's
code: that crate fixed the signature's shape, not what the body does.
`impl Drop for Foo { fn drop }` is where a wrapper's unsafe free lives, and it
is the one case `fn.safe.of_which.with_unsafe` exists for. A foreign
*declaration*, an item in an `extern` block, is excluded because it has no
body to walk.

Counting them makes the family sensitive to boilerplate that a macro wrote:
`#[derive]`, `bitflags!`, ffibox's `define_ctype!`. On libgit2-bindings that
is 802 of 2755 and on git2-rs 2452 of 4134, most of the latter from
`bitflags!`. It is counted anyway. What a macro emitted is compiled into the
crate and runs like a hand-written method, which is the grounds
`code.unsafe_block` already stands on. `fn.total.of_which.macro` carries the
share, so a reader who wants the hand-written total subtracts it.

`fn.unsafe`'s shares say what made an `unsafe fn` unsafe when the crate did
not:

- `in_trait_impl` is a method of a trait impl, by whose trait it is, in the
  same arms as `ty.impl_trait.of_which`: the trait's declaration made the
  method unsafe, and an impl cannot declare it safe. A method of a trait's own
  default body is the crate's choice, not an impl's, and is not in this share.
- `seam` is a fn that `--seams` names, matched by name as `raw_ptr`'s seam
  shares are.

The two overlap: git2-rs's `Binding::from_raw` is both. So the residual is
emitted, as `other`, and is not left for a reader to subtract.

`fn.sig.of_which.ffibox` reads every type that a value of an argument or of
the return holds or borrows, the type itself first. It reads through the
generic arguments of an ADT, a reference's pointee, and the elements of a
tuple, array or slice. That is the walk by which `raw_ptr.fn_sig_arg` and
`fn_sig_ret` find their pointers, so the two families agree on what a
signature carries. The walk does not enter:

- a raw pointer, `NonNull` or `AtomicPtr`, which are positions of `raw_ptr`'s;
- `PhantomData`, which holds nothing;
- a fn pointer, whose parameters are the callback's interface;
- a trait object or an opaque type, whose bounds say what a hidden type does,
  not what it holds; or
- a named type's fields, which are counted where the type is defined.

Aliases are no step, because the walk reads the types that typeck resolved. So
a constructor that returns `Result<Repository, Error>`, with
`type Repository = CBox<git_repository>`, is a `CBox` mention. A method's
receiver is not read, because its impl fixed the type.

`fn.extern_abi` is every fn with a body whose signature's ABI is not Rust's.
An `extern` block's declarations have no body. `exported` reads the codegen
attributes that rustc resolved, so `#[unsafe(no_mangle)]` and `#[export_name]`
are one fact.

`catches_unwind` is a call in the fn's own body to one of these:

- std's `catch_unwind`;
- a fn that `--barriers` named; or
- under `--ffibox`, ffibox's `callback::barrier`.

The call is identified by the callee's definition or, for a named barrier, by
its name. A barrier inside a helper that the body calls is seen only where the
helper is named: following the call into the helper would be data flow.
git2-rs's callbacks call its own `panic::wrap`. On git2-rs the share reads 0
of 42 without `--barriers wrap` and 39 with it. The other three, `append`,
`tracing_cb_c` and `smart_factory`, call no barrier at all.

`fn.sig.of_which.c_type` and `fn.sig.of_which.result` leave a trait impl's
methods out, for the reason `fn_sig_trait_impl` exists: the trait chose those
signatures, so `fmt`'s `fmt::Result` is `Display`'s. `c_type` is read off the
signature as written, the HIR, because typeck resolves `c_int` to `i32` and
the name, which is the fact, is gone. Each of these is one mention, wherever
it sits in the type:

- a path to a type alias that `core::ffi` or `std::os::raw` declares with a
  `c_` name;
- a path to any alias of `libc`; and
- a fn pointer with a foreign ABI.

`c_void` is an enum, not an alias. It is `raw_ptr`'s, through the pointer that
holds it.

### 9.5 Types and impls

`ty.impl_block` counts an inherent `impl T`, and `ty.impl_trait` counts an
`impl Tr for T`. The split is the one the counters ask either side of: a trait
impl satisfies someone else's shape, and an inherent block is the API the
crate wrote for its own type. Under `--ffibox` an inherent block is also split
by the self type's role in the convention, which [`ffibox.md`](ffibox.md)
decides.

`ty.impl_trait.of_which.{std,local,ffibox}` is whose trait it is. A local
trait is a shape the crate chose. A std or framework trait is one it adopted.
libgit2-bindings has 1765 std, 257 ffibox and 2 local. git2-rs has 1713 std
and 115 local, the latter mostly its own `Binding`.

The `std` arm is that large because of `#[derive]`, not because the crates
implement std by hand. `of_which.derived` is 1171 of libgit2-bindings' 2024
trait impls and 683 of git2-rs' 1916, so the hand-written std impls are 594
and 1030. Without that share, a reader who compares vocabularies is reading
how many derives each crate spells. The share is the counterpart of
`fn.total.of_which.macro`. It is also the reason `of_which.unsafe` skips
`TrivialClone`, the marker that `#[derive(Clone)]` emits as an `unsafe impl`:
on libgit2-bindings it is 206 of 477, so counting it would make the counter
mostly derive expansions.

Every sub-classification of the same impls sits under `of_which`, nested where
it refines another share. That keeps the derived total the population: a
classification counted as a family beside `impl_trait` would be added into the
total, and the record would exceed the impls there are.

`ty.total.of_which.{std_trait,local_trait,ffibox_trait,no_trait}` asks the
same of TYPES, not impls. It is the denominator that the `ty.storing_raw_ptr`
shares are read against: that family says 3 of libgit2-bindings' 41 pointer
holders implement `Drop`, and this one says 317 of its 374 types implement a
std trait at all. These are shares, not a partition: a type may implement
std's `Drop`, ffibox's `CDrop` and one of the crate's own traits. `no_trait`
is the residual. The cross-tabulation is recorded once, in
`ty.storing_raw_ptr.of_which`, which is the finer direction: it separates
`impl_drop` from `impl_clone` from `impl_send_sync`, which a single `std` arm
would collapse.

The first six shares of `ty.storing_raw_ptr.of_which` read std traits, so a
crate that declares its lifecycle through a framework says something that none
of them can see. The `ffibox` share is that statement, and
[`ffibox.md`](ffibox.md#7-why-ffibox-is-a-declaration-share) is why it belongs
beside them. `pub_field` is not a declaration, and it does not rescue a type
from the residual. It is the opposite: an access the type does not govern.

`ty.generic`'s arms are shares, because a type can carry both kinds of
parameter at once. On libgit2-bindings 199 of 374 types are generic, 195 over
a lifetime and 5 over a type, and 23 of them hold a raw pointer.

`ty.total.of_which.repr_c` and `repr_transparent` read the representation that
rustc resolved for the type. `ty.total.of_which.std_impl` reads the crate's
trait impls whose trait is a std one of its fixed list and whose self type is
the crate's own, derived or written. A type counts once per trait, however
many impls it has (`From<u32>` and `From<i64>` are one `From`).

`static.*` is every static item with a definition. Its `exported` share is
read from the item's attributes, as a fn's is. A static that an `extern` block
declares is C's and is not the crate's.

### 9.6 Test code

`code.tests` is the test code, and every other counter is the library without
it. `cargo build` enables no `cfg(test)` and builds nothing under `tests/`, so
the test code was invisible, not excluded by a rule. On libgit2-bindings it is
92693 lines against the library's 16081, and 4909 fns against 2755.

The exclusion is two mechanisms, not one rule:

- In the library build, `cfg(test)` is off. So rustc strips those items during
  expansion and they never reach HIR: there is nothing to traverse.
- In the `--test` build, the items are there and the driver does walk them,
  along with the whole library, which a lib test target recompiles. But only
  `code.tests.*` is emitted. The library-shaped counters are computed and
  discarded.

So a test's own types, signatures and conversions are nowhere. A type that
holds a raw pointer inside `#[cfg(test)]` is in no `ty` population, and its
unsafe blocks and FFI calls are in no `code` total.

Only the quantities that mean the same thing for a test as for a library are
there: its size, its fns and its unsafe. The rest of the tree asks what a
crate's API hands its consumers, which a test harness has none of.

A lib's test target recompiles the library with `cfg(test)` on, so its figures
include the library's. They are subtracted, keyed on the crate name that the
test target shares with the non-test emission. An integration test crate
shares its name with no library, so nothing is subtracted from it. A build
script is skipped: under `--all-targets` it is its own crate, and it builds
the crate; it is not part of the crate.

### 9.7 Regions and the C-ABI boundary

A body is in a region when a module that encloses it carries a name that
`--regions` named. The enclosing modules are found by walking out through
closures, fns and impls. The innermost such module names the region, so a
module nested in a region is in it. The rule is the module tree alone: a
region is wherever the crate put it.

`code.unsafe_block.of_which.ffi_export` is decided differently, by the fn. A
block is in it when its fn, or the fn that a closure is in, has a foreign ABI
or a C symbol name. It needs no input, so it stays beside the regions. The two
agree where a crate puts its exports in a region and its region holds nothing
else.

`outside_regions` includes the blocks that another crate's macro expands into
the crate's code, std's `write!` and `format_args!` among them. They are
compiled into the crate like any other block, and they are what a lint on the
crate's own source cannot see.

## 10. Calls

### 10.1 Classifying a call

The callee's signature is read from the type of the callee expression. That
type carries an ABI and a safety whether or not the callee resolves to an
item:

```rust
match typeck.expr_ty_adjusted(callee).kind() {
    ty::FnDef(did, args) => { /* tcx.fn_sig(did).instantiate(..) */ }
    ty::FnPtr(_, hdr)    => { /* hdr.abi(), hdr.safety */ }
    _ => None,                       // Fn-trait call, not a direct call
}
```

A `MethodCall` has no callee expression. Its `DefId` comes from
`typeck.type_dependent_def_id` and takes the `FnDef` path.

`is_foreign_item` is not used. It is a property of the declaration site. The
ABI is part of the function's type, so it survives being stored in a field or
passed as an argument. That is what admits calls through function pointers,
which have no item to ask. Invoking a stored `extern "C"` callback is one of
those calls.

### 10.2 `code.unsafe_call`

Safety decides whether a call counts, and ABI decides which arm it lands in.

| signature | arm |
|---|---|
| `safety == Safe` | not counted |
| `tcx.intrinsic(did).is_some()` | `intrinsic` |
| `abi != Rust` | `ffi` |
| otherwise | `rust` |

Safety gates membership because an `extern "C" fn` *defined in Rust* is safe
to call. The `ffi_export` gateways of a port campaign, a Crustify campaign
that reimplements C code in Rust, have a C ABI but cross no boundary and
discharge no obligation. Foreign declarations keep their `Unsafe` safety, so
the real crossings still land in `ffi`.

Intrinsics are tested with `tcx.intrinsic`, not by ABI. Current rustc marks
them `#[rustc_intrinsic]` with the Rust ABI, so an ABI test would file
`transmute` under `rust`.

### 10.3 What crosses to C

`code.fn_ptr.extern_abi` is a fn item turned into a fn pointer, where the
item's ABI is foreign. The fn item is turned into a fn pointer by the
`ReifyFnPointer` coercion that typeck records on an expression, or by an `as`
cast to a fn pointer type. The arm is read off the item:

- `foreign` is an `extern` block's declaration, whichever crate declares it;
- `local` is a definition of the crate's own; and
- `other` is any other item.

ffibox hands its trampolines out from inside ffibox, so the crate sees a call,
not a coercion. Under `--ffibox`, a call to ffibox's `trampoline`,
`release_fn` or `release_fn_of` is the counter's `ffibox` arm.

`code.call.ffibox` is any call, safe or not, to a fn of ffibox's `status`
module, or to `callback::barrier`.

## 11. `raw_ptr.casted_to`

The counter has two axes: whose vocabulary the conversion belongs to, and what
shape the pointer became. Conversions are recognised by name, never inferred
from types, because a type rule cannot show that the output derives from the
pointer input.

| arm | names from | shape from |
|---|---|---|
| `std` | the (krate, type, method) table below | the table |
| `ffibox` | `<primitive>` x the adoption methods | the primitive's group |
| `local_seam` | `--seams` / `UM_SEAM_FNS` | the seam's return type |

A declared seam needs no derivation proof. The declaration states that the
function is a conversion, and only its shape is read from the return type.

### 11.1 The std table

```
borrow   <*const T>::as_ref   <*mut T>::as_mut   NonNull::as_ref   NonNull::as_mut
slice    slice::from_raw_parts    slice::from_raw_parts_mut
         slice::from_ptr_range    slice::from_mut_ptr_range
string   CStr::from_ptr   CString::from_raw   String::from_raw_parts
owner    Box::from_raw   Vec::from_raw_parts   Rc::from_raw   Arc::from_raw
```

Matching is on (crate, type, method). It is gated on `did.krate` being `core`,
`alloc` or `std`, so a custom `Box::from_raw` cannot collide.

`CString` and `String` are `string`, not `owner`. The bucket records what
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

`std.other` and `ffibox.other` are structurally zero, because every name in
those tables maps to a known shape. So a nonzero reading means that the name
table and the shape classifier have drifted apart. `local_seam.other` is a
real arm: a declared seam's shape is read from its return type, which may be a
handle that neither table knows.

### 11.4 `raw_ptr.surrendered`

This counter is the other direction, decided by the same means. It counts a
call whose callee is a std or ffibox definition that turns an owned value into
a raw pointer. The callee is matched by owner and method in a table:

- std's table is `Box`'s `into_raw` and `into_non_null`, `Vec::into_raw_parts`,
  `Rc` and `Arc`'s `into_raw` (`owner`), and `CString::into_raw` and
  `String::into_raw_parts` (`string`).
- ffibox's table is `into_raw`, `into_c` and `into_raw_parts` on any
  primitive, by the primitive's shape.

A hand-rolled conversion is not seen, as for `casted_to`.

## 12. What the analysis cannot see

`raw_ptr.casted_to` is a filter, not a partition. A conversion that a crate
hand-rolls and does not declare in `--seams` is invisible; it is not filed
under `other`. This bites hardest in an audit of an existing crate, where the
seam list starts empty: a low `local_seam` there means that nothing was
declared, not that nothing was hand-rolled.

`ty.storing_raw_ptr` reads what the peel set admits, so its population moves
with the `-sys` crates named. Figures from different invocations are
comparable only with the same list.

`code.unsafe_call.rust` is dominated by the standard library. On the canary
fixture it reads 13. Of those, 1 is a call to the crate's own `unsafe fn` and
12 are std's unsafe constructors: `Box::from_raw` and its siblings, the same
calls that `casted_to` already classifies. The arm is therefore not a measure
of the crate's own unsafety. [`TODO.md`](TODO.md) carries the split that would
make it one.
