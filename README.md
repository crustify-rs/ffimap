# ffimap

A deterministic scanner of a Rust crate's `unsafe` surface and raw-pointer usage.

ffimap checks a Cargo workspace through a rustc driver and counts, from the
compiler's own HIR and type information, how the crate's code bypasses safe Rust: its
`unsafe` functions, blocks and calls, the raw pointers its functions take or return
and its structs hold in their fields, the primitives they are cast to and built from,
and more. [docs/schema.md](docs/schema.md) lists every counter.  

It is meant for Rust crates that interact with FFI libraries (C/C++), and is
integrated with [ffibox](https://github.com/crustify-rs/ffibox)
for building safe FFI bindings. ffimap is also the safety scan
used by [crustify](https://github.com/crustify-rs/crustify).

- **Deterministic.** The same tree gives the same bytes under a fixed
  scanner.
- **Compiler-precise.** Counts are made after macro expansion, `cfg` selection
  and type resolution, which source-text tools cannot do.
- **Fact-driven.** A counter is a declaration or one expression node, with no
  dataflow and no points-to analysis behind it.

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
ffimap path/to/workspace --sys-crates libgit2-sys > scan.json
```

`WORKSPACE` is the directory holding the Cargo workspace or package to scan.
ffimap writes no files: the JSON document goes to stdout, and progress and
errors go to stderr. There is no prose rendering of the counters:
`docs/schema.md` describes them and the document carries them.

## CLI

```text
ffimap WORKSPACE [--ffibox] [--sys-crates CRATE[,CRATE...]]
                 [--seams NAMES] [--sites COUNTER ...]
```

| Option | Effect |
|---|---|
| `--sites COUNTER ...` | Also report where each named counter's increments are in the source (file, count, lines). Each is a counter's dotted path, such as `raw_ptr.fn_sig_arg.safe.pub`. |
| `--sys-crates CRATE,...` | Treat these crates' `#[repr(C)]` types as C's, and descend through their types when deciding which types store a raw pointer. Name the crate's own bindings and anything else it reaches C through, such as `libc`. Nothing is discovered — a Cargo `links` key and a `*-sys` name both over-report — so unnamed means the scanned crate alone. |
| `--seams NAMES` | Function names that are seams -- the conversion between a wrapper and its raw pointer (`raw`, `from_raw`, `as_ptr`). Newline- or comma-separated, so `--seams "$(cat seams.txt)"` works. Reported as the `of_which.seam` share of each fn-signature counter, so plumbing can be told from the pointer management a consumer actually faces. ffimap never guesses the names. |
| `--ffibox` | The crate is built on [ffibox](https://github.com/crustify-rs/ffibox). Turns on the vocabulary's arms, which [docs/ffibox.md](docs/ffibox.md) describes, and sanctions the conventions' `as_ref` / `as_mut` layout accessors, which are matched by name and so hold only where that convention does. |

## Output

The JSON document has these top-level fields:

| Field | Contents |
|---|---|
| `crate_path` | The scanned workspace. |
| `sys_crates` | The crates whose `#[repr(C)]` types were taken as C's, as `--sys-crates` named them. |
| `scanner` | What scanned: the ffimap commit, the pinned toolchain, and the `--ffibox` and `--seams` inputs. A figure is comparable with another only under the same ones. |
| `counts` | The counters of `docs/schema.md`, or `null` when the workspace could not be built. Every counter lives here; there is no second, flat block. |
| `counts_unavailable` | Why `counts` is `null`, otherwise `null`. |
| `sites` | With `--sites`: source locations per requested counter. |

When the check fails, ffimap reports no counts rather than approximate ones.
Generated `-sys` binding crates are never counted as the subject, and neither
is test code: it has `code.tests` to itself.

## Documentation

| | |
|---|---|
| [docs/schema.md](docs/schema.md) | the counters: what each one holds, how a record is shaped, and how a report is built from them |
| [docs/analysis.md](docs/analysis.md) | the analysis: how a scan runs, and what each counter is decided from |
| [docs/ffibox.md](docs/ffibox.md) | the `--ffibox` arms and the conventions they read |

[examples/](examples) has full documents from three real wrappers: two that
crustify generated, over FFmpeg and libgit2, and the hand-written git2-rs.

## Tests

```sh
python -m unittest discover -s tests
```

## Maintainers

- Marius Momeu ([marius.momeu@berkeley.edu](mailto:marius.momeu@berkeley.edu))

## Acknowledgements

This material is based upon work supported by the Defense Advanced Research
Projects Agency (DARPA) Translating All C To Rust (TRACTOR) program under
Agreement No. HR00112590134.
