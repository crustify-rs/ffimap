# The ffimap document

`ffimap WORKSPACE` builds the workspace through a rustc driver over
HIR and type checking. Its output is a deterministic description of the code
that the build's active `cfg` selects—not a soundness verdict or quality score.

The scan writes no file. `--json` prints the document on stdout and the caller
redirects it wherever that run's record belongs. Where a scan is kept is the
caller's decision, so nothing here creates paths or edits a `.gitignore`.

## Availability

The scan requires:

- the dated nightly pinned in `src/ffimap/driver/rust-toolchain.toml`
  (a `rustc_private` driver builds only against the compiler internals it was
  written for), with `rustc-dev` and `llvm-tools`;
- successful `cargo metadata`;
- a workspace that builds under the nightly driver, including its native
  dependencies.

When measurement cannot run, `counts` is `null` and `counts_unavailable`
contains the failure. The tool does not substitute approximate results.

Generated `-sys` binding crates are excluded from the aggregate because they
are not the wrapper being audited.

## Document shape

- `crate_path`: audited Cargo workspace.
- `counts`: aggregate compiled-code metrics (numbers only), or `null`.
- `counts_unavailable`: failure text when counts are unavailable.
- `derived`: ratios and sums calculated from counts.
- `sites`: present when `--sites` names counters; see Counter sites.
- `ffibox`: present with `--ffibox`; see ffibox surface. `null` when there are
  no counts.

Unsafe-block totals provide context only. A C wrapper must contain unsafe code,
and combining many small unsafe blocks into fewer large ones improves the count
without improving the code.

## The crate's own surface: visibility and safety

Every counter measures what the scanned crate itself defines: its types, its
fns and its methods. Items of other crates are never counted (ffibox's `CBox`,
`CArc` and their methods, std's), and neither are methods implementing another
crate's trait (`Clone`, `Drop`, ffibox's `CDrop`, ..), whose signature that
crate fixed. "pub" is rustc's effective visibility, reachable from outside the
crate: a `pub` item in a private module is not, unless it is re-exported, and a
`pub(crate)` item (such as the constructors `define_ctype!` emits) is private.

- `unsafe_fns` = `unsafe_fns_pub` + `unsafe_fns_priv`. `unsafe_fns_pub` is the
  public unsafe surface: every obligation the crate exports to its callers.
- `unsafe_impls` counts the crate's `unsafe impl`s of any trait, and
  `unsafe_traits` the `unsafe trait`s it declares. The `TrivialClone` impl a
  `#[derive(Clone)]` emits is not counted.
- `unsafe_send_impl` and `unsafe_sync_impl` count the `unsafe impl Send` and
  `unsafe impl Sync` among `unsafe_impls`: every type the crate opts into
  thread safety by assertion instead of earning it from its fields. A negative
  impl (`impl !Send`) is not unsafe and is not counted. Each impl asserts that
  a value may move to, or be shared with, another thread; for a type holding
  a C object, that is the C library's to allow, so check it against the
  library's thread-safety contract. A wrong one is a data race reachable from
  safe code.
