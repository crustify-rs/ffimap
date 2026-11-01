# TODO

What is open. Anything resolved by a counter's retirement is in
[`schema.md`](schema.md)'s Retired counters and Rules that were tried and
rejected; this file is only the live work.

## `code.unsafe_call.rust` is dominated by the standard library

On the canary fixture it reads 13, of which 1 is a call to the crate's own
`unsafe fn` and 12 are std's unsafe constructors -- `Box::from_raw` and its
siblings, the same calls `raw_ptr.casted_to` already classifies. Splitting the
arm into own-crate and dependency, which is one `did.krate` test at the
classification site, separates "wrote unsafe helpers" from "used std's unsafe
API". Until it is split the arm is not a measure of the crate's own unsafety.

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
a split that had to be read off `--sites` twice in one session to answer
"which of this surface did the framework write".

## `ty.generic.of_which.storing_raw_ptr` overlaps `has_lifetime`

23 against `ty.storing_raw_ptr.of_which.has_lifetime`'s 20 on
libgit2-bindings, the difference being holders generic over a type parameter
only. Neither subsumes the other -- the share is coarser, `has_lifetime` is
per-kind -- so both are emitted, which is one cross-tabulation recorded twice.
Picking a direction means either a `has_type_param` share beside
`has_lifetime`, or nesting the holder share under each generic kind.

## `--sites` takes a leaf, and a prefix reads empty

`--sites ty.by_val.of_which.fn_sig` validates, because `is_tree_counter`
checks the prefix and family, and then reports an empty list: `compose` looks
the name up in the driver's emissions, which are keyed by the leaf
(`...fn_sig.pub`). So a reader who asks for an arm rather than a leaf is told
there are no places rather than that the name is incomplete. Either the
lookup should aggregate every leaf under the requested path, which is what the
name reads like, or the validation should reject a path that is not a leaf.

## A path dependency can break a shipped campaign

Not ffimap's to fix, but ffimap is what found it. `ffmpeg-bindings` pinned
ffibox as `{ path = "/opt/venv/share/ffibox" }` with no commit, so an ffibox
change that moved `as_ptr` and `as_mut_ptr` onto the seam traits left both
`crustify/devel` and `main` not compiling -- 683 errors on a tree that had
already shipped. The scan reported `counts_unavailable`, which is how it
surfaced. Recording the ffibox commit beside the pin, as a campaign's
`dependencies.json` does for its other dependencies, would make the break a
deliberate step rather than an accident.
