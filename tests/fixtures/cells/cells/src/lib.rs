//! A crate built on ffibox, for the cell counters `--ffibox` turns on:
//! `ty.ffibox.wrapper` (the layout newtype), `ty.ffibox.ffi` (the raw struct
//! it covers) and `ty.ffibox.by_val` (either held as a value).
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

use ffibox::{CBorrowedPtr, CBox, CCell, CDrop, CNew};

/// Stands in for a `-sys` crate's declaration.
#[repr(C)]
pub struct raw_widget {
    pub n: i32,
}

/// The layout newtype.
///
/// ty.ffibox.ffi.of_which.field.priv -- its own field is the raw struct, and the
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
    /// ty.ffibox.wrapper.of_which.borrow.of_which.in_ref_accessor.pub -- the mint
    /// ffibox's contract licenses, and the reason the share exists.
    pub fn as_ref(&self) -> WidgetRef<'_> {
        WidgetRef(core::ptr::from_ref(&self.0), PhantomData)
    }

    /// ty.ffibox.wrapper.of_which.borrow.of_which.in_ref_accessor.pub
    pub fn as_mut(&mut self) -> WidgetMut<'_> {
        WidgetMut(core::ptr::from_mut(&mut self.0), PhantomData)
    }

    /// Not an accessor by name, so the borrow is NOT sanctioned, although it
    /// is the same `&self`. The share is a name rule, deliberately: an
    /// `as_c_ptr` is a conversion the convention did not name.
    ///
    /// ty.ffibox.wrapper.of_which.borrow.pub
    pub fn peek(&self) -> i32 {
        self.0.n
    }
}

impl PartialEq for Widget {
    /// Two borrows; only the receiver is sanctioned.
    ///
    /// ty.ffibox.wrapper.of_which.borrow.of_which.self_in_trait_impl.pub,
    /// ty.ffibox.wrapper.of_which.borrow.pub x2 -- `other` is a published
    /// `&Widget` like any other, and `PartialEq` compelled none of it.
    fn eq(&self, other: &Self) -> bool {
        self.0.n == other.0.n
    }
}

/// A local trait, to put a borrow in a trait method's argument AND its return.
pub trait Widest {
    /// Not a mention: a trait's own declaration is not an impl's signature.
    fn widest<'a>(&'a self, other: &'a Widget) -> &'a Widget;
}

impl Widest for Widget {
    /// Three borrows, one sanctioned: the receiver. The returned `&Widget` is
    /// the case the receiver rule exists to keep visible -- a trait method
    /// handing out a reference to C-owned memory.
    ///
    /// ty.ffibox.wrapper.of_which.borrow.of_which.self_in_trait_impl.pub,
    /// ty.ffibox.wrapper.of_which.borrow.pub x3
    fn widest<'a>(&'a self, other: &'a Widget) -> &'a Widget {
        if other.0.n > self.0.n { other } else { self }
    }
}

/// ty.ffibox.wrapper.of_which.borrow.pub, sanctioned by neither share: a bare
/// `&Widget` on the public interface, which ffibox's convention says should
/// be a `WidgetRef`.
pub fn leaked(w: &Widget) -> i32 {
    w.peek()
}

/// Through `Option`, which the walk enters: one borrow, unsanctioned.
///
/// ty.ffibox.wrapper.of_which.borrow.pub
pub fn leaked_optional(w: Option<&Widget>) -> i32 {
    w.map_or(0, Widget::peek)
}

/// A slice of cells taken by reference: a borrow AND a slice, one mention.
///
/// ty.ffibox.wrapper.of_which.borrow.pub, ty.ffibox.wrapper.of_which.slice.pub
pub fn leaked_slice(ws: &[Widget]) -> usize {
    ws.len()
}

/// Two mentions held as values, both in a signature.
///
/// ty.ffibox.by_val.of_which.fn_sig.pub x2
pub fn by_value(w: Widget) -> Widget {
    w
}

/// A std owner holds its cell inline, so these are by value as well as
/// behind an owner: two mentions, each in both shares.
///
/// ty.ffibox.by_val.of_which.fn_sig.pub x2, ty.ffibox.by_val.of_which.std_owner.pub x2,
/// ty.ffibox.wrapper.of_which.std_owner.pub x2
pub fn boxed(w: Box<Widget>) -> Vec<Widget> {
    vec![*w]
}

/// A reference to the raw struct, published: no convention covers it.
///
/// ty.ffibox.ffi.of_which.borrow.pub
pub fn raw_borrow(c: &raw_widget) -> i32 {
    c.n
}

/// NOT counted. An ffibox primitive holds the cell behind its own pointer and
/// manages it; `fn.sig` counts the delegation. The walk goes THROUGH the
/// primitive, but nothing below claims the storage, so the mention is dropped.
pub fn in_ffibox_owner(_w: CBox<Widget>) {}

