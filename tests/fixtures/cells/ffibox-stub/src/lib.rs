//! As much of ffibox as the cell counters read: the `CCell` contract, whose
//! `C`, `Ref` and `Mut` name the raw struct and the two handles, one owning
//! primitive, to prove the walk stops at it, and two of the lifecycle
//! contracts, whose own shape puts a raw pointer in every impl's signature --
//! which is what `raw_ptr.fn_sig_trait_impl`'s `ffibox` arm reads.
//!
//! The real crate is at <https://github.com/crustify-rs/ffibox>; this stub
//! carries no implementation, since the driver reads declarations only.

use core::ptr::NonNull;

/// The layout contract: `Self` is a `#[repr(transparent)]` newtype over `C`,
/// reached through `Ref` and `Mut`.
///
/// # Safety
///
/// A stub: the real contract is ffibox's.
pub unsafe trait CCell: Sized {
    type C;
    type Ref<'a>;
    type Mut<'a>;
}

/// An owning handle over a C allocation, which holds its cell behind a
/// pointer rather than inline.
pub struct CBox<T>(NonNull<T>);

/// The release contract: the strategy frees the allocation the pointer names,
/// so the pointer is in the TRAIT's signature and no impl of it chose the
/// position. ffibox's own is `CDrop`.
///
/// # Safety
///
/// A stub: the real contract is ffibox's.
pub unsafe trait CDrop: CCell {
    /// # Safety
    ///
    /// A stub.
    unsafe fn c_drop(p: NonNull<Self::C>);
}

/// The allocating contract, the same shape the other way and safe, so the
/// `ffibox` arm carries both halves of its `{safe,unsafe}` split.
pub trait CNew: CCell {
    /// Hands out the allocation it made.
    fn c_new() -> NonNull<Self::C>;
}

/// A shared borrowed handle, which holds its cell behind a pointer too.
pub struct CBorrowedPtr<'a, T>(NonNull<T>, core::marker::PhantomData<&'a T>);
