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
[`docs/scanning.md`](../docs/scanning.md)'s flags section explains: the peel
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

| | `in_impl` | of which `seam` |
|---|---|---|
| git2-rs | 134 | **125** |
| libgit2-bindings | 64 | 0 |
| ffmpeg-bindings | 93 | 0 |

git2-rs' trait-impl pointer surface is `Binding::raw` and `Binding::from_raw`,
implemented for 91 types -- plumbing a consumer of the safe API never
performs. The crustify campaigns' `in_impl` is ffibox's lifecycle strategies
(`c_drop`, `c_new`, `c_up_ref`), which take a `NonNull` but are not in either
crate's declared seam list, because nothing local defines them: the seam
traits' `as_ptr` and `from_ptr` are ffibox's provided methods, so no local fn
carries the name.

The same reading applies to `returned`: 66 of libgit2-bindings' 86 and 14 of
git2-rs' 19 are seams.

## Keeping to ffibox's convention

The cell mentions, which only the two crustify campaigns have, since git2-rs
is built on no ffibox. ffibox's convention is that a consumer reaches a cell's
bytes through the `Ref` and `Mut` handles, so a `&Foo` that is neither an
accessor's receiver nor a trait method's receiver is the layout published
directly:

| | `borrow.pub` | `self_in_ref_accessor` | `self_in_trait_impl` | rest |
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

## Reading them

Every counter is described in [`docs/schema.md`](../docs/schema.md), the
`--ffibox` arms in [`docs/ffibox.md`](../docs/ffibox.md), and how a scan is
produced in [`docs/scanning.md`](../docs/scanning.md).

A figure is comparable with another only under the same ffimap commit, peel
set and seam list. These three are not comparable with any document scanned
before the counter tree replaced the flat block.
