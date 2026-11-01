//! A crate built on ffibox, for the cell counters `--ffibox` turns on:
//! `ty.wrapper` (the layout newtype), `ty.ffi` (the raw struct it covers) and
//! `ty.by_val` (either held as a value).
//!
//! Every item is annotated with the counters it should move, and the point is
//! the negatives as much as the positives: the mentions ffibox manages must
//! not be counted as the crate's own.
//!
//! A mention is counted once per place, not once per type, so a signature
//! naming the cell twice counts twice.

#![allow(non_camel_case_types, reason = "stands in for a -sys declaration")]
#![allow(dead_code, reason = "a fixture: the driver reads declarations")]

use core::marker::PhantomData;
use core::ptr::NonNull;

use ffibox::{CBorrowedPtr, CBox, CCell};

/// Stands in for a `-sys` crate's declaration.
#[repr(C)]
pub struct raw_widget {
    pub n: i32,
}

/// The layout newtype.
///
/// ty.ffi.of_which.field.priv -- its own field is the raw struct, and the
/// field is private even though the type is not.
#[repr(transparent)]
pub struct Widget(raw_widget);

/// The shared handle `CCell::Ref` names.
pub struct WidgetRef<'a>(*const raw_widget, PhantomData<&'a ()>);

/// The exclusive handle `CCell::Mut` names.
pub struct WidgetMut<'a>(*mut raw_widget, PhantomData<&'a mut ()>);

// SAFETY: a stub fixture; the driver reads the declaration only.
unsafe impl CCell for Widget {
    type C = raw_widget;
    type Ref<'a> = WidgetRef<'a>;
    type Mut<'a> = WidgetMut<'a>;
}

impl Widget {
    /// ty.wrapper.of_which.borrow.of_which.in_ref_accessor.pub -- the mint
    /// ffibox's contract licenses, and the reason the share exists.
    pub fn as_ref(&self) -> WidgetRef<'_> {
        WidgetRef(core::ptr::from_ref(&self.0), PhantomData)
    }

    /// ty.wrapper.of_which.borrow.of_which.in_ref_accessor.pub
    pub fn as_mut(&mut self) -> WidgetMut<'_> {
        WidgetMut(core::ptr::from_mut(&mut self.0), PhantomData)
    }

    /// Not an accessor by name, so the borrow is NOT sanctioned, although it
    /// is the same `&self`. The share is a name rule, deliberately: an
    /// `as_c_ptr` is a conversion the convention did not name.
    ///
    /// ty.wrapper.of_which.borrow.pub
    pub fn peek(&self) -> i32 {
        self.0.n
    }
}

impl PartialEq for Widget {
    /// Two borrows, both ty.wrapper.of_which.borrow.of_which.in_trait_impl.pub:
    /// the receiver and `other`. The trait fixed both positions.
    fn eq(&self, other: &Self) -> bool {
        self.0.n == other.0.n
    }
}

/// ty.wrapper.of_which.borrow.pub, sanctioned by neither share: a bare
/// `&Widget` on the public interface, which ffibox's convention says should
/// be a `WidgetRef`.
pub fn leaked(w: &Widget) -> i32 {
    w.peek()
}

/// Through `Option`, which the walk enters: one borrow, unsanctioned.
///
/// ty.wrapper.of_which.borrow.pub
pub fn leaked_optional(w: Option<&Widget>) -> i32 {
    w.map_or(0, Widget::peek)
}

/// A slice of cells taken by reference: a borrow AND a slice, one mention.
///
/// ty.wrapper.of_which.borrow.pub, ty.wrapper.of_which.slice.pub
pub fn leaked_slice(ws: &[Widget]) -> usize {
    ws.len()
}

/// Two mentions held as values, both in a signature.
///
/// ty.by_val.of_which.fn_sig.pub x2
pub fn by_value(w: Widget) -> Widget {
    w
}

/// A std owner holds its cell inline, so these are by value as well as
/// behind an owner: two mentions, each in both shares.
///
/// ty.by_val.of_which.fn_sig.pub x2, ty.by_val.of_which.std_owner.pub x2,
/// ty.wrapper.of_which.std_owner.pub x2
pub fn boxed(w: Box<Widget>) -> Vec<Widget> {
    vec![*w]
}

/// A reference to the raw struct, published: no convention covers it.
///
/// ty.ffi.of_which.borrow.pub
pub fn raw_borrow(c: &raw_widget) -> i32 {
    c.n
}

/// NOT counted. An ffibox primitive holds the cell behind its own pointer and
/// manages it, so the walk stops there; `fn.ffibox` counts the delegation.
pub fn in_ffibox_owner(_w: CBox<Widget>) {}

/// NOT counted, for the same reason.
pub fn in_ffibox_borrow(_w: CBorrowedPtr<'_, Widget>) {}

/// NOT counted: a raw pointer to the cell is `raw_ptr`'s position, not
/// storage holding one.
pub fn via_non_null(_p: NonNull<Widget>) {}

/// NOT counted: a raw pointer, likewise.
pub fn via_raw(_p: *mut Widget) {}

/// A public field holding a cell inline.
///
/// ty.wrapper.of_which.field.pub, ty.by_val.of_which.field.pub
pub struct Holder {
    pub w: Widget,
}

/// A private field, and a ZST marker that names the cell without holding one.
///
/// ty.wrapper.of_which.field.priv, ty.by_val.of_which.field.priv
pub struct PrivateHolder {
    w: Widget,
    /// NOT counted: `PhantomData` holds nothing.
    _m: PhantomData<Widget>,
}

impl PrivateHolder {
    /// Reaches the private field, so the mention is private: the fn is not
    /// exported.
    ///
    /// ty.by_val.of_which.fn_sig.priv
    fn take(self) -> Widget {
        self.w
    }
}

/// Keeps `take` and `Holder` from being dead code.
pub fn consume(h: PrivateHolder, o: &Holder) -> bool {
    h.take() == o.w
}
