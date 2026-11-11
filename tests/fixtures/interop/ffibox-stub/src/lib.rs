//! As much of ffibox as the outbound counters read: owners that hand their
//! pointer to C, a payload whose trampoline and release C is handed as fn
//! pointers, the status conventions, the panic barrier, and an export macro.
//!
//! The real crate is at <https://github.com/crustify-rs/ffibox>; this stub
//! carries only what makes the fixture compile.

use core::ffi::{c_char, c_int, c_void};
use core::ptr::NonNull;

/// An owner over one object.
pub struct CBox<T>(NonNull<T>);

impl<T> CBox<T> {
    /// Hands the object to C.
    pub fn into_raw(self) -> *mut T {
        self.0.as_ptr()
    }
}

/// An owned NUL-terminated string.
pub struct CStrBox(NonNull<c_char>);

impl CStrBox {
    /// Hands the string to C.
    pub fn into_raw(self) -> *mut c_char {
        self.0.as_ptr()
    }
}

extern "C" fn tramp(_: *mut c_void) {}

/// A Rust value C keeps, and releases through the routine it is given.
pub struct CPayload<T>(Box<T>);

impl<T> CPayload<T> {
    /// Hands the value to C as its context.
    pub fn into_raw(self) -> *mut c_void {
        Box::into_raw(self.0).cast()
    }

    /// The fn pointer C calls the value through.
    pub fn trampoline(&self) -> extern "C" fn(*mut c_void) {
        tramp
    }

    /// The fn pointer C releases the value through.
    pub fn release_fn() -> extern "C" fn(*mut c_void) {
        tramp
    }
}

/// C's status conventions as `Result`.
pub mod status {
    use core::ffi::c_int;

    /// A negative return as the error.
    pub fn nonneg(ret: c_int) -> Result<c_int, c_int> {
        if ret < 0 { Err(ret) } else { Ok(ret) }
    }

    /// Zero for success.
    pub fn zero(ret: c_int) -> Result<(), c_int> {
        if ret == 0 { Ok(()) } else { Err(ret) }
    }
}

/// Callbacks, and the barrier no panic crosses.
pub mod callback {
    /// Runs `f`, and `on_panic` where it panics.
    pub fn barrier<R>(f: impl FnOnce() -> R, _on_panic: impl FnOnce() -> R) -> R {
        f()
    }
}

/// An export that releases an owner C hands back.
#[macro_export]
macro_rules! export_cdrop {
    ($name:ident) => {
        #[no_mangle]
        pub extern "C" fn $name(b: Option<$crate::CBox<u8>>) {
            drop(b)
        }
    };
}

/// Keeps `c_int` used outside `status`.
pub type Status = c_int;