- Every raw-pointer position falls in exactly one of seven counters, by where
  it sits. A position is a `*const T` / `*mut T`, a `NonNull<T>`, which is a
  `*const T` that is never null, or an `AtomicPtr<T>`, a `*mut T` behind an
  atomic:

  ```text
  raw_ptr_ty_pub_fields_pub, raw_ptr_ty_pub_fields_priv, raw_ptr_ty_priv
                                                 fields of types
  raw_ptr_fn_pub_safe,  raw_ptr_fn_pub_unsafe    fn signatures (args and return)
  raw_ptr_fn_priv_safe, raw_ptr_fn_priv_unsafe
  ```

  A field counts by its type's visibility and, in a public type, by the
  field's own: `_fields_pub` are reachable from outside the crate (a `pub`
  field of an exported type), `_fields_priv` are the representation a public
  type keeps to itself. A signature counts by the
  fn's visibility and its safety: `_safe` is a safe fn, reachable from safe
  code, `_unsafe` an `unsafe fn`, whose caller has taken the obligation on. The
  raw pointers on the safe public interface are `raw_ptr_ty_pub_fields_pub` +
  `raw_ptr_fn_pub_safe`. The public positions measure the raw-pointer work a
  consumer of the crate is left with; the private ones the backend's, which
  the consumer never sees. A handle that keeps its pointer in a private field
  behind safe methods therefore counts only on the backend side, while a
  `NonNull` or `AtomicPtr` on the public interface counts like a raw pointer:
  its API is the pointer's, so using it is pointer management. `raw_ptr_has_c_type_wrapper` counts the positions whose pointee is a C type that already has a
  wrapper. Generated bindings compiled into the crate are skipped: files under
  the build script's `OUT_DIR` and files named `bindings.rs`; bindings in a
  `-sys` crate are excluded with that crate.
- `void_ptr_ty_pub_fields_{pub,priv}`, `void_ptr_ty_priv` and
  `void_ptr_fn_{pub,priv}_{safe,unsafe}` count
  the `*const c_void` / `*mut c_void` positions among them, partitioned the
  same way.

The C-ABI gateway (`#[no_mangle]` / `#[export_name]` / `extern "C"` fns) is
counted like any other fn; its unsafe blocks are also counted apart, in
`unsafe_blocks_ffi_export`.

`safe_fns_pub` and `safe_fns_priv` count the safe functions and methods with
a body, on the same terms as `unsafe_fns_*`: by visibility, leaving out
methods implementing another crate's trait. So the crate's own functions are
`fns_pub` = `safe_fns_pub` + `unsafe_fns_pub` and likewise `fns_priv`, both
given in `derived`. Trait method declarations without a body are not counted.

A position is every raw pointer in a parameter, return or field type, including
those nested in references, generic arguments (`Option<*const T>`), tuples,
arrays and slices. A pointer to a pointer (`*mut *mut T`) is one position,
fn-pointer types are not entered, and `PhantomData<*const T>` is a zero-sized
marker, not a position. Type aliases are resolved, so
`type P = *const T` counts as a raw pointer.

The derived fields:

- `fns_pub` / `fns_priv`: `safe_fns_pub + unsafe_fns_pub`, likewise `_priv`.
- `unsafe_fn_pub_ratio`: `unsafe_fns_pub / unsafe_fns`.
- `unsafe_fn_share_of_pub_fns`: `unsafe_fns_pub / fns_pub`.
- `raw_ptr_pub`: `raw_ptr_ty_pub_fields_pub + raw_ptr_ty_pub_fields_priv +
  raw_ptr_fn_pub_safe + raw_ptr_fn_pub_unsafe`.
- `raw_ptr_pub_safe_interface`: `raw_ptr_ty_pub_fields_pub + raw_ptr_fn_pub_safe`.
- `unsafe_loc_ratio` and `loc_per_unsafe_block`: context, not a score.

## Wrappers and references into C memory

### Which types are C's

`#[repr(C)]` does not make a type C's: Rust crates use it for their own
layouts too. The driver decides by provenance instead, as a closure over the
types the build hands to C:

- **Seeds.** Every type behind a pointer (`*const T`, `*mut T`, `&T`,
  `NonNull<T>`, nested) in the signature of a foreign function (an `extern`
  block), of a function the crate defines with a non-Rust ABI (callbacks, the
  `#[no_mangle]` gateway), or of a C-ABI function-pointer type anywhere in the
  crate (vtables, callback slots); a foreign static's own type; the type a
  pointer cast or `transmute` converts to or from `*c_void` (a payload handed
  to C, or C memory typed as Rust); and every `#[repr(C)]` type of a **sys
  crate**, and every enum without variants it declares (`pub enum git_blob
  {}`, the opaque C type of hand-written bindings).
