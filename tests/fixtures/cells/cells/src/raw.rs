//! Raw bindings that are a module of the scanned crate, not a `-sys` crate, as bindgen
//! writes them: a struct with its derives and its `Default`, and an `extern` block. The
//! file is not named `bindings.rs`, so nothing but the scan's naming tells it from the
//! crate's own code.
//!
//! Named to the scan as `crate::raw`, it joins the inventory `cells-sys` gives and
//! leaves every other counter: ty.ffibox.sys.total, of_which.raw_ptr_in_sys
//! (`raw_local`, behind `local_get`'s pointer, and not `used`: only these bindings
//! name it); fn.ffibox.sys.total twice (`local_get`, `nope`). `nope` is the name
//! `value_or`'s second alias gives: fn.ffibox.wrapper.non_trait, of_which.unique.
//!
//! Unnamed, its derives, its `Default` and that impl's `unsafe` block count as the
//! crate's own.

#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct raw_local {
    pub n: i32,
    pub next: *mut raw_local,
}

impl Default for raw_local {
    fn default() -> Self {
        // SAFETY: all-zero is a valid `raw_local`.
        unsafe { core::mem::zeroed() }
    }
}

unsafe extern "C" {
    pub fn local_get(l: *mut raw_local) -> i32;
    pub fn nope() -> i32;
}
