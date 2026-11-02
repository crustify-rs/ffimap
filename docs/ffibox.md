# The ffibox arms

What `--ffibox` adds, and the conventions each arm reads. These are the only
conditional counters in the tree: without the flag they are absent, not zero.
This document owns the convention: what ffibox's vocabulary is, and how a
cell, a handle, a role, a seam and an adoption are identified from it. What
each counter holds is [`schema.md`](schema.md)'s, and the passes and tests that
produce them [`analysis.md`](analysis.md)'s, which cites this document wherever
a decision rests on the convention rather than on the analysis.

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
ty.ffibox.wrapper.{pub,priv}
ty.ffibox.wrapper.of_which.{borrow,std_owner,slice,field}.{pub,priv}
ty.ffibox.wrapper.of_which.borrow.of_which.{self_in_ref_accessor,self_in_trait_impl}.{pub,priv}
ty.ffibox.ffi.<the same arms as ty.ffibox.wrapper>
ty.ffibox.by_val.{pub,priv}
ty.ffibox.by_val.of_which.{field,fn_sig,std_owner}.{pub,priv}
fn.sig.of_which.ffibox.{arg,ret}.<primitive>.{pub,priv}
raw_ptr.fn_sig_trait_impl.of_which.ffibox.{safe,unsafe}.{pub,priv}
raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.<trait>
raw_ptr.casted_to.ffibox.{borrow,slice,string,owner,other}
```

## 3. A type's role in the convention

ffibox's convention is three types per wrapped C object, as the
[crustify conventions](https://github.com/crustify-rs/crustify)' Type route
describes: the layout newtype `Foo`, its shared handle `FooRef<'a>` and its
exclusive one `FooMut<'a>`. `ty.impl_block.of_which.ffibox` splits an inherent
`impl` block by which of those its self type is, because they are different
surfaces: the layout type carries the constructors, the shared handle the
getters, the exclusive handle the setters. On libgit2-bindings: 408 blocks, 100
on layout types, 86 on shared handles, 103 on exclusive ones and 119 on
everything else -- the handles outnumbering the layout types, which is what a
convention routing every field access through them implies.

The role is read from `CCell`'s own `Ref<'a>` and `Mut<'a>` associated types,
**not** from the seam trait a type implements. `define_ctype!` generates
`CRefSeam` and `CMutSeam` only for a cell with no parameters of its own -- its
pattern takes a bare `$name:ident` -- so a lifetime-carrying cell such as
`Blob<'r>` hand-writes `CCell` and no seam at all. Reading the seams would
therefore leave every hand-written cell's handles under `other`: 49 `*Ref` and
40 `*Mut` blocks on libgit2-bindings. The associated types name the handles
whatever wrote the impl.

## 4. `ccell.of_which.no_seam_trait`

A cell whose handles implement neither seam. Those handles sit outside the
generic seam the traits carry **on the handle type** -- `from_ptr`,
`from_void_ptr`, `as_ptr`, `as_void_ptr` -- so code generic over a handle has
to reach the cell and call `CCell::ref_from_ptr` instead. `define_ctype!`
writes both seams and a hand-written cell gets neither, so the share is the
hand-written cells that were not given them: 0 of libgit2-bindings' 65 and 0 of
ffmpeg-bindings' 58, both campaigns having written them.

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

## 8. Where the declarations mention a cell

`ty.ffibox.wrapper`, `ty.ffibox.ffi` and `ty.ffibox.by_val` read how far the
crate's own declarations keep to the convention section 3 describes. `CCell`
is the authority on all three: its `type C` names the raw struct a cell
covers, as its `Ref` and `Mut` name the handles a consumer is meant to reach
that struct's bytes through. So a `&Foo` written anywhere other than one of
those mints is the layout published directly, and a `&Foo::C` is the raw C
struct published with no convention over it at all.

`wrapper` is keyed on the cell, `ffi` on its `type C`, and `by_val` on the
cell held as a value. They sit under `ty.ffibox` beside `ccell`, which is
where every counter that reads the convention belongs -- and `ty.ffibox`
carries no total, being a namespace rather than a quantity, as
[`schema.md`](schema.md)'s Namespaces section describes: `ccell` counts types
while these three count places, and `wrapper` and `by_val` overlap, since a
cell held in a field is in both.

### 8.1 Mentions, not types

