# The ffibox arms

What `--ffibox` adds, and the conventions each arm reads. These are the only
conditional counters in the tree: without the flag they are absent, not zero.
The tree itself is [`schema.md`](schema.md); how a scan runs is
[`scanning.md`](scanning.md).

The arms are generated from a vocabulary rather than enumerated, so a trait or
primitive ffibox adds appears without a change here. That is why `--sites`
validates a dotted path by its prefix and family and not against a list of
leaves.

## 1. The vocabulary

```
<trait>      layout    CCell · CPlainElem · CZeroable
             allocate  CAlloc · CAllocZeroed · CNew
             release   CDrop · CDispose · CLenDrop
             clone     CDupClone · CRefClone · CLenClone
             seam      CRefSeam · CMutSeam · CLockedSeam
             guard     CGuarded · CGuardedAll · LockScope

<primitive>  owner     CBox · CArc · CStrBox · CVec · CVal
             borrow    CBorrowedPtr · CSlice · CSliceMut
             guard     CGuardedRef · CGuard
```

## 2. The arms

```
ty.storing_raw_ptr.of_which.ffibox.{pub,priv}
ty.field.ffibox.<primitive>.{pub,priv}
ty.ffibox.ccell.{pub,priv}
ty.ffibox.ccell.of_which.no_seam_trait.{pub,priv}
ty.impl_block.of_which.ffibox.{layout,ref,mut,locked}.{pub,priv}
ty.impl_trait.of_which.ffibox.{pub,priv}
ty.impl_trait.of_which.ffibox.of_which.<trait>.{handwritten,macro}
ty.total.of_which.ffibox_trait.{pub,priv}
fn.ffibox.{taken,returned}.<primitive>.{pub,priv}
raw_ptr.casted_to.ffibox.{borrow,slice,string,owner,other}
```

## 3. A type's role in the convention

ffibox's convention is three types per wrapped C object, as the
[crustify conventions](https://github.com/crustify-rs/crustify)' Type route
describes: the layout newtype `Foo`, its shared handle `FooRef<'a>` and its
exclusive one `FooMut<'a>`. `ty.impl_block.of_which.ffibox` splits an inherent
`impl` block by which of those its self type is, because they are different
surfaces: the layout type carries the constructors, the shared handle the
getters, the exclusive handle the setters.

The role is read from `CCell`'s own `Ref<'a>` and `Mut<'a>` associated types,
**not** from the seam trait a type implements. `define_ctype!` generates
`CRefSeam` and `CMutSeam` only for a cell with no parameters of its own -- its
pattern takes a bare `$name:ident` -- so a lifetime-carrying cell such as
`Blob<'r>` hand-writes `CCell` and no seam at all. Reading the seams therefore
missed every hand-written cell's handles: on libgit2-bindings 49 `*Ref` and 40
`*Mut` blocks fell through to `other`.

## 4. `ccell.of_which.no_seam_trait`

A cell whose handles implement neither seam. Those handles sit outside the
generic seam the traits carry **on the handle type** -- `from_ptr`,
`from_void_ptr`, `as_ptr`, `as_void_ptr` -- so code generic over a handle has
to reach the cell and call `CCell::ref_from_ptr` instead.

It is an omission rather than a limit. This compiles against ffibox:

```rust
impl<'a, 'r: 'a> CRefSeam<'a> for FooRef<'a, 'r> { type Cell = Foo<'r>; }
```

The trait never needs to name the owner's lifetime -- the implementing type
carries it, and `'r: 'a` discharges the `Cell: 'a` the bound requires.

## 5. `handwritten` against `macro`

`ty.impl_trait.of_which.ffibox.of_which.<trait>.{handwritten,macro}` splits an
impl by whether a generator wrote it. ffibox ships `define_ctype!` and the
`impl_c*!` family (`impl_cdrop!`, `impl_cdupclone!`, `impl_cdispose!`,
`impl_clendrop!`, `impl_clenclone!`, `impl_crefclone!`, `impl_cguarded!`), so an
impl either carries expansion context or was typed out, and
`Span::from_expansion()` decides it exactly.

The split is not on `{pub,priv}`: whether a generator was used does not vary
with visibility, and the cells would cost 68 for nothing.

`macro` is a reserved word; the driver's enum variant is spelled otherwise
while the emitted key stays `macro`.

## 6. `casted_to.ffibox`

Derived, not hand-written: the adoption methods are `from_raw`,
`from_raw_with`, `from_ptr`, `from_c`, `from_c_with`, `from_raw_parts`,
`from_raw_parts_with`, `from_raw_parts_or_empty` and
`from_raw_parts_or_empty_with`, crossed with the `<primitive>` vocabulary and
bucketed by the primitive's group -- `CStrBox` to `string`, the other owners to
`owner`, `CBorrowedPtr` to `borrow`, `CSlice` and `CSliceMut` to `slice`.

`as_ref`, `as_slice`, `as_c_str` and `as_bytes` are excluded: they take `&self`
on an owner, so they are owner-to-borrow, not raw-to-borrow. `as_ptr`,
`as_mut_ptr`, `as_c_ptr` and `as_elem_ptr` run the other direction.

`casted_to.ffibox.other` is structurally zero, every primitive mapping to a
known shape, so a nonzero reading means the vocabulary and the shape
classifier have drifted apart.

## 7. Why `ffibox` is a declaration share

The six std-trait shares of `ty.storing_raw_ptr.of_which` read `Drop`,
`Clone`, a lifetime, `Deref`, `DerefMut` and `Send`/`Sync`. A crate that
declares its lifecycle through ffibox instead has said something none of them
can see, so `ffibox` is counted beside them and the `none` residual means what
it says.

On libgit2-bindings `none` read 12 of 41 while 8 of those 12 were
`define_ctype!` layout newtypes whose release and clone sit on ffibox traits
and whose lifetimes sit on their handles. With the share it reads 4, against
git2-rs' 15 of 97 -- the direction `impl_drop` 3 against 52 already pointed.
