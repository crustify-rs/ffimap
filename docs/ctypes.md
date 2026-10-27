# C types

Which types the crate shares with C, the wrappers it puts over them, the
references it forms into C memory, and the C values it holds by value.

Visibility and safety are read as [`output.md`](output.md)'s Conventions
section describes.

## Counters

- `c_type_layout_wrapper` -- Layout newtypes: a `#[repr(C)]` / `#[repr(transparent)]` struct holding a C type's bytes inline.
- `c_type_borrow_fn_sig_sanctioned_pub` -- Borrow of a C type in the signature of a public fn, in a position the language forces: a `&Self` of a std value-trait impl, or an `as_ref` / `as_mut` layout accessor under `--ffibox`.
- `c_type_borrow_fn_sig_sanctioned_priv` -- Borrow of a C type in the signature of a private fn, in a position the language forces: a `&Self` of a std value-trait impl, or an `as_ref` / `as_mut` layout accessor under `--ffibox`.
- `c_type_borrow_fn_sig_non_sanctioned_pub` -- Borrow into C memory in the signature of a public fn, anywhere else -- target 0.
- `c_type_borrow_fn_sig_non_sanctioned_priv` -- Borrow into C memory in the signature of a private fn, anywhere else -- target 0.
- `c_type_borrow_fn_sig_opaque_pub` -- Borrow into C memory in the signature of a public fn, of an opaque C type, which covers no bytes.
- `c_type_borrow_fn_sig_opaque_priv` -- Borrow into C memory in the signature of a private fn, of an opaque C type, which covers no bytes.
- `c_type_borrow_fn_body_non_sanctioned` -- Borrow a function body forms from a raw pointer, whose referent is a C type.
- `c_type_borrow_fn_body_opaque` -- Borrow a function body forms from a raw pointer, whose referent is an opaque C type.
- `c_type_borrow_fn_body_generic` -- Borrow a function body forms from a raw pointer, whose referent is a type parameter, so it depends on the instantiation.
- `c_type_borrow_ty_non_sanctioned_pub_fields_pub` -- Field of a public type, publicly reachable, holding a borrow of a C type.
- `c_type_borrow_ty_non_sanctioned_pub_fields_priv` -- Private field of a public type holding a borrow of a C type.
- `c_type_borrow_ty_non_sanctioned_priv` -- Field of a private type holding a borrow of a C type.
- `c_type_borrow_ty_opaque_pub_fields_pub` -- Field of a public type, publicly reachable, holding a borrow of an opaque C type.
- `c_type_borrow_ty_opaque_pub_fields_priv` -- Private field of a public type holding a borrow of an opaque C type.
- `c_type_borrow_ty_opaque_priv` -- Field of a private type holding a borrow of an opaque C type.
- `c_type_by_val_fn_sig_pub` -- C type held directly by value in a public fn's signature.
- `c_type_by_val_fn_sig_priv` -- C type held directly by value in a private fn's signature.
- `c_type_by_val_ty_pub_fields_pub` -- C type held directly by value in a public field of a public type.
- `c_type_by_val_ty_pub_fields_priv` -- C type held directly by value in a private field of a public type.
- `c_type_by_val_ty_priv` -- C type held directly by value in a field of a private type.
- `c_type_std_owner_fn_sig_pub` -- C type held under a std heap owner (`Box`, `Rc`, `Arc`, `Vec`) in a public fn's signature.
- `c_type_std_owner_fn_sig_priv` -- C type held under a std heap owner (`Box`, `Rc`, `Arc`, `Vec`) in a private fn's signature.
- `c_type_std_owner_ty_pub_fields_pub` -- C type held under a std heap owner (`Box`, `Rc`, `Arc`, `Vec`) in a public field of a public type.
- `c_type_std_owner_ty_pub_fields_priv` -- C type held under a std heap owner (`Box`, `Rc`, `Arc`, `Vec`) in a private field of a public type.
- `c_type_std_owner_ty_priv` -- C type held under a std heap owner (`Box`, `Rc`, `Arc`, `Vec`) in a field of a private type.
- `non_c_type_borrow_pub_safe` -- `&T` / `&mut T` in the signature of a public safe fn where `T` is NOT a C type: a borrow that stays on the Rust side.
- `non_c_type_borrow_pub_unsafe` -- `&T` / `&mut T` in the signature of a public `unsafe` fn where `T` is NOT a C type: a borrow that stays on the Rust side.
- `non_c_type_borrow_priv_safe` -- `&T` / `&mut T` in the signature of a private safe fn where `T` is NOT a C type: a borrow that stays on the Rust side.
- `non_c_type_borrow_priv_unsafe` -- `&T` / `&mut T` in the signature of a private `unsafe` fn where `T` is NOT a C type: a borrow that stays on the Rust side.
- `c_type_std_value_impl_pub` -- Public C types implementing a std trait whose receiver is forced (`Clone`, `Hash`, `Deref`, ...). Each puts a `&self` over memory C may write; the borrow is sanctioned, so the impl is what is worth counting. Distinct types, not impls.
- `c_type_std_value_impl_priv` -- Private C types implementing such a trait.
- `c_type_std_value_impl_derived` -- Of those, the ones where at least one such impl is derived: a `#[derive(Clone)]` on a `#[repr(C)]` C type forms the same borrow with nobody having weighed it. A subset, never summed in.
- `drop_impl` -- Crate-defined types with an `impl Drop`: a teardown written by hand.
- `clone_impl` -- Crate-defined types with a hand-written, not derived, `impl Clone`.

