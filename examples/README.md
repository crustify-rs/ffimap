# Examples

ffimap documents for three safe Rust wrappers over C libraries: two that
[crustify](https://github.com/crustify-rs/crustify) generated, scanned at the
tip of their campaigns, and the hand-written
[git2-rs](https://github.com/rust-lang/git2-rs), scanned as its crustify audit
campaign found it.

| Example | Wraps | Written by | Branch | Scanned commit |
|---|---|---|---|---|
| [`libgit2-bindings/ffimap.json`](libgit2-bindings/ffimap.json) | libgit2 | crustify | `crustify/devel` | `4f053ad7ba` |
| [`ffmpeg-bindings/ffimap.json`](ffmpeg-bindings/ffimap.json) | FFmpeg | crustify | `crustify/devel` | `d410346821` |
| [`git2-rs/ffimap.json`](git2-rs/ffimap.json) | libgit2 | hand-written (git2 0.21.0) | upstream `main` | `f6f11169de` |

`crate_path` is the workspace's path in the campaign's container.

## How they were scanned

Both inputs that change the figures are recorded, as
[`docs/analysis.md`](../docs/analysis.md)'s flags section explains: the peel
set is named rather than discovered, and the seam names are declared per
crate.

    libgit2-bindings  --ffibox --sys-crates libgit2-sys,pcre2-sys
                      --seams "from_ptr as_ptr as_mut_ptr from_void_ptr as_void_ptr"

    ffmpeg-bindings   --ffibox --sys-crates libavutil-sys,libswresample-sys,libswscale-sys,
                                            libavcodec-sys,libavformat-sys,libavfilter-sys,
                                            libavdevice-sys,libc-sys
                      --seams "from_ptr as_ptr as_mut_ptr from_void_ptr as_void_ptr"

    git2-rs                    --sys-crates libgit2-sys,libssh2-sys,libz-sys,
                                            openssl-sys,curl-sys
                      --seams "raw from_raw raw_mut from_raw_opt from_raw_const unwrap"

git2-rs is built on no ffibox, so it is scanned without the flag and its
`--ffibox` arms are absent rather than zero. The crustify campaigns depend on
ffibox by path, so their numbers move with that checkout as well as with their
own commit; these were scanned against ffibox `55e5f8ace6`.

## Why the seam names matter

Without them the three are not comparable. git2-rs reaches every raw pointer
through one trait it declares itself:

| | `fn_sig_trait_impl` | `seam` | `std` | `local` | `ffibox` |
|---|---|---|---|---|---|
| git2-rs | 134 | **125** | 0 | 134 | - |
| libgit2-bindings | 64 | 0 | 0 | 0 | 64 |
| ffmpeg-bindings | 93 | 0 | 0 | 26 | 67 |

The same family, three different things, which is what whose-trait-it-was
says. git2-rs' trait-impl pointer surface is `Binding::raw` and
`Binding::from_raw`, one local trait implemented for 91 types -- plumbing a
consumer of the safe API never performs. The crustify campaigns' is ffibox's
lifecycle vocabulary, broken down by trait:

| | `CDrop` | `CDupClone` | `CNew` | `CRefClone` | `CDispose` | `CAlloc` | `CAllocZeroed` | `CLenClone` | `CLenDrop` |
|---|---|---|---|---|---|---|---|---|---|
| libgit2-bindings | 36 | 8 | 5 | 5 | 5 | 1 | 1 | 2 | 1 |
| ffmpeg-bindings | 31 | 12 | 9 | 4 | 1 | 4 | 2 | 2 | 2 |

each taking or returning a `NonNull<T>`, which is the contract: the strategy
names the allocation by pointer so that a consumer never holds one.
ffmpeg-bindings' other 26 are private generic helpers of its own
(`into_void`, `to_c`, an element-adoption pair), every one of them `priv`.
The `std` column is zero on all three, and stays zero unless a crate writes a
`From<*mut T>`: `Drop::drop` takes `&mut self` and `Deref::deref` returns a
reference.

None of the ffibox positions is in either campaign's declared seam list, for
the reason [`docs/ffibox.md`](../docs/ffibox.md#9-the-pointers-the-conventions-traits-declare)
gives: the seam traits are implemented empty there, so the campaigns' own seams
are inherent methods and land in `fn_sig_ret` and `fn_sig_arg` instead.

The same reading applies to `fn_sig_ret`: 66 of libgit2-bindings' 86 and 14 of
git2-rs' 19 are seams.

## Keeping to ffibox's convention

The cell mentions, which only the two crustify campaigns have, since git2-rs
is built on no ffibox. ffibox's convention is that a consumer reaches a cell's
bytes through the `Ref` and `Mut` handles, so a `&Foo` that is neither an
accessor's receiver nor a trait method's receiver is the layout published
directly:

| | `as.borrowed.std.pub` | `self_in_ref_accessor` | `self_in_trait_impl` | rest |
|---|---|---|---|---|
| libgit2-bindings | 161 | 90 | 54 | 17 |
| ffmpeg-bindings | 215 | 116 | 77 | 22 |

The shares are the receiver only: a trait fixes the shape of `&self` and not
that of its other arguments or its return, and 11 of libgit2-bindings' trait
mentions and 20 of ffmpeg-bindings' are those. Six of libgit2-bindings'
remainder are distinct signatures, all `&[Foo]`, so it publishes no bare
`&Foo`; ffmpeg-bindings' include a `&[Self]` and an `as_c_ptr(&self)`, the
same conversion as an accessor under a name the convention did not give it.
[`docs/ffibox.md`](../docs/ffibox.md) section 8 describes the arms.

## What the trait impls do

`ty.impl_trait.of_which.std`, by what an impl of the trait can do to the type:

| | `drop` | `clone` | `send` | `sync` | `ref_forming` | `other` |
|---|---|---|---|---|---|---|
| git2-rs | 54 | 87 | 7 | 1 | 26 | 1538 |
| libgit2-bindings | 6 | 225 | 73 | 71 | 0 | 1390 |
| ffmpeg-bindings | 4 | 229 | 112 | 112 | 0 | 1386 |

git2-rs releases its objects in 54 `Drop` impls of its own and has 26
ref-forming impls; the campaigns release through ffibox's policies
(`ty.impl_trait.of_which.ffibox.policy`: 59 on each) and implement no
ref-forming trait at all, so no impl of theirs can hand out a reference of a
type it chose.

## Reading them

Every counter is described in [`docs/schema.md`](../docs/schema.md), which
also gives the arithmetic a report may do with them; the `--ffibox` arms are
in [`docs/ffibox.md`](../docs/ffibox.md), and how a scan is produced and what
each counter is decided from in [`docs/analysis.md`](../docs/analysis.md).

A figure is comparable with another only under the same ffimap commit, peel
set and seam list. These three are not comparable with any document scanned
before the counter tree replaced the flat block.
