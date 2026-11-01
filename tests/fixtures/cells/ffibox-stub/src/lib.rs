//! As much of ffibox as the cell counters read: the `CCell` contract, whose
//! `C`, `Ref` and `Mut` name the raw struct and the two handles, and one
//! owning primitive, to prove the walk stops at it.
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

/// A shared borrowed handle, which holds its cell behind a pointer too.
pub struct CBorrowedPtr<'a, T>(NonNull<T>, core::marker::PhantomData<&'a T>);
