# Examples

`ffimap --json --ffibox` documents for two safe Rust wrappers that
[crustify](https://github.com/crustify-rs/crustify) generated over C libraries,
each scanned at the tip of its campaign.

| Example | Wraps | Campaign branch | Scanned commit |
|---|---|---|---|
| [`ffmpeg/ffimap.json`](ffmpeg/ffimap.json) | FFmpeg (`libavutil`) | `crustify/campaigns/20261005` | `9c11c4e79a` |
| [`libgit2/ffimap.json`](libgit2/ffimap.json) | libgit2 | `crustify/campaigns/20261008-170008` | `4f1c7aa50c` |

Every field is described in [docs/output.md](../docs/output.md).