These count places, not types: a cell named in twenty signatures counts
twenty times, and `--sites` lists them. A type population washes the signal
out, because nearly every cell has an `as_ref`: `self_in_ref_accessor` would cover
nearly the whole `borrow` population, and the mentions that are *not*
sanctioned -- the ones worth reading -- would not be recoverable by
subtracting it.

### 8.2 The sanctioned borrows

`define_ctype!`'s own safety comment licenses `&self` on a cell on the
premise that *nothing hands out a `&$name` over C-owned memory*. The two
shares are where that premise holds:

| share | what it is |
|---|---|
| `self_in_ref_accessor` | the receiver of an inherent `as_ref` / `as_mut`: the handle mint the macro writes |
| `self_in_trait_impl` | the receiver of a trait impl's method, whose shape the trait fixed rather than the crate |

The **receiver**, in both. A trait fixes the shape of `&self` and nothing
else: a trait method's other arguments and its return are as much a published
borrow as a free function's, and `fn deref(&self) -> &Foo` hands one out that
no trait compelled. A free-standing `fn as_ref(w: &Foo)` is the same case
under the accessor's name, so the share asks for `self` rather than for input
0.

Both stand on the same contract, so the remainder is the surface worth
reading -- and the remainder is exactly what could break the premise the
shares rest on, so the counter audits its own exemption. On the campaigns:

| | `borrow.pub` | `self_in_ref_accessor` | `self_in_trait_impl` | rest |
|---|---|---|---|---|
| libgit2-bindings | 161 | 90 | 54 | 17 |
| ffmpeg-bindings | 215 | 116 | 77 | 22 |

Every accessor mention was already a receiver on both -- 90 and 116, unmoved.
The trait share was not: 11 of libgit2-bindings' 65 and 20 of ffmpeg-bindings'
97 were arguments and returns, and taking them out is most of each remainder.
Six of libgit2-bindings' are distinct signatures, all `&[Foo]`; it publishes
no bare `&Foo` at all. ffmpeg-bindings' include a `&[Self]` and an
`as_c_ptr(&self)`, which is the same conversion as an accessor under a name
the convention did not give it.

The share is a name rule deliberately: `as_ref` and `as_mut` are the mints
the convention names, and a conversion spelled otherwise stays in the
remainder rather than being inferred into the exemption.

### 8.3 What is not a mention

Four shapes name a cell without the crate publishing its layout. They are not
small corrections: on libgit2-bindings they were 76 of 80 field mentions and
308 of 423 signature mentions.

| shape | why |
|---|---|
| an ffibox primitive (`CBox<Foo>`, `CSlice<Foo>`, `CVal<Foo>`) | it holds the cell behind its own pointer and manages it; `ty.field.ffibox` and `fn.sig.of_which.ffibox` count the delegation, and `in_peel_set` follows the same rule |
| `NonNull<Foo>`, `AtomicPtr<Foo>` | a pointer to the cell, which is `raw_ptr`'s position: ffibox's lifecycle strategies take `NonNull<Cell>`, so counting it would put every `c_drop` in the by-value hazard |
| `*const Foo`, `*mut Foo` | likewise, and the `&Foo` made from one is `raw_ptr.casted_to`'s |
| `PhantomData<Foo>` | a ZST marker holds nothing |

`CVal` goes with the other primitives. It *is* inline storage, but it is
ffibox's inline storage, which is the answer to the by-value hazard rather
than a case of it.

The first three are **walked through**, not stopped at. A pointer-like carries
its own flag down the walk, and a mention that arrives still carrying it is
dropped -- but a qualifier below one clears it, so a hazard nested under a
pointer is still seen: `CBox<Vec<Foo>>` is a vector holding cells by value,
whoever manages the vector, while `Vec<CBox<Foo>>` is a vector of owners
ffibox manages and is nothing of the crate's. The innermost qualifier of each
class describes a mention, which is the same rule that makes `Vec<&Foo>` a
borrow and no owner. Stopping hid the nested cases; neither campaign has one.

`PhantomData` is the one true stop: it holds nothing, so there is nothing
below it to walk.

### 8.4 `by_val`

A cell with nothing above the mention is held as a value: Rust-owned storage
that moves with whatever holds it, so a C pointer retained into it dangles
and no owner runs the C destructor. Those are the cases `CBox` and `CVal`
exist for.

