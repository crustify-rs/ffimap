# Goals

ffimap measures how a Rust crate meets C: what its code leaves unsafe, which
raw pointers it hands to its consumers, what it claims about memory and threads
that no type system checked, how it reaches C and how C reaches it, and how much
of that it says through a convention such as ffibox's. Each measure is a fact
the compiler states, so that a person or an agent can check a change to the
crate against the crate before it, and see where the change moved what.

Three parties use it:

- **the driver** states facts: a rustc pass over one build's HIR and type
  information;
- **inputs** state what a fact cannot: the names that need judgement or a
  convention, which the caller passes (`--sys-crates`, `--seams`, `--regions`,
  `--barriers`, `--ffibox`);
- **readers** take the measures: a reviewer forming suspicions, an agent
  verifying its own change, a dashboard tracking a campaign. They read a
  document, or the difference between two.

The goals below are grouped by what they serve. Each states what it means and
how it is checked. A change that departs from one says so, in its commit and
here.

## Facts

### G1. Facts, not data flow

Every counter is a declaration or one expression node, read after macro
expansion, `cfg` selection and type resolution. Nothing follows a value through
locals, memory or calls, and no points-to analysis runs. Where an answer would
need data flow, ffimap counts the fact it can see at the site and leaves the
rest to a reader, who has the sites to start from.

*Checked by:* every counter's row in [`schema.md`](schema.md) names the one
declaration or node that moves it, and [`analysis.md`](analysis.md) the rule it
is decided by.

### G2. Compiler-precise

A fact comes from the compiler's own resolution, never from source text: a
callee is identified by its definition, a type by its `DefId`, an ABI by the
signature's. A name is matched only where the compiler cannot say more, and
only against a caller's input or a fixed vocabulary.

*Checked by:* the driver reads names only in the tables
[`analysis.md`](analysis.md) lists.

### G3. One build, stated

The facts are those of the build `cargo check --all-targets` compiles on the
pinned toolchain. What that build does not compile contributes nothing, and a
crate that does not build has no counts rather than approximate ones.

*Checked by:* [`analysis.md`](analysis.md#3-the-build) describes the build,
and `counts_unavailable` carries the reason a document has none.

## Measures

### G4. Measures of how the crate meets C

Each counter bears on one of four properties, which its row says: safety (how
much is left unsafe, and where), soundness (claims and conversions a reviewer
must vouch for), ergonomics (what a consumer has to handle that C would have
made it handle) and idiomaticity (how much of the API speaks Rust's own
vocabulary). A counter that bears on none is not added.

*Checked by:* the readings of [`schema.md`](schema.md#31-the-readings-worth-taking)
name the counters each property is read from.

### G5. Feedback through differences and sites

A reader learns most from two documents of one crate: which counters a change
moved, and, with sites, where the new increments are. `ffimap diff` states
that difference, so that an agent checks its own change without reading the
whole document.

*Checked by:* the diff of a document against itself is empty, and the diff of
two scans of the canary differs in exactly the items changed between them.

### G6. No target values

A lower count is not a better crate, as
[`schema.md`](schema.md#33-no-target-values) explains. ffimap states figures,
and a threshold is its reader's to set.

## Inputs

### G7. Judgement is an input, never a guess

What needs judgement or a convention to decide enters as a flag the caller
sets: the crates that are C's, the functions that are seams, the modules that
are regions, the convention a crate is built on. ffimap does not discover them,
and a counter that needs one is absent without it rather than zero.

*Checked by:* every such counter is registered only under its flag, which
`RegistryTests` holds.

### G8. General rules, no overfitting

A rule follows from Rust's and C's semantics and holds for every crate. It
matches no names, paths or conventions of one crate or one tool that builds
crates, and does not special-case the crate that motivated it. A convention's
vocabulary, such as ffibox's, is a fixed set of arms its flag turns on, read
from the convention's own declarations.

*Checked by:* each rule has a fixture written for it, and its effect is
measured on a crate other than the one that motivated it (G10).

## Validation

### G9. Every counter is tested

Each counter has a fixture whose expected count is derived by hand, item by
item, with the items that must NOT move it beside those that must. Every site a
counter records is checked to be addressable and to sum to the counter.

*Checked by:* the canary, cells and interop suites, and `SiteTests`.

### G10. Every change is measured on real code

A change to a counter is run on the crates under [`examples/`](../examples)
before it lands, and its commit states what moved and that nothing else did.
An unexplained difference is a defect until it is explained.

*Checked by:* the commit message, and the rescanned examples.

### G11. Readings are checked against the source

A new counter's sites are read on at least one real crate, to show that what it
counts is what its row says it counts.

*Checked by:* the commit message names the crate and what its sites showed.

## Interface

### G12. Deterministic

The same tree under the same scanner gives the same bytes. The document
records the scanner and its inputs, so a difference between two documents can
be told from a difference between two scanners.

*Checked by:* the `scanner` field, and the canary scanned twice.

### G13. Documented

Every counter has a row, every input a description, and every known blind spot
an entry in [`analysis.md`](analysis.md#12-what-the-analysis-cannot-see) or
[`TODO.md`](TODO.md).

*Checked by:* `SchemaDocTests`, both ways.

## Non-goals

- **Data flow and points-to analysis.** See G1.
- **Proving soundness.** ffimap measures where a reviewer should look; the
  reviewer decides what is wrong.
- **Lints.** What rustc and Clippy already check is theirs.
- **Target values.** See G6.
- **The C side.** What the C does with what it is given is the C analysis's.

## Known departures

- `code.unsafe_block.of_which.ffi_export` attributes a block to the C-ABI
  boundary by its function's ABI and symbol, and so stays without `--regions`;
  its name is a campaign's term for that boundary rather than Rust's (G8).
- The `--ffibox` arms match the `as_ref` and `as_mut` layout accessors by name,
  which holds only where the convention does (G2).
