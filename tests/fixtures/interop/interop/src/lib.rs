//! How a crate meets C from the Rust side: the fns C calls, the fn pointers
//! and pointers Rust hands it, the statics it reads, the layouts it shares,
//! and what a consumer of the Rust API is handed instead. Each item names the
//! counters it moves; `tests/test_interop.py` holds them to it, scanned with
//! `--ffibox` and `--regions ffi_import,ffi_export`.
#![allow(dead_code, improper_ctypes_definitions, non_upper_case_globals)]

use core::ffi::{c_char, c_int, c_void};
use ffibox::{callback, status, CBox, CPayload, CStrBox};

extern "C" {
    // Foreign declarations: no body, no static of the crate's own.
    static sys_global: c_int;
    fn sys_register(cb: extern "C" fn(*mut c_void), ctx: *mut c_void);
    fn sys_free(p: *mut c_void);
}

// ------------------------------------------------------------- layouts

/// ty.total.of_which.repr_c.pub
#[repr(C)]
pub struct Point {
    pub x: c_int,
    pub y: c_int,
}

/// ty.total.of_which.repr_transparent.pub
#[repr(transparent)]
pub struct Handle(*mut c_void);

/// ty.total.of_which.repr_c.priv
#[repr(C)]
struct Private {
    a: u8,
}

/// No repr: neither share.
pub struct Plain(u8);

// ------------------------------------------------- the std traits a type has

/// std_impl Debug, Clone, Default, PartialEq (derived), Display, From: pub.
/// `write!` below expands to std's own unsafe block, which sits outside every
/// region: code.unsafe_block.of_which.outside_regions.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Value(u32);

impl core::fmt::Display for Value {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl From<u32> for Value {
    fn from(v: u32) -> Self {
        Value(v)
    }
}

/// std_impl Debug, Display, Error: pub.
#[derive(Debug)]
pub struct Failure;

impl core::fmt::Display for Failure {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str("failure")
    }
}

impl std::error::Error for Failure {}

/// std_impl Iterator: pub.
pub struct Iter(u8);

impl Iterator for Iter {
    type Item = u8;
    fn next(&mut self) -> Option<u8> {
        None
    }
}

/// std_impl PartialEq, Eq, Hash: priv.
#[derive(PartialEq, Eq, Hash)]
struct Key(u8);

// ------------------------------------------------------------- statics

/// static.total.pub
pub static LIMIT: u32 = 4;

/// static.total.priv, static.of_which.mut.priv
static mut STATE: u32 = 0;

/// static.total.pub, static.of_which.mut.pub, static.of_which.exported.pub
#[no_mangle]
pub static mut interop_flag: c_int = 0;

// ------------------------------------------------- the fns C calls

/// fn.extern_abi.pub, of_which.exported.pub; c_type arg 2, ret 1.
#[no_mangle]
pub extern "C" fn interop_add(a: c_int, b: c_int) -> c_int {
    a + b
}

/// fn.extern_abi.pub, of_which.exported, catches_unwind, raw_ptr_sig: pub;
/// c_type ret 1 (`c_void` is no alias, so the argument is none).
#[no_mangle]
pub extern "C" fn interop_guarded(p: *mut c_void) -> c_int {
    let _ = p;
    std::panic::catch_unwind(|| 0).unwrap_or(-1)
}

/// fn.extern_abi.pub, catches_unwind.pub through ffibox's barrier (under
/// `--ffibox` only); code.call.ffibox.barrier; c_type ret 1. Not exported.
pub extern "C" fn barrier_guarded() -> c_int {
    callback::barrier(|| 1, || -1)
}

/// fn.extern_abi.priv, of_which.raw_ptr_sig.priv: a callback C is handed.
extern "C" fn on_event(ctx: *mut c_void) {
    let _ = ctx;
}

// fn.extern_abi.pub, of_which.exported, macro, ffibox_sig, ffibox_macro: pub.
ffibox::export_cdrop!(interop_widget_free);

/// The crate's own panic barrier, which `--barriers guard` names.
fn guard<R>(f: impl FnOnce() -> R) -> R {
    f()
}

/// fn.extern_abi.priv; catches_unwind.priv only with `--barriers guard`;
/// c_type ret 1.
extern "C" fn guarded_by_helper() -> c_int {
    guard(|| 0)
}

