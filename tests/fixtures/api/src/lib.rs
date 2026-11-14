//! The `ffimap api` fixture: one crate documented without and with
//! `--cfg after` (and `--cfg drop_getter` beside it), so that every
//! classification has an item that earns it. Each item says what
//! `ffimap api diff` must report for it.
//!
//! `foo` is a `port/layout` step: before, `Foo` is a wrapped layout type with
//! pointer-wrapper handles `FooRef` and `FooMut` and an ffibox owner
//! `FooBox`; after, `Foo` is native, its getters on `impl Foo`, and the
//! handles are `&'a Foo`, `&'a mut Foo` and `Box<Foo>`. Its consumers can
//! call the same methods, so `st::foo` is kept; with `drop_getter`, the
//! unanchored getter `id` is gone and it is changed.
#![allow(dead_code)]

pub mod foo {
    use core::marker::PhantomData;

    #[cfg(not(after))]
    mod ffi_import {
        use core::marker::PhantomData;

        /// The layout type over C.
        ///
        /// Wraps `st::foo`
        #[doc(alias = "foo")]
        #[derive(Debug)]
        pub struct Foo(PhantomData<*const ()>);

        impl ffibox::CCell for Foo {
            type Ref<'a> = super::FooRef<'a>;
            type Mut<'a> = super::FooMut<'a>;
        }
    }
    #[cfg(not(after))]
    pub use ffi_import::Foo;

    /// The native type: still `!Send`, as the C one was.
    ///
    /// Replaces `st::foo`
    #[doc(alias = "foo")]
    #[cfg(after)]
    #[derive(Debug)]
    pub struct Foo {
        size: u32,
        marker: PhantomData<*const ()>,
    }

    /// Its free policy, tied to `fn::foo_free` by the method it owns.
    pub struct FooFree;

    impl FooFree {
        /// Wraps `fn::foo_free`
        #[doc(alias = "foo_free")]
        pub fn release(&self) {}
    }

    #[cfg(not(after))]
    impl ffibox::CDrop<Foo> for FooFree {}

    /// The owner: an ffibox owner before, a `Box` after.
    #[cfg(not(after))]
    pub type FooBox = ffibox::CBox<Foo, FooFree>;
    /// The owner: an ffibox owner before, a `Box` after.
    #[cfg(after)]
    pub type FooBox = Box<Foo>;

