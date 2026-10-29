//! In the peel set: named `*-sys`, so the field walk descends through it.
#[repr(C)]
pub struct SysHolder {
    pub p: *mut u8,
}

unsafe extern "C" {
    pub fn sys_c_fn(p: *mut u8) -> u32;
}
