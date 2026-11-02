//! A crate built on ffibox, for the counters `--ffibox` turns on: the cell
//! types (`ty.ffibox.wrapper`), the `-sys` crate's (`ty.ffibox.sys`, in
//! `cells-sys`), and where the declarations mention a cell or the raw struct
//! it covers (`ty.ffibox.{wrapper,sys}.as`), by the innermost holder above the
//! mention.
//!
//! Every item is annotated with the counters it should move, the cell ones
//! relative to `ty.ffibox`, and the point is the negatives as much as the
//! positives: a raw pointer to a cell is `raw_ptr`'s position, not a holder.
//!
//! A mention is counted once per place, not once per type, so a signature
//! naming the cell twice counts twice. A signature's mention is `fn_sig`, a
//! field's `field`.

#![allow(non_camel_case_types, reason = "stands in for a -sys declaration")]
#![allow(dead_code, reason = "a fixture: the driver reads declarations")]

use core::marker::PhantomData;
use core::ptr::NonNull;

use cells_sys::raw_widget;
use ffibox::{CBorrowedPtr, CBox, CCell, CDrop, CNew};

/// The layout newtype, and the fixture's one cell.
///
/// wrapper.pub, wrapper.of_which.no_seam_trait.pub -- its handles implement
/// no seam. sys.as.by_val.field.priv -- its own field is the raw struct, and
/// the field is private even though the type is not.
#[repr(transparent)]
pub struct Widget(raw_widget);

/// The shared handle `CCell::Ref` names. Its raw pointer is no mention.
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
    /// wrapper.as.borrowed.std.fn_sig.pub, of_which.self_in_ref_accessor -- the
    /// mint ffibox's contract licenses, and the reason the share exists.
    pub fn as_ref(&self) -> WidgetRef<'_> {
        WidgetRef(core::ptr::from_ref(&self.0), PhantomData)
    }

    /// wrapper.as.borrowed.std.fn_sig.pub, of_which.self_in_ref_accessor
    pub fn as_mut(&mut self) -> WidgetMut<'_> {
        WidgetMut(core::ptr::from_mut(&mut self.0), PhantomData)
    }

    /// Not an accessor by name, so the borrow is NOT sanctioned, although it
    /// is the same `&self`. The share is a name rule, deliberately: an
    /// `as_c_ptr` is a conversion the convention did not name.
    ///
    /// wrapper.as.borrowed.std.fn_sig.pub
    pub fn peek(&self) -> i32 {
        self.0.n
    }
}

impl PartialEq for Widget {
    /// Two borrows; only the receiver is sanctioned.
    ///
    /// wrapper.as.borrowed.std.fn_sig.pub x2, of_which.self_in_trait_impl x1 --
    /// `other` is a published `&Widget` like any other, and `PartialEq`
    /// compelled none of it.
    fn eq(&self, other: &Self) -> bool {
        self.0.n == other.0.n
    }
}