    /// The shared handle, a pointer wrapper before.
    #[cfg(not(after))]
    #[derive(Clone, Copy, Debug)]
    pub struct FooRef<'a>(PhantomData<&'a Foo>);
    /// The shared handle, a reference after.
    #[cfg(after)]
    pub type FooRef<'a> = &'a Foo;

    /// The exclusive handle, a pointer wrapper before.
    #[cfg(not(after))]
    #[derive(Debug)]
    pub struct FooMut<'a>(PhantomData<&'a mut Foo>);
    /// The exclusive handle, a reference after.
    #[cfg(after)]
    pub type FooMut<'a> = &'a mut Foo;

    #[cfg(not(after))]
    impl FooRef<'_> {
        /// Kept: moves to `impl Foo`, its signature the same.
        ///
        /// Wraps `fld::foo.size`
        #[doc(alias = "foo.size")]
        pub fn size(&self) -> u32 {
            0
        }

        /// An unanchored getter: the contract's, and lost with `drop_getter`.
        pub fn id(&self) -> u32 {
            0
        }

        /// A seam: no part of the contract.
        pub fn as_ptr(&self) -> *const Foo {
            core::ptr::null()
        }
    }

    #[cfg(not(after))]
    impl<'a> FooMut<'a> {
        /// The shared reborrow.
        pub fn as_ref(&self) -> FooRef<'_> {
            FooRef(PhantomData)
        }

        /// The exclusive reborrow, returning its own type: adds nothing.
        pub fn as_mut(&mut self) -> FooMut<'_> {
            FooMut(PhantomData)
        }

        /// Kept: moves to `impl Foo`.
        ///
        /// Wraps `fld::foo.size`
        #[doc(alias = "foo.size")]
        pub fn set_size(&mut self, _size: u32) {}
    }

    #[cfg(not(after))]
    impl Foo {
        /// The layout type's reborrows.
        pub fn as_ref(&self) -> FooRef<'_> {
            FooRef(PhantomData)
        }

        /// The layout type's reborrows.
        pub fn as_mut(&mut self) -> FooMut<'_> {
            FooMut(PhantomData)
        }
    }

    #[cfg(after)]
    impl Foo {
        /// The native type's reborrows.
        pub fn as_ref(&self) -> FooRef<'_> {
            self
        }

        /// The native type's reborrows.
        pub fn as_mut(&mut self) -> FooMut<'_> {
            self
        }

        /// Replaces `fld::foo.size`
        #[doc(alias = "foo.size")]
        pub fn size(&self) -> u32 {
            self.size
        }

        /// The unanchored getter.
        #[cfg(not(drop_getter))]
        pub fn id(&self) -> u32 {
            0
        }

        /// Replaces `fld::foo.size`
        #[doc(alias = "foo.size")]
        pub fn set_size(&mut self, size: u32) {
            self.size = size;
        }
    }

    impl Foo {
        /// Kept: the same signature on both sides.
        ///
        /// Wraps `fn::foo_new`
        #[doc(alias = "foo_new")]
        pub fn new() -> Option<FooBox> {
            None
        }

        /// Changed: takes a `u32` after.
        ///
        /// Wraps `fn::foo_set`
        #[doc(alias = "foo_set")]
        #[cfg(not(after))]
        pub fn set(&mut self, _value: i32) {}

        /// Changed: takes a `u32` after.
        ///
        /// Wraps `fn::foo_set`
        #[doc(alias = "foo_set")]
        #[cfg(after)]
        pub fn set(&mut self, _value: u32) {}

        /// Kept, though its parameter is renamed after, and ported:
        /// `Wraps` becomes `Replaces`.
        ///
        /// Wraps `fn::foo_len`
        #[doc(alias = "foo_len")]
        #[cfg(not(after))]
        pub fn len(&self, _before: u8) -> usize {
            0
        }

        /// Kept, though its parameter is renamed after, and ported:
        /// `Wraps` becomes `Replaces`.
        ///
        /// Replaces `fn::foo_len`
        #[doc(alias = "foo_len")]
        #[cfg(after)]
        pub fn len(&self, _after: u8) -> usize {
            0
        }

        /// Removed: gone after.
        ///
        /// Wraps `fn::foo_old`
        #[doc(alias = "foo_old")]
        #[cfg(not(after))]
        pub fn old(&self) {}

        /// New: only after.
        ///
        /// Wraps `fn::foo_fresh`
        #[doc(alias = "foo_fresh")]
        #[cfg(after)]
        pub fn fresh(&self) {}
    }
}

/// A plain value type.
///
/// Wraps `st::point`
#[doc(alias = "point")]
#[derive(Clone, Copy)]
pub struct Point {
    /// A public field, so a field added would change consumers.
    pub x: i32,
}

/// Extended: `Point` gains `Debug` after.
#[cfg(after)]
impl core::fmt::Debug for Point {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str("Point")
    }
}

#[cfg(after)]
impl Point {
    /// A raw addition: an associated function, which no contract holds.
    pub fn origin() -> Self {
        Point { x: 0 }
    }
}

/// Changed: loses `Send` and `Sync` after, through a raw pointer it holds.
///
/// Wraps `st::cell`
#[doc(alias = "cell")]
pub struct Cell {
    #[cfg(not(after))]
    inner: u8,
    #[cfg(after)]
    inner: *const u8,
}

/// Both accessors of two members stand in for each of them.
///
/// Wraps `fld::pair.a`
/// Wraps `fld::pair.b`
#[doc(alias = "pair.a")]
#[doc(alias = "pair.b")]
pub fn pair_get() -> (i32, i32) {
    (0, 0)
}

/// A malformed anchor, mid-sentence: Wraps `fn::bad_anchor` here.
pub fn bad_anchor() {}

/// An anchor without its alias.
///
/// Wraps `fn::no_alias`
pub fn lacks_alias() {}

/// An anchor whose path is the item's own name: rustdoc rejects that alias, so
/// it carries none and is no defect.
///
/// Wraps `fn::same_name`
pub fn same_name() {}

/// Unattributed: no anchor reaches it, and it loses `Drop` after.
pub struct Loose;

#[cfg(not(after))]
impl Drop for Loose {
    fn drop(&mut self) {}
}