## Which types are C's

`#[repr(C)]` does not make a type C's: Rust crates use it for their own layouts
too, and the crate a type is declared in says nothing either. The driver decides
by provenance -- a closure over the types the build actually hands to C -- and
every rule in it is a fact the compiler already records, never an inference
about what C might do with a value.

- **Seeds.** Every type behind a pointer (`*const T`, `*mut T`, `&T`,
  `NonNull<T>`, nested) in the signature of a foreign function, of a function
  the crate defines with a non-Rust ABI (callbacks, the `#[no_mangle]`
  gateway), or of a C-ABI function-pointer type anywhere in the crate (vtables,
  callback slots); and a foreign static's own type. The `extern` blocks of
  **every linked crate** are read, not just the scanned one: a safe wrapper
  crate declares none of its own, its foreign declarations living in its `-sys`
  crate, and `foreign_modules` is encoded into crate metadata so upstream
  blocks resolve from here.
- **Closure.** A field a C-reachable type holds **by value**, when that field's
  own type has a layout C can describe (`#[repr(C)]`, `#[repr(transparent)]`,
  or a primitive-representation enum); a field it **points to**; and a
  `#[repr(C)]` / `#[repr(transparent)]` type holding a C-reachable type by
  value.

Passing a type by value is a copy and seeds nothing. A std type is never a
seed: bindgen gives every C function pointer the type
`Option<unsafe extern "C" fn(..)>`, and the `Option` is Rust's.

The repr condition on by-value fields is what separates a C object from the
Rust tail of an allocation that merely contains one. The hybrid callback idiom
puts a C ABI base at offset zero and Rust's own state after it:

```rust
/// Rust-owned callback payload: C only accesses its offset-zero ABI base.
#[repr(C)]
struct Filtered<'c> { base: Iterator<'c>, state: State<'c> }
struct State<'c>    { inner: IteratorBox<'c>, regex: RegexBox }
```

`Filtered` is C's -- it is cast to `*mut git_config_iterator` and handed over --
but `State` has no `repr`, so it has no guaranteed layout and C cannot be
reading it as a type of its own. Without the condition the walk continues into
the tail and admits everything it reaches, which on libgit2-bindings meant 123
spurious by-value occurrences.

### What is not evidence

Two things the pass deliberately does not treat as evidence, both because they
cannot be read as facts:

- **A `*c_void` round trip.** A cast to or from `*c_void`, in either
  direction, cannot say who owns the bytes: `*mut T as *mut c_void` hands a
  Rust payload to C, and `*mut c_void as *mut T` is what both C's own memory
  and that payload's trampoline look like coming back. Such a type is recorded
  in a separate **erased** class, which never closes over -- if C does not read
  a payload's bytes it does not read its fields' bytes either -- and a type
  with any other evidence stays in the accessible set regardless.
- **A cast between two named types.** Reading one as evidence would mean
  composing casts from unrelated program points into a chain, symmetrically,
  which says nothing about who owns the bytes. Measured on libgit2-bindings (12
  such casts) and git2-rs (42), the rule admitted no type that declarations and
  containment did not already reach, so it was removed.

The `sys_crates` set -- packages with a Cargo `links` key or a `*-sys` name,
plus any named by `--sys-crates` -- no longer decides whether a type is C's. It
survives only to skip those crates' own emissions, which are generated
bindings rather than the audit subject, and as a guard in wrapper detection.

## Wrappers

A wrapper is a struct that is either a **handle**, a `#[repr(transparent)]`
newtype whose one non-zero-sized field is a raw pointer, `NonNull` or
reference, or a **layout newtype**, `#[repr(transparent)]` or `#[repr(C)]`,
holding a C-reachable type by value (local `#[repr(C)]` fields C does not
reach are searched through). `c_type_layout_wrapper` counts the layout newtypes.
A local C type C reaches itself -- a hand-written mirror, a callback payload --
is not a wrapper of anything, but its references are checked like a layout
newtype's. How the layout newtypes relate to ffibox's `CCell` is in
[`ffibox.md`](ffibox.md).

