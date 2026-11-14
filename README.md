# ffimap

A deterministic scanner of a Rust crate's `unsafe` surface and raw-pointer usage.

ffimap checks a Cargo workspace through a rustc driver. From the compiler's
own HIR and type information, it counts how the crate's code bypasses safe
Rust:

- its `unsafe` functions, blocks and calls;
- the raw pointers that its functions take or return, and that its structs
  hold in their fields;
- the primitives those pointers are cast to and built from; and
- more: [docs/schema.md](docs/schema.md) lists every counter.

ffimap is meant for Rust crates that interact with FFI libraries (C/C++). It
is integrated with [ffibox](https://github.com/crustify-rs/ffibox), a library
for building safe FFI bindings, and it is the safety scan that
[crustify](https://github.com/crustify-rs/crustify) uses.

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

The first scan builds the driver itself. Later scans rebuild it only when the
toolchain changes.

## Usage

Scan a workspace and save the document:

```sh
ffimap path/to/workspace --sys-crates libgit2-sys > scan.json
```

`WORKSPACE` is the directory that holds the Cargo workspace or package to
scan. ffimap writes no files: the JSON document goes to stdout, and progress
and errors go to stderr.

The document holds the counters as one tree. This excerpt is from the scan of
git2-rs in [examples/](examples):

```json
{
  "counts": {
    "code": {
      "loc": {"total": 15434, "unsafe": 3497},
      "unsafe_block": {"total": 1004, "of_which": {"ffi_export": 49}},
      "unsafe_call": {"total": 1319, "ffi": 674, "rust": 633, "intrinsic": 12}
    }
  }
}
```

### Commands

```text
ffimap WORKSPACE [--ffibox] [--sys-crates CRATE[,CRATE...]]
                 [--seams NAMES] [--regions NAMES] [--barriers NAMES]
                 [--sites COUNTER ...]
ffimap diff BEFORE AFTER
ffimap api extract RUSTDOC_JSON [--dep RUSTDOC_JSON ...] [--plumbing CRATES]
ffimap api diff BEFORE AFTER [--dep RUSTDOC_JSON ...] [--items KEYS] [--raw]
                [--format json|text]
```

### Scan options

| Option | Effect |
|---|---|
| `--sys-crates CRATE,...` | Name the crates that hold the raw C bindings. |
| `--seams NAMES` | Name the functions that are seams. |
| `--regions NAMES` | Name the modules that are regions. |
| `--barriers NAMES` | Name the functions that are the crate's own panic barriers. |
| `--ffibox` | Say that the crate is built on [ffibox](https://github.com/crustify-rs/ffibox). |
| `--sites COUNTER ...` | Also report where each named counter's increments are in the source. |

ffimap never guesses the names these options take: you declare them.

**`--sys-crates`.** ffimap treats the `#[repr(C)]` types of these crates as
C's, and descends through their types when it decides which types store a raw
pointer. Name the crate's own bindings and anything else it reaches C through,
such as `libc`. Nothing is discovered, because a Cargo `links` key and a
`*-sys` name both over-report: when you name no crate, ffimap takes the
scanned crate alone. If the raw bindings are a module of the scanned crate,
not a crate of their own, name them by their path: `crate::sys`.

**`--seams`.** A seam is a function that converts between a wrapper and its
raw pointer, such as `raw`, `from_raw` or `as_ptr`. Separate the names with
newlines or commas, so that `--seams "$(cat seams.txt)"` works. ffimap reports
the seams as the `of_which.seam` share of each fn-signature counter. That
share tells the plumbing apart from the pointer management a consumer of the
crate actually faces.

**`--regions`.** A region is a module that a crate confines one kind of code
to, such as its unsafe FFI. ffimap reports the unsafe blocks by the region
they sit in, and reports apart the unsafe blocks and fns that sit outside
every region.

**`--barriers`.** A barrier is one of the crate's own panic barriers: a
helper that calls `catch_unwind` for its caller. A foreign-ABI fn that calls a barrier counts as catching a panic, as
one that calls `catch_unwind` does.

**`--ffibox`.** This option turns on the arms of ffibox's vocabulary, which
[docs/ffibox.md](docs/ffibox.md) describes. It also sanctions the
`as_ref` / `as_mut` layout accessors of ffibox's conventions. ffimap matches
those accessors by name, so the result holds only where the crate follows
that convention.

**`--sites`.** For each named counter, ffimap reports the file, the count and
the lines of its increments. Name a counter by its dotted path, such as
`raw_ptr.fn_sig_arg.safe.pub`.

### Compare two scans

```sh
ffimap diff before.json after.json
```

`ffimap diff` scans nothing. It reads two documents of one crate, and prints:

- the counters that moved, with their values before and after; and
- for each counter that both documents carry sites for, the lines its
  increments were added at or removed from.

Use it to check a change against the crate before the change. A difference in
`scanner` is reported first, because a counter can move with the scanner as
well as with the crate. Two scanners that are recorded only by package version
are reported too, because a version does not identify one scanner.

### Track a C item's Rust API

`ffimap api` answers a different question, from rustdoc JSON instead of the
driver: did a C item's Rust API survive the landing that wrapped, ported or
migrated the item? A landing is a change as it is merged into the crate.

It finds the Rust items that stand in for a C item by the doc-comment anchors
of [crustify](https://github.com/crustify-rs/crustify)'s convention, such as
``/// Wraps `fn::git_x` ``.

- `ffimap api extract` records, for each C item an anchor names:
  - the public signatures and trait impls of the Rust items that stand in for
    it, and of its handles and owners; and
  - the contract a consumer may rely on, whatever form a handle takes.
- `ffimap api diff` compares two such records of one crate: one from the
  item's first landing, and one from a later landing. It takes two extracts,
  or two rustdoc JSON documents, which it extracts first. It labels each item
  `kept`, `extended`, `changed`, `removed` or `new`. It compares by the contract, or,
  with `--raw`, by the signatures as they stand. It also flags a `Wraps`
  anchor that became `Replaces`.
- `--dep` adds ffibox's rustdoc JSON, so that owners that alias ffibox's types
  resolve.
- `--items` narrows the diff to a worklist.

```sh
cargo +nightly-2026-10-07 rustdoc -p libgit2 --lib -- -Z unstable-options --output-format json
ffimap api extract target/doc/libgit2.json --dep ffibox.json > first.json
ffimap api diff first.json later.json --format text
```

[docs/api.md](docs/api.md) describes the record, its rules and the classes of
the diff.

## Output

The JSON document has these top-level fields:

| Field | Contents |
|---|---|
| `crate_path` | The scanned workspace. |
| `sys_crates` | The crates whose `#[repr(C)]` types were taken as C's, as `--sys-crates` named them. |
| `scanner` | What scanned: the ffimap commit, the pinned toolchain, and the `--ffibox`, `--seams`, `--regions` and `--barriers` inputs. The commit carries the hash of any uncommitted changes. Outside a checkout of ffimap's own, the package version stands in for the commit. Compare two figures only when their scanners are the same. |
| `counts` | The counters of [docs/schema.md](docs/schema.md), or `null` when the workspace could not be built. Every counter lives here; there is no second, flat block. |
| `counts_unavailable` | Why `counts` is `null`, otherwise `null`. |
| `sites` | With `--sites`: the source locations of each requested counter. |

When the check fails, ffimap reports no counts instead of approximate ones.

ffimap never counts generated `-sys` binding crates as the subject. It does
not count test code as the subject either: test code has `code.tests` to
itself.

## Documentation

| Document | Contents |
|---|---|
| [docs/schema.md](docs/schema.md) | The counters: what each one holds, how a record is shaped, and how a report is built from them. |
| [docs/analysis.md](docs/analysis.md) | The analysis: how a scan runs, and what each counter is decided from. |
| [docs/ffibox.md](docs/ffibox.md) | The `--ffibox` arms and the conventions they read. |
| [docs/api.md](docs/api.md) | `ffimap api`: the per-C-item API record, its rules, the diff's classes and the rustdoc JSON formats it reads. |
| [docs/goals.md](docs/goals.md) | For contributors: what ffimap is for, the goals a change to it is judged against, and what it does not do. |

[examples/](examples) has full documents from three real wrappers: two that
crustify generated, over FFmpeg and libgit2, and the hand-written git2-rs.

## Tests

```sh
python -m unittest discover -s tests
```

## License

Licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE) or
  <https://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or
  <https://opensource.org/licenses/MIT>)

at your option.

### Contribution

Unless you explicitly state otherwise, any contribution intentionally
submitted for inclusion in the work by you, as defined in the Apache-2.0
license, shall be dual licensed as above, without any additional terms
or conditions.

## Maintainers

- Marius Momeu <marius.momeu@berkeley.edu>

## Acknowledgements

This material is based upon work supported by the Defense Advanced Research
Projects Agency (DARPA) Translating All C To Rust (TRACTOR) program under
Agreement No. HR00112590134.