`field` and `fn_sig` partition the population; `std_owner` cuts across both,
since `Box<Foo>` holds its cell in storage of its own. That is the whole rule:
a heap allocation, or a collection that owns a run of elements. The std types
that merely *are* the value -- `Option`, `Result`, `Cell`, `Mutex`,
`ManuallyDrop`, a tuple, an array -- are deliberately out, since the cell sits
in the mention's own place exactly as a bare `Foo` would and `by_val` says it
already. Admitting them read 34 mentions on libgit2-bindings, 31 of them
`Result<Foo, Error>` returns, and moved `ty.ffibox.wrapper` with them: a share
whose figure is a crate's error convention measures nothing. Both campaigns
read 0 under the rule as it stands. The field arm is the
discriminating one: libgit2-bindings reads 4 fields against 115 signature
mentions, most of the latter being `Oid`, a value type with no pointers for
which by-value is the whole point.

`{pub,priv}` carries field reachability already -- the type exported and the
field exported, as `raw_ptr.field` keys it -- so the arm is `field` rather
than `pub_field`, whose `.priv` leaf would be a contradiction.

### 8.5 Limitations

`ty.ffibox.ffi` is keyed on `CCell::C`, so a raw `-sys` struct no cell covers is
invisible to it. libgit2-bindings names `Option<&ffi::git_filter_options>` in
three signatures, two of them public -- a reference to C layout with no
wrapper at all -- and the counter reads nothing, since nothing declares
`CCell` for that struct. The wider keying, any `-sys` type, is a different
counter.

An autoref through a raw pointer forms a reference without a cast expression
or a signature to carry it: `(*p).field`, or a method call on `*p`. Neither
`ty.ffibox.wrapper` nor `raw_ptr.casted_to.*.borrow` sees it.

`ty.ffibox.ffi` is keyed on `CCell::C` for a second reason: it answers what
the campaign's own wrapped C types are mentioned as. The keying is deliberate
rather than a gap to close in place.

`--sites` takes a leaf, so the places behind an arm are asked for by their
`{pub,priv}` leaf: `--sites ty.ffibox.wrapper.of_which.borrow.pub`, not the
arm above it, which validates and then reads empty (see
[`TODO.md`](TODO.md)). The unsanctioned borrows are then the arm's places less
the two shares' -- as a COUNT. Not as places: every position of one signature
reports the signature's own line, so a trait method's sanctioned receiver and
its unsanctioned argument are one place, and subtracting the shares' places
leaves only the signatures that have no sanctioned position at all. On
libgit2-bindings that is 6 of the 17.

## 9. The pointers the convention's traits declare

`raw_ptr.fn_sig_trait_impl` holds the raw-pointer positions a trait fixed, and
its `of_which.ffibox` arm is the share ffibox's vocabulary fixed, broken down
by trait. Every lifecycle contract names the allocation it manages by pointer
-- `CDrop::c_drop(NonNull<T>)`, `CNew::c_new() -> NonNull<T>` -- so a crate
built on the convention declares one such position per implementing type, and
the arm is where they go.

That is the reading the bare family cannot give. On libgit2-bindings all 64 of
its positions are ffibox's, `CDrop` 36 of them; on ffmpeg-bindings 67 of 93
are, the remaining 26 private traits of its own; on git2-rs, which is built on
no ffibox, all 134 are its own `Binding`. The arm says which of the three a
figure is.

The breakdown is keyed on the trait, not on the role
[§1](#1-the-vocabulary) gives it, so it reads as the vocabulary rather than as
a classification of it, and it cross-reads with
`ty.impl_trait.of_which.ffibox.of_which.<trait>`: that one counts the types a
trait is implemented for, this one the positions those impls declare, and for a
one-pointer trait the two agree.

The leaves are the 18 traits of the vocabulary, registered whether they fire or
not, so a document says which contracts a crate does not use as plainly as
which it does: a zero `CGuarded` means nothing in the crate is lock-guarded.
A trait ffibox adds and the vocabulary has not caught up with is counted in the
`ffibox` arm and in no leaf below it, and the arm's total exceeding the sum of
its leaves is how that shows.

An ffibox position is never a `seam` share: the seam traits are implemented
empty -- `impl CRefSeam<'a> for FooRef<'a, 'o> { type Cell = Foo<'o>; }` -- so
`as_ptr` and `from_ptr` are ffibox's provided methods and no local fn carries
the name. A campaign's own seams are inherent methods, and they land in
`fn_sig_arg` and `fn_sig_ret` with their seam shares.
