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
                 [--seams NAMES] [--sites COUNTER ... | all]
```

| Option | Effect |
|---|---|
| `--json` | Print the full JSON document instead of the summary. |
| `--sites COUNTER ...` | Also report where each named counter's increments are in the source (file, count, lines). `all` names every counter that counts locations. |
| `--sys-crates CRATE,...` | Treat these crates' `#[repr(C)]` types as C's, and descend through their types when deciding which types store a raw pointer. Name the crate's own bindings and anything else it reaches C through, such as `libc`. Nothing is discovered — a Cargo `links` key and a `*-sys` name both over-report — so unnamed means the scanned crate alone. |
| `--seams NAMES` | Function names that are seams -- the conversion between a wrapper and its raw pointer (`raw`, `from_raw`, `as_ptr`). Newline- or comma-separated, so `--seams "$(cat seams.txt)"` works. Reported as the `of_which.seam` share of each fn-signature counter, so plumbing can be told from the pointer management a consumer actually faces. ffimap never guesses the names. |
| `--ffibox` | The crate is built on [ffibox](https://github.com/crustify-rs/ffibox). Sanctions the conventions' `as_ref` / `as_mut` layout accessors, which are matched by name and so hold only where that convention does. The owner and handle record is emitted either way. |

## Output

The JSON document has these top-level fields:

| Field | Contents |
|---|---|
| `crate_path` | The scanned workspace. |
| `sys_crates` | The crates whose `#[repr(C)]` types were taken as C's, as `--sys-crates` named them. |
| `counts` | The compiler-derived counters, or `null` when the workspace could not be built. |
| `counts_unavailable` | Why `counts` is `null`, otherwise `null`. |
| `derived` | Ratios computed from `counts`, such as the share of public functions that are `unsafe`. |
| `sites` | With `--sites`: source locations per requested counter. |
| `ffibox` | The owner and handle surface, per counter and breakdown key, split into ffibox's and the crate's own. Always present. |

When the build fails, ffimap reports no counts rather than approximate ones.
Generated `-sys` binding crates are never counted as the subject.

[docs/output.md](docs/output.md) describes the document's shape, the
conventions every counter is read under, and the known limitations. The
counters themselves are described per area, in
[docs/unsafe.md](docs/unsafe.md) (the unsafe surface),
[docs/raw.md](docs/raw.md) (raw and `void` pointers),
[docs/ctypes.md](docs/ctypes.md) (C types, wrappers and borrows into C memory)
and [docs/ffibox.md](docs/ffibox.md) (the owner and handle record).

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
