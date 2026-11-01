//! Known-value fixture for the counter schema. Every item below is annotated
//! with the counters it is expected to move, and `tests/test_canary.py`
//! asserts the exact totals. An item that moves a counter it should not, or
//! fails to move one it should, is the false positive / negative this crate
//! exists to catch.
#![allow(dead_code, clippy::missing_safety_doc, unused_unsafe)]

use std::cell::UnsafeCell;
use std::ffi::{c_void, CStr, CString};
use std::ptr::NonNull;
use std::rc::Rc;
use std::sync::Arc;

use canary_sys::SysHolder;
use canary_vendor::VendorHolder;

// ---------------------------------------------------------------- signatures

/// raw_ptr.fn_sig_arg.safe.pub
pub fn taken_safe_pub(_p: *mut u8) {}

/// raw_ptr.fn_sig_arg.unsafe.pub
pub unsafe fn taken_unsafe_pub(_p: *const u8) {}

/// raw_ptr.fn_sig_arg.safe.priv
fn taken_safe_priv(_p: *mut u8) {}

/// raw_ptr.fn_sig_ret.safe.pub
#[must_use]
pub fn returned_safe_pub() -> *mut u8 {
    std::ptr::null_mut()
}

/// raw_ptr.fn_sig_ret.unsafe.priv
unsafe fn returned_unsafe_priv() -> *const u8 {
    std::ptr::null()
}

/// raw_ptr.fn_sig_arg.safe.pub -- NonNull is a pointer carrier, so it peels.
pub fn taken_nonnull(_p: NonNull<u8>) {}

/// raw_ptr.fn_sig_arg.safe.pub x2 -- both arguments count, independently.
pub fn taken_twice(_a: *mut u8, _b: *const u16) {}

/// raw_ptr.fn_sig_arg.safe.pub, and its `of_which.void` share -- a `*c_void` is a
/// raw pointer whose pointee is erased, counted once and labelled.
pub fn taken_void(_p: *mut c_void) {}

/// raw_ptr.fn_sig_ret.unsafe.pub, and its `of_which.void` share
#[must_use]
pub unsafe fn returned_void() -> *const c_void {
    std::ptr::null()
}

/// Moves NOTHING: a reference is not a raw pointer.
pub fn taken_ref(_r: &u8) {}

/// Moves NOTHING: a type that happens to embed a pointer is not pointer work
/// for the caller, who never touches it.
pub fn taken_holder(_h: &Owned) {}

// ---------------------------------------------------------------- conversions

/// raw_ptr.casted_to.std.owner x4
pub unsafe fn std_owners(p: *mut u8, n: usize) {
    let _b = unsafe { Box::from_raw(p) };
    let _v = unsafe { Vec::from_raw_parts(p, n, n) };
    let _r = unsafe { Rc::from_raw(p) };
    let _a = unsafe { Arc::from_raw(p) };
}

/// raw_ptr.casted_to.std.string x3
pub unsafe fn std_strings(p: *mut u8, c: *const i8, n: usize) {
    let _s = unsafe { CStr::from_ptr(c) };
    let _o = unsafe { CString::from_raw(c.cast_mut()) };
    let _t = unsafe { String::from_raw_parts(p, n, n) };
}

/// raw_ptr.casted_to.std.slice x2
pub unsafe fn std_slices(p: *mut u8, n: usize) {
    let _a = unsafe { std::slice::from_raw_parts(p, n) };
    let _b = unsafe { std::slice::from_raw_parts_mut(p, n) };
}

/// raw_ptr.casted_to.std.borrow x4 -- two method calls and two `&*p` forms.
pub unsafe fn std_borrows(p: *mut u8, nn: NonNull<u8>) {
    let _a = unsafe { p.as_ref() };
    let _b = unsafe { nn.as_ref() };
    let _c = unsafe { &*p };
    let _d = unsafe { &mut *p };
}

/// Moves NOTHING in `casted_to`: a conversion the crate wrote itself, which
/// `--seams` did not declare. It is the documented blind spot, and it must be
/// silent rather than filed under some other arm.
pub struct Undeclared(*mut u8);

impl Undeclared {
    /// raw_ptr.casted_to.local_seam.other -- only when `--seams` names it.
    pub unsafe fn from_raw(p: *mut u8) -> Self {
        Self(p)
    }
}

// ---------------------------------------------------------------- calls

unsafe extern "C" {
    fn c_fn(p: *mut u8) -> u32;
}

/// A safe `extern "C" fn` DEFINED in Rust: the ffi_export gateway shape.
/// Calling it moves NOTHING, because it crosses no boundary.
pub extern "C" fn gateway(_p: *mut u8) {}

unsafe fn local_unsafe_fn() {}

/// A stored C callback, invoked through a function pointer: no callee item
/// exists, so only the ABI of its type can classify the call.
pub struct Callbacks {
    pub cb: unsafe extern "C" fn(*mut u8) -> u32,
}

/// code.unsafe_call.ffi x3 (c_fn, sys_c_fn, the fn-pointer call),
/// code.unsafe_call.rust x1, code.unsafe_call.intrinsic x1,
/// and NOTHING for `gateway` or `safe_helper`.
pub unsafe fn calls(p: *mut u8, cbs: &Callbacks) -> u32 {
    let a = unsafe { c_fn(p) };
    let b = unsafe { canary_sys::sys_c_fn(p) };
    let c = unsafe { (cbs.cb)(p) };
    unsafe { local_unsafe_fn() };
    let d: u32 = unsafe { std::mem::transmute(0u32) };
    gateway(p);
    safe_helper();
    a ^ b ^ c ^ d
}

fn safe_helper() {}

