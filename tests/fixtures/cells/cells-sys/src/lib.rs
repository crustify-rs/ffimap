//! Stands in for a `-sys` crate: the types and declarations bindgen writes,
//! for `ty.ffibox.sys`. Five C aggregates, three of them behind a raw pointer
//! somewhere in these declarations; of those, `cells` names two and a cell's
//! `CCell::C` one.

#![allow(non_camel_case_types, reason = "C's names")]

/// ty.ffibox.sys.total, of_which.raw_ptr_in_sys (`widget_free`), of_which.used
/// and of_which.wrapped (`Widget`'s `CCell::C`).
#[repr(C)]
pub struct raw_widget {
    pub n: i32,
}

/// raw_ptr_in_sys only through a callback's parameter: `visit_cb`; used by
/// `cells::lists_none`'s body.
#[repr(C)]
pub struct raw_list {
    /// Puts `raw_item` behind a pointer, two deep.
    pub head: *mut *mut raw_item,
}

/// raw_ptr_in_sys through `raw_list.head`.
#[repr(C)]
pub struct raw_item {
    pub v: i32,
}

/// Returned by value only: in the total, not behind a pointer.
#[repr(C)]
pub struct raw_value {
    pub v: i32,
}

/// A union, never behind a pointer.
#[repr(C)]
pub union raw_either {
    pub a: i32,
    pub b: f32,
}

/// Not counted: a C enum takes no cell.
#[repr(u32)]
pub enum raw_kind {
    A = 0,
}

/// Not counted either: a C enum as bindgen's `newtype_enum` writes it, and
/// behind a pointer in `formats`, so a struct by the compiler's lights.
#[repr(transparent)]
pub struct raw_format(pub u32);

/// A callback typedef, as bindgen writes one.
pub type visit_cb = Option<unsafe extern "C" fn(list: *const raw_list) -> i32>;

extern "C" {
    pub fn widget_free(w: *mut raw_widget);
    pub fn value_get() -> raw_value;
    pub fn kind_of(k: raw_kind) -> i32;
    pub fn formats(out: *mut raw_format) -> i32;
}
