# ffimap

A deterministic map of a Rust crate's FFI and `unsafe` surface.

ffimap compiles a Cargo workspace through a rustc driver and counts, from the
compiler's own HIR and type information, how the crate's code meets C: its
`unsafe` blocks and functions, raw and `void` pointers on its API, references
it forms into memory C may write, wrappers over C types, and FFI calls. It is
built for Rust crates that wrap C libraries, and is the safety scan used by
[crustify](https://github.com/crustify-rs/crustify).

- **Deterministic.** No LLM and no network. The same tree gives the same
  bytes, so a diff between two scans is a change in the crate.
- **Compiler-precise.** Counts are made after macro expansion, `cfg` selection
  and type resolution, which source-text tools cannot do.
- **Counts, not verdicts.** It says how much unsafety there is and where, never
  which of it is wrong.

## Requirements

- Python 3.13 or newer.
- `rustup`, for the dated nightly the driver is pinned to
  ([`rust-toolchain.toml`](src/ffimap/driver/rust-toolchain.toml)), with its
  `rustc-dev` and `llvm-tools` components.
- A workspace that builds on that nightly, native dependencies included.

## Install

```sh
git clone https://github.com/crustify-rs/ffimap.git
python -m pip install -e ffimap
(cd ffimap/src/ffimap/driver && rustup toolchain install)   # the pinned nightly
```

The driver itself is built on the first scan and rebuilt only when the
toolchain changes.

## Usage

```sh
ffimap path/to/workspace                 # human-readable summary
ffimap path/to/workspace --json > scan.json
```

`WORKSPACE` is the directory holding the Cargo workspace or package to scan.
ffimap writes no files: the summary or the JSON document goes to stdout, and
progress and errors go to stderr.

## CLI

```text
ffimap WORKSPACE [--json] [--ffibox] [--sys-crates CRATE[,CRATE...]]
                 [--sites COUNTER ... | all]
```

| Option | Effect |
|---|---|
| `--json` | Print the full JSON document instead of the summary. |
| `--sites COUNTER ...` | Also report where each named counter's increments are in the source (file, count, lines). `all` names every counter that counts locations. A shared-borrow counter also takes `COUNTER:ORIGIN` (`self`, `param` or `other`). |
| `--sys-crates CRATE,...` | Treat these crates' `#[repr(C)]` types as C's, beside those found automatically (crates with a Cargo `links` key or named `*-sys`). Use it for bindings such as `libc`. |
| `--ffibox` | Also count the crate's use of [ffibox](https://github.com/crustify-rs/ffibox): owners and handles in signatures and fields, and ffibox trait impls. Adds an `ffibox` record whose counters also take `--sites`. |

## Output

The JSON document has these top-level fields:

| Field | Contents |
|---|---|
| `crate_path` | The scanned workspace. |
| `sys_crates` | The crates whose `#[repr(C)]` types were taken as C's. |
| `counts` | The compiler-derived counters, or `null` when the workspace could not be built. |
| `counts_unavailable` | Why `counts` is `null`, otherwise `null`. |
| `derived` | Ratios computed from `counts`, such as the share of public functions that are `unsafe`. |
| `provenance` | The accesses to C memory under a shared borrow of a wrapper, split by where the pointer came from: `self`, another parameter, or elsewhere. |
| `sites` | With `--sites`: source locations per requested counter. |
| `ffibox` | With `--ffibox`: the ffibox surface, per counter and breakdown key. |

When the build fails, ffimap reports no counts rather than approximate ones.
Generated `-sys` binding crates are never counted as the subject.

Every counter, how C types are identified, and the known limitations are
described in [docs/output.md](docs/output.md).

[examples/](examples) has full documents from two real wrappers, over FFmpeg
and libgit2.

## Tests

```sh
python -m unittest discover -s tests
```
