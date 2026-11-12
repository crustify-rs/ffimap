//! The `ffimap api` fixture: one crate documented twice, without and with
//! `--cfg after`, so that every classification has an item that earns it.
//! Each item says what `ffimap api diff` must report for it.
#![allow(dead_code)]

use core::marker::PhantomData;

/// A stand-in for an ffibox owner: an owner alias names its cell and policy.
pub struct Holder<T, P>(PhantomData<(T, P)>);

/// A second owner, which `FooBox` is retargeted to.
pub struct Shared<T>(PhantomData<T>);

/// Glue a handle declares itself a view of its cell through.
pub trait View {
    /// The cell the handle views.
    type Cell;
}

pub mod foo {
    use super::{Holder, Shared, View};
    use core::marker::PhantomData;

    mod ffi_import {
        use core::marker::PhantomData;

        /// The layout type: kept, since it is moved into the parent module
        /// after, behind the same re-export path.
        ///
        /// Wraps `st::foo`
        #[doc(alias = "foo")]
        #[cfg(not(after))]
        pub struct Foo(PhantomData<*const ()>);

        /// Its free policy, tied to `fn::foo_free` by the method it owns.
        pub struct FooFree;

        impl FooFree {
            /// Wraps `fn::foo_free`
            #[doc(alias = "foo_free")]
            pub fn release(&self) {}
        }
    }
    pub use ffi_import::FooFree;
    #[cfg(not(after))]
    pub use ffi_import::Foo;

    /// The layout type, defined here after a port; still `!Send`.
    ///
    /// Wraps `st::foo`
    #[doc(alias = "foo")]
    #[cfg(after)]
    pub struct Foo(PhantomData<*const ()>);

    /// `st::foo`'s owner alias: retargeted after, so `st::foo` is changed.
    #[cfg(not(after))]
    pub type FooBox = Holder<Foo, FooFree>;
    /// `st::foo`'s owner alias: retargeted after, so `st::foo` is changed.
    #[cfg(after)]
    pub type FooBox = Shared<Foo>;

    /// `st::foo`'s shared handle, tied to it through `View::Cell`.
    pub struct FooRef<'a>(PhantomData<&'a Foo>);

    impl View for FooRef<'_> {
        type Cell = Foo;
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

/// Extended: `Point` gains `Debug` after, and an accessor of its own.
#[cfg(after)]
impl core::fmt::Debug for Point {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str("Point")
    }
}

#[cfg(after)]
impl Point {
    /// An addition to `st::point`: an inherent item no anchor claims.
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
pub fn no_alias() {}

/// Unattributed: no anchor reaches it, and it loses `Drop` after.
pub struct Loose;

#[cfg(not(after))]
impl Drop for Loose {
    fn drop(&mut self) {}
}