/// NOT counted, for the same reason.
pub fn in_ffibox_borrow(_w: CBorrowedPtr<'_, Widget>) {}

/// NOT counted: a raw pointer to the cell is `raw_ptr`'s position, not
/// storage holding one.
pub fn via_non_null(_p: NonNull<Widget>) {}

/// NOT counted: a raw pointer, likewise.
pub fn via_raw(_p: *mut Widget) {}

/// NOT counted either, although the walk now enters the pointer: `raw_widget`
/// arrives behind it with nothing below claiming it. The handles' own fields
/// are the same case, which is why `ty.ffibox.ffi.field` stays the newtype's
/// one inline mention.
pub fn via_raw_c(_p: *const raw_widget) {}

/// A std owner of BORROWS owns no cell: the inner qualifier wins, so this is
/// one borrow and no owner.
///
/// ty.ffibox.wrapper.of_which.borrow.pub
pub fn borrowed_in_vec(ws: Vec<&Widget>) -> usize {
    ws.len()
}

/// By value, and NOT an owner: an `Option` allocates nothing and owns no run
/// of elements, so the cell sits in the mention's own place exactly as a bare
/// `Widget` would. `by_val` says that already.
///
/// ty.ffibox.by_val.of_which.fn_sig.pub
pub fn maybe(w: Option<Widget>) -> bool {
    w.is_some()
}

/// NESTED below a primitive: whatever manages the vector, the vector holds its
/// cells by value, and a C pointer into one dangles when it reallocates. The
/// walk goes through `CBox` and the `Vec` below it claims the storage.
///
/// ty.ffibox.by_val.of_which.fn_sig.pub, ty.ffibox.by_val.of_which.std_owner.pub,
/// ty.ffibox.wrapper.of_which.std_owner.pub
pub fn nested_owner(_w: CBox<Vec<Widget>>) {}

/// NOT counted, the other way round: the vector holds owners ffibox manages,
/// so the innermost qualifier is the primitive and nothing is this crate's
/// storage.
pub fn owners_in_vec(_w: Vec<CBox<Widget>>) {}

/// A primitive returned inside a `Result`, as a constructor returns it.
///
/// fn.sig.of_which.ffibox.ret.CBox.pub
pub fn opened() -> Result<CBox<Widget>, i32> {
    Err(0)
}

/// A primitive borrowed, inside an `Option`.
///
/// fn.sig.of_which.ffibox.arg.CBox.pub
pub fn peeked(_w: Option<&CBox<Widget>>) {}

/// NOT counted in `fn.sig`: a fn pointer's parameters are the callback's
/// interface, not data this signature passes.
pub fn called_back(_f: fn(CBox<Widget>) -> Widget) {}

/// A public field holding a cell inline.
///
/// ty.ffibox.wrapper.of_which.field.pub, ty.ffibox.by_val.of_which.field.pub
pub struct Holder {
    pub w: Widget,
}

/// A private field, and a ZST marker that names the cell without holding one.
///
/// ty.ffibox.wrapper.of_which.field.priv, ty.ffibox.by_val.of_which.field.priv
pub struct PrivateHolder {
    w: Widget,
    /// NOT counted: `PhantomData` holds nothing.
    _m: PhantomData<Widget>,
}

impl PrivateHolder {
    /// Reaches the private field, so the mention is private: the fn is not
    /// exported.
    ///
    /// ty.ffibox.by_val.of_which.fn_sig.priv
    fn take(self) -> Widget {
        self.w
    }
}

impl Holder {
    /// An `as_ref` by name with no receiver, so NOT sanctioned: the borrow is
    /// one the author chose, and `Holder` is not even the cell.
    ///
    /// ty.ffibox.wrapper.of_which.borrow.pub
    pub fn as_ref(w: &Widget) -> WidgetRef<'_> {
        w.as_ref()
    }
}

/// Keeps `take` and `Holder` from being dead code.
pub fn consume(h: PrivateHolder, o: &Holder) -> bool {
    h.take() == o.w
}

/// The release strategy. Its `NonNull<raw_widget>` is a position in a trait
/// impl's method, so it goes to `raw_ptr.fn_sig_trait_impl` and NOT to
/// `fn_sig_arg` or `raw_ptr.total`: ffibox's contract dictates the position,
/// and `c_drop` is the strategy that exists so a consumer never holds the
/// pointer at all.
///
/// raw_ptr.fn_sig_trait_impl.unsafe.pub,
/// raw_ptr.fn_sig_trait_impl.of_which.ffibox.unsafe.pub,
/// raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.CDrop
unsafe impl CDrop for Widget {
    unsafe fn c_drop(p: NonNull<raw_widget>) {
        let _ = p;
    }
}

/// The allocating strategy: the same family, returning instead of taking, and
/// safe.
///
/// raw_ptr.fn_sig_trait_impl.safe.pub,
/// raw_ptr.fn_sig_trait_impl.of_which.ffibox.safe.pub,
/// raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.CNew
impl CNew for Widget {
    fn c_new() -> NonNull<raw_widget> {
        NonNull::dangling()
    }
}
