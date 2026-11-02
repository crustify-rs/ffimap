# Counter schema

The counters ffimap reports: what each one holds, how a record is shaped, and
how a report is built from them. Every counter is determined from declarations
and single expression nodes -- no value is followed, no cast chain is composed,
and no dataflow is performed.

What each counter is decided FROM, and how a scan runs, is
[`analysis.md`](analysis.md); the ffibox vocabulary the `<trait>` and
`<primitive>` arms are generated from is [`ffibox.md`](ffibox.md).

## 1. The counters

Each row below is one counter, named by its dotted path into the document's
`counts`. A `{a,b}` is a split the counter carries: `raw_ptr.field.{pub,priv}`
is two leaves, and every row's leaves are integers. Each partition also carries
a `total`, derived from its children unless the driver emits it, so
`raw_ptr.field.total` exists and `raw_ptr.field.pub + raw_ptr.field.priv`
equals it; the `of_which` rows are shares of the row above them and are never
summed ([2.1](#21-partitions-and-shares)).

The counters are the whole of the document's `counts`. There is no second,
flat counter block beside them, and no prose rendering of them: a reader who
wants a rate divides the leaves it names.

Across the tree, `unsafe` and `safe` are the safety of the *function* the
position or site is in, `pub` and `priv` whether a consumer of the crate can
reach the item, and `void` a pointer whose pointee is erased (`*c_void`). A row
naming `ffibox`, a `<trait>` or a `<primitive>` is present only under
`--ffibox`, and an `of_which.seam` row only with `--seams`; both are absent
rather than zero otherwise ([2.3](#23-zero-and-absent)).

### 1.1 `raw_ptr`

The raw pointers the crate declares in its signatures and types, and what its
bodies do with them.

- `raw_ptr.total.{safe,unsafe}.{pub,priv}` -- the denominator: every
  raw-pointer position the crate CHOSE, which is `fn_sig_arg` plus
  `fn_sig_ret` plus `field`. Emitted rather than derived, so it is not a sum of
  the families beside it ([analysis 9.2](analysis.md#92-what-raw_ptrtotal-admits)).
- `raw_ptr.fn_sig_arg.{safe,unsafe}.{pub,priv}` -- raw pointers an argument of
  a signature takes. Taking is the hazard: a safe fn that takes one lets a
  caller pass anything with no `unsafe` at the call site.
- `raw_ptr.fn_sig_arg.of_which.void.{safe,unsafe}.{pub,priv}` -- of those, the
  erased ones. Subtract the share for the typed ones.
- `raw_ptr.fn_sig_arg.of_which.seam.{safe,unsafe}.{pub,priv}` -- of those, the
  ones in a function `--seams` declared to be nothing but a conversion between
  a wrapper and its raw pointer.
- `raw_ptr.fn_sig_ret.{safe,unsafe}.{pub,priv}` -- raw pointers a signature
  returns. Returning one still forces the caller to write `unsafe` before it
  means anything, which is why it is counted apart from `fn_sig_arg`.
- `raw_ptr.fn_sig_ret.of_which.void.{safe,unsafe}.{pub,priv}` -- as above.
- `raw_ptr.fn_sig_ret.of_which.seam.{safe,unsafe}.{pub,priv}` -- as above.
- `raw_ptr.fn_sig_trait_impl.{safe,unsafe}.{pub,priv}` -- positions in a trait
  impl's method, both directions in one counter: a trait declaration fixed the
  signature, so the crate did not choose the position, and the figure would
  otherwise move with how many types a trait is implemented for
  ([analysis 9.3](analysis.md#93-positions-a-trait-fixed)).
- `raw_ptr.fn_sig_trait_impl.of_which.void.{safe,unsafe}.{pub,priv}` -- as above.
- `raw_ptr.fn_sig_trait_impl.of_which.seam.{safe,unsafe}.{pub,priv}` -- as above.
- `raw_ptr.fn_sig_trait_impl.of_which.std.{safe,unsafe}.{pub,priv}` -- of
  those, the ones a standard-library trait fixed.
- `raw_ptr.fn_sig_trait_impl.of_which.local.{safe,unsafe}.{pub,priv}` -- the
  ones a trait the crate declared itself fixed.
- `raw_ptr.fn_sig_trait_impl.of_which.ffibox.{safe,unsafe}.{pub,priv}` -- the
  ones an ffibox contract fixed, which for a crate built on the convention is
  its lifecycle strategies.
- `raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.<trait>` -- those by
  trait, over the whole vocabulary, so a document says which contracts reach a
  raw pointer and which do not. No safety or visibility split: a trait method's
  are the declaration's ([2.5](#25-deliberate-asymmetries)).
- `raw_ptr.field.{pub,priv}` -- struct and union fields declared with a raw
  pointer. `pub` is one reachability question, the type exported AND the field
  exported, rather than two levels a reader has to combine.
- `raw_ptr.field.of_which.void.{pub,priv}` -- of those, the erased ones.
- `raw_ptr.deref.{rd,wr}` -- dereference sites in bodies, by whether the place
  is read or written. Sites, not positions, so they are outside `raw_ptr.total`.
- `raw_ptr.casted_to.std.{owner,string,borrow,slice,other}` -- a raw pointer
  converted into a standard-library shape, by the shape it became: an owner
  (`Box`, `Vec`, `Rc`, `Arc`), a string (`CStr`, `CString`, `String`), a
  borrow, a slice. `other` is a shape the table does not know, which for `std`
  is none of them ([analysis 11.3](analysis.md#113-other)).
- `raw_ptr.casted_to.ffibox.{owner,string,borrow,slice}` -- adopted into an
  ffibox primitive, by the primitive's group. There is no `other` arm: every
  primitive maps to a shape.
- `raw_ptr.casted_to.local_seam.{owner,string,borrow,slice,other}` -- converted
  through a function `--seams` named, by the seam's return type. `other` is a
  seam returning a bespoke handle.

### 1.2 `ty`

The types the crate defines, by what they hold and what they declare about it.

- `ty.total.{pub,priv}` -- every type the crate defines. Emitted, and the
  denominator its shares are read against.
- `ty.total.of_which.std_trait.{pub,priv}` -- of those, the types that
  implement a standard-library trait.
- `ty.total.of_which.local_trait.{pub,priv}` -- the types that implement a
  trait the crate declared itself.
- `ty.total.of_which.ffibox_trait.{pub,priv}` -- the types that implement an
  ffibox contract.
- `ty.total.of_which.no_trait.{pub,priv}` -- the residual: types that
  implement no trait at all.
- `ty.storing_raw_ptr.{pub,priv}` -- types whose fields reach a raw pointer,
  within the peel set, so these are the types that manage one themselves
  rather than delegating to `Vec` or to an ffibox owner
  ([analysis 9.1](analysis.md#91-the-peel-set)).
- `ty.storing_raw_ptr.of_which.impl_drop.{pub,priv}` -- of those, the ones that
  implement `Drop`: they free memory Rust did not allocate.
- `ty.storing_raw_ptr.of_which.impl_clone.{pub,priv}` -- the ones that
  implement `Clone`, where a shallow clone duplicates the pointer and, with
  `Drop`, double-frees it.
- `ty.storing_raw_ptr.of_which.{impl_deref,impl_deref_mut}.{pub,priv}` -- the
  ones that hand out a reference derived from the pointer implicitly, at every
  call site.
- `ty.storing_raw_ptr.of_which.impl_send_sync.{pub,priv}` -- the ones that
  assert thread safety for memory no type system checked.
- `ty.storing_raw_ptr.of_which.has_lifetime.{pub,priv}` -- the ones that tie
  the pointer to a lifetime parameter.
- `ty.storing_raw_ptr.of_which.ffibox.{pub,priv}` -- the ones that declare
  their lifecycle through an ffibox contract, which none of the std shares can
  see.
- `ty.storing_raw_ptr.of_which.pub_field.{pub,priv}` -- the ones that publish
  the pointer as a public field. Not a declaration: an access the type does not
  govern.
- `ty.storing_raw_ptr.of_which.none.{pub,priv}` -- the residual: the type
  stores a pointer and declares nothing about it, in any vocabulary.
- `ty.wrapping_unsafe_cell.{pub,priv}` -- types holding an `UnsafeCell`, the
  one way to hold a value C may write while Rust holds a shared reference to it.
- `ty.impl_block.{pub,priv}` -- inherent `impl T` blocks: the API the crate
  wrote for its own type.
- `ty.impl_block.of_which.ffibox.{layout,ref,mut,locked}.{pub,priv}` -- of
  those, the blocks on a cell and on each of its handles, which are different
  surfaces: the layout type carries the constructors, the shared handle the
  getters, the exclusive handle the setters.
- `ty.impl_block.of_which.other.{pub,priv}` -- the blocks on everything else.
- `ty.impl_trait.{pub,priv}` -- `impl Tr for T` blocks: satisfying someone
  else's shape.
- `ty.impl_trait.of_which.unsafe` -- of those, the `unsafe impl`s, which assert
  what the compiler cannot check. `TrivialClone`, which `#[derive(Clone)]`
  emits, is skipped.
- `ty.impl_trait.of_which.derived.{pub,priv}` -- the ones a `#[derive]` wrote.
  Nobody typed them, and they are most of the `std` arm.
- `ty.impl_trait.of_which.send_sync.{send,sync}.{pub,priv}` -- the
  `unsafe impl Send` and `unsafe impl Sync` claims, counted separately from
  each other.
- `ty.impl_trait.of_which.std.{pub,priv}` -- the impls of a standard-library
  trait.
- `ty.impl_trait.of_which.local.{pub,priv}` -- the impls of a trait the crate
  declared itself: a shape it chose rather than adopted.
- `ty.impl_trait.of_which.ffibox.{pub,priv}` -- the impls of an ffibox
  contract.
- `ty.impl_trait.of_which.ffibox.of_which.<trait>.{handwritten,macro}` -- those
  by trait, split by whether a generator wrote the impl rather than by
  visibility ([2.5](#25-deliberate-asymmetries)).
- `ty.generic.{pub,priv}` -- types carrying a generic parameter.
- `ty.generic.of_which.{lifetime,type}.{pub,priv}` -- of those, by kind of
  parameter. A lifetime ties the type to something it borrows; a type parameter
  makes it a family rather than one layout, so each instantiation is a separate
  question about C's bytes. A type may carry both.
- `ty.generic.of_which.storing_raw_ptr.{pub,priv}` -- the generic types that
  hold a raw pointer.
- `ty.field.ffibox.<primitive>.{pub,priv}` -- fields holding an ffibox
  primitive, by primitive: the delegation `ty.storing_raw_ptr` deliberately
  does not count as the crate's own pointer.
- `ty.ffibox.ccell.{pub,priv}` -- the layout types, those that implement
  `CCell`.
- `ty.ffibox.ccell.of_which.no_seam_trait.{pub,priv}` -- of those, the cells
  whose handles implement neither seam, so code generic over a handle has to
  special-case them.
- `ty.ffibox.wrapper.{pub,priv}` -- MENTIONS of a cell in the crate's
  declarations, counted where a qualifier below makes the mention a question:
  a cell named in twenty signatures is twenty of these.
- `ty.ffibox.wrapper.of_which.borrow.{pub,priv}` -- of those, the mentions
  behind a reference, which the convention says should be a handle instead.
- `ty.ffibox.wrapper.of_which.borrow.of_which.self_in_ref_accessor.{pub,priv}`
  -- of the borrows, the receiver of an `as_ref` / `as_mut` accessor, which
  ffibox's contract licenses.
- `ty.ffibox.wrapper.of_which.borrow.of_which.self_in_trait_impl.{pub,priv}` --
  the receiver of a trait impl's method, whose shape the trait fixed rather
  than the crate. The remainder of the borrows is the unsanctioned surface.
- `ty.ffibox.wrapper.of_which.std_owner.{pub,priv}` -- the mentions inside a
  standard-library container that owns its storage (`Box`, `Vec`, a map).
- `ty.ffibox.wrapper.of_which.slice.{pub,priv}` -- the mentions behind a slice.
- `ty.ffibox.wrapper.of_which.field.{pub,priv}` -- the mentions that are a
  field's type, which cuts across the other three.
- `ty.ffibox.ffi.{pub,priv}` -- the same mentions for the raw `-sys` struct a
  cell covers, its `CCell::C`: the C layout named where the wrapper could have
  been.
- `ty.ffibox.ffi.of_which.borrow.{pub,priv}` -- of those, the mentions behind a
  reference.
- `ty.ffibox.ffi.of_which.borrow.of_which.self_in_ref_accessor.{pub,priv}` --
  the receiver of an accessor, as above.
- `ty.ffibox.ffi.of_which.borrow.of_which.self_in_trait_impl.{pub,priv}` -- the
  receiver of a trait impl's method, as above.
- `ty.ffibox.ffi.of_which.std_owner.{pub,priv}` -- the mentions inside a
  standard-library owner.
- `ty.ffibox.ffi.of_which.slice.{pub,priv}` -- the mentions behind a slice.
- `ty.ffibox.ffi.of_which.field.{pub,priv}` -- the mentions that are a field's
  type.
- `ty.ffibox.by_val.{pub,priv}` -- mentions of a cell by value rather than
  behind a reference.
- `ty.ffibox.by_val.of_which.{field,fn_sig}.{pub,priv}` -- of those, where the
  value sits: a field's type, or a signature's. These two partition the record.
- `ty.ffibox.by_val.of_which.std_owner.{pub,priv}` -- the ones inside a
  standard-library owner, which cuts across both.

### 1.3 `fn`

Every function the crate defines, the methods of its trait impls included
([analysis 9.4](analysis.md#94-functions-and-methods)).

- `fn.total.{pub,priv}` -- the denominator, emitted: every function with a body.
- `fn.total.of_which.macro.{pub,priv}` -- of those, the ones a macro wrote.
  Subtract for the hand-written total.
- `fn.safe.{pub,priv}` -- the safe ones.
- `fn.safe.of_which.with_unsafe.{pub,priv}` -- of those, the ones whose body
  contains an `unsafe` block: a safe fn discharging an obligation internally.
  Counted on the safe arm only ([2.5](#25-deliberate-asymmetries)).
- `fn.unsafe.{pub,priv}` -- the `unsafe fn`s. `fn.unsafe.pub` is the unsafe
  surface a consumer meets.
- `fn.sig.of_which.ffibox.{arg,ret}.<primitive>.{pub,priv}` -- mentions of an
  ffibox primitive in a signature, by position and by primitive: whether the
  vocabulary actually crosses the interface.

### 1.4 `code`

The size of the crate and what its bodies do, as the denominators the rest is
read against.

- `code.loc.total` -- lines of code, from the compiled crate: the union of HIR
  definition spans, blanks and comments excluded, so items `cfg` removed are
  not in the denominator.
- `code.loc.unsafe` -- of those, the lines inside an `unsafe` block, filtered
  the same way so the two are comparable.
- `code.unsafe_block.total` -- `unsafe` blocks, however many lines each holds.
- `code.unsafe_block.of_which.ffi_export` -- of those, the ones inside an
  `ffi_export` gateway module, which a port campaign generates rather than
  writes.
- `code.unsafe_call.ffi` -- unsafe calls whose callee carries a foreign ABI:
  the real crossings, counted by the callee's type rather than by its
  declaration site, so calls through a stored function pointer are in
  ([analysis 10](analysis.md#10-calls)).
- `code.unsafe_call.rust` -- unsafe calls to a Rust-ABI function, the crate's
  own `unsafe fn`s and the standard library's unsafe constructors alike.
- `code.unsafe_call.intrinsic` -- unsafe calls to a compiler intrinsic,
  `transmute` among them.
- `code.tests.loc.{total,unsafe}` -- the same two line counts for the test
  code, which no other counter includes
  ([analysis 9.6](analysis.md#96-test-code)).
- `code.tests.unsafe_block` -- `unsafe` blocks in the test code.
- `code.tests.fn` -- functions in the test code, including one generated
  harness `main` per test binary.

## 2. The shape of a record

### 2.1 Partitions and shares

A partition's children are disjoint and sum to it; an `of_which` node's
children are subsets that overlap and are never summed. `nest_ptr` derives
every partition `total` bottom-up and skips `of_which` when summing, so no sum
is written by the driver and none can disagree with its parts.

`ty.storing_raw_ptr.of_which` is a share family: a type may implement both
`Drop` and `Clone`, so its arms overlap and only the record itself is a
population. An `of_which` node therefore carries no `total` of its own --
summing two shares is not a quantity -- while each share keeps the total of its
own `{pub,priv}` partition. A share may refine another share, and then it nests
under it: `fn_sig_trait_impl.of_which.ffibox.of_which.<trait>` is the ffibox
positions by trait.

Where a residual is wanted it is emitted as a share named for it --
`ty.storing_raw_ptr.of_which.none`, `ty.total.of_which.no_trait` -- rather than
left for a reader to subtract.

### 2.2 Namespaces

Three kinds of node carry no derived `total`: an `of_which` node, as above; a
node that already carries an emitted one, which is how the denominators
`raw_ptr.total`, `ty.total` and `code.loc.total` survive a derivation that
would otherwise take their name; and a NAMESPACE, a node whose children are
families rather than the parts of one quantity.

A top-level prefix is always a namespace -- `raw_ptr.fn_sig_arg` counts
signature positions and `raw_ptr.deref` counts body sites, so their sum means
nothing -- and three are namespaces a level down. `ty.ffibox` holds a type
population (`ccell` counts types) beside three records of mentions (`wrapper`,
`ffi` and `by_val` count places, and overlap each other, since a cell held in a
field is in `wrapper` and in `by_val` both). `code.tests` holds four separate
measurements of the test build: its lines, its unsafe lines -- a subset of them
-- its unsafe blocks and its fns; their sum read 103840 on libgit2-bindings, a
figure with no unit at all. `fn.sig` holds what a signature carries, in
mentions -- a fn taking two `CBox` is two of them -- so it is a share of no
count of fns, and `fn.total` beside it is the denominator a reader divides by.
Its own arms do carry totals: `fn.sig.of_which.ffibox` is `arg` plus `ret`,
which are disjoint.

`nest_ptr` declares them in `NAMESPACES` rather than inferring them, since no
shape distinguishes a namespace from a partition: `raw_ptr.fn_sig_arg`'s
`{safe,unsafe}` children are records with their own totals too, and summing
those is exactly right.

### 2.3 Zero, and absent

Every counter the invocation's flags turn on is in the document, at `0` when
it never fired. A reader of one document cannot tell an absent counter from
one the schema does not have -- no `std_owner` under `ty.ffibox.wrapper` could
mean "no cell is held in a std collection" or "that arm was never written" --
and the schema is too long to hold in the head, so the driver registers every
path it can emit before the passes run and they count up from there.

What is absent is what the flags did not turn on, which is a different
statement and a deliberate one: the ffibox arms without `--ffibox`, and the
`of_which.seam` shares without `--seams`. A `0` there would say the scan
looked and found none, when it did not look.

The registry is in the driver, beside the passes, and it iterates the same
vocabulary lists they do, so the trait and primitive arms cannot drift from
it. `RegistryTests` reads the registry off a scan of
`tests/fixtures/empty/` -- a crate with nothing in it, whose every counter is
therefore 0 -- and holds the other fixtures' fired counters to it.

### 2.4 The order of a record

A record's children are written in a declared order, most salient first: the
record's own `total`, then the splits it is cut by (`unsafe` before `safe`,
`pub` before `priv`), then its families, then its shares and arms, and
`of_which` last, since a share is read against the partition it cuts across.
The prefixes come in this document's order: `raw_ptr`, `ty`, `fn`, `code`.

The driver emits a sorted map, so the alternative is alphabetical: `fn` would
read `{safe, sig, total, unsafe}`, with the denominator in the middle.

A name the order does not hold comes after every name it does, alphabetically.
That is where the primitive arms land -- `CArc`, `CBorrowedPtr`, `CBox` -- so a
primitive added to ffibox needs no change to the order and still reads
predictably. The trait arms are declared, in the order
[`ffibox.md`](ffibox.md) gives the vocabulary, so a breakdown by trait reads as
the lifecycle it describes rather than alphabetically.
`measure.KEY_ORDER` is one table for every level, since a name that earns an
early rank in one record earns it in the others: `unsafe` is early as
`fn.unsafe`, as `code.loc.unsafe` and as the unsafe trait impls. Two records
cannot both be satisfied by it -- `field` leads `by_val`'s shares and trails
`wrapper`'s, and it is ranked with the positions -- and `fn` is split out,
being a prefix as well as one of `code.tests`'s three measurements.

### 2.5 Deliberate asymmetries

A split that is not carried where a reader might expect it, and why.

`ty.impl_trait.of_which.ffibox.of_which.<trait>` splits `{handwritten,macro}`
but not `{pub,priv}`: whether a generator was used does not vary with
visibility, and the split would cost 68 cells for nothing.

`ty.impl_trait.of_which.send_sync` splits `{pub,priv}` but not by origin:
asserting `Send` on a public type is a claim to consumers, on a private one it
is internal bookkeeping.

`raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.<trait>` splits by neither:
a trait method's safety and visibility are the trait declaration's, one
spelling dictating every impl, so the split would restate the parent cell by
cell. The parent `ffibox` arm carries both, since the mix of traits a crate
implements does move them.

`fn.safe.of_which.with_unsafe` is counted on the safe arm only. With
`unsafe_op_in_unsafe_fn` denied, every `unsafe fn` doing anything raw has a
block by construction, so counting it there would measure the lint.

`raw_ptr.fn_sig_trait_impl` carries no direction, while `fn_sig_arg` and
`fn_sig_ret` are separate counters: the direction says what the crate chose to
do with the pointer, and in a trait impl it chose neither.

## 3. Building a report

A report is leaves divided and subtracted, named by their paths. Three rules
make the arithmetic sound:

- a partition may be summed, an `of_which` may not. Two shares of one record
  overlap, so `borrow + std_owner` is not a quantity, while
  `pub + priv` is the record;
- a rate stays inside one record, or between a record and the denominator
  emitted for it: `fn.unsafe.pub / fn.total.pub`, `code.loc.unsafe /
  code.loc.total`, `ty.storing_raw_ptr.pub / ty.total.pub`. Dividing across
  prefixes mixes grains -- signature positions by lines of code says nothing;
- a share is read against the record it cuts, and the remainder is a
  subtraction: `wrapper.of_which.borrow.pub` less its two sanctioned shares is
  the convention's unsanctioned surface.

### 3.1 The readings worth taking

Each reading below names the leaves it is made of. The figures are not here: a
reading of one crate is in [`analysis.md`](analysis.md), where it is the
evidence for a rule, and a reading of several is in
[`examples/README.md`](../examples/README.md), where three real documents are
tabulated side by side. A figure copied into this document would be a second
copy to keep current, and the counters are what this document is for.

**What a consumer meets without writing `unsafe`.**
`raw_ptr.total.safe.pub` is the raw pointers on the safe public interface,
`fn.unsafe.pub` against `fn.total.pub` the public unsafe surface, and
`raw_ptr.field.pub` the pointers a public field hands over with no `unsafe` at
all.

**How much unsafe, and where it sits.** `code.loc.unsafe / code.loc.total` is
the density and `code.unsafe_block.total` the number of blocks; read both,
since folding small blocks into large ones moves one and not the other.
`code.unsafe_block.of_which.ffi_export` subtracts the gateways a port campaign
generated, and the `code.unsafe_call` arms say what the unsafe is for: `ffi`
is the boundary, `rust` is the standard library's constructors and the crate's
own helpers, `intrinsic` is `transmute` and its siblings.

**What the crate wrote, as opposed to what a macro did.** Subtract
`fn.total.of_which.macro` from `fn.total`, and
`ty.impl_trait.of_which.derived` from `ty.impl_trait`. A comparison of two
crates without those shares is partly a comparison of how much boilerplate
each spells.

**What the crate declares about the pointers it manages.**
`ty.storing_raw_ptr.of_which.none` against `ty.storing_raw_ptr` is the types
that hold a pointer and say nothing about it. The other shares say what the
rest declared -- `impl_drop`, `impl_clone`, `ffibox` -- and `pub_field` is the
opposite of a declaration.

**Whether a convention is kept.** Under `--ffibox`,
`ty.ffibox.wrapper.of_which.borrow` less `self_in_ref_accessor` and
`self_in_trait_impl` is the bare `&Foo` surface the convention says should be a
handle. `ty.ffibox.ccell.of_which.no_seam_trait` is the cells a generic handle
has to special-case, and `fn.sig.of_which.ffibox` whether the vocabulary
reaches the interface at all.

**Whose shape the pointers in trait impls are.** `fn_sig_trait_impl` is read
through its `of_which` arms, never bare: one crate's are a convention's
lifecycle strategies, another's its own private helpers, a third's one local
conversion trait, and the bare figure is the same for all three.

**The test code, beside the library and never added to it.**
`code.tests.loc.total` against `code.loc.total` is how much of the tree is
tests, and the `code.tests` arms are the only counters that include them.

A report of several crates is a table of leaves, one row per crate, with the
denominator beside every share.

### 3.2 What a comparison requires

The document is a pure function of the source tree under a fixed scanner, so
two figures are comparable only when the scanner and the flags match: the
ffimap commit, the toolchain, `--sys-crates` (which decides what
`ty.storing_raw_ptr` admits), `--seams` (which decides what the `seam` shares
and `casted_to.local_seam` can see) and any framework the crate is built on.
The `scanner` and `sys_crates` fields carry all of it, which is why they are in
the document rather than beside it
([analysis 1](analysis.md#1-determinism-and-what-it-rests-on)).

A counter added or a rule corrected moves figures too. The ones already known
to be incomparable across versions are named in
[analysis 12](analysis.md#12-what-the-analysis-cannot-see).

### 3.3 No target values

ffimap has none, and this is the place that says so. Absolute counts are not
comparable across crates of different size, and lower is not automatically
better: a wrapper over C must contain unsafe, and folding 600 small audited
blocks into 200 large ones improves the number while making the crate worse.
A reader who wants a rate divides the leaves it names.

Finding what is worth looking at is the opposite kind of work, and belongs to
a reviewer who reads the code, forms suspicions and defends them. `none` and
`no_seam_trait` name an absence, not a defect.
