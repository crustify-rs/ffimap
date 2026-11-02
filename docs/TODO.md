# TODO

What is open: the work each entry proposes. What a counter holds is
[`schema.md`](schema.md)'s and what it is decided from
[`analysis.md`](analysis.md)'s, so an entry states its proposal and cites the
measurement rather than repeating it.

## `scanner.ffibox` says whether, not which

A crate built on ffibox depends on it by path during a campaign, so its
vocabulary, its primitives and the types they wrap move the figures as much as
the scanned crate does -- and `scanner.ffibox` is a boolean, which records that
the flag was passed and not which ffibox was underneath. A reader cannot tell
two documents apart when the crate stood still and ffibox moved.

The commit is what the field should carry when the dependency is a path or a
git checkout: resolvable from the manifest's resolved source. A campaign
records it beside the scan today, in a file of its own, which is a second
record to keep in step with the first.

## `code.unsafe_call.rust` is dominated by the standard library

Splitting the arm into own-crate and dependency, which is one `did.krate` test
at the classification site, separates "wrote unsafe helpers" from "used std's
unsafe API". [`analysis.md`](analysis.md#12-what-the-analysis-cannot-see) has
the measurement.

## `storing_raw_ptr.of_which.none` interrogates the wrong type

The shares ask what the pointer-holder declares. Where ownership is factored
out -- into a generic owner (`CBox<Foo>`, `CArc<Foo>`) or onto borrowed
handles -- the holder declares nothing *by design*, so asking it is a category
error. Adding the `ffibox` share fixed the ffibox-shaped case
(libgit2-bindings 12 of 41 to 4), but git2-rs' remaining 15 are options
structs embedding a `raw::git_*_options` whose fields are string pointers into
buffers the struct keeps beside them: declaring nothing is correct for them.

The question worth counting is whether anything in the crate declares a
lifecycle for that pointer, which means following the owner rather than
inspecting the holder, and would read the same for a crate with no framework.

## The seam share covers signatures only

`--seams` is reported as the `of_which.seam` share of the fn-signature
positions. `code.unsafe_block` and `raw_ptr.deref` inside seam bodies are
counted undifferentiated, so a crate whose seams are its own reads as having
more unsafe than one whose seams live in a dependency.

Nothing marks the *escape hatch* distinction either, which is what a reader
wants: git2-rs documents `Binding` in prose ("do consider contributing to the
git2 project") but does not mark it `#[doc(hidden)]`, and libgit2-bindings uses
no `doc(hidden)` at all, so there is no machine-readable signal.

## `ty.impl_block` has no `{handwritten,macro}` split

`ty.impl_trait.of_which.ffibox` splits an impl by whether a generator wrote
it; the inherent blocks do not, although the same `Span::from_expansion()`
decides it. On libgit2-bindings the 98 public layout blocks are 67
hand-written across 55 distinct self types and 31 emitted by `define_ctype!`,
a split that takes two `--sites` passes to answer
"which of this surface did the framework write".

## `ty.generic.of_which.storing_raw_ptr` overlaps `has_lifetime`

23 against `ty.storing_raw_ptr.of_which.has_lifetime`'s 20 on
libgit2-bindings, the difference being holders generic over a type parameter
only. Neither subsumes the other -- the share is coarser, `has_lifetime` is
per-kind -- so both are emitted, which is one cross-tabulation recorded twice.
Picking a direction means either a `has_type_param` share beside
`has_lifetime`, or nesting the holder share under each generic kind.

## `fn_sig_trait_impl.of_which.local` does not name the trait

The ffibox arm breaks down by trait, because its vocabulary is 18 names a
registry can carry. A local trait's name is the crate's own, so the breakdown
would be a counter per name discovered at scan time -- and a registry whose
leaves depend on the crate measured cannot say which of them read 0 by
absence. Today the names come off `--sites`: ffmpeg-bindings' 26 are
`into_void`, `to_c`, `refusal` and an adopt/zero pair, all private, and
git2-rs' 134 are one `Binding`. A `{one,several}` split, or the name of the
dominant trait as a string beside the counts, would put the reading in the
document.

## `--sites` takes a leaf, and a prefix reads empty

`--sites ty.ffibox.wrapper.as.by_val.of_which.fn_sig` validates, because `is_tree_counter`
checks the prefix and family, and then reports an empty list: `compose` looks
the name up in the driver's emissions, which are keyed by the leaf
(`...fn_sig.pub`). So a reader who asks for an arm rather than a leaf is told
there are no places rather than that the name is incomplete. Either the
lookup should aggregate every leaf under the requested path, which is what the
name reads like, or the validation should reject a path that is not a leaf.

The sibling case, a leaf whose places the driver recorded under a name that is
no counter's path, is fixed: the four mirrored counters carried their `Counts`
field name, and `test_canary.SiteTests` now holds every site list to a path
`--sites` accepts.

## `code.tests.fn` counts the harness `main`

A crate with no functions at all reads `code.tests.fn: 1`, which
`tests/fixtures/empty/` makes plain. The figure is the test build's fn count
less the library's own, and the test build carries the `main` that rustc
generates for the harness, which the library has nothing to subtract against.
It is one per test target, so a tree with many integration tests is over by
that many. Either the generated `main` is excluded where `in_generated_file`
already excludes macro-written items, or the figure is documented as "fns in
the test build, harness included".

## A signature's mentions share one place

Every position of a signature records the signature's own line, so the cell
counters cannot point at a position: on a `fn eq(&self, other: &Self)` the
sanctioned receiver and the unsanctioned argument are one place, and the
unsanctioned mentions are recoverable as a count but not as a list. The
driver has the per-position spans -- `FnDecl.inputs[i].span` and the return's
-- and could record those instead of `def_span`. A one-line signature would
still collapse to one line, since a site is `(file, line)`, so the fix is
worth only as much as the multi-line signatures in a tree.

## A path dependency can break a shipped campaign

Not ffimap's to fix, but ffimap is what found it. `ffmpeg-bindings` pinned
ffibox as `{ path = "/opt/venv/share/ffibox" }` with no commit, so an ffibox
change that moved `as_ptr` and `as_mut_ptr` onto the seam traits left both
`crustify/devel` and `main` not compiling -- 683 errors on a tree that had
already shipped. The scan reported `counts_unavailable`, which is how it
surfaced. Recording the ffibox commit beside the pin, as a campaign's
`dependencies.json` does for its other dependencies, would make the break a
deliberate step rather than an accident.