macro_rules! make_type {
    ($name:ident) => {
        /// ty.total.of_which.macro.pub; std_impl Debug.pub.
        #[derive(Debug)]
        pub struct $name;
    };
}

make_type!(Made);

// ------------------------------------------------- fn pointers handed to C

/// code.fn_ptr.extern_abi.local: `on_event` coerced to a fn pointer.
/// One unsafe block, outside every region.
pub fn register() {
    unsafe { sys_register(on_event, core::ptr::null_mut()) }
}

/// code.fn_ptr.extern_abi.local, by an `as` cast; c_type ret 1 (a foreign-ABI
/// fn pointer).
pub fn register_cast() -> extern "C" fn(*mut c_void) {
    on_event as extern "C" fn(*mut c_void)
}

/// code.fn_ptr.extern_abi.foreign: a C fn handed back to C; c_type ret 1.
pub fn register_other() -> unsafe extern "C" fn(*mut c_void) {
    sys_free
}

/// code.fn_ptr.extern_abi.ffibox, twice: the payload's trampoline and its
/// release; fn.sig.of_which.ffibox.arg.CPayload.pub.
pub fn register_payload(p: &CPayload<u8>) {
    let _t = p.trampoline();
    let _r = CPayload::<u8>::release_fn();
}

// ------------------------------------------------- ownership handed to C

/// raw_ptr.surrendered.std.owner
pub fn give_box() -> *mut u32 {
    Box::into_raw(Box::new(1))
}

/// raw_ptr.surrendered.std.string; c_type ret 1.
pub fn give_cstring() -> *mut c_char {
    std::ffi::CString::new("x").unwrap().into_raw()
}

/// raw_ptr.surrendered.ffibox.owner; fn.sig.of_which.ffibox.arg.CBox.pub.
pub fn give_cbox(b: CBox<u8>) -> *mut u8 {
    b.into_raw()
}

/// raw_ptr.surrendered.ffibox.owner; fn.sig.of_which.ffibox.arg.CPayload.pub.
pub fn give_payload(p: CPayload<u8>) -> *mut c_void {
    p.into_raw()
}

/// raw_ptr.surrendered.ffibox.string; c_type ret 1.
pub fn give_cstr(s: CStrBox) -> *mut c_char {
    s.into_raw()
}

/// Not a surrender: a value boxed and kept.
pub fn keep_box() -> Box<u32> {
    Box::new(1)
}

// ------------------------------------------------- what a consumer is handed

/// code.call.ffibox.status; fn.sig.of_which.result.ret.pub; c_type arg 1,
/// ret 2 (`Result<c_int, c_int>`).
pub fn checked(r: c_int) -> Result<c_int, c_int> {
    status::nonneg(r)
}

/// code.call.ffibox.status; result.ret.pub; c_type arg 1, ret 1.
pub fn checked_zero(r: c_int) -> Result<(), c_int> {
    status::zero(r)
}

/// fn.sig.of_which.result.ret.priv
fn private_result() -> Result<(), ()> {
    Ok(())
}

// ------------------------------------------------- regions

mod ffi_import {
    /// code.unsafe_block.of_which.region.ffi_import
    pub(crate) fn read(p: *const u8) -> u8 {
        unsafe { *p }
    }

    /// The same region, and an unsafe fn inside it: not outside_regions.
    pub(crate) unsafe fn adopt(p: *mut u8) -> u8 {
        unsafe { *p }
    }

    pub(crate) mod nested {
        /// A module inside a region is in it.
        pub(crate) fn touch(p: *const u8) -> u8 {
            unsafe { *p }
        }
    }
}

mod ffi_export {
    /// code.unsafe_block.of_which.region.ffi_export; fn.extern_abi.priv (its
    /// module is private), of_which.exported.priv and raw_ptr_sig.priv.
    #[no_mangle]
    pub extern "C" fn interop_export_read(p: *const u8) -> u8 {
        unsafe { *p }
    }
}

/// code.unsafe_block.of_which.outside_regions
pub fn outside(p: *const u8) -> u8 {
    unsafe { *p }
}

/// code.unsafe_block.of_which.outside_regions;
/// fn.unsafe.of_which.outside_regions.pub
pub unsafe fn outside_unsafe(p: *const u8) -> u8 {
    unsafe { *p }
}