The handle test is narrower than the idea it stands for: it requires
`#[repr(transparent)]` with a single non-zero-sized pointer field, so a handle
that carries a companion -- ffibox's
`#[repr(C)] struct CBox<T, D> { ptr: NonNull<T>, policy: D }`, or one built on
`AtomicPtr` -- is neither handle nor layout newtype. Such a type is classified
by provenance alone, like any other.

## Borrows into C memory

A borrow into C memory is `&W` / `&mut W` -- or `&[W]`, `Option<&W>`, .. --
where `W` is a C type. A shared `&W` over storage holding an `UnsafeCell` is
not counted: it asserts neither `readonly` nor `noalias`; `&mut W` still is. A
`PhantomData<&W>` marker holds no reference and is not counted.

The counters split by the **position** the borrow sits in, then by kind, then
by visibility, because position is what reaches a caller: a `&*p` in a
`pub fn`'s body is an internal operation, while the same borrow in its
signature is part of the interface. A kind that cannot occur in a position has
no counter there rather than one that is always 0 -- `sanctioned` is a
signature-only distinction, and `generic` is only decidable in a body -- so
there is no `fn_sig.generic`, no `fn_body.sanctioned` and no `ty.sanctioned`.

- `c_type_borrow_*` counts the borrows into C memory -- `&W` / `&mut W` (or
  `&[W]`, `Option<&W>`, ..) -- split by the POSITION the borrow sits in, then
  by kind, then by visibility. Position comes first because that is what
  reaches a caller: a `&*p` in a `pub fn`'s **body** is an internal operation,
  while the same borrow in its **signature** is part of the interface.

  ```json
  "c_type_borrow": {"total": 170,
    "fn_sig":  {"total": 166, "sanctioned":     {"total": 137, "pub": 137, "priv": 0},
                              "non_sanctioned": {"total": 7,   "pub": 7,   "priv": 0},
                              "opaque":         {"total": 22,  "pub": 18,  "priv": 4}},
    "fn_body": {"total": 4, "non_sanctioned": 0, "opaque": 0, "generic": 4},
    "ty":      {"total": 0, "non_sanctioned": {..}, "opaque": {..}}}
  ```

  `fn_sig` carries the function's effective visibility; `ty` carries the
  type's and the field's, as `raw_ptr_ty_*` does -- a borrow in a field of one
  of the crate's structs or unions; `fn_body` carries none, since
  the enclosing function's visibility would say where the operation sits rather
  than that the interface exposes it.

  A kind that cannot occur in a position has no counter there, rather than one
  that is always 0: `sanctioned` is a signature-only distinction, and `generic`
  is only decidable in a body. So there is no `fn_sig.generic`, no
  `fn_body.sanctioned` and no `ty.sanctioned`.

  The kinds, where `W` is a C type that is not opaque:
  - in function signatures (the receiver included): a position is sanctioned
    when two things hold. The method is one whose receiver the language
    forces -- an impl of a standard trait that takes `&self` by definition
    (`Clone`, `PartialEq`, `Eq`, `PartialOrd`, `Ord`, `Hash`, `Debug`,
    `AsRef`, `AsMut`, `Borrow`, `BorrowMut`, `Deref`, `DerefMut`), derived or
    not, matched on the trait's identity in `core` / `alloc` / `std`; or,
    under `--ffibox`, one of the conventions' `as_ref` / `as_mut` layout
    accessors, matched by name. AND the borrow is of that impl's own self
    type. Every other position is non-sanctioned.

    The second condition is what keeps the rule honest. A trait forces its
    RECEIVER, never the rest of its signature. `PartialEq::eq(&self, &Self)`
    has no other shape, so both its positions are sanctioned; but
    `Deref::deref(&self) -> &Self::Target` chooses its target, and git2-rs's
    `impl Deref for OidArray { type Target = [Oid] }` hands out a `&[Oid]`
    over a buffer libgit2 allocated and will free. Sanctioning the method
    must not hide that borrow, which is the counter's whole subject;
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
  `c_type_borrow.fn_sig.non_sanctioned`'s target is 0.
- `opaque` is the same shapes, in any of the three positions, whose `W` is an
  opaque C type. `generic` is a borrow a function body forms from a raw
  pointer, as above, whose referent -- or a slice's element -- is a type
  parameter or an associated type (`&*p` with `p: *const T`,
  `NonNull<T::C>::as_ref`). It is not "a borrow inside generic code": it is a
  borrow whose *referent type* is generic, so whether it covers C memory
  depends on the instantiation. The pass reads each generic body once, not its
  instantiations, so it cannot tell whether `T` is a C type; each site forms
  the reference for every `T` its callers pick.
