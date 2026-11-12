//! A stand-in for ffibox: an owner over a C cell, and the traits it is
//! generic over. Only what the `api` fixture's contracts read is here.
#![allow(clippy::missing_safety_doc, dead_code)]

use core::marker::PhantomData;
use core::ptr::NonNull;

/// A C type's layout newtype, naming its handles.
pub trait CCell {
    /// The shared handle.
    type Ref<'a>
    where
        Self: 'a;
    /// The exclusive handle.
    type Mut<'a>
    where
        Self: 'a;
}

/// A free policy for `T`.
pub trait CDrop<T> {}

/// The zero-sized policy an owner holds: private, as ffibox's is.
pub(crate) struct ZstPolicy<D>(PhantomData<D>);

/// The sole owner of a C-allocated `T`, freed through `D`.
pub struct CBox<T, D> {
    ptr: NonNull<T>,
    policy: ZstPolicy<D>,
}

impl<T: CCell, D: CDrop<T>> CBox<T, D> {
    /// The shared reborrow: part of every form's contract.
    pub fn as_ref(&self) -> T::Ref<'_> {
        unimplemented!()
    }

    /// The exclusive reborrow.
    pub fn as_mut(&mut self) -> T::Mut<'_> {
        unimplemented!()
    }

    /// What this form offers beyond the native ones: no part of a contract.
    pub fn try_clone(&self) -> Option<Self> {
        None
    }

    /// Raw access.
    pub fn into_raw(self) -> *mut T {
        self.ptr.as_ptr()
    }

    /// A seam.
    pub fn as_ptr(&self) -> *const T {
        self.ptr.as_ptr()
    }

    /// A seam, and `unsafe`.
    pub unsafe fn from_raw(ptr: NonNull<T>) -> Self {
        CBox { ptr, policy: ZstPolicy(PhantomData) }
    }
}

impl<T, D> Drop for CBox<T, D> {
    fn drop(&mut self) {}
}

impl<T, D> core::fmt::Debug for CBox<T, D> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str("CBox")
    }
}

impl<T, D> core::fmt::Pointer for CBox<T, D> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        core::fmt::Pointer::fmt(&self.ptr, f)
    }
}
