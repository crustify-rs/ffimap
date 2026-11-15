# TODO

This file lists the work that is open. Each entry proposes one piece of work.
[`schema.md`](schema.md) says what a counter holds, and
[`analysis.md`](analysis.md) says what it is decided from. So an entry states
its proposal and cites the measurement, and does not repeat it.

## `scanner.ffibox` says whether, not which

During a campaign, which is a crustify project that generates or audits a crate, a
crate built on ffibox depends on it by path. So ffibox's vocabulary, its
primitives and the types they wrap move the figures as much as the scanned
crate does. But `scanner.ffibox` is a boolean: it records that the flag was
passed, and not which ffibox was underneath. When the crate stood still and
ffibox moved, a reader cannot tell the two documents apart.

When the dependency is a path or a git checkout, the field should carry
ffibox's commit, which is resolvable from the manifest's resolved source.
Today a campaign records the commit beside the scan, in a file of its own.
That file is a second record to keep in step with the first.

## `code.unsafe_call.rust` is dominated by the standard library

Splitting the arm into own-crate and dependency would separate "wrote unsafe
helpers" from "used std's unsafe API". The split is one `did.krate` test at
the classification site.
[`analysis.md`](analysis.md#12-what-the-analysis-cannot-see) has the
measurement.

## `storing_raw_ptr.of_which.none` interrogates the wrong type

The shares ask what the pointer-holder declares. Where ownership is factored
out, into a generic owner (`CBox<Foo>`, `CArc<Foo>`) or onto borrowed handles,
the holder declares nothing *by design*. So asking the holder is a category
error. Adding the `ffibox` share fixed the ffibox-shaped case
(libgit2-bindings 12 of 41 to 4). But git2-rs' remaining 15 are options
structs that embed a `raw::git_*_options`, whose fields are string pointers
into buffers the struct keeps beside them. Declaring nothing is correct for
them.

The question worth counting is whether anything in the crate declares a
lifecycle for that pointer. Answering it means following the owner rather than
inspecting the holder. The question reads the same for a crate with no
framework.

## The seam share covers signatures only

`--seams` is reported as the `of_which.seam` share of the fn-signature
positions. `code.unsafe_block` and `raw_ptr.deref` inside seam bodies are
counted undifferentiated. So a crate whose seams are its own reads as having
more unsafe than one whose seams live in a dependency.

Nothing marks the *escape hatch* distinction either, which is what a reader
wants. git2-rs documents `Binding` in prose ("do consider contributing to the
git2 project") but does not mark it `#[doc(hidden)]`, and libgit2-bindings uses
no `doc(hidden)` at all. So there is no machine-readable signal.

## `ty.impl_block` has no `{handwritten,macro}` split

`ty.impl_trait.of_which.ffibox` splits an impl by whether a generator wrote
it. The inherent blocks are not split, although the same
`Span::from_expansion()` decides it. On libgit2-bindings the 98 public layout
blocks are 67 hand-written across 55 distinct self types and 31 emitted by
`define_ctype!`. That split takes two `--sites` passes to answer
"which of this surface did the framework write".

## `ty.generic.of_which.storing_raw_ptr` overlaps `has_lifetime`

On libgit2-bindings the share reads 23 against
`ty.storing_raw_ptr.of_which.has_lifetime`'s 20. The difference is the holders
that are generic over a type parameter only. Neither subsumes the other: the
share is coarser, and `has_lifetime` is per-kind. So both are emitted, which
is one cross-tabulation recorded twice. Picking a direction means either a
`has_type_param` share beside `has_lifetime`, or nesting the holder share
under each generic kind.

## `fn_sig_trait_impl.of_which.local` does not name the trait

The ffibox arm breaks down by trait, because its vocabulary is 18 names a
registry can carry. A local trait's name is the crate's own, so the breakdown
would be a counter per name discovered at scan time. A registry whose leaves
depend on the crate measured cannot say which of them read 0 by absence.
Today the names come off `--sites`:

- ffmpeg-bindings' 26 are `into_void`, `to_c`, `refusal` and an adopt/zero
  pair, all private;
- git2-rs' 134 are one `Binding`.

A `{one,several}` split, or the name of the dominant trait as a string beside
the counts, would put the reading in the document.

## `--sites` takes a leaf, and a prefix reads empty

`--sites ty.ffibox.wrapper.as.by_val.of_which.fn_sig` validates, because `is_tree_counter`
checks the prefix and family. It then reports an empty list: `compose` looks
the name up in the driver's emissions, which are keyed by the leaf
(`...fn_sig.pub`). So a reader who asks for an arm rather than a leaf is told
that there are no places, not that the name is incomplete. There are two
fixes:

- the lookup aggregates every leaf under the requested path, which is what the
  name reads like; or
- the validation rejects a path that is not a leaf.

The sibling case is fixed. It was a leaf whose places the driver recorded
under a name that is no counter's path: the four mirrored counters carried
their `Counts` field name. `test_canary.SiteTests` now holds every site list
to a path `--sites` accepts.

## `code.tests.fn` counts the harness `main`

A crate with no functions at all reads `code.tests.fn: 1`, which
`tests/fixtures/empty/` makes plain. The figure is the test build's fn count
less the library's own. The test build carries the `main` that rustc
generates for the harness, and the library has nothing to subtract against
it. There is one such `main` per test target, so a tree with many integration
tests is over by that many. There are two fixes:

- the generated `main` is excluded where `in_generated_file` already excludes
  macro-written items; or
- the figure is documented as "fns in the test build, harness included".

## A signature's mentions share one place

Every position of a signature records the signature's own line, so the cell
counters cannot point at a position. On a `fn eq(&self, other: &Self)`, the
sanctioned receiver and the unsanctioned argument are one place. The
unsanctioned mentions are recoverable as a count but not as a list. The
driver has the per-position spans, `FnDecl.inputs[i].span` and the return's,
and could record those instead of `def_span`. A one-line signature would
still collapse to one line, since a site is `(file, line)`. So the fix is
worth only as much as the multi-line signatures in a tree.

## A path dependency can break a shipped campaign

This is not ffimap's to fix, but ffimap is what found it. `ffmpeg-bindings`
pinned ffibox as `{ path = "/opt/venv/share/ffibox" }` with no commit. So an
ffibox change that moved `as_ptr` and `as_mut_ptr` onto the seam traits left
both `crustify/devel` and `main` not compiling: 683 errors on a tree that had
already shipped. The scan reported `counts_unavailable`, which is how the
break surfaced. A campaign's `dependencies.json` records the commit of its
other dependencies. Recording the ffibox commit beside the pin in the same
way would make the break a deliberate step rather than an accident.

## `ffimap api` attributes by anchor, and anchors stop at types

[`api.md`](api.md#2-c-items-and-their-stand-ins) defines an anchor. Two
figures from libgit2-crustify's `main` bound what the measure can attribute
([`api.md`](api.md#11-what-the-measure-cannot-see) lists the rest):

- Of its 265 public enum variants and 25 public fields, none carries an
  anchor, though the convention annotates each enum constant. A variant added
  or lost is still seen, on its enum.
- 48 public items are tied to no C item by any rule of
  [`api.md`](api.md#5-handles-and-owners): error types, option views,
  iterators, `OdbDataStrVec`. So their changes are reported per module. A rule
  that followed a type's own signatures to the stand-ins they name would reach
  more of them, at the price of tying a type to every item it mentions.

Generic parameters are compared by name. Renaming them by position within each
declaration would make a rename read as kept, and would make the declarations
harder to read in a report.

The contract view models the standard library's pointer forms by a table and
leaves every other standard type unresolved. It also leaves unresolved a bound
on a generic alias's free parameter (`OdbDataBox<T>`, `OdbDataVec<T>` on
libgit2-crustify). Those entries fall back to their raw records. The standard
library's own rustdoc JSON (`rust-docs-json`) would let `Vec`, `Option` and
the rest answer as a `--dep` does.