- `raw_ptr_as_slice_borrow` counts the references a function body forms from
  a raw pointer, as above, to a slice-like target over a type that is not a
  C type: `[T]`, `[T; N]`, `str`, or a standard byte string (`CStr`, `OsStr`,
  `Path`). `CStr::from_ptr(p)`, `slice::from_raw_parts(p, n)` with `p: *const
  u8`, `&*ptr::slice_from_raw_parts(p, n)` and `&(*p).name` of an array field
  are each one. A slice of a C type counts in `c_type_borrow_*` instead. Each
  asserts that C neither frees nor changes those bytes for the reference's
  lifetime: a C string or buffer C releases or rewrites is a use-after-free
  or a write under a shared borrow.
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

## Hand-written lifecycles

  `addr_of_mut!`, a `&mut self` method or `IndexMut` autoref), `_rd`
  otherwise, shared borrows and `addr_of!` included. `*(*p).next = x` is a
  read of `(*p).next` and a write. `raw_ptr_derefs_outside_impl` counts the
  dereferences of either kind outside any `impl` or trait body.

- `drop_impl` counts the crate-defined types with an `impl Drop`, and
  `clone_impl` those with a hand-written, not derived, `impl Clone`; one per
  type. Each is an owner or a copy written by hand: a decision about how
  a C object is torn down or duplicated, which deserves a look. A type that
  owns through another crate's owner (`Box`, or ffibox's `CBox` / `CArc` /

## Limitations of the C-type pass

Provenance bounds what the pass can decide, and each of these is a *silent*
miss or over-count: the document reports a number either way. They divide into
types wrongly admitted and types wrongly dropped.

### Over-admission

**A `#[repr(C)]` Rust tail defeats the repr condition.** The rule above
separates a C object from the Rust tail behind it by asking whether the tail
has a layout C could describe. A tail its author marked `#[repr(C)]` anyway --
out of habit, or because some other part of it does cross -- is admitted, and
with it everything it reaches. libgit2-bindings leaves its tails repr-less,
which is why the rule separates its by-value fields exactly; that is a property
of that codebase, not of the idiom. A codebase that marks everything
`#[repr(C)]` gets no benefit from the condition at all.

**A pointer field is admitted whatever it points at.** The repr condition
guards fields held by value only. A C type holding `*mut T` admits `T` even
when nothing says C dereferences it, and even when `T` is a `repr(Rust)` type C
could not read.

**The declaration is taken on its word.** The pass never reads the C headers.
A Rust mirror that is `#[repr(C)]` but has drifted from the C struct, or has a
field the C side does not, is admitted as declared.

**Offset zero is assumed, not checked.** The hybrid idiom is sound only because
the C base sits at offset zero. The pass admits a container with a C-ish field
wherever in the struct that field sits.

**Pointer origin is invisible.** C reachability is a property of a *type*, not
of a value. A `Copy` value of a C-reachable type sitting in Rust memory is
checked like one C owns, and a pointer C only reads during a call counts like
one it retains. A site means "check this", never "this is wrong".

### Under-admission

**Variadics hide the type.** A type that crosses into C only through a variadic
argument has no type in the signature to read. libgit2's `git_allocator`
reaches C only through
`git_libgit2_opts(GIT_OPT_SET_ALLOCATOR, git_allocator *)`, which bindgen types
as `(c_int, ...)`, so provenance cannot see it. It is the one type on that
crate that the old sys-crate rule admitted and provenance does not.

**By value seeds nothing.** Passing a type by value is a copy, so it does not
make the type C-reachable -- deliberate, but a `#[repr(C)]` struct C only ever
returns by value still has an ABI layout contract the closure never registers.
`c_type_by_val_*` tracks that separately.

**Bindings that omit `#[repr(C)]` are dropped.** A hand-written binding for a C
aggregate that forgets the attribute no longer enters through a by-value field.
That binding is already unsound, so the outcome is arguably right, but it is a
behaviour change from the crate-membership rule that preceded it.

**Generics are not instantiated.** A field's type is resolved as declared, so a
field of type `T` yields no type at all: `#[repr(C)] struct W<T> { inner: T }`
instantiated with a C type is never walked, and neither is a generic wrapper
`W<T>` over one.

**Erasure and integer round trips.** Memory C reaches through a `void *` the
crate never casts to a named type, or through an integer round trip
(`usize as *mut T`), is not seen. A `void *` the crate *does* cast lands in the
erased class rather than the accessible one, by design.

**The variantless-enum idiom is a near miss.** `pub enum git_blob {}`, the
opaque C type hand-written bindings declare, fails the repr condition --
no `#[repr(C)]`, no primitive representation. It does not bite today only
because an uninhabited type is never held by value; such types are reached
exclusively through pointers, and the pointer arm has no repr condition. If
one were ever embedded, it would be wrongly dropped.

### Scope

**The set is computed per compilation unit.** Each crate of a workspace runs
the pass over what it can see, so one type can be classified differently in two
crates of the same build.
