# Examples

`ffimap --json --ffibox` documents for three safe Rust wrappers over C
libraries: two that [crustify](https://github.com/crustify-rs/crustify)
generated, scanned at the tip of their campaigns, and the hand-written
[git2-rs](https://github.com/rust-lang/git2-rs), scanned as its crustify audit
campaign found it.

| Example | Wraps | Written by | Branch | Scanned commit |
|---|---|---|---|---|
| [`ffmpeg-bindings/ffimap.json`](ffmpeg-bindings/ffimap.json) | FFmpeg (`libavutil`) | crustify | `crustify/campaigns/20261005` | `164ee2717c` |
| [`libgit2-bindings/ffimap.json`](libgit2-bindings/ffimap.json) | libgit2 | crustify | `crustify/campaigns/20261008-170008` | `7109066913` |
| [`git2-rs/ffimap.json`](git2-rs/ffimap.json) | libgit2 | hand-written (git2 0.21.0) | `crustify/campaign` of the audit | `cbc7a16b58`, upstream `db31ed4` |

`crate_path` is the workspace's path in the campaign's container. git2-rs
uses no ffibox, so its `ffibox` record counts only the owners and handles it
wrote itself (`*_non_ffibox_*`).

Every field is described in [docs/output.md](../docs/output.md).
