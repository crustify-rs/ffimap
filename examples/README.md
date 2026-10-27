# Examples

`ffimap --json` documents for three safe Rust wrappers over C libraries: two
that [crustify](https://github.com/crustify-rs/crustify) generated, scanned at
the tip of their campaigns, and the hand-written
[git2-rs](https://github.com/rust-lang/git2-rs), scanned as its crustify audit
campaign found it.

| Example | Wraps | Written by | Branch | Scanned commit |
|---|---|---|---|---|
| [`ffmpeg-bindings/ffimap.json`](ffmpeg-bindings/ffimap.json) | FFmpeg (`libavutil`) | crustify | `crustify/campaigns/20261005` | `164ee2717c` |
| [`libgit2-bindings/ffimap.json`](libgit2-bindings/ffimap.json) | libgit2 | crustify | `crustify/devel` | `2236cf82ef` |
| [`git2-rs/ffimap.json`](git2-rs/ffimap.json) | libgit2 | hand-written (git2 0.21.0) | upstream `main` | `f6f11169de` |

`crate_path` is the workspace's path in the campaign's container. git2-rs
uses no ffibox, so its `ffibox` record counts only the owners and handles it
wrote itself (`*_non_ffibox_*`).

libgit2-bindings builds against a path dependency on ffibox, so its numbers
move with that checkout as well as with its own commit; this document was
scanned against ffibox `55e5f8ace6`. A handful of counters shifted between
`203b1a0` and that commit, so a rescan that does not match will not reproduce
it exactly.

The libgit2 and git2-rs documents are on the current schema -- `counts` as a
tree, `c_type_borrow` split by position -- and were scanned with each crate's
own seam names declared, and `--ffibox` only where it is true:

    libgit2-bindings  --ffibox --seams "from_ptr as_ptr as_mut_ptr from_void_ptr as_void_ptr"
    git2-rs                    --seams "raw from_raw raw_mut from_raw_opt from_raw_const unwrap"

git2-rs is built on no ffibox, so it is scanned without the flag; it still
carries the owner and handle record, whose `non_ffibox` half counts what it
wrote itself.

so the fn and raw-pointer counters carry an `of_which.seam` share. Without it
the two crates are not comparable: git2-rs's entire public raw-pointer surface
is its `Binding` seam. See [docs/raw.md](../docs/raw.md)'s Seams section.

The FFmpeg document predates the schema and has not been regenerated; see
[docs/TODO.md](../docs/TODO.md).

Every field is described in [docs/output.md](../docs/output.md) and the
per-area counter documents it indexes.