- **Closure.** A field a C-reachable type holds by value or points to; either
  side of a pointer cast (`as`, `.cast()`) or `transmute` whose other side is
  C-reachable; and a local `#[repr(C)]` / `#[repr(transparent)]` type holding a
  C-reachable type by value.

Passing a type by value is a copy and seeds nothing. The sys crates are every
crate in the dependency graph with a Cargo `links` key or named `*-sys`
(`cargo metadata`; a binding crate that links nothing itself, such as
`pcre2-sys`, sets no `links`), plus any named with
`--sys-crates CRATE[,CRATE...]` -- for bindings that are neither, such as
`libc`. A crate may set `links` only to pass build-script metadata (such as
`prettyplease`); it then joins the set harmlessly, having no C types. The document records the set in `sys_crates`; their emissions
are bindings and are skipped, whatever their name.

### Wrappers

A wrapper is a struct that is either a **handle**, a `#[repr(transparent)]`
newtype whose one non-zero-sized field is a raw pointer, `NonNull` or
reference, or a **layout newtype**, `#[repr(transparent)]` or `#[repr(C)]`,
holding a C-reachable type by value (local `#[repr(C)]` fields C does not
reach are searched through). `c_type_wrapper` counts the layout newtypes.
A local C type C reaches itself -- a hand-written mirror, a callback payload --
is not a wrapper of anything, but its references are checked like a layout
newtype's. How the layout newtypes relate to ffibox's `CCell` is in the
`--ffibox` record (`ffibox_layout_not_ccell`, `ffibox_ccell_not_layout`).

Handles, newtypes over a pointer to a C object, are not counted as wrappers:
the raw pointer a handle stores counts at its field in `raw_ptr_ty_*`, and a
reference it hands out, through `Deref` or otherwise, in
`c_type_borrow_non_sanctioned`.

A layout newtype's memory is C's when it is reached through a C pointer, so a
Rust reference to it asserts `noalias`, `readonly` or validity over memory C
may write. Access goes through the handles instead.

The `c_type_*` counters below cover the **C types**: a sys crate's, the
local `#[repr(C)]` / `#[repr(transparent)]` types C reaches, and the layout
newtypes over them. A Rust type C reaches only as a `void *` payload, a
callback's state say, is not one: C never reads its bytes. A C type is
**opaque** when its values take up no bytes or there are none: an enum
without variants, or bindgen's `struct { _unused: [u8; 0] }`. A reference
to one covers no bytes of C's, so it asserts nothing over memory C may
write; whether it is valid at all is the question it raises.

- `c_type_borrow_sanctioned` and `c_type_borrow_non_sanctioned` count
  the borrows into C memory -- `&W` / `&mut W` (or `&[W]`, `Option<&W>`, ..),
  W a C type that is not opaque -- wherever they occur:
  - in function signatures (the receiver included): sanctioned are the
    accessors `as_ref` / `as_mut`, which hand out borrowed handles over a
    Rust-owned value, and methods of impls of the standard value traits
    `Clone`, `PartialEq`, `Eq`, `PartialOrd`, `Ord`, `Hash` and `Debug`,
    derived or not; every other position is non-sanctioned, the `&self` /
    `&mut self` of an `impl Deref` / `DerefMut` on a layout newtype included,
    which turns every `*w` and auto-deref into a reference to the C object;
  - in function bodies: an expression that forms such a reference from a raw
    pointer -- `&*p`, `&mut *p`, `&(*p).f` (casts included), an autoref through
    `*p` for a `&self` method, or a call to a function from another crate that
    takes a raw pointer or `NonNull` and returns a type holding `&W`
    (`p.as_ref()`, `NonNull::as_ref`, `slice::from_raw_parts`). Calls to the
    crate's own functions are not counted at the call site; their bodies are.
    Never sanctioned;
  - in fields of the crate's types: a field holding such a reference, a
    handle over `&'a ffi::T` included. Never sanctioned.

  A shared `&W` over storage that holds an `UnsafeCell` is not counted: it
  asserts neither `readonly` nor `noalias`; `&mut W` still is. A
  `PhantomData<&W>` marker holds no reference and is not counted.
  `c_type_borrow_non_sanctioned`'s target is 0.
