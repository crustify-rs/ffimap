# TODO

## References into C memory the counters miss

Three ways to form a Rust reference into memory C may write go uncounted
(see Known limitations in [output.md](output.md)):

- **Deep places.** `ty_field_borrow_wrapped` matches only `&(*p).field`, one field
  below the raw-pointer dereference. Follow the whole place instead — any
  depth of fields and indexing back to a raw-pointer deref — so `&(*p).a.b`,
  `&(*p).arr[i]` and `&mut (*p).a[i].b` count.
- **Autoref on a field.** `(*p).field.method()` with a `&self` method borrows
  the field implicitly. Count `Adjust::Borrow` adjustments on raw-based places,
  as `ty_wrapper_borrow_non_sanctioned` already does for whole wrappers.
- **References to the C type itself.** `ty_wrapper_borrow_*` only cover
  layout wrappers, so `&*p` with `p: *const ffi::T`, or
  `NonNull<ffi::T>::as_ref()`, is counted nowhere although it is the same
  hazard. Open question: widen `ty_wrapper_borrow_*` in bodies to C types that
  have a wrapper, or add a separate counter so "reference to a wrapper" and
  "reference to the raw C type" stay apart.
