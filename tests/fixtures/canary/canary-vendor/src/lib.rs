//! NOT in the peel set: a third-party crate that is neither local nor `-sys`.
//! A type holding one of these must not count as managing a pointer itself.
pub struct VendorHolder {
    p: *mut u8,
}

impl VendorHolder {
    #[must_use]
    pub fn new() -> Self {
        Self { p: std::ptr::null_mut() }
    }
}

impl Default for VendorHolder {
    fn default() -> Self {
        Self::new()
    }
}