- `c_type_borrow_opaque` counts the borrows of those shapes, in any of the
  three positions, whose `W` is an opaque C type. `c_type_borrow_generic`
  counts the borrows a function body forms from a raw pointer, as above,
  whose `W` is a type parameter or an associated type (`&*p` with
  `p: *const T`, `NonNull<T::C>::as_ref`). The pass reads each generic body
  once, not its instantiations, so it cannot tell whether `T` is a C type;
  each site forms the reference for every `T` its callers pick.
- `c_type_by_val_*` and `c_type_std_owner_*` count the C types, opaque ones
  aside, held by value outside ffibox's owners. `by_val` counts one held
  directly: `Foo`, or `Foo` inside a tuple, an array or a standard value
  container (`Option`, `Result`, `Cell`, `RefCell`, `UnsafeCell`, `OnceCell`,
  `Mutex`, `RwLock`, `MaybeUninit`, `ManuallyDrop`, `Pin`). `std_owner` counts
  one under a standard heap owner (`Box`, `Rc`, `Arc`, `Vec`, `VecDeque`, so
  `Pin<Box<Foo>>` and `Option<Arc<Foo>>` too). Each occurrence counts once,
  in one family. Nothing behind a reference or raw pointer counts, and no
  other type is searched: ffibox owners belong to the `--ffibox` record, and a
  local type's fields are counted where it is declared. The fields of a C
  type are not counted: they are its C layout, and a layout newtype's C
  field is its storage.
  - `_fn_sig_{pub,priv}`: parameters and returns, by the function's effective
    visibility. A constructor's `-> Self` counts. Methods implementing another
    crate's trait (`Clone::clone`) are left out.
  - `_ty_{pub_fields_pub,pub_fields_priv,priv}`: fields of the crate's structs,
    unions and enums, split as for `raw_ptr_ty_*`.

  A C object held by value is Rust-owned storage that moves, so a pointer C retained
  into it dangles after a move, and no owner runs its C destructor. Those are
  the cases ffibox's `CBox` and `CVal` exist for. A site is not a defect in
  itself: a plain record C never retains is sound by value. It means "check
  that C does not keep this address and that the value owns no C resources".
- `non_c_type_borrow_{pub,priv}_{safe,unsafe}` are the counterpart: every
  `&T` / `&mut T` in a function signature (the receiver and nested references
  included), by the function's visibility and safety as for `raw_ptr_fn_*`,
  where `T` -- or a slice's element -- is not a C type: `&CStr`, `&str`,
  `&[u8]`, `&mut Config`. These borrows stay on the Rust side of the
  boundary.
- `raw_ptr_derefs_rd` and `raw_ptr_derefs_wr` count the dereferences `*p` of a
  raw pointer, decided by the operand's type, so `*` on a `Box`, a reference
  or a `Deref` impl is not one. Each falls in one of the two by what is done
  with the place `*p`, or a field or index below it: `_wr` when it is
  assigned (`=`, `op=`) or borrowed mutably (`&mut`, `&raw mut` /
  `addr_of_mut!`, a `&mut self` method or `IndexMut` autoref), `_rd`
  otherwise, shared borrows and `addr_of!` included. `*(*p).next = x` is a
  read of `(*p).next` and a write. `raw_ptr_derefs_outside_impl` counts the
  dereferences of either kind outside any `impl` or trait body.

- `drop_impl` counts the crate-defined types with an `impl Drop`, and
  `clone_impl` those with a hand-written, not derived, `impl Clone`; one per
  type. Each is an owner or a copy written by hand: a decision about how
  a C object is torn down or duplicated, which deserves a look. A type that
  owns through another crate's owner (`Box`, or ffibox's `CBox` / `CArc` /
  `CVec` and its clone policies) has neither, since those impls are that
  crate's; so on an ffibox wrapper the two count what was written outside
  ffibox.