/// A std trait whose method hands out a reference the impl chose, on the
/// cell itself.
///
/// ty.impl_trait.of_which.std.ref_forming.pub
impl AsRef<Widget> for Widget {
    /// wrapper.as.borrowed.std.fn_sig.pub x2, of_which.self_in_trait_impl x1,
    /// of which ref_forming -- the receiver is sanctioned, the returned
    /// `&Widget` is not: it is the shape the share exists to keep visible.
    fn as_ref(&self) -> &Widget {
        self
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
    /// wrapper.as.borrowed.std.fn_sig.pub x3, of_which.self_in_trait_impl x1
    fn widest<'a>(&'a self, other: &'a Widget) -> &'a Widget {
        if other.0.n > self.0.n { other } else { self }
    }
}

/// A local trait that declares its method unsafe, so an impl of it cannot be
/// safe.
pub trait Poke {
    /// Not counted: a trait's own declaration has no body.
    ///
    /// # Safety
    ///
    /// None; a fixture.
    unsafe fn poke(&mut self, v: i32);
}

impl Poke for Widget {
    /// fn.unsafe.of_which.in_trait_impl.local.pub,
    /// wrapper.as.borrowed.std.fn_sig.pub, of_which.self_in_trait_impl
    unsafe fn poke(&mut self, v: i32) {
        self.0.n = v;
    }
}

/// wrapper.as.borrowed.std.fn_sig.pub, sanctioned by neither share: a bare
/// `&Widget` on the public interface, which ffibox's convention says should
/// be a `WidgetRef`.
pub fn leaked(w: &Widget) -> i32 {
    w.peek()
}

/// Through `Option`, which the walk enters and which holds nothing of its own.
///
/// wrapper.as.borrowed.std.fn_sig.pub
pub fn leaked_optional(w: Option<&Widget>) -> i32 {
    w.map_or(0, Widget::peek)
}

/// A slice of cells taken by reference: the slice holds its elements where it
/// is, so the reference is the holder.
///
/// wrapper.as.borrowed.std.fn_sig.pub
pub fn leaked_slice(ws: &[Widget]) -> usize {
    ws.len()
}

/// Two mentions with nothing above them, both in a signature.
///
/// wrapper.as.by_val.fn_sig.pub x2
pub fn by_value(w: Widget) -> Widget {
    w
}

/// A std owner holds its cell in storage of its own.
///
/// wrapper.as.owned.std.fn_sig.pub x2
pub fn boxed(w: Box<Widget>) -> Vec<Widget> {
    vec![*w]
}

/// A reference to the raw struct, published: no convention covers it.
///
/// sys.as.borrowed.std.fn_sig.pub
pub fn raw_borrow(c: &raw_widget) -> i32 {
    c.n
}

/// An ffibox owner holds the cell behind its own pointer and manages it.
///
/// wrapper.as.owned.ffibox.fn_sig.pub
pub fn in_ffibox_owner(_w: CBox<Widget>) {}

/// An ffibox borrow.
///
/// wrapper.as.borrowed.ffibox.fn_sig.pub
pub fn in_ffibox_borrow(_w: CBorrowedPtr<'_, Widget>) {}

/// NOT counted: a raw pointer to the cell is `raw_ptr`'s position, not a
/// holder of one.
pub fn via_non_null(_p: NonNull<Widget>) {}

/// NOT counted: a raw pointer, likewise.
pub fn via_raw(_p: *mut Widget) {}

/// NOT counted either: `raw_widget` arrives behind the pointer with nothing
/// below it holding it. The handles' own fields are the same case.
pub fn via_raw_c(_p: *const raw_widget) {}

/// The innermost holder describes the mention: a vector of borrows owns no
/// cell, so this is one borrow.
///
/// wrapper.as.borrowed.std.fn_sig.pub
pub fn borrowed_in_vec(ws: Vec<&Widget>) -> usize {
    ws.len()
}

/// Nothing above the cell: an `Option` allocates nothing and owns no run of
/// elements, so the cell sits in the mention's own place, as a bare `Widget`
/// would.
///
/// wrapper.as.by_val.fn_sig.pub
pub fn maybe(w: Option<Widget>) -> bool {
    w.is_some()
}

/// NESTED below a primitive: whatever manages the vector, the vector holds its
/// cells by value, and a C pointer into one dangles when it reallocates. The
/// innermost holder is the `Vec`.
///
/// wrapper.as.owned.std.fn_sig.pub
pub fn nested_owner(_w: CBox<Vec<Widget>>) {}

/// The other way round: the innermost holder is the primitive.
///
/// wrapper.as.owned.ffibox.fn_sig.pub
pub fn owners_in_vec(_w: Vec<CBox<Widget>>) {}

/// A primitive returned inside a `Result`, as a constructor returns it.
///
/// fn.sig.of_which.ffibox.ret.CBox.pub, wrapper.as.owned.ffibox.fn_sig.pub
pub fn opened() -> Result<CBox<Widget>, i32> {
    Err(0)
}

/// A primitive borrowed, inside an `Option`: the innermost holder of the cell
/// is the primitive, not the reference to it.
///
/// fn.sig.of_which.ffibox.arg.CBox.pub, wrapper.as.owned.ffibox.fn_sig.pub
pub fn peeked(_w: Option<&CBox<Widget>>) {}

/// NOT counted: a fn pointer's parameters are the callback's interface, not
/// data this signature passes.
pub fn called_back(_f: fn(CBox<Widget>) -> Widget) {}

/// A cell borrowed in a public field and owned in a private one: the shapes a
/// signature gives a mention, in a field instead.
///
/// wrapper.as.borrowed.std.field.pub (`w`), wrapper.as.owned.std.field.priv
/// (`ws`)
pub struct Lens<'a> {
    pub w: &'a Widget,
    ws: Vec<Widget>,
}

/// A public field holding a cell inline.
///
/// wrapper.as.by_val.field.pub
pub struct Holder {
    pub w: Widget,
}

/// A std trait whose method takes the type by `&mut`: the receiver is a
/// `Holder`, no cell.
///
/// ty.impl_trait.of_which.std.drop.pub
impl Drop for Holder {
    fn drop(&mut self) {}
}

/// A private field, and a ZST marker that names the cell without holding one.
///
/// wrapper.as.by_val.field.priv
pub struct PrivateHolder {
    w: Widget,
    /// NOT counted: `PhantomData` holds nothing.
    _m: PhantomData<Widget>,
}

impl PrivateHolder {
    /// Reaches the private field, so the mention is private: the fn is not
    /// exported.
    ///
    /// wrapper.as.by_val.fn_sig.priv
    fn take(self) -> Widget {
        self.w
    }
}

impl Holder {
    /// An `as_ref` by name with no receiver, so NOT sanctioned: the borrow is
    /// one the author chose, and `Holder` is not even the cell.
    ///
    /// wrapper.as.borrowed.std.fn_sig.pub
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
/// raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.CDrop,
/// ty.impl_trait.of_which.ffibox.policy.pub,
/// fn.unsafe.of_which.in_trait_impl.ffibox.pub
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
/// raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.CNew,
/// ty.impl_trait.of_which.ffibox.policy.pub
impl CNew for Widget {
    fn c_new() -> NonNull<raw_widget> {
        NonNull::dangling()
    }
}
