# TODO

## References into C memory the counters miss

Two ways to form a Rust reference into memory C may write go uncounted
(see Known limitations in [output.md](output.md)):

- **Fields of other types.** `c_type_borrow_non_sanctioned` follows the
  whole place back to a raw-pointer deref, but counts only a reference whose
  type holds a C type, so `&(*p).len` or
  `&mut (*p).a[i].b` of a C scalar counts nowhere.
- **Autoref on a field.** `(*p).field.method()` with a `&self` method borrows
  the field implicitly. Count `Adjust::Borrow` adjustments on raw-based places,
  as `c_type_borrow_non_sanctioned` already does for whole wrappers.