/// raw_ptr.casted_to.local_seam.other -- `Undeclared` is no std or ffibox
/// shape, so a declared seam returning one lands in the residual.
pub unsafe fn calls_seam(p: *mut u8) -> Undeclared {
    unsafe { Undeclared::from_raw(p) }
}

// ---------------------------------------------------------------- holders

/// ty.storing_raw_ptr.of_which.impl_drop, .impl_clone
pub struct Owned {
    p: *mut u8,
}

impl Drop for Owned {
    /// A safe method of a foreign trait whose body frees through FFI: the
    /// shape `fn.safe.of_which.with_unsafe` exists for, and the one a
    /// counter that skipped trait impls could not see.
    fn drop(&mut self) {
        // SAFETY: canary fixture -- `c_fn` is a no-op stub.
        unsafe { c_fn(self.p) };
    }
}

impl Clone for Owned {
    fn clone(&self) -> Self {
        Self { p: self.p }
    }
}

/// ty.impl_trait.of_which.derived: `#[derive]` writes two std trait impls
/// here that nobody typed, which is most of the `std` arm on a real crate.
#[derive(Debug, Default)]
pub struct Derived {
    pub n: u32,
}

/// ty.storing_raw_ptr.of_which.has_lifetime
pub struct Borrowed<'a> {
    p: *mut u8,
    _parent: std::marker::PhantomData<&'a Owned>,
}

/// ty.storing_raw_ptr.of_which.impl_deref, .impl_deref_mut
pub struct Viewing {
    p: *mut u8,
}

impl std::ops::Deref for Viewing {
    type Target = u8;
    fn deref(&self) -> &u8 {
        unsafe { &*self.p }
    }
}

impl std::ops::DerefMut for Viewing {
    fn deref_mut(&mut self) -> &mut u8 {
        unsafe { &mut *self.p }
    }
}

/// ty.storing_raw_ptr.of_which.impl_send_sync
pub struct Asserted {
    p: *mut u8,
}

unsafe impl Send for Asserted {}
unsafe impl Sync for Asserted {}

/// ty.storing_raw_ptr.of_which.pub_field AND .none: a public field reaching
/// the pointer is an access the type does not govern, so it is not a
/// declaration and does not rescue the type from the residual.
pub struct Exposed {
    pub p: *mut u8,
}

/// ty.storing_raw_ptr.of_which.none: stores a pointer, declares nothing.
pub struct Silent {
    p: *mut u8,
}

/// ty.storing_raw_ptr: the pointer is reached through a `-sys` struct, which
/// IS in the peel set. git2-rs's `OidArray { raw: git_oidarray }` is this
/// shape, and a walk that stopped at the crate boundary would miss it.
pub struct ThroughSys {
    raw: SysHolder,
}

/// Moves NOTHING: `canary-vendor` is neither local nor `-sys`, so the walk
/// stops there and the pointer inside is not this crate's to manage.
pub struct ThroughVendor {
    inner: VendorHolder,
}

/// Moves NOTHING: a pointer inside `Vec` is the standard library's.
pub struct ThroughStd {
    v: Vec<u8>,
}

/// ty.wrapping_unsafe_cell
pub struct Cellular {
    c: UnsafeCell<u32>,
}

/// ty.wrapping_unsafe_cell: through a local type.
pub struct CellularNested {
    inner: Cellular,
}

// ---------------------------------------------------------------- fn bodies

/// fn.safe.of_which.with_unsafe
pub fn safe_with_unsafe(p: *mut u8) -> u8 {
    unsafe { *p }
}

/// Moves NOTHING on the safe arm: an `unsafe fn` with a block is what
/// `unsafe_op_in_unsafe_fn` requires, so counting it would measure the lint.
pub unsafe fn unsafe_with_unsafe(p: *mut u8) -> u8 {
    unsafe { *p }
}

/// raw_ptr.deref.wr
pub fn deref_write(p: *mut u8) {
    unsafe {
        *p = 1;
    }
}

/// A trait impl a macro wrote: counted like any other, and carried by
/// `fn.total.of_which.macro` so a reader can subtract the boilerplate.
macro_rules! impl_stub_display {
    ($t:ty) => {
        impl core::fmt::Display for $t {
            fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
                f.write_str("stub")
            }
        }
    };
}

impl_stub_display!(Owned);

/// A trait whose shape puts a raw pointer in every impl's signature: one
/// declaration, a position per implementing type. Its positions go to
/// `raw_ptr.fn_sig_trait_impl`, not to `raw_ptr.{taken,returned}` -- the crate did not
/// choose the position here, and no consumer of the safe API is routed to it.
/// This is git2-rs's `Binding` and ffibox's `CDrop` in miniature.
pub trait RawSeam {
    /// Takes one and returns one: both land in the same `in_impl` counter.
    fn round_trip(&self, p: *mut u8) -> *mut u8;
}

impl RawSeam for Owned {
    fn round_trip(&self, p: *mut u8) -> *mut u8 {
        p
    }
}

impl RawSeam for Borrowed<'_> {
    fn round_trip(&self, p: *mut u8) -> *mut u8 {
        p
    }
}

/// Test code: `cfg(test)` is off in the library build, so rustc strips this
/// whole module before HIR and no library counter can see it. It reappears in
/// the `--test` build, where only `code.tests.*` is emitted.
#[cfg(test)]
mod unit_tests {
    use super::*;

    /// A raw pointer taken by a safe public fn, a holder type, an unsafe
    /// block and an FFI call -- every shape the library counters pin. None of
    /// them may move.
    pub struct TestHolder {
        p: *mut u8,
    }

    #[test]
    fn takes_a_pointer_and_calls_c() {
        let mut n = 0u8;
        let h = TestHolder { p: &raw mut n };
        // SAFETY: canary fixture -- `c_fn` is a no-op stub.
        let _ = unsafe { c_fn(h.p) };
    }
}