Read these together with `c_type_wrapper`; when there are no wrapper
newtypes, zero is vacuous. The driver cannot tell a pointer to C memory from
one to a Rust-owned value, so a site means "check where this pointer comes
from".

## ffibox surface

`--ffibox` adds an `ffibox` record, `{"counts": {counter: N}, "by": {counter:
{key: N}}}`: each counter's total, and its breakdown by ffibox type, handle
kind or trait. Every counter is present, zeros included, and each takes
`--sites` alongside `--ffibox`, whole or for one key of its breakdown as `<counter>:<key>` (`fn_sig_ffibox_owner_pub:CVal`). `_pub` / `_priv` is the effective visibility of
the function for a signature position, and of the implementing type for an
impl.

Signature positions, parameters and return types, nested ones included as for
raw pointers (`Option<CBox<T>>` is one `CBox`):

- `fn_sig_ffibox_owner_*`: an ffibox owner (`CBox`, `CArc`, `CVec`, `CStrBox`,
  `CVal`), keyed by type. Aliases are resolved, so `type FooBox = CBox<..>` is
  a `CBox`.
- `fn_sig_ffibox_handle_*`: an ffibox-based borrowed handle: one of the crate's
  own, keyed `Ref`, `Mut` or `Locked` (the types its `impl CCell` binds to
  `Ref` / `Mut` and its `impl CGuarded` binds to `Locked`, read off the impls
  rather than the names); one of ffibox's borrowed views, keyed by type
  (`CSlice`, `CSliceMut`, `CBorrowedPtr`, `CGuardedRef`, `CGuard`); or another
  newtype over one of those -- exactly one non-zero-sized field, whatever
  its `repr`, a handle built on ffibox by hand -- keyed by its path; a record
  holding one beside other fields is not a handle. A method's
  receiver counts here when it is such a handle, since that is where a C
  function's borrowed `T *` lands.
- `fn_sig_non_ffibox_owner_*`: one of the crate's own owners, keyed by type: a
  crate-defined type with an `impl Drop`, one of the types the main counter
  `drop_impl` counts. Together with `fn_sig_ffibox_*` it says how much of the
  ownership an API hands out goes through ffibox and how much does not.
  (`fn_sig_ffibox_owner_*` is its ffibox counterpart.)
- `fn_sig_non_ffibox_handle_*`: one of the crate's other handles, keyed by
  type: a crate-defined type that points at a C object -- a raw pointer,
  `NonNull` or reference, in a field, to a C-reachable type, a layout wrapper
  or `c_void` -- and is none of the above nor a layout type. These are handles
  written outside ffibox. A pointer to Rust data, or a borrow of a Rust view
  (`&[u8]`, `&str`), does not make a handle: those types are views and
  iterators. A method's receiver of such a type counts too.

Each splits by the fn's visibility, `_pub` and `_priv`. The
functions read are free functions, inherent methods and the crate's own trait
declarations. A trait impl's methods are left out, since the trait fixes their
signatures. A method's `self` receiver counts only when it is a borrowed handle
(`fn_sig_ffibox_handle_*` or `fn_sig_non_ffibox_handle_*`): `&self` on an owner or a plain value borrows a Rust
value, not a C object, and is skipped.

The field families -- `ty_pub_fields_pub_<kind>`, `ty_pub_fields_priv_<kind>`
and `ty_priv_<kind>`, for the kinds `ffibox_owner`, `ffibox_handle`,
`non_ffibox_owner` and `non_ffibox_handle` -- count the same kinds in the fields of the structs,
unions and enums the crate defines, split as for `raw_ptr_ty_*`: by the type's
visibility and, in a public type, by the field's own. They say what the
crate's types hold, where the `fn_sig_*` families say what its functions take
and return. Borrows of memory that is not C's are a main counter,
`non_c_type_borrow_*`, since they do not depend on ffibox.

