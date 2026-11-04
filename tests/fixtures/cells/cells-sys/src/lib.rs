//! Stands in for a `-sys` crate: the types and declarations bindgen writes,
//! for `ty.ffibox.sys`. Five C structs, four of them behind a raw pointer
//! somewhere in these declarations, one through a union; of those, `cells`
//! names two and a cell's `CCell::C` one. Unions and enums are not counted.

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

/// Returned by value only: in the total, not behind a pointer. Its members
/// are the shapes a member path walks through: a C member named `type`,
/// which bindgen escapes; an anonymous union held by the named member `u`;
/// an unnamed anonymous union, whose members C reaches as `raw_value`'s; and
/// a bitfield.
#[repr(C)]
pub struct raw_value {
    pub v: i32,
    pub type_: i32,
    pub u: raw_value__bindgen_ty_1,
    pub __bindgen_anon_1: raw_value__bindgen_ty_2,
    pub _bitfield_1: [u8; 1],
}

/// A bitfield, `flag : 1`, as bindgen declares one: packed storage, and a
/// getter and a setter of the bitfield's name.
impl raw_value {
    pub fn flag(&self) -> u32 {
        0
    }
    pub fn set_flag(&mut self, _v: u32) {}
}

/// Not counted: the anonymous union `raw_value.u` holds.
#[repr(C)]
#[derive(Clone, Copy)]
pub union raw_value__bindgen_ty_1 {
    pub mask: u64,
    pub order: i32,
}

/// Not counted: `raw_value`'s unnamed union.
#[repr(C)]
#[derive(Clone, Copy)]
pub union raw_value__bindgen_ty_2 {
    pub lo: i32,
    pub hi: i32,
}

/// A typedef of a struct, from which a member path can start too.
pub type raw_value_t = raw_value;

/// Not counted: a union, never behind a pointer.
#[repr(C)]
pub union raw_either {
    pub a: i32,
    pub b: f32,
}

/// Not counted: a union, behind a pointer in `slot_get`, which puts its
/// members there instead.
#[repr(C)]
pub union raw_slot {
    pub member: core::mem::ManuallyDrop<raw_member>,
    pub n: i32,
}

/// raw_ptr_in_sys only as a member of `raw_slot`, behind `slot_get`'s pointer.
#[repr(C)]
pub struct raw_member {
    pub v: i32,
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
    pub fn slot_get(s: *mut raw_slot) -> i32;
}
