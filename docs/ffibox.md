# The owner and handle surface

Always present. It measures the owners and handles the crate puts in
signatures and fields, split by whether they come from
[ffibox](https://github.com/crustify-rs/ffibox) or the crate wrote them
itself, together with its ffibox trait impls.

The `non_ffibox` half is a fact about any FFI crate -- how much pointer
ownership it implements rather than inherits -- so it is measured whether or
not ffibox is in the build, and for a crate with no ffibox the other half is
simply zero. `--ffibox` asserts that the crate is built on ffibox; it decides
whether the conventions' `as_ref` / `as_mut` accessors are sanctioned (see
[`ctypes.md`](ctypes.md)'s Borrows into C memory), not whether this record is
emitted.

Visibility is read as [`output.md`](output.md)'s Conventions section
describes; `_pub` / `_priv` is the effective visibility of the function for a
signature position, and of the implementing type for an impl.

## Counters

Each is a breakdown `{key: N}` rather than a bare number; the totals are the
tree in `counts`, the breakdowns are `by`, keyed by the flat name below.

- `fn_sig_ffibox_owner_pub` -- An ffibox owner (`CBox`, `CArc`, `CVec`, `CStrBox`, `CVal`), in the signature of a public fn.
- `fn_sig_ffibox_owner_priv` -- An ffibox owner (`CBox`, `CArc`, `CVec`, `CStrBox`, `CVal`), in the signature of a private fn.
- `fn_sig_ffibox_handle_pub` -- An ffibox-based borrowed handle (`Ref`, `Mut`, `Locked`, or one of ffibox's own views), in the signature of a public fn.
- `fn_sig_ffibox_handle_priv` -- An ffibox-based borrowed handle (`Ref`, `Mut`, `Locked`, or one of ffibox's own views), in the signature of a private fn.
- `fn_sig_non_ffibox_owner_pub` -- An owner written outside ffibox, by the crate itself, in the signature of a public fn.
- `fn_sig_non_ffibox_owner_priv` -- An owner written outside ffibox, by the crate itself, in the signature of a private fn.
- `fn_sig_non_ffibox_handle_pub` -- A borrowed handle written outside ffibox, by the crate itself, in the signature of a public fn.
- `fn_sig_non_ffibox_handle_priv` -- A borrowed handle written outside ffibox, by the crate itself, in the signature of a private fn.
- `ty_pub_fields_pub_ffibox_owner` -- An ffibox owner (`CBox`, `CArc`, `CVec`, `CStrBox`, `CVal`), in a public field of a public type.
- `ty_pub_fields_priv_ffibox_owner` -- An ffibox owner (`CBox`, `CArc`, `CVec`, `CStrBox`, `CVal`), in a private field of a public type.
- `ty_priv_ffibox_owner` -- An ffibox owner (`CBox`, `CArc`, `CVec`, `CStrBox`, `CVal`), in a field of a private type.
- `ty_pub_fields_pub_ffibox_handle` -- An ffibox-based borrowed handle (`Ref`, `Mut`, `Locked`, or one of ffibox's own views), in a public field of a public type.
- `ty_pub_fields_priv_ffibox_handle` -- An ffibox-based borrowed handle (`Ref`, `Mut`, `Locked`, or one of ffibox's own views), in a private field of a public type.
- `ty_priv_ffibox_handle` -- An ffibox-based borrowed handle (`Ref`, `Mut`, `Locked`, or one of ffibox's own views), in a field of a private type.
- `ty_pub_fields_pub_non_ffibox_owner` -- An owner written outside ffibox, by the crate itself, in a public field of a public type.
- `ty_pub_fields_priv_non_ffibox_owner` -- An owner written outside ffibox, by the crate itself, in a private field of a public type.
- `ty_priv_non_ffibox_owner` -- An owner written outside ffibox, by the crate itself, in a field of a private type.
- `ty_pub_fields_pub_non_ffibox_handle` -- A borrowed handle written outside ffibox, by the crate itself, in a public field of a public type.
- `ty_pub_fields_priv_non_ffibox_handle` -- A borrowed handle written outside ffibox, by the crate itself, in a private field of a public type.
- `ty_priv_non_ffibox_handle` -- A borrowed handle written outside ffibox, by the crate itself, in a field of a private type.
- `ffibox_impl_macro` -- Types implementing an ffibox trait where an ffibox macro emitted the impl, keyed by trait.
- `ffibox_impl_manual` -- Types implementing an ffibox trait where the impl was written by hand, keyed by trait.
- `ffibox_define_ctype_macro` -- The crate's layout types whose `CCell` impl `define_ctype!` emitted, keyed by type.
- `ffibox_define_ctype_manual` -- The crate's layout types whose `CCell` impl was written by hand, keyed by type.
- `ffibox_ccell_not_layout` -- Types implementing `CCell` that are not layout newtypes by shape: a wrapper without the layout it claims.
- `ffibox_layout_not_ccell` -- Layout newtypes that do not implement `CCell`: wrappers written outside ffibox.

## Details

`--ffibox` adds an `ffibox` record, `{"counts": <tree>, "by": {counter:
{key: N}}}`: each counter's total, and its breakdown by ffibox type, handle
kind or trait. `counts` is a tree, as the Counter tree section describes,
grouping by framework (`ffibox` / `non_ffibox`), then kind (`owner` /
`handle`), then visibility:

```json
"fn_sig": {"total": 1670,
           "ffibox":     {"total": 1652, "owner":  {"total": 278,  "pub": 230,  "priv": 48},
                                         "handle": {"total": 1374, "pub": 1185, "priv": 189}},
           "non_ffibox": {"total": 18,   "owner":  {"total": 15, "pub": 13, "priv": 2},
                                         "handle": {"total": 3,  "pub": 1,  "priv": 2}}}
```

`by` is keyed by the flat leaf name. Every counter is present, zeros included, and each takes
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