Trait impls, counted as distinct crate-defined types per trait, so a type
implementing `From<A>` and `From<B>` counts once for `From`:

- `ffibox_impl_macro` / `ffibox_impl_manual`: types implementing each ffibox
  trait (`CCell`, `CDrop`, `CRefClone`, `CDupClone`, `CGuarded`, ..), keyed by
  trait, split by whether an ffibox macro (`define_ctype!`, `impl_cdrop!`, ..)
  emitted the impl. A lifecycle policy implements `CDrop<T>` and the like, so
  it is the policy type that counts here, not the layout type.
- `ffibox_define_ctype_macro` / `ffibox_define_ctype_manual`: the crate's
  layout types, its `CCell` implementors, keyed by type, split by whether
  `define_ctype!` emitted the `CCell` impl or it was written by hand.
- `ffibox_ccell_not_layout` / `ffibox_layout_not_ccell`: the crate's types,
  keyed by type, that implement `CCell` without being layout newtypes by shape
  (a wrapper without the layout it claims), and the layout newtypes that do
  not implement `CCell` (wrappers written outside ffibox).

Impls for a type the crate does not define, or for a reference or other
non-ADT type, are not counted. The compiler's `TrivialClone` and
`StructuralPartialEq` marker impls, which a `#[derive]` adds, are skipped.

## Counter sites

`--sites COUNTER [COUNTER ...]` (or `--sites all`) adds a `sites` record beside
`counts`, with one list per named counter: where that counter's increments are
in the source, as `[{"file": .., "count": N, "lines": [..]}]` per file. `count`
is the number of increments in that file, so a counter's per-file counts sum to
its value in `counts`; `lines` are the distinct lines they fell on, sorted. A
signature position (raw/void pointer, `unsafe fn`, `c_type_borrow_*`) is
sited at its function's signature line; a block, dereference, projection,
reference or call at the expression. A site inside macro output
(`define_ctype!`, `#[derive]`) is the line in the measured crate that invoked
the macro. Only counters that count source locations take `--sites`: the line
and statement totals (`code_lines`, `total_stmts`, `unsafe_block_*lines`,
`unsafe_block_stmts`) have none.

## Known limitations

- **References into C memory the counters miss.** A reference to a field of C
  memory whose type is not a C type (`&(*p).len`, a C scalar), and an autoref
  on such a field (`(*p).field.method()` with `&self`), are counted by no
  counter, since `c_type_borrow_*` only cover C types. See
  [TODO.md](TODO.md).
- **Generic code.** Each generic body is read once, generically. A reference
  to a type parameter counts in `c_type_borrow_generic`, whatever `T` turns
  out to be; a `*mut T` counts as a raw-pointer position but never as a
  `void_ptr_*` one or with a wrapper, and a generic type holding a `T` by
  value is not a `c_type_by_val_*` position.
- **Signatures and fields only for pointer positions.** Raw-pointer, `c_void`
  and `c_type_borrow_*` signature counters read the parameter and return
  types of functions with bodies; raw-pointer and `c_void` positions also
  include struct and union fields. Raw pointers in locals, casts, closure parameters, enum variants and
  statics are not positions, and a trait method
  declared without a default body is not counted.
- **Pointer origin.** No counter can tell C-owned memory from Rust-owned memory
  behind a pointer. C reachability is a property of a TYPE, not of a value: a
  `Copy` value of a C-reachable type held in Rust memory (`git2::Oid`) is
  checked like one C owns, and a pointer C only reads during a call counts
  like one it retains.
- **C reachability it cannot see.** Memory C reaches through an erased
  `void *` with no visible cast in the crate, through integer round trips, or
  through a generic wrapper (`W<T>` over a C type: only declarations are read);
  and C types of a binding crate with neither a `links` key nor a `*-sys`
  name, unless named with `--sys-crates`. Every `#[repr(C)]` type and
  variantless enum of a sys crate is taken as C's, including ones C only
  passes by value.
