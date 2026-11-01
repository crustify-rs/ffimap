# How a scan runs

What produces a document, and what it requires. The counters themselves are
[`schema.md`](schema.md); the `--ffibox` arms are [`ffibox.md`](ffibox.md).

## 1. Determinism, and what it rests on

The document is a pure function of the source tree **under a fixed scanner**.
Two runs over one tree agree byte for byte, so a diff between them is a change
in the crate -- but only if the ffimap commit, the flags and any framework the
crate is built on are the same. A campaign that records a scan should record
those beside it, or a later diff cannot tell a change in the crate from a
change in the scanner.

## 2. The toolchain

A `rustc_private` driver compiles only against the compiler internals it was
written for, so the nightly is pinned by date in
`src/ffimap/driver/rust-toolchain.toml` and both the driver and the scanned
workspace build on it. It needs `rustc-dev` and `llvm-tools`.

## 3. The build

```sh
cargo +<pinned nightly> check --all-targets
```

`check`, not `build`: the driver reports from `after_analysis`, so HIR and
typeck are all it needs, and `--emit=metadata` links nothing. A wrapper's test
binaries link the C library, and a fixture's `extern` declarations may have no
implementation at all, so linking them would make the scan fail where it
otherwise succeeds.

`--all-targets`, not `--tests`: the latter checks the test targets *instead of*
the plain library, and the library's emission is the scan.

The scan needs the workspace to compile. When it does not, `counts` is `null`
and `counts_unavailable` carries the reason; ffimap reports no counts rather
than approximate ones.

## 4. The emission protocol

The driver runs as `RUSTC`, so it sees one invocation per crate per target.
Each prints one line:

```json
{"crate": "<name>", "test": false, "counts": {"<dotted path>": 12}, "sites": {}}
```

Four rules decide what the Python side does with a line.

- **`CARGO_PRIMARY_PACKAGE`.** `after_analysis` returns early without it, so
  only workspace members emit and dependencies are silent. A workspace member
  that another member depends on is built in a dependency unit where it is
  unset, which is why a `-sys` crate inside the scanned workspace emits
  nothing -- and is also dropped by the next rule, so nothing is lost.
- **`-sys` crates are skipped**, by a `*_sys` suffix or by being named in
  `--sys-crates`. Their generated bindings are not the audit subject; their
  types are still walked into, as the peel set.
- **`build_script_build` is skipped.** Under `--all-targets` a build script is
  its own crate, and it builds the crate rather than being part of it. Left
  in, it added 128 lines to libgit2-bindings' library count.
- **`--test` routes a line to `code.tests`.** Cargo passes it for the lib's
  test target and for each integration test crate, so the driver tells test
  code from the library without inspecting an item. A lib test target
  recompiles the library with `cfg(test)` on, so its figures include the
  library's and are subtracted, keyed on the crate name it shares with the
  non-test emission; an integration crate shares its name with no library, so
  nothing is subtracted from it.

## 5. The flags that change what is counted

Two inputs change the figures and belong with any recorded scan.

`--sys-crates` is the peel set, which decides what `ty.storing_raw_ptr` means
(see [`schema.md`](schema.md)'s peel set section). It is named, never
discovered: a Cargo `links` key and a `*-sys` name both over-report --
`prettyplease` carries a `links` key to detect duplicate versions of itself,
and bindgen's `clang_sys` matches the name -- and discovery had put both in the
peel set of libgit2-bindings. An unnamed `-sys` crate drops out of the walk and
the counter reads low for a reason that is not in the code, so the document
records the set it ran with in `sys_crates`.

`--seams` names the functions that only convert between a wrapper and its raw
pointer. It is established once per campaign and recorded, so every batch's
scan reads the same list: a list inferred per batch would make
`casted_to.local_seam` a measure of which agent looked harder.

## 6. The cache

A scan measures nothing if cargo serves the build from cache, so the source
roots of every workspace member are touched to a strictly future mtime first.
`time.time()` alone is not enough: two scans less than a filesystem tick apart
leave the mtime unchanged, the second is served from cache, and the document
would report a crate that was never analysed. The collector counts the crates
that emitted and raises when none did.

## 7. Sites

`--sites` takes a counter's dotted path and adds a `sites` record beside
`counts`, one list per counter, each entry a file with a count and its lines.
Paths are validated against the prefix and the family under it, not against a
list of leaves, because the ffibox arms are generated from a vocabulary. There
is no `all`: enumerating every leaf is a different request.

A site for a macro-generated item reports the macro's **call site**, since that
is where the item's span points. A `define_ctype!(` or `impl_cdrop!(` line
among the sites of a type or impl counter is that, not a miscount.

## 8. The document

| field | contents |
|---|---|
| `crate_path` | the scanned workspace |
| `sys_crates` | the peel set it ran with |
| `counts` | the counter tree, or `null` |
| `counts_unavailable` | why `counts` is `null`, otherwise `null` |
| `sites` | with `--sites` only |

The document is the only output: there is no prose rendering of the counters,
which would be a second description of the schema in a place no test reads.
