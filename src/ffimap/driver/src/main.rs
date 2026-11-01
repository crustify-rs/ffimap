//! The rustc driver behind `ffimap`.
//!
//! Changes to the deterministic safety pass belong here.
//!
//! A rustc driver (HIR + typeck) over a crate's FFI and unsafe surface,
//! counting what the regex and `syn` approaches cannot decide precisely: a
//! raw-pointer dereference is `*p` where typeck says `p: *const T | *mut T`,
//! so `*Box`, `*&` and a `Deref` impl are not one, and a call's FFI-ness is
//! read from the callee's ABI rather than from its declaration site.
//!
//! The counters it emits, and the rule behind each, are `docs/schema.md`.
//! They go out as one JSON object per crate, `{"crate", "counts", "sites"}`,
//! where `counts` is that document's tree keyed by dotted path. Nothing here
//! describes them a second time.
//!
//! Run as a rustc-compatible front end: it compiles the given file or crate
//! and prints its line in `after_analysis`.
#![feature(rustc_private)]

extern crate rustc_abi;
extern crate rustc_driver;
extern crate rustc_hir;
extern crate rustc_interface;
extern crate rustc_middle;
extern crate rustc_span;

use rustc_abi::ExternAbi;
use rustc_driver::{Callbacks, Compilation};
use rustc_hir as hir;
use rustc_hir::def::DefKind;
use rustc_hir::intravisit::{self, Visitor};
use rustc_middle::middle::codegen_fn_attrs::CodegenFnAttrFlags;
use rustc_middle::ty::{self, Ty, TyCtxt, TypeckResults};
use rustc_span::def_id::DefId;
use rustc_span::Span;
use std::collections::{HashMap, HashSet};

/// True if `t` is `PhantomData<..>` -- a ZST, so it is not the wrapper's
/// storage and must be skipped when deciding the storage shape.
fn is_phantom(tcx: TyCtxt<'_>, t: Ty<'_>) -> bool {
    matches!(t.kind(), ty::TyKind::Adt(d, _)
        if tcx.item_name(d.did()).as_str() == "PhantomData")
}

/// True when `span` comes from generated source compiled into the crate --
/// bindings `include!`d from the build script's `OUT_DIR`, or a committed
/// `bindings.rs` -- which nobody writes by hand and the audit does not judge.
fn in_generated_file(tcx: TyCtxt<'_>, span: Span) -> bool {
    let (file, _) = span_site(tcx, span.source_callsite());
    // Cargo sets OUT_DIR for a crate with a build script; it is where bindgen
    // output is written before `include!` pulls it in.
    std::env::var("OUT_DIR").is_ok_and(|out| !out.is_empty() && file.starts_with(&out))
        || file.ends_with("bindings.rs")
}

/// Raw-pointer positions in the fields of a struct or union the crate
/// declares (nested ones included, as for signatures), into
/// `raw_ptr.field.{pub,priv}`, with the erased ones as its `of_which.void`.
///
/// `pub` is one reachability question -- can a consumer of this crate touch
/// the field -- so it is the type being exported AND the field being
/// exported, rather than two levels a reader has to combine.
fn count_ptr_fields(
    tcx: TyCtxt<'_>,
    did: DefId,
    ptr: &mut PtrTally,
    sites: &mut Sites,
) {
    if in_generated_file(tcx, tcx.def_span(did)) {
        return;
    }
    let vis = tcx.effective_visibilities(());
    let exported = did.as_local().is_some_and(|l| vis.is_exported(l));
    for f in tcx.adt_def(did).all_fields() {
        let ft = tcx.type_of(f.did).instantiate_identity().skip_norm_wip();
        let mut pointees = Vec::new();
        raw_pointees(tcx, ft, &mut pointees);
        if pointees.is_empty() {
            continue;
        }
        let reachable = exported && f.did.as_local().is_some_and(|l| vis.is_exported(l));
        let v = if reachable { "pub" } else { "priv" };
        let site = counter_site(tcx, tcx.def_span(f.did));
        for pointee in pointees {
            *ptr.entry(format!("raw_ptr.field.{v}")).or_default() += 1;
            sites.add(&format!("raw_ptr.field.{v}"), site.clone());
            // Into the denominator's SAFE arm: reading a field holding a
            // pointer takes no `unsafe`, so a public one on a public type is
            // a pointer the interface hands over without asking for any.
            let k = format!("raw_ptr.total.safe.{v}");
            *ptr.entry(k.clone()).or_default() += 1;
            sites.add(&k, site.clone());
            if is_c_void(tcx, pointee) {
                let k = format!("raw_ptr.field.of_which.void.{v}");
                *ptr.entry(k.clone()).or_default() += 1;
                sites.add(&k, site.clone());
            }
        }
    }
}

/// The pointees of every raw pointer position in `t`: `t` itself when it is a
/// raw pointer, a `NonNull<T>` (a `*const T` that is never null) or an
/// `AtomicPtr<T>` (a `*mut T` behind an atomic), else those
/// reached through references, generic arguments (`Option<*const T>`), tuples,
/// arrays and slices. A raw pointer is one
/// position whatever it points to (`*mut *mut T` counts once), and fn-pointer
/// types are not entered: their parameters are the callback's interface, not
/// data this signature passes.
fn raw_pointees<'tcx>(tcx: TyCtxt<'tcx>, t: Ty<'tcx>, out: &mut Vec<Ty<'tcx>>) {
    match t.kind() {
        ty::TyKind::RawPtr(p, _) => out.push(*p),
        ty::TyKind::Adt(d, args)
            if is_std_crate(tcx, d.did()) && matches!(tcx.item_name(d.did()).as_str(), "NonNull" | "AtomicPtr") =>
        {
            out.extend(args.types().next())
        }
        ty::TyKind::Ref(_, inner, _) => raw_pointees(tcx, *inner, out),
        // `PhantomData<*const T>` is a zero-sized marker (opting out of
        // `Send`/`Sync`, say): it stores no pointer.
        ty::TyKind::Adt(d, _) if tcx.item_name(d.did()).as_str() == "PhantomData" => {}
        ty::TyKind::Adt(_, args) => {
            for a in args.types() {
                raw_pointees(tcx, a, out)
            }
        }
        ty::TyKind::Tuple(tys) => {
            for a in tys.iter() {
                raw_pointees(tcx, a, out)
            }
        }
        ty::TyKind::Array(e, _) | ty::TyKind::Slice(e) => raw_pointees(tcx, *e, out),
        _ => {}
    }
}

/// True if `p` (a pointee) is `c_void`.
fn is_c_void(tcx: TyCtxt<'_>, p: Ty<'_>) -> bool {
    matches!(p.kind(), ty::TyKind::Adt(def, _) if tcx.item_name(def.did()).as_str() == "c_void")
}

/// The crates whose `#[repr(C)]` types are C's and whose types the field walk
/// descends through, by crate name: `UM_SYS_CRATES`, comma-separated, which
/// `ffimap` sets from `--sys-crates` alone. Nothing is discovered; see
/// docs/scanning.md.
fn sys_crates() -> &'static HashSet<String> {
    static SYS: std::sync::OnceLock<HashSet<String>> = std::sync::OnceLock::new();
    SYS.get_or_init(|| {
        std::env::var("UM_SYS_CRATES")
            .unwrap_or_default()
            .split(',')
            .map(|n| n.trim().replace('-', "_"))
            .filter(|n| !n.is_empty())
            .collect()
    })
}

/// The function names `--seams` declared, by bare item name: `UM_SEAM_FNS`,
/// comma-separated, set by `ffimap`. A seam is the conversion between a
/// wrapper and its raw pointer (`raw`, `from_raw`, `as_ptr`, `from_ptr`); the
/// driver never guesses the names, so an unset variable means no seam is
/// reported and every counter reads as it always did.
fn seam_fns() -> &'static HashSet<String> {
    static SEAMS: std::sync::OnceLock<HashSet<String>> = std::sync::OnceLock::new();
    SEAMS.get_or_init(|| {
        std::env::var("UM_SEAM_FNS")
            .unwrap_or_default()
            .split(',')
            .map(str::trim)
            .filter(|n| !n.is_empty())
            .map(String::from)
            .collect()
    })
}

/// True when `did`'s own name is one of the declared seam names.
fn is_seam_fn(tcx: TyCtxt<'_>, did: DefId) -> bool {
    !seam_fns().is_empty()
        && tcx.opt_item_name(did).is_some_and(|n| seam_fns().contains(n.as_str()))
}

fn is_std_crate(tcx: TyCtxt<'_>, did: DefId) -> bool {
    matches!(tcx.crate_name(did.krate).as_str(), "core" | "alloc" | "std")
}

/// The crates the field walk descends through: the scanned crate and the
/// `-sys` crates named on the command line (`UM_SYS_CRATES`).
///
/// The rule decides what `ty.storing_raw_ptr` means. A pointer inside `Vec` is
/// the standard library's to manage, and one inside an ffibox owner is
/// ffibox's, so neither makes its holder a pointer manager. What is left is the
/// types that manage a pointer themselves; delegation is counted by
/// `ty.field.ffibox` instead.
///
/// A `-sys` crate left unnamed drops out of the walk and the counter reads low
/// for a reason that is not in the code. That is not diagnosed: most crates
/// that stop the walk do so legitimately, so a warning would be noise. See
/// docs/schema.md, The peel set.
fn in_peel_set(tcx: TyCtxt<'_>, did: DefId) -> bool {
    did.is_local() || sys_crates().contains(tcx.crate_name(did.krate).as_str())
}

thread_local! {
    /// `(accessible, erased)`, computed once (see `compute_c_visible`).
    static C_VISIBLE: std::cell::RefCell<Option<(HashSet<DefId>, HashSet<DefId>)>> =
        const { std::cell::RefCell::new(None) };
}

// ---------------------------------------------------------------- slot classifier
//
// One walk over a type, yielding one `Slot` per carrier it finds, as
// `docs/schema-draft.md` describes. It replaces what `count_ptr_position`,
// `non_wrapper_borrows`, `wrapper_values`, `c_ref_kind` and `ffibox_positions`
// each did over the same types, so a position is classified once on three
// axes instead of five times on one each.










/// The `ptr` axis: one count per cell, keyed by the flat name
/// `docs/schema-draft.md` gives. A keyed tally rather than 96 struct fields,
/// as the owner / handle record already is.
type PtrTally = std::collections::BTreeMap<String, u64>;



/// The `ptr` tally as a JSON object of dotted paths. The Python side splits
/// on `.` to assemble one record per counter and derives each `total`, so the
/// driver emits only leaves and never has to know the record's shape.
/// The counters the schema places in the tree but the main pass counts as
/// flat fields. They are mirrored rather than recounted, so the tree and the
/// flat record cannot disagree about the same measurement.
/// Whether this invocation is building a test harness. Cargo passes `--test`
/// for the lib's test target and for each integration test crate, so the
/// driver can tell test code from the library it is scanning without
/// inspecting a single item.
fn is_test_build() -> bool {
    std::env::args().any(|a| a == "--test")
}

/// The test build's counters, under `code.tests`. Only the quantities that
/// mean the same thing for a test as for the library -- its size, its fns and
/// its unsafe -- because the rest of the tree asks what a crate's API hands
/// its consumers, which a test harness has none of.
///
/// The lib's test target recompiles the whole library with `cfg(test)` on, so
/// its figures include the library's; the Python side subtracts them, keyed on
/// the crate name it shares with the non-test emission.
fn tests_into_tree<'a>(ptr: &'a mut PtrTally, c: &Counts, fns: u64) -> &'a PtrTally {
    let mut out = PtrTally::new();
    for (key, n) in [
        ("code.tests.loc.total", c.code_lines),
        ("code.tests.loc.unsafe", c.unsafe_block_code_lines),
        ("code.tests.unsafe_block", c.unsafe_blocks),
        ("code.tests.fn", fns),
    ] {
        if n != 0 {
            out.insert(key.to_string(), n);
        }
    }
    *ptr = out;
    ptr
}

fn mirror_into_tree<'a>(ptr: &'a mut PtrTally, c: &Counts) -> &'a PtrTally {
    for (key, n) in [
        ("code.loc.total", c.code_lines),
        ("code.loc.unsafe", c.unsafe_block_code_lines),
        ("code.unsafe_block.total", c.unsafe_blocks),
        ("code.unsafe_block.of_which.ffi_export", c.unsafe_blocks_ffi_export),
        ("raw_ptr.deref.rd", c.raw_ptr_derefs_rd),
        ("raw_ptr.deref.wr", c.raw_ptr_derefs_wr),
    ] {
        if n != 0 {
            *ptr.entry(key.to_string()).or_default() += n;
        }
    }
    ptr
}

/// Every counter this invocation can emit, registered at zero.
///
/// A document is read on its own, and an ABSENT counter cannot be told from
/// one the schema does not have: a reader who finds no `std_owner` under
/// `ty.ffibox.wrapper` cannot tell "no cell is held in a std collection" from
/// "that arm was never written", and the schema is too long to hold in the
/// head. So the tally starts with every path at 0 and the passes count up
/// from there.
///
/// Gated exactly as the passes are. The ffibox arms are registered only under
/// `--ffibox` and the seam shares only with a seam list, because those are
/// absent BY DESIGN without their flag -- a 0 there would claim the scan
/// looked and found none, when it did not look.
///
/// `RegistryTests` holds this to the counters that actually fire: an arm
/// added to a pass and not here fails there rather than going out as an
/// absence.
fn register_counters(ptr: &mut PtrTally) {
    const VIS: [&str; 2] = ["pub", "priv"];
    const SAFETY: [&str; 2] = ["safe", "unsafe"];
    let seams = !seam_fns().is_empty();
    let mut at = |k: String| {
        ptr.entry(k).or_default();
    };

    for k in [
        "code.loc.total", "code.loc.unsafe",
        "code.unsafe_block.total", "code.unsafe_block.of_which.ffi_export",
        "code.tests.loc.total", "code.tests.loc.unsafe",
        "code.tests.unsafe_block", "code.tests.fn",
        "raw_ptr.deref.rd", "raw_ptr.deref.wr",
        "ty.impl_trait.of_which.unsafe",
    ] {
        at(k.to_string());
    }
    for arm in ["ffi", "rust", "intrinsic"] {
        at(format!("code.unsafe_call.{arm}"));
    }

    // raw_ptr: the positions, their shares, and the denominator.
    // `fn_sig_trait_impl` is a position of its own, outside `raw_ptr.total`.
    for pos in ["fn_sig_arg", "fn_sig_ret", "fn_sig_trait_impl"] {
        for safety in SAFETY {
            for vis in VIS {
                at(format!("raw_ptr.{pos}.{safety}.{vis}"));
                at(format!("raw_ptr.{pos}.of_which.void.{safety}.{vis}"));
                if seams {
                    at(format!("raw_ptr.{pos}.of_which.seam.{safety}.{vis}"));
                }
            }
        }
    }
    // `fn_sig_trait_impl`'s own shares: whose trait fixed the signature, and
    // which of ffibox's it is. The whole vocabulary is registered, so a
    // document says which traits reach a raw pointer AND which do not.
    for whose in ["std", "local", "ffibox"] {
        if whose == "ffibox" && !is_ffibox() {
            continue;
        }
        for safety in SAFETY {
            for vis in VIS {
                at(format!(
                    "raw_ptr.fn_sig_trait_impl.of_which.{whose}.{safety}.{vis}"
                ));
            }
        }
    }
    if is_ffibox() {
        for (name, _) in FFIBOX_TRAITS {
            at(format!(
                "raw_ptr.fn_sig_trait_impl.of_which.ffibox.of_which.{name}"
            ));
        }
    }
    for vis in VIS {
        at(format!("raw_ptr.field.{vis}"));
        at(format!("raw_ptr.field.of_which.void.{vis}"));
        for safety in SAFETY {
            at(format!("raw_ptr.total.{safety}.{vis}"));
        }
    }
    for shape in ["owner", "string", "slice", "borrow", "other"] {
        at(format!("raw_ptr.casted_to.std.{shape}"));
        if seams {
            at(format!("raw_ptr.casted_to.local_seam.{shape}"));
        }
    }
    if is_ffibox() {
        // The shapes the vocabulary itself has, which is fewer than the five
        // above: no ffibox primitive gives a pointer the `other` shape.
        for (_, shape) in FFIBOX_PRIMITIVES {
            at(format!("raw_ptr.casted_to.ffibox.{shape}"));
        }
    }

    for vis in VIS {
        for arm in ["safe", "unsafe", "total"] {
            at(format!("fn.{arm}.{vis}"));
        }
        at(format!("fn.safe.of_which.with_unsafe.{vis}"));
        at(format!("fn.total.of_which.macro.{vis}"));

        at(format!("ty.total.{vis}"));
        at(format!("ty.total.of_which.no_trait.{vis}"));
        at(format!("ty.wrapping_unsafe_cell.{vis}"));
        at(format!("ty.generic.{vis}"));
        at(format!("ty.storing_raw_ptr.{vis}"));
        at(format!("ty.impl_block.{vis}"));
        at(format!("ty.impl_block.of_which.other.{vis}"));
        at(format!("ty.impl_trait.{vis}"));
        at(format!("ty.impl_trait.of_which.derived.{vis}"));
        for name in ["lifetime", "type", "storing_raw_ptr"] {
            at(format!("ty.generic.of_which.{name}.{vis}"));
        }
        for name in ["impl_drop", "impl_clone", "has_lifetime", "impl_deref",
                     "impl_deref_mut", "impl_send_sync", "pub_field", "none"] {
            at(format!("ty.storing_raw_ptr.of_which.{name}.{vis}"));
        }
        for name in ["send", "sync"] {
            at(format!("ty.impl_trait.of_which.send_sync.{name}.{vis}"));
        }
        for whose in ["std", "local"] {
            at(format!("ty.impl_trait.of_which.{whose}.{vis}"));
            at(format!("ty.total.of_which.{whose}_trait.{vis}"));
        }

        if is_ffibox() {
            for pos in ["arg", "ret"] {
                for (name, _) in FFIBOX_PRIMITIVES {
                    at(format!("fn.sig.of_which.ffibox.{pos}.{name}.{vis}"));
                }
            }
            for (name, _) in FFIBOX_PRIMITIVES {
                at(format!("ty.field.ffibox.{name}.{vis}"));
            }
            at(format!("ty.impl_trait.of_which.ffibox.{vis}"));
            at(format!("ty.total.of_which.ffibox_trait.{vis}"));
            at(format!("ty.storing_raw_ptr.of_which.ffibox.{vis}"));
            // The roles `CCell`, `CRefSeam`, `CMutSeam` and `CLockedSeam` name.
            for shape in ["layout", "ref", "mut", "locked"] {
                at(format!("ty.impl_block.of_which.ffibox.{shape}.{vis}"));
            }
            at(format!("ty.ffibox.ccell.{vis}"));
            at(format!("ty.ffibox.ccell.of_which.no_seam_trait.{vis}"));
            for tree in ["wrapper", "ffi"] {
                at(format!("ty.ffibox.{tree}.{vis}"));
                for name in ["borrow", "std_owner", "slice", "field"] {
                    at(format!("ty.ffibox.{tree}.of_which.{name}.{vis}"));
                }
                for name in ["self_in_ref_accessor", "self_in_trait_impl"] {
                    at(format!(
                        "ty.ffibox.{tree}.of_which.borrow.of_which.{name}.{vis}"));
                }
            }
            at(format!("ty.ffibox.by_val.{vis}"));
            for name in ["field", "fn_sig", "std_owner"] {
                at(format!("ty.ffibox.by_val.of_which.{name}.{vis}"));
            }
        }
    }
    if is_ffibox() {
        for (name, _) in FFIBOX_TRAITS {
            for how in ["handwritten", "macro"] {
                at(format!("ty.impl_trait.of_which.ffibox.of_which.{name}.{how}"));
            }
        }
    }
}

fn ptr_json(t: &PtrTally) -> String {
    let body = t
        .iter()
        .map(|(k, v)| format!("\"{k}\":{v}"))
        .collect::<Vec<_>>()
        .join(",");
    format!("{{{body}}}")
}


/// True when `did` stores a raw pointer anywhere in its fields: `*const T`,
/// `*mut T`, `NonNull`, `AtomicPtr`, nested through `Option`, tuples, arrays
/// and generic arguments. Purely structural -- no provenance, no closure.
fn holds_raw_ptr(tcx: TyCtxt<'_>, did: DefId) -> bool {
    holds_raw_ptr_at(tcx, did, 0, &mut HashSet::new())
}

/// Transitively: a field whose own type holds one counts too.
///
/// One level is not enough. git2-rs's `struct OidArray { raw: git_oidarray }`
/// stores the pointer inside the C struct, so a shallow test misses it -- and
/// `OidArray` is the motivating case, since its `Deref` hands out `&[Oid]`
/// over a buffer libgit2 allocated. Descends through the peel set only,
/// depth- and cycle-guarded.
fn holds_raw_ptr_at(tcx: TyCtxt<'_>, did: DefId, depth: u32, seen: &mut HashSet<DefId>) -> bool {
    if depth > 8 || !seen.insert(did) {
        return false;
    }
    tcx.adt_def(did).all_fields().any(|f| {
        let ft = tcx.type_of(f.did).instantiate_identity().skip_norm_wip();
        let mut ps = Vec::new();
        raw_pointees(tcx, ft, &mut ps);
        if !ps.is_empty() {
            return true;
        }
        field_adt(tcx, ft).is_some_and(|d| {
            in_peel_set(tcx, d.did()) && holds_raw_ptr_at(tcx, d.did(), depth + 1, seen)
        })
    })
}

/// What a local type declares through its trait impls: the std traits that
/// bear on a raw pointer it holds, and which provenance of trait it
/// implements at all.
#[derive(Clone, Copy, Default)]
struct HolderTraits {
    drop_: bool,
    deref: bool,
    deref_mut: bool,
    clone: bool,
    derived_clone: bool,
    send_sync: bool,
    std_trait: bool,
    local_trait: bool,
    ffibox_trait: bool,
    /// For a `CCell` implementor: whether NEITHER of its handles implements
    /// its seam. `define_ctype!` writes them, but a cell with parameters of
    /// its own cannot go through the macro and nothing else supplies them, so
    /// its handles fall outside the generic seam unless written by hand.
    cell_no_seam: bool,
    /// The type's role in ffibox's convention, from the seam trait it
    /// implements: `CCell` the layout type, `CRefSeam` its shared handle,
    /// `CMutSeam` its exclusive one, `CLockedSeam` its locked one.
    ffibox_shape: Option<&'static str>,
}

/// The traits a raw-pointer-holding type implements, which is what
/// makes holding one hazardous:
///
///  * `Drop`   -- it frees memory Rust did not allocate.
///  * `Deref` / `DerefMut` -- every `*x` and auto-deref hands out a reference
///    derived from that pointer, implicitly, at every call site. git2-rs's
///    `impl Deref for OidArray` yields `&[Oid]` over a libgit2 buffer.
///  * `Clone`  -- a shallow clone duplicates the pointer; with `Drop` that is
///    a double free, and `#[derive(Clone)]` is how it happens unnoticed.
///  * `Send` / `Sync` -- an unsafe assertion that memory reached through that
///    pointer is thread-safe, which no type system checked.
fn ptr_holder_traits(tcx: TyCtxt<'_>) -> HashMap<DefId, HolderTraits> {
    let mut out: HashMap<DefId, HolderTraits> = HashMap::new();
    // The handles that implement a seam, and each cell's handles, so the cells
    // whose handles have none can be found once every impl has been seen.
    let mut seam_impls: HashSet<DefId> = HashSet::new();
    let mut cell_handles: HashMap<DefId, Vec<DefId>> = HashMap::new();
    for ld in tcx.hir_crate_items(()).definitions() {
        let did = ld.to_def_id();
        if !matches!(tcx.def_kind(did), DefKind::Impl { of_trait: true }) {
            continue;
        }
        let tr = tcx.impl_trait_ref(did).skip_binder().def_id;
        let ty::TyKind::Adt(d, _) = tcx.type_of(did).instantiate_identity().skip_norm_wip().kind()
        else {
            continue;
        };
        if !d.did().is_local() {
            continue;
        }
        let e = out.entry(d.did()).or_default();
        let name = tcx.item_name(tr);
        if is_std_crate(tcx, tr) {
            e.std_trait = true;
            match name.as_str() {
                "Drop" => e.drop_ = true,
                "Deref" => e.deref = true,
                "DerefMut" => e.deref_mut = true,
                "Send" | "Sync" => e.send_sync = true,
                "Clone" => {
                    e.clone = true;
                    e.derived_clone |= tcx.is_automatically_derived(did);
                }
                _ => {}
            }
        } else if tr.is_local() {
            e.local_trait = true;
        } else if is_ffibox_crate(tcx, tr) {
            e.ffibox_trait = true;
            // A type's role in the convention. The seam traits are
            // implemented ON the handle, so implementing one names the role
            // directly -- but `define_ctype!` only generates them for a cell
            // with no parameters of its own, and a lifetime-carrying one
            // (`Blob<'r>`) hand-writes `CCell` and no seam at all. Reading
            // only the seams therefore missed every hand-written cell's
            // handles: on libgit2-bindings 49 `*Ref` and 40 `*Mut` blocks
            // landed under `other`.
            //
            // `CCell`'s own `Ref<'a>` and `Mut<'a>` associated types name the
            // handles whatever wrote the impl, so they are the authority.
            e.ffibox_shape = match name.as_str() {
                "CCell" => Some("layout"),
                "CRefSeam" => Some("ref"),
                "CMutSeam" => Some("mut"),
                "CLockedSeam" => Some("locked"),
                _ => e.ffibox_shape,
            };
            if matches!(name.as_str(), "CRefSeam" | "CMutSeam") {
                seam_impls.insert(d.did());
            }
            if name.as_str() == "CCell" {
                let cell = d.did();
                for assoc in tcx.associated_items(did).in_definition_order() {
                    let role = match tcx.item_name(assoc.def_id).as_str() {
                        "Ref" => "ref",
                        "Mut" => "mut",
                        _ => continue,
                    };
                    let handle = tcx.type_of(assoc.def_id).instantiate_identity();
                    if let ty::TyKind::Adt(h, _) = handle.skip_norm_wip().kind() {
                        if h.did().is_local() {
                            cell_handles.entry(cell).or_default().push(h.did());
                            let he = out.entry(h.did()).or_default();
                            he.ffibox_trait = true;
                            if he.ffibox_shape.is_none() {
                                he.ffibox_shape = Some(role);
                            }
                        }
                    }
                }
            }
        }
    }
    // A cell whose handles implement no seam: they sit outside the generic
    // seam `CRefSeam::from_ptr` and `CMutSeam::as_mut_ptr` give, so code over
    // the handle has to special-case them.
    for (cell, handles) in cell_handles {
        if !handles.is_empty() && !handles.iter().any(|h| seam_impls.contains(h)) {
            out.entry(cell).or_default().cell_no_seam = true;
        }
    }
    out
}

thread_local! {
    /// Built once per compilation (the driver is one rustc invocation per crate).
    static DECLARED: std::cell::RefCell<Option<HashMap<DefId, DefId>>> =
        const { std::cell::RefCell::new(None) };
}

/// STRUCTURAL wrapper detection, replacing the `CCell`-declared keying.
///
/// A wrapper is a `#[repr(transparent)]` newtype whose single non-ZST field is,
/// after peeling further transparent newtypes, either
///   * a raw pointer / `NonNull` -- a HANDLE (borrowed or owning), or
///   * a `#[repr(C)]` ADT by value -- a LAYOUT newtype over the C object.
///
/// This is what a wrapper IS, in any crate. Keying on `CCell` measured what an
/// author DECLARED, which cannot see a hand-written wrapper (the translator
/// playbook permits them for lifetime-carrying and generic cases) and
/// which ties the audit to ffibox. Every `CCell` wrapper satisfies the
/// structural test by construction -- ffibox requires `#[repr(transparent)]`
/// over `Self::C` -- so the structural set SUBSUMES the declared one,
/// and a type that declares `CCell` while failing this test is a wrapper
/// without the layout it claims: reported by `--ffibox` as
/// `ffibox_ccell_not_layout`, never silently admitted.
fn peel_transparent<'tcx>(tcx: TyCtxt<'tcx>, t: Ty<'tcx>) -> Ty<'tcx> {
    let mut cur = t;
    for _ in 0..8 {
        // depth guard; nesting is 2-3 in practice
        // `NonNull<T>` lowers to a PATTERN type (`*const T is !null`), so a
        // handle peeled to the bottom lands here rather than on `RawPtr`.
        if let ty::TyKind::Pat(base, _) = cur.kind() {
            cur = *base;
            continue;
        }
        let ty::TyKind::Adt(def, args) = cur.kind() else {
            return cur;
        };
        if !def.repr().transparent() || !def.is_struct() {
            return cur;
        }
        let mut inner = None;
        for f in def.all_fields() {
            let ft = tcx.type_of(f.did).instantiate(tcx, args).skip_norm_wip();
            if is_phantom(tcx, ft) || is_zst_marker(tcx, ft) {
                continue;
            }
            inner = Some(ft);
            break;
        }
        match inner {
            Some(i) => cur = i,
            None => return cur,
        }
    }
    cur
}

/// `PhantomPinned` and friends: unit-like ZST markers that are not storage.
fn is_zst_marker(tcx: TyCtxt<'_>, t: Ty<'_>) -> bool {
    matches!(t.kind(), ty::TyKind::Adt(d, _)
        if matches!(tcx.item_name(d.did()).as_str(),
                    "PhantomPinned" | "PhantomData"))
}

/// Peel transparent newtypes, then unwrap arrays/slices, to the ADT a field
/// ultimately stores. `[git_oid; 4]` and a layout type over `ffi::git_oid` both
/// land on `git_oid`.
fn field_adt<'tcx>(tcx: TyCtxt<'tcx>, t: Ty<'tcx>) -> Option<ty::AdtDef<'tcx>> {
    let mut cur = peel_transparent(tcx, t);
    for _ in 0..8 {
        match cur.kind() {
            ty::TyKind::Array(e, _) | ty::TyKind::Slice(e) => {
                cur = peel_transparent(tcx, *e);
            }
            ty::TyKind::Adt(d, _) => return Some(*d),
            _ => return None,
        }
    }
    None
}

/// True if `did` — or an enclosing item — IS the C-ABI boundary, by either of
/// the two ways a fn can be one:
///
///  * it carries a C symbol name (`#[unsafe(no_mangle)]` / `#[export_name]`),
///    so C callers reach it by that name; or
///  * it has a non-Rust ABI (`extern "C"`), so C reaches it by function
///    pointer — the callback-shim form, which needs no symbol name.
///
/// Both are the port stage's C-ABI gateway: the unsafe blocks inside belong to
/// the boundary rather than to the port body, so `unsafe_blocks_ffi_export`
/// counts them apart. Its raw pointers are counted like any other position.
fn in_ffi_export(tcx: TyCtxt<'_>, mut did: DefId) -> bool {
    loop {
        if matches!(tcx.def_kind(did), DefKind::Fn | DefKind::AssocFn) {
            let attrs = tcx.codegen_fn_attrs(did);
            if attrs.flags.contains(CodegenFnAttrFlags::NO_MANGLE) || attrs.symbol_name.is_some() {
                return true;
            }
            if tcx.fn_sig(did).skip_binder().skip_binder().abi() != ExternAbi::Rust {
                return true;
            }
        }
        match tcx.opt_parent(did) {
            // Keep walking out of closures / nested bodies into the owning fn;
            // stop at the module boundary.
            Some(p) if !matches!(tcx.def_kind(p), DefKind::Mod | DefKind::ForeignMod) => did = p,
            _ => return false,
        }
    }
}

#[derive(Default)]
struct Counts {
    // The quantities the tree reads through `mirror_into_tree`, which are
    // accumulated while walking rather than bumped at a single site: line
    // metrics need the outermost block's span, and the deref split needs the
    // place's write-ness. Every other counter is a `bump` straight into the
    // tree, so it has no field here.
    code_lines: u64,              // non-blank, non-`//`-comment source lines
    unsafe_blocks: u64,
    unsafe_block_code_lines: u64, // the same, inside outermost unsafe blocks
    // Of `unsafe_blocks`, those at the C-ABI boundary (`in_ffi_export`:
    // `#[no_mangle]` / `#[export_name]` / `extern "C"`). A region
    // attribution, never an exemption.
    unsafe_blocks_ffi_export: u64,
    raw_ptr_derefs_rd: u64,
    raw_ptr_derefs_wr: u64,
}



/// Source sites `(file, 1-based line)` per counter, keyed by the counter's
/// output name -- its dotted path in the tree, which is what `--sites` names,
/// and NOT the `Counts` field a mirrored counter is tallied in: a key that is
/// no counter's path is a site list nothing can ask for.
///
/// Every increment of a location-counting counter records where it happened.
/// The line and statement counters (`code.loc`, `code.tests`) have none: their
/// increment is a line, so their sites would be the file's own lines.
/// Aggregated by `Sites::json`.
#[derive(Default)]
struct Sites(std::collections::BTreeMap<String, Vec<(String, usize)>>);

impl Sites {
    fn add(&mut self, counter: impl Into<String>, site: (String, usize)) {
        self.0.entry(counter.into()).or_default().push(site);
    }

    /// `{"<counter>": [{"file":..,"count":N,"lines":[..]}], ..}`, where `count`
    /// is the number of increments in the file (so a counter's per-file counts
    /// sum to the counter) and `lines` the distinct lines they fell on.
    fn json(&self) -> String {
        use std::collections::BTreeMap;
        let rows: Vec<String> = self
            .0
            .iter()
            .map(|(k, v)| {
                let mut by_file: BTreeMap<&str, Vec<usize>> = BTreeMap::new();
                for (f, l) in v {
                    by_file.entry(f.as_str()).or_default().push(*l);
                }
                let files: Vec<String> = by_file
                    .iter()
                    .map(|(f, ls)| {
                        let mut u = ls.clone();
                        u.sort_unstable();
                        u.dedup();
                        let arr: Vec<String> = u.iter().map(|l| l.to_string()).collect();
                        format!(
                            "{{\"file\":\"{}\",\"count\":{},\"lines\":[{}]}}",
                            f,
                            ls.len(),
                            arr.join(",")
                        )
                    })
                    .collect();
                format!("\"{}\":[{}]", k, files.join(","))
            })
            .collect();
        format!("{{{}}}", rows.join(","))
    }
}

/// `span_site` for a counter site: a span produced by a macro (`define_ctype!`,
/// a `#[derive]`) is mapped to the invocation in this crate, so the site names
/// the line the author wrote rather than a line of the macro's own source.
fn counter_site(tcx: TyCtxt<'_>, span: Span) -> (String, usize) {
    span_site(tcx, span.source_callsite())
}

/// `(file, 1-based line)` for a span, local-path filename.
fn span_site(tcx: TyCtxt<'_>, span: Span) -> (String, usize) {
    let sm = tcx.sess.source_map();
    let file = sm
        .span_to_filename(span)
        .into_local_path()
        .map(|p| p.display().to_string())
        .unwrap_or_default();
    let line = sm.lookup_char_pos(span.lo()).line;
    (file, line)
}

struct BodyVisitor<'a, 'tcx> {
    tcx: TyCtxt<'tcx>,
    typeck: &'tcx TypeckResults<'tcx>,
    depth: u32,       // unsafe-block nesting depth
    in_ffi: bool,     // this body IS / is inside the C-ABI boundary
    c: &'a mut Counts,
    ptr: &'a mut PtrTally,
    sites: &'a mut Sites,
}

impl<'a, 'tcx> BodyVisitor<'a, 'tcx> {
    /// `raw_ptr.casted_to`: a Rust value constructed from a raw pointer, by
    /// whose vocabulary did it and what shape the pointer took.
    ///
    /// Conversions are recognised by name, never inferred from types. A type
    /// rule cannot show the output derives from the pointer input -- `f(p, s)
    /// -> &str` may take its result from `s` -- and only the callee's identity
    /// settles it. A declared seam needs no such proof: the declaration states
    /// the function converts, so only its shape is read from the return type.
    ///
    /// `owner` is the sharp arm: `Box::from_raw`, `Vec::from_raw_parts` hand
    /// an allocation to Rust's allocator, which will free it. Over a buffer C
    /// allocated that is an allocator mismatch, and nothing in the type system
    /// objects.
    fn count_casted_to(&mut self, e: &'tcx hir::Expr<'tcx>) {
        // `&*p` / `&mut *p`: a borrow out of a raw pointer with no call to
        // name. Core language, so it is std's vocabulary.
        if let hir::ExprKind::AddrOf(hir::BorrowKind::Ref, _, inner) = e.kind {
            if let hir::ExprKind::Unary(hir::UnOp::Deref, base) = inner.kind {
                if self.typeck.expr_ty(base).is_raw_ptr() {
                    self.bump_casted_to("std", "borrow", e.span);
                    return;
                }
            }
        }

        let (did, args) = match e.kind {
            hir::ExprKind::Call(f, args) => {
                let hir::ExprKind::Path(ref qp) = f.kind else { return };
                let hir::def::Res::Def(_, did) = self.typeck.qpath_res(qp, f.hir_id) else {
                    return;
                };
                (did, args)
            }
            hir::ExprKind::MethodCall(_, recv, args, _) => {
                let Some(did) = self.typeck.type_dependent_def_id(e.hir_id) else { return };
                // The receiver is the pointer for `p.as_ref()`, and CARRIES
                // one for `NonNull::as_ref` -- which is in the table, so a
                // bare `is_raw_ptr` left that entry unreachable.
                let rt = self.typeck.expr_ty_adjusted(recv);
                let mut ps = Vec::new();
                raw_pointees(self.tcx, rt, &mut ps);
                if ps.is_empty() {
                    return;
                }
                (did, args)
            }
            _ => return,
        };
        let from_raw = args
            .iter()
            .any(|a| self.typeck.expr_ty_adjusted(a).is_raw_ptr())
            || matches!(e.kind, hir::ExprKind::MethodCall(..));
        if !from_raw {
            return;
        }

        let name = self.tcx.item_name(did);
        let name = name.as_str();
        let owners = callee_owners(self.tcx, did);

        let std_shape = if is_std_crate(self.tcx, did) {
            owners.iter().find_map(|o| std_conversion(o, name))
        } else {
            None
        };
        let ffibox_shape = if is_ffibox()
            && is_ffibox_crate(self.tcx, did)
            && FFIBOX_ADOPTERS.contains(&name)
        {
            owners
                .iter()
                .find_map(|o| FFIBOX_PRIMITIVES.iter().find(|(p, _)| p == o))
                .map(|(_, shape)| *shape)
        } else {
            None
        };
        if let Some(shape) = std_shape {
            self.bump_casted_to("std", shape, e.span);
        } else if let Some(shape) = ffibox_shape {
            self.bump_casted_to("ffibox", shape, e.span);
        } else if is_seam_fn(self.tcx, did) {
            let shape = out_shape(self.tcx, self.typeck.expr_ty(e));
            self.bump_casted_to("local_seam", shape, e.span);
        }
    }

    fn bump_casted_to(&mut self, arm: &str, shape: &str, span: Span) {
        let k = format!("raw_ptr.casted_to.{arm}.{shape}");
        *self.ptr.entry(k.clone()).or_default() += 1;
        self.sites.add(k, counter_site(self.tcx, span));
    }

    /// `code.unsafe_call`: safety decides whether a call counts, ABI decides
    /// which arm it lands in.
    ///
    /// The signature is read from the TYPE of the callee, so a call through a
    /// function pointer -- a stored `extern "C"` callback, which has no item
    /// to ask -- is classified like any other. `is_foreign_item` is a property
    /// of the declaration site and misses every one of those.
    fn count_unsafe_call(&mut self, e: &'tcx hir::Expr<'tcx>) {
        let callee = match e.kind {
            hir::ExprKind::Call(f, _) => Some(f),
            hir::ExprKind::MethodCall(..) => None,
            _ => return,
        };
        let (did, abi, safety) = match callee {
            Some(f) => match self.typeck.expr_ty_adjusted(f).kind() {
                // ABI and safety do not depend on the generic arguments, so
                // the identity signature answers both.
                ty::TyKind::FnDef(did, _) => {
                    let sig = self.tcx.fn_sig(*did).skip_binder().skip_binder();
                    (Some(*did), sig.abi(), sig.safety())
                }
                ty::TyKind::FnPtr(_, hdr) => (None, hdr.abi(), hdr.safety()),
                _ => return,
            },
            None => {
                let Some(did) = self.typeck.type_dependent_def_id(e.hir_id) else { return };
                let sig = self.tcx.fn_sig(did).skip_binder().skip_binder();
                (Some(did), sig.abi(), sig.safety())
            }
        };
        // An `extern "C" fn` DEFINED in Rust is safe to call: a port
        // campaign's `ffi_export` gateway has a C ABI but crosses no boundary
        // and discharges no obligation. Foreign declarations keep `Unsafe`.
        if safety.is_safe() {
            return;
        }
        // Intrinsics are tested by `tcx.intrinsic`, not by ABI: rustc marks
        // them `#[rustc_intrinsic]` with the Rust ABI, so an ABI test would
        // file `transmute` under `rust`.
        let arm = if did.is_some_and(|d| self.tcx.intrinsic(d).is_some()) {
            "intrinsic"
        } else if abi != ExternAbi::Rust {
            "ffi"
        } else {
            "rust"
        };
        let k = format!("code.unsafe_call.{arm}");
        *self.ptr.entry(k.clone()).or_default() += 1;
        self.sites.add(k, counter_site(self.tcx, e.span));
    }

    /// Is the place the raw-pointer dereference `e` (`*p`) begins written:
    /// it, or a field or index below it, is assigned (`=`, `op=`), borrowed
    /// mutably (`&mut`, `&raw mut` / `addr_of_mut!`), or auto-borrowed mutably
    /// (a `&mut self` method, an `IndexMut`)?
    fn place_written(&self, e: &'tcx hir::Expr<'tcx>) -> bool {
        let mut cur = e;
        loop {
            let mut_borrow = self.typeck.expr_adjustments(cur).iter().any(|a| {
                matches!(a.kind, rustc_middle::ty::adjustment::Adjust::Borrow(_))
                    && matches!(a.target.kind(), ty::TyKind::Ref(_, _, m) | ty::TyKind::RawPtr(_, m) if m.is_mut())
            });
            if mut_borrow {
                return true;
            }
            let hir::Node::Expr(parent) = self.tcx.parent_hir_node(cur.hir_id) else {
                return false;
            };
            match parent.kind {
                hir::ExprKind::Field(base, _) | hir::ExprKind::Index(base, _, _) if base.hir_id == cur.hir_id => {
                    cur = parent
                }
                hir::ExprKind::Assign(lhs, _, _) | hir::ExprKind::AssignOp(_, lhs, _) => {
                    return lhs.hir_id == cur.hir_id;
                }
                hir::ExprKind::AddrOf(_, m, _) => return m.is_mut(),
                _ => return false,
            }
        }
    }

}

impl<'a, 'tcx> Visitor<'tcx> for BodyVisitor<'a, 'tcx> {
    fn visit_expr(&mut self, e: &'tcx hir::Expr<'tcx>) {
        self.count_casted_to(e);
        self.count_unsafe_call(e);
        match e.kind {
            // `unsafe { ... }`
            hir::ExprKind::Block(b, _)
                if matches!(b.rules, hir::BlockCheckMode::UnsafeBlock(_)) =>
            {
                self.c.unsafe_blocks += 1;
                self.sites.add("code.unsafe_block.total", counter_site(self.tcx, e.span));
                if self.in_ffi {
                    self.c.unsafe_blocks_ffi_export += 1;
                    self.sites.add("code.unsafe_block.of_which.ffi_export",
                        counter_site(self.tcx, e.span));
                }
                // Line metrics: outermost blocks only (nested ones would
                // double-count). EVERY outermost block counts, macro-expanded
                // or not: the metric asks how much unsafe is compiled into this
                // crate, and a block ffibox's `define_ctype!` emitted runs here
                // exactly like one an agent typed. Sanctioning is the only axis
                // that excuses anything, and it does not apply to blocks --
                // `unsafe_blocks_ffi_export` ATTRIBUTES a block to a region,
                // it does not exempt it.
                //
                // The earlier exclusion was justified by `span_to_snippet` being
                // unable to reach a macro span's text; that is not so -- every
                // macro-expanded block on libippcp resolves -- and dropping them
                // understated the ratio in proportion to how macro-driven the
                // wrapping is (7.28% against 10.01% here), which is the same bias
                // the `code_lines` rebuild removed from the denominator.
                if self.depth == 0 {
                    let sm = self.tcx.sess.source_map();
                    // filtered: drop blank + `//`-comment lines (same filter as
                    // the code_LOC denominator, so the ratio is apples-to-apples)
                    if let Ok(snip) = sm.span_to_snippet(b.span) {
                        self.c.unsafe_block_code_lines +=
                            snip.lines()
                                .filter(|l| {
                                    let t = l.trim();
                                    !t.is_empty() && !t.starts_with("//")
                                })
                                .count() as u64;
                    }
                }
                self.depth += 1;
                intravisit::walk_expr(self, e);
                self.depth -= 1;
                return;
            }
            // `*operand` where operand is a raw pointer (type-decided)
            hir::ExprKind::Unary(hir::UnOp::Deref, inner) => {
                if self.typeck.expr_ty(inner).is_raw_ptr() {
                    let (k, slot) = if self.place_written(e) {
                        ("raw_ptr.deref.wr", &mut self.c.raw_ptr_derefs_wr)
                    } else {
                        ("raw_ptr.deref.rd", &mut self.c.raw_ptr_derefs_rd)
                    };
                    *slot += 1;
                    self.sites.add(k, counter_site(self.tcx, e.span));
                }
            }
            _ => {}
        }
        intravisit::walk_expr(self, e);
    }
}

// --------------------------------------------------------------- ffibox mode


fn is_ffibox_crate(tcx: TyCtxt<'_>, did: DefId) -> bool {
    tcx.crate_name(did.krate).as_str() == "ffibox"
}

/// `--ffibox`: the counters that read ffibox's vocabulary are emitted only
/// when the scanned crate is meant to use it.
fn is_ffibox() -> bool {
    std::env::var_os("UM_FFIBOX").is_some()
}

/// True when `did` holds an `UnsafeCell` in its fields, directly or through
/// the peel set. The same walk as `holds_raw_ptr`, with a different sink.
fn holds_unsafe_cell(tcx: TyCtxt<'_>, did: DefId) -> bool {
    holds_unsafe_cell_at(tcx, did, 0, &mut HashSet::new())
}

fn holds_unsafe_cell_at(
    tcx: TyCtxt<'_>,
    did: DefId,
    depth: u32,
    seen: &mut HashSet<DefId>,
) -> bool {
    if depth > 8 || !seen.insert(did) {
        return false;
    }
    tcx.adt_def(did).all_fields().any(|f| {
        let ft = tcx.type_of(f.did).instantiate_identity().skip_norm_wip();
        // The field type is read BEFORE `field_adt`, which peels
        // `repr(transparent)` -- and `UnsafeCell` is transparent, so peeling
        // leaves `u32` and the cell is gone. A canary caught exactly that.
        is_unsafe_cell_ty(tcx, ft, 0)
            || field_adt(tcx, ft).is_some_and(|d| {
                in_peel_set(tcx, d.did())
                    && holds_unsafe_cell_at(tcx, d.did(), depth + 1, seen)
            })
    })
}

/// `UnsafeCell` in `t` itself, under arrays and generic arguments.
fn is_unsafe_cell_ty<'tcx>(tcx: TyCtxt<'tcx>, t: Ty<'tcx>, depth: u32) -> bool {
    if depth > 8 {
        return false;
    }
    match t.kind() {
        ty::TyKind::Adt(d, args) => {
            (is_std_crate(tcx, d.did()) && tcx.item_name(d.did()).as_str() == "UnsafeCell")
                || args.types().any(|a| is_unsafe_cell_ty(tcx, a, depth + 1))
        }
        ty::TyKind::Array(e, _) | ty::TyKind::Slice(e) => is_unsafe_cell_ty(tcx, *e, depth + 1),
        ty::TyKind::Tuple(ts) => ts.iter().any(|a| is_unsafe_cell_ty(tcx, a, depth + 1)),
        _ => false,
    }
}

/// Bump a tree counter and record the site of `did`'s definition.
fn tree_bump(
    ptr: &mut PtrTally,
    sites: &mut Sites,
    tcx: TyCtxt<'_>,
    did: DefId,
    key: &str,
) {
    *ptr.entry(key.to_string()).or_default() += 1;
    sites.add(key, counter_site(tcx, tcx.def_span(did)));
}

/// Whether the type an impl is written for is exported. An impl of a foreign
/// or non-ADT self type counts as private: no consumer of this crate reaches
/// a claim it cannot name.
fn impl_self_vis(tcx: TyCtxt<'_>, imp: DefId) -> &'static str {
    let exported = match tcx.type_of(imp).instantiate_identity().skip_norm_wip().kind() {
        ty::TyKind::Adt(d, _) => d
            .did()
            .as_local()
            .is_some_and(|l| tcx.effective_visibilities(()).is_exported(l)),
        _ => false,
    };
    if exported { "pub" } else { "priv" }
}

/// The std conversions out of a raw pointer, by (owner, method), with the
/// shape the pointer takes. Matching is gated on the callee's crate being
/// `core`, `alloc` or `std`, so a custom `Box::from_raw` cannot collide.
///
/// `CString` and `String` are `string`, not `owner`: the bucket records what
/// shape the pointer became, and the C-string boundary is the distinction
/// worth keeping.
fn std_conversion(owner: &str, method: &str) -> Option<&'static str> {
    Some(match (owner, method) {
        ("ptr" | "NonNull", "as_ref" | "as_mut") => "borrow",
        ("slice", "from_raw_parts" | "from_raw_parts_mut") => "slice",
        ("slice", "from_ptr_range" | "from_mut_ptr_range") => "slice",
        ("CStr", "from_ptr") => "string",
        ("CString", "from_raw") => "string",
        ("String", "from_raw_parts") => "string",
        ("Box", "from_raw") => "owner",
        ("Vec", "from_raw_parts") => "owner",
        ("Rc" | "Arc", "from_raw") => "owner",
        _ => return None,
    })
}

/// The names a callee could be matched under: the self type of an inherent or
/// trait impl, `ptr` for an impl on a raw pointer, and every ancestor module.
///
/// Ancestors, not just the parent: `slice::from_raw_parts` is DEFINED in
/// `core::slice::raw` and re-exported, so the defining module is `raw` and a
/// parent-only lookup finds nothing. A canary caught that as a silent zero on
/// `casted_to.std.slice`.
fn callee_owners(tcx: TyCtxt<'_>, did: DefId) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = did;
    for _ in 0..8 {
        let Some(parent) = tcx.opt_parent(cur) else { break };
        match tcx.def_kind(parent) {
            DefKind::Impl { .. } => {
                match tcx.type_of(parent).instantiate_identity().skip_norm_wip().kind() {
                    ty::TyKind::Adt(d, _) => out.push(tcx.item_name(d.did()).to_string()),
                    ty::TyKind::RawPtr(..) => out.push("ptr".to_string()),
                    _ => {}
                }
            }
            DefKind::Mod => {
                if let Some(n) = tcx.opt_item_name(parent) {
                    out.push(n.to_string());
                }
            }
            _ => {}
        }
        cur = parent;
    }
    out
}

/// The shape of a declared seam's result. Used for `local_seam` only, where
/// the declaration already states the function converts, so reading the
/// return type infers nothing.
fn out_shape<'tcx>(tcx: TyCtxt<'tcx>, out: Ty<'tcx>) -> &'static str {
    let out = peel_option(tcx, out);
    match out.kind() {
        ty::TyKind::Ref(_, p, _) => match p.kind() {
            ty::TyKind::Slice(_) | ty::TyKind::Array(..) => "slice",
            ty::TyKind::Str => "string",
            ty::TyKind::Adt(d, _)
                if matches!(tcx.item_name(d.did()).as_str(), "CStr" | "OsStr" | "Path") =>
            {
                "string"
            }
            _ => "borrow",
        },
        ty::TyKind::Adt(d, _) if is_std_crate(tcx, d.did()) => {
            match tcx.item_name(d.did()).as_str() {
                "CString" | "String" | "OsString" | "PathBuf" => "string",
                "Box" | "Vec" | "VecDeque" | "Rc" | "Arc" => "owner",
                _ => "other",
            }
        }
        ty::TyKind::Adt(d, _) => match ffibox_primitive(tcx, d.did()) {
            Some((_, shape)) => shape,
            None => "other",
        },
        _ => "other",
    }
}

/// `Option<T>` to `T`: `<*const T>::as_ref` returns one.
fn peel_option<'tcx>(tcx: TyCtxt<'tcx>, t: Ty<'tcx>) -> Ty<'tcx> {
    if let ty::TyKind::Adt(d, args) = t.kind() {
        if is_std_crate(tcx, d.did()) && tcx.item_name(d.did()).as_str() == "Option" {
            if let Some(inner) = args.types().next() {
                return inner;
            }
        }
    }
    t
}

/// ffibox's traits, by group. The groups are the schema's `<trait>`
/// vocabulary (docs/schema.md); `Sealed` and `__UnitStatus` are internal and
/// carry no claim, so they are not listed.
const FFIBOX_TRAITS: &[(&str, &str)] = &[
    ("CCell", "layout"), ("CPlainElem", "layout"), ("CZeroable", "layout"),
    ("CAlloc", "allocate"), ("CAllocZeroed", "allocate"), ("CNew", "allocate"),
    ("CDrop", "release"), ("CDispose", "release"), ("CLenDrop", "release"),
    ("CDupClone", "clone"), ("CRefClone", "clone"), ("CLenClone", "clone"),
    ("CRefSeam", "seam"), ("CMutSeam", "seam"), ("CLockedSeam", "seam"),
    ("CGuarded", "guard"), ("CGuardedAll", "guard"), ("LockScope", "guard"),
];

/// ffibox's types, by the shape a raw pointer takes once it is adopted into
/// one. The shape names are `raw_ptr.casted_to`'s, so one list serves the
/// conversion table, `ty.field.ffibox` and `fn.sig.of_which.ffibox`.
const FFIBOX_PRIMITIVES: &[(&str, &str)] = &[
    ("CBox", "owner"), ("CArc", "owner"), ("CVec", "owner"), ("CVal", "owner"),
    ("CStrBox", "string"),
    ("CBorrowedPtr", "borrow"), ("CSlice", "slice"), ("CSliceMut", "slice"),
    ("CGuardedRef", "borrow"), ("CGuard", "borrow"),
];

/// The methods that adopt a raw pointer into an ffibox primitive.
///
/// `as_ref`, `as_slice`, `as_c_str` and `as_bytes` are excluded: they take
/// `&self` on an owner, so they are owner-to-borrow, not raw-to-borrow.
/// `as_ptr` and its siblings run the other direction.
const FFIBOX_ADOPTERS: &[&str] = &[
    "from_raw", "from_raw_with", "from_ptr", "from_c", "from_c_with",
    "from_raw_parts", "from_raw_parts_with",
    "from_raw_parts_or_empty", "from_raw_parts_or_empty_with",
];

/// The ffibox primitive `did` names, with the shape it gives a pointer.
fn ffibox_primitive(tcx: TyCtxt<'_>, did: DefId) -> Option<(&'static str, &'static str)> {
    if !is_ffibox_crate(tcx, did) {
        return None;
    }
    let n = tcx.opt_item_name(did)?;
    FFIBOX_PRIMITIVES.iter().find(|(p, _)| *p == n.as_str()).copied()
}

/// True when the local type `did` implements any ffibox trait. Its negation is
/// `ty.storing_raw_ptr.of_which.no_ffibox_trait`: the type manages a pointer
/// itself and takes none of the vocabulary that would say how.
///
/// Cached: the holder loop asks once per type, and the answer is a scan of
/// every impl in the crate.
fn implements_ffibox_trait(tcx: TyCtxt<'_>, did: DefId) -> bool {
    thread_local! {
        static IMPLS: std::cell::RefCell<Option<HashSet<DefId>>> =
            const { std::cell::RefCell::new(None) };
    }
    IMPLS.with(|c| {
        let mut b = c.borrow_mut();
        if b.is_none() {
            let mut set = HashSet::new();
            for ld in tcx.hir_crate_items(()).definitions() {
                let imp = ld.to_def_id();
                if !matches!(tcx.def_kind(imp), DefKind::Impl { of_trait: true }) {
                    continue;
                }
                if !is_ffibox_crate(tcx, tcx.impl_trait_ref(imp).skip_binder().def_id) {
                    continue;
                }
                if let ty::TyKind::Adt(d, _) =
                    tcx.type_of(imp).instantiate_identity().skip_norm_wip().kind()
                {
                    set.insert(d.did());
                }
            }
            *b = Some(set);
        }
        b.as_ref().unwrap().contains(&did)
    })
}

/// True when `span` is output of an ffibox macro (`define_ctype!`,
/// `impl_cguarded!`, ..), at any depth of expansion. Resolved through the
/// macro's definition, so a renamed import still counts.
fn from_ffibox_macro(tcx: TyCtxt<'_>, span: Span) -> bool {
    let mut ctxt = span.ctxt();
    while !ctxt.is_root() {
        let data = ctxt.outer_expn_data();
        if data.macro_def_id.is_some_and(|m| is_ffibox_crate(tcx, m)) {
            return true;
        }
        ctxt = data.call_site.ctxt();
    }
    false
}

/// The `CCell` types the crate declares, and the raw C types they cover.
///
/// `CCell` is the authority on both, as it is on the handles: its `type C`
/// names the raw struct a cell is a `#[repr(transparent)]` newtype over, and
/// its `Ref` and `Mut` name the two handles a consumer is meant to reach that
/// struct's bytes through. So a `&Foo` written anywhere other than one of
/// those mints is the layout published directly, and a `&Foo::C` is the raw C
/// struct published with no convention over it at all.
#[derive(Default)]
struct CellTypes {
    /// The layout newtypes: `Foo` in `impl CCell for Foo`.
    cells: HashSet<DefId>,
    /// Their `type C`: the raw struct each cell covers.
    cs: HashSet<DefId>,
}

fn cell_types(tcx: TyCtxt<'_>) -> CellTypes {
    let mut out = CellTypes::default();
    for ld in tcx.hir_crate_items(()).definitions() {
        let did = ld.to_def_id();
        if !matches!(tcx.def_kind(did), DefKind::Impl { of_trait: true }) {
            continue;
        }
        let tr = tcx.impl_trait_ref(did).skip_binder().def_id;
        if !is_ffibox_crate(tcx, tr) || tcx.item_name(tr).as_str() != "CCell" {
            continue;
        }
        if let ty::TyKind::Adt(d, _) =
            tcx.type_of(did).instantiate_identity().skip_norm_wip().kind()
        {
            out.cells.insert(d.did());
        }
        for assoc in tcx.associated_items(did).in_definition_order() {
            if tcx.item_name(assoc.def_id).as_str() != "C" {
                continue;
            }
            if let ty::TyKind::Adt(d, _) =
                tcx.type_of(assoc.def_id).instantiate_identity().skip_norm_wip().kind()
            {
                out.cs.insert(d.did());
            }
        }
    }
    out
}

/// What stands between one mention of a type and an owner of it. A
/// `&Vec<Foo>` is a borrow and a std owner at once, so these are flags over
/// the one mention rather than a choice between arms.
#[derive(Clone, Copy, Default)]
struct Shape {
    borrow: bool,
    std_owner: bool,
    slice: bool,
    /// Behind a pointer its holder manages: an ffibox primitive, `NonNull`,
    /// `AtomicPtr`, a raw pointer. The walk CONTINUES through one, so that a
    /// hazard nested below it is seen -- `CBox<Vec<Foo>>` is a vector holding
    /// cells by value, whatever manages the vector -- but a mention that
    /// arrives still carrying the flag is nobody's storage and no borrow, and
    /// is dropped.
    via_ptr: bool,
}

/// What the walk carries into a pointer-like: the flag, and nothing of what
/// stood above it. The INNERMOST qualifier of each class describes a mention,
/// so the arms clear the classes they override -- a `Vec<&Foo>` owns no `Foo`,
/// and a `Vec` inside a `CBox` owns its elements itself.
const VIA_PTR: Shape =
    Shape { borrow: false, std_owner: false, slice: false, via_ptr: true };

/// The std types that hold a `Foo` in storage OF THEIR OWN: a heap allocation
/// (`Box`, `Rc`, `Arc`) or a collection that owns a run of elements. A map and
/// a set own their keys and their values alike, so both arguments take the
/// flag.
///
/// Naming the types rather than the crate is the cost of the rule being
/// mechanical, and `is_std_crate` cannot stand in for it in either direction.
/// The borrow-like and guard-like std types -- `Ref`, `RefMut`, `MutexGuard`
/// -- hold a reference to storage that is somebody else's, and a `Foo`
/// reached through one is a borrow.
///
/// The ones that merely ARE the value are deliberately out: `Option`,
/// `Result`, `Cell`, `Mutex`, `ManuallyDrop`, `MaybeUninit`, a tuple, an
/// array. They allocate nothing and own no run of elements -- the cell sits in
/// the mention's own place, exactly as a bare `Foo` would -- so `by_val`
/// already says everything the share could. Admitting them read 34 mentions
/// on libgit2-bindings, 31 of them `Result<Foo, Error>` returns, and moved
/// `ty.ffibox.wrapper` with them: a share whose figure is a crate's error
/// convention measures nothing.
///
/// `Cow` is out for its own reason: whether it owns is its discriminant's
/// answer and no type rule settles it.
const STD_OWNERS: &[&str] = &[
    "Box", "Rc", "Arc",
    "Vec", "VecDeque", "LinkedList", "BinaryHeap",
    "BTreeMap", "BTreeSet", "HashMap", "HashSet",
];

/// Every ADT `t` mentions, each with the shape it is mentioned in.
///
/// A pointer-like is walked THROUGH, carrying `via_ptr`: `*mut Foo` is
/// `raw_ptr`'s position and not storage holding a cell, but `*mut Vec<Foo>`
/// reaches a vector that holds cells by value, and stopping at the pointer
/// hid it. A fn pointer is not entered at all, its parameters being a
/// callback's interface rather than this position's -- the rule `raw_pointees`
/// follows, for the same reason.
fn walk_shapes<'tcx>(
    tcx: TyCtxt<'tcx>,
    t: Ty<'tcx>,
    at: Shape,
    out: &mut Vec<(DefId, Shape)>,
) {
    match t.kind() {
        ty::TyKind::Ref(_, inner, _) => {
            let at = Shape { borrow: true, std_owner: false, via_ptr: false, ..at };
            walk_shapes(tcx, *inner, at, out);
        }
        ty::TyKind::RawPtr(inner, _) => walk_shapes(tcx, *inner, VIA_PTR, out),
        ty::TyKind::Slice(e) | ty::TyKind::Array(e, _) => {
            walk_shapes(tcx, *e, Shape { slice: true, ..at }, out);
        }
        ty::TyKind::Tuple(ts) => {
            for a in ts.iter() {
                walk_shapes(tcx, a, at, out);
            }
        }
        // A ZST marker names its parameter without holding one. Gated on the
        // crate like the arm below: a local type that happens to carry the
        // name holds whatever it holds.
        ty::TyKind::Adt(d, _)
            if is_std_crate(tcx, d.did())
                && tcx.item_name(d.did()).as_str() == "PhantomData" => {}
        // `NonNull<Foo>` and `AtomicPtr<Foo>` are raw pointers to the cell,
        // not storage holding one: `c_drop(&self, ptr: NonNull<Commit>)` is
        // ffibox's lifecycle strategy, and `raw_ptr` counts the position.
        ty::TyKind::Adt(d, args)
            if is_std_crate(tcx, d.did())
                && matches!(tcx.item_name(d.did()).as_str(), "NonNull" | "AtomicPtr") =>
        {
            for a in args.types() {
                walk_shapes(tcx, a, VIA_PTR, out);
            }
        }
        // An ffibox primitive holds the cell behind its own pointer and
        // manages it, so the cell inside is not a position the crate chose:
        // `fn to_commit(&self) -> CArc<Commit<'r>>` publishes neither the
        // layout nor inline storage, and `ty.field.ffibox` and `fn.sig`
        // count the delegation already. The rule `in_peel_set` follows, for
        // the same reason.
        //
        // `CVal` goes with them. It IS inline storage, but it is ffibox's,
        // which is the answer to the by-value hazard rather than a case of
        // it.
        ty::TyKind::Adt(d, args) if ffibox_primitive(tcx, d.did()).is_some() => {
            for a in args.types() {
                walk_shapes(tcx, a, VIA_PTR, out);
            }
        }
        ty::TyKind::Adt(d, args) => {
            out.push((d.did(), at));
            let at = if is_std_crate(tcx, d.did())
                && STD_OWNERS.contains(&tcx.item_name(d.did()).as_str())
            {
                Shape { std_owner: true, via_ptr: false, ..at }
            } else {
                at
            };
            for a in args.types() {
                walk_shapes(tcx, a, at, out);
            }
        }
        _ => {}
    }
}

/// One mention of a type in the crate's own declarations.
struct Mention {
    did: DefId,
    shape: Shape,
    /// The mention is a field's type rather than a signature's.
    field: bool,
    /// A consumer of the crate reaches the mention: the fn is exported, or
    /// both the field and the type that declares it are.
    reachable: bool,
    /// The RECEIVER of an inherent `as_ref` / `as_mut`: the handle mint
    /// `define_ctype!` writes, which ffibox's own contract licenses, since a
    /// cell value is Rust-owned inline storage.
    self_in_ref_accessor: bool,
    /// The RECEIVER of a trait impl's method, whose shape the trait fixed
    /// rather than the crate: one declaration dictates it in every impl.
    ///
    /// The receiver only. A trait method's other arguments and its return are
    /// as much a published borrow as any free function's -- `fn deref(&self)
    /// -> &Foo` hands one out, and the trait compelled none of it.
    self_in_trait_impl: bool,
    site: (String, usize),
}

/// Where the crate's declarations mention a `CCell` layout newtype
/// (`ty.ffibox.wrapper`), the raw C type it covers (`ty.ffibox.ffi`), or hold
/// it by value (`ty.ffibox.by_val`). They sit under `ty.ffibox` with
/// `ty.ffibox.ccell`, since every one of them reads ffibox's convention and
/// none is emitted without the flag.
///
/// MENTIONS, not types. One cell is named in many places and it is the places
/// that are actionable, so a cell named in twenty signatures counts twenty
/// times and `--sites` lists them. The alternative, a type population, washes
/// the signal out: nearly every cell has an `as_ref`, so `in_ref_accessor`
/// would cover nearly the whole `borrow` population and the mentions that are
/// NOT sanctioned -- the ones worth reading -- would not be recoverable by
/// subtracting it.
///
/// `by_val` is the cell held as a value: nothing above the mention is a
/// reference, so the bytes are Rust-owned storage that moves with whatever
/// holds it. A C pointer retained into it dangles, and no owner runs the C
/// destructor -- the cases ffibox's `CBox` and `CVal` exist for.
fn count_cell_mentions(tcx: TyCtxt<'_>, ptr: &mut PtrTally, sites: &mut Sites) {
    let types = cell_types(tcx);
    if types.cells.is_empty() {
        return;
    }
    let evis = tcx.effective_visibilities(());
    let mut mentions: Vec<Mention> = Vec::new();

    for ld in tcx.hir_crate_items(()).definitions() {
        let did = ld.to_def_id();
        if !matches!(tcx.def_kind(did), DefKind::Struct | DefKind::Union)
            || in_generated_file(tcx, tcx.def_span(did))
        {
            continue;
        }
        let exported = did.as_local().is_some_and(|l| evis.is_exported(l));
        for f in tcx.adt_def(did).all_fields() {
            let ft = tcx.type_of(f.did).instantiate_identity().skip_norm_wip();
            let mut found = Vec::new();
            walk_shapes(tcx, ft, Shape::default(), &mut found);
            let reachable =
                exported && f.did.as_local().is_some_and(|l| evis.is_exported(l));
            let site = counter_site(tcx, tcx.def_span(f.did));
            for (did, shape) in found {
                mentions.push(Mention {
                    did,
                    shape,
                    field: true,
                    reachable,
                    self_in_ref_accessor: false,
                    self_in_trait_impl: false,
                    site: site.clone(),
                });
            }
        }
    }

    // Signatures, over the same population `fn.*` counts: a foreign
    // declaration has no body, so it never reaches `hir_body_owners`, and the
    // C declarations in a `-sys` crate are not this crate's choices.
    for owner in tcx.hir_body_owners() {
        let did = owner.to_def_id();
        if !matches!(tcx.def_kind(did), DefKind::Fn | DefKind::AssocFn) {
            continue;
        }
        let parent_kind = tcx.opt_parent(did).map(|p| tcx.def_kind(p));
        let trait_impl = matches!(parent_kind, Some(DefKind::Impl { of_trait: true }));
        // An `as_ref` / `as_mut` in an INHERENT impl, by name: a conversion
        // the convention did not name, such as an `as_c_ptr`, stays in the
        // remainder, which is the point of the share.
        let accessor = matches!(parent_kind, Some(DefKind::Impl { of_trait: false }))
            && tcx
                .opt_item_name(did)
                .is_some_and(|n| matches!(n.as_str(), "as_ref" | "as_mut"));
        // `self`, not input 0. A free-standing `fn as_ref(w: &Foo)` is a
        // borrow the author chose and no contract licenses, and only the
        // receiver's shape is a trait's doing.
        let has_self = matches!(parent_kind, Some(DefKind::Impl { .. }))
            && tcx.associated_item(did).is_method();
        let reachable = did.as_local().is_some_and(|l| evis.is_exported(l));
        let site = counter_site(tcx, tcx.def_span(did));
        let sig = tcx.fn_sig(did).skip_binder().skip_binder();
        let mut positions: Vec<Ty<'_>> = sig.inputs().to_vec();
        positions.push(sig.output());
        for (i, t) in positions.iter().enumerate() {
            let mut found = Vec::new();
            walk_shapes(tcx, *t, Shape::default(), &mut found);
            for (did, shape) in found {
                mentions.push(Mention {
                    did,
                    shape,
                    field: false,
                    reachable,
                    self_in_ref_accessor: has_self && accessor && i == 0,
                    self_in_trait_impl: has_self && trait_impl && i == 0,
                    site: site.clone(),
                });
            }
        }
    }

    for m in &mentions {
        // Behind a pointer its holder manages, with nothing below it claiming
        // the storage or publishing a borrow: not a mention of this crate's.
        // The walk went through the pointer for the nested cases, and any of
        // them clears the flag.
        if m.shape.via_ptr {
            continue;
        }
        let tree = if types.cells.contains(&m.did) {
            "wrapper"
        } else if types.cs.contains(&m.did) {
            "ffi"
        } else {
            continue;
        };
        let vis = if m.reachable { "pub" } else { "priv" };
        let mut bump = |k: String| {
            *ptr.entry(k.clone()).or_default() += 1;
            sites.add(k, m.site.clone());
        };
        // Shares, not a partition: a mention is several of these at once, and
        // `field` cuts across the other three.
        let arms = [
            (m.shape.borrow, "borrow"),
            (m.shape.std_owner, "std_owner"),
            (m.shape.slice, "slice"),
            (m.field, "field"),
        ];
        if arms.iter().any(|(yes, _)| *yes) {
            bump(format!("ty.ffibox.{tree}.{vis}"));
            for (yes, name) in arms {
                if yes {
                    bump(format!("ty.ffibox.{tree}.of_which.{name}.{vis}"));
                }
            }
            // The two sanctioned borrows, so the rest subtracts: the
            // RECEIVER of an accessor and of a trait method stand on the same
            // contract, that nothing hands out a `&Foo` over C-owned memory.
            // Which is what the unsanctioned mentions would do, so the
            // counter audits the premise its own shares rest on.
            if m.shape.borrow {
                for (yes, name) in [
                    (m.self_in_ref_accessor, "self_in_ref_accessor"),
                    (m.self_in_trait_impl, "self_in_trait_impl"),
                ] {
                    if yes {
                        bump(format!("ty.ffibox.{tree}.of_which.borrow.of_which.{name}.{vis}"));
                    }
                }
            }
        }
        if tree == "wrapper" && !m.shape.borrow {
            bump(format!("ty.ffibox.by_val.{vis}"));
            // `field` and `fn_sig` partition these; `std_owner` cuts across
            // both, so all three are shares.
            for (yes, name) in
                [(m.field, "field"), (!m.field, "fn_sig"), (m.shape.std_owner, "std_owner")]
            {
                if yes {
                    bump(format!("ty.ffibox.by_val.of_which.{name}.{vis}"));
                }
            }
        }
    }
}

struct MetricsCallbacks;

impl Callbacks for MetricsCallbacks {
    fn after_analysis(
        &mut self,
        _compiler: &rustc_interface::interface::Compiler,
        tcx: TyCtxt<'_>,
    ) -> Compilation {
        let krate = tcx.crate_name(rustc_span::def_id::LOCAL_CRATE);
        // Under cargo, only emit for workspace primary packages (skips deps and
        // build scripts); standalone (run.sh) always emits.
        let under_cargo = std::env::var_os("CARGO").is_some();
        let primary = std::env::var_os("CARGO_PRIMARY_PACKAGE").is_some();
        if under_cargo && (!primary || krate.as_str() == "build_script_build") {
            return Compilation::Continue;
        }
        let mut c = Counts::default();
        let mut ptr: PtrTally = PtrTally::new();
        // A test build emits only `code.tests.*`, which `tests_into_tree`
        // builds fresh, so the registry would be wiped: it belongs to the
        // document the library's emission makes.
        if !is_test_build() {
            register_counters(&mut ptr);
        }
        let mut sites = Sites::default();
        // Every body owner (fn, closure, const/static initializer, ...). Each is
        // a separate typeck context; intravisit does not descend into nested
        // bodies, so visiting every owner covers the whole crate exactly once.
        // Declaration-shaped metrics need their own pass: `hir_body_owners()`
        // yields only fns, closures and initializers, so a struct / impl /
        // trait never reaches it.
        // The types that store a raw pointer, by what they declare about it.
        let facts = ptr_holder_traits(tcx);
        for ld in tcx.hir_crate_items(()).definitions() {
            let did = ld.to_def_id();
            if matches!(tcx.def_kind(did), DefKind::Struct | DefKind::Union | DefKind::Enum)
                && !in_generated_file(tcx, tcx.def_span(did))
            {
                let vis = if did.as_local()
                    .is_some_and(|l| tcx.effective_visibilities(()).is_exported(l))
                { "pub" } else { "priv" };
                tree_bump(&mut ptr, &mut sites, tcx, did, &format!("ty.total.{vis}"));
                // `UnsafeCell` is the one way to hold a value C may write
                // while Rust holds a shared reference to it.
                if holds_unsafe_cell(tcx, did) {
                    tree_bump(&mut ptr, &mut sites, tcx, did,
                              &format!("ty.wrapping_unsafe_cell.{vis}"));
                }
                // What vocabulary the type speaks, as shares of every type
                // the crate declares. These are the DENOMINATORS the
                // `ty.storing_raw_ptr` shares were missing: that family says
                // 29 of the pointer holders implement a std trait, and this
                // says 317 types do, so the two read as a rate.
                //
                // Shares, not a partition: a type may implement std's `Drop`,
                // ffibox's `CDrop` and one of the crate's own traits. `none`
                // is the residual, a type with no trait impl at all.
                //
                // The cross-tabulation is NOT repeated here.
                // `ty.storing_raw_ptr.of_which` already holds it from the
                // other side, and finer -- `impl_drop` against `impl_clone`
                // against `impl_send_sync`, which one `std` arm would
                // collapse.
                {
                    let f = facts.get(&did).copied().unwrap_or_default();
                    let whose = [
                        (f.std_trait, "std"),
                        (f.local_trait, "local"),
                        (is_ffibox() && f.ffibox_trait, "ffibox"),
                    ];
                    for (yes, name) in whose {
                        if yes {
                            tree_bump(&mut ptr, &mut sites, tcx, did,
                                      &format!("ty.total.of_which.{name}_trait.{vis}"));
                        }
                    }
                    if !whose.iter().any(|(yes, _)| *yes) {
                        tree_bump(&mut ptr, &mut sites, tcx, did,
                                  &format!("ty.total.of_which.no_trait.{vis}"));
                    }
                }
                // Generic types, by the kind of parameter. A lifetime ties the
                // type to something it borrows; a type parameter makes it a
                // family rather than one layout, so every instantiation is a
                // separate question about C's bytes. A type can carry both,
                // hence shares.
                {
                    let g = tcx.generics_of(did);
                    let lifetimes = g.own_params.iter().any(|p| {
                        matches!(p.kind, ty::GenericParamDefKind::Lifetime)
                    });
                    let types = g.own_params.iter().any(|p| {
                        matches!(p.kind, ty::GenericParamDefKind::Type { .. })
                    });
                    if lifetimes || types {
                        tree_bump(&mut ptr, &mut sites, tcx, did,
                                  &format!("ty.generic.{vis}"));
                        for (yes, name) in [(lifetimes, "lifetime"), (types, "type")] {
                            if yes {
                                tree_bump(&mut ptr, &mut sites, tcx, did,
                                          &format!("ty.generic.of_which.{name}.{vis}"));
                            }
                        }
                        if holds_raw_ptr(tcx, did) {
                            tree_bump(&mut ptr, &mut sites, tcx, did,
                                      &format!("ty.generic.of_which.storing_raw_ptr.{vis}"));
                        }
                    }
                }
                // The ffibox primitives the type's fields hold: the
                // population `ty.storing_raw_ptr` gives up by not peeling
                // into ffibox. A type can be in both, which is partial
                // delegation.
                if is_ffibox() {
                    let f = facts.get(&did).copied().unwrap_or_default();
                    if f.ffibox_shape == Some("layout") {
                        tree_bump(&mut ptr, &mut sites, tcx, did,
                                  &format!("ty.ffibox.ccell.{vis}"));
                        if f.cell_no_seam {
                            tree_bump(&mut ptr, &mut sites, tcx, did, &format!(
                                "ty.ffibox.ccell.of_which.no_seam_trait.{vis}"));
                        }
                    }
                    for f in tcx.adt_def(did).all_fields() {
                        let ft = tcx.type_of(f.did).instantiate_identity().skip_norm_wip();
                        if let Some(d) = field_adt(tcx, ft) {
                            if let Some((name, _)) = ffibox_primitive(tcx, d.did()) {
                                tree_bump(&mut ptr, &mut sites, tcx, did,
                                          &format!("ty.field.ffibox.{name}.{vis}"));
                            }
                        }
                    }
                }
            }
            if matches!(tcx.def_kind(did), DefKind::Struct | DefKind::Union | DefKind::Enum)
                && !in_generated_file(tcx, tcx.def_span(did))
                && holds_raw_ptr(tcx, did)
            {
                let vis = if did.as_local()
                    .is_some_and(|l| tcx.effective_visibilities(()).is_exported(l))
                { "pub" } else { "priv" };
                let site = counter_site(tcx, tcx.def_span(did));
                let mut bump = |k: String| {
                    *ptr.entry(k.clone()).or_default() += 1;
                    sites.add(k, site.clone());
                };
                bump(format!("ty.storing_raw_ptr.{vis}"));

                let t = facts.get(&did).copied().unwrap_or_default();
                // A declared lifetime parameter is how a borrow is tied to its
                // parent -- git2-rs's `Commit<'repo>` with
                // `PhantomData<Object<'repo>>`.
                let has_lifetime = tcx.generics_of(did).own_params.iter()
                    .any(|g| matches!(g.kind, ty::GenericParamDefKind::Lifetime));
                // A public field that reaches the pointer: a consumer can take
                // it without going through any of the crate's own code, so the
                // type's declarations do not govern the access.
                let pub_field = tcx.adt_def(did).all_fields().any(|f| {
                    f.vis.is_public() && {
                        let ft = tcx.type_of(f.did).instantiate_identity().skip_norm_wip();
                        let mut ps = Vec::new();
                        raw_pointees(tcx, ft, &mut ps);
                        !ps.is_empty()
                            || field_adt(tcx, ft).is_some_and(|d| {
                                in_peel_set(tcx, d.did()) && holds_raw_ptr(tcx, d.did())
                            })
                    }
                });

                // The declaration shares. The first six read std traits, so
                // a crate that declares its lifecycle through a framework
                // instead -- ffibox's `CDrop`, `CDispose`, `CDupClone` -- said
                // something that none of them can see. `ffibox` is that
                // statement, counted beside them so the residual below means
                // what it says.
                let shares = [
                    (t.drop_, "impl_drop"),
                    (t.clone, "impl_clone"),
                    (has_lifetime, "has_lifetime"),
                    (t.deref, "impl_deref"),
                    (t.deref_mut, "impl_deref_mut"),
                    (t.send_sync, "impl_send_sync"),
                    (is_ffibox() && implements_ffibox_trait(tcx, did), "ffibox"),
                    (pub_field, "pub_field"),
                ];
                for (yes, name) in shares {
                    if yes {
                        bump(format!("ty.storing_raw_ptr.of_which.{name}.{vis}"));
                    }
                }
                // `none` is the residual: the type stores a pointer and
                // declares nothing about it, in any vocabulary. `pub_field` is
                // not a declaration, so it does not rescue a type from the
                // residual -- it is the opposite, an access the type does not
                // govern.
                if !shares[..7].iter().any(|(yes, _)| *yes) {
                    bump(format!("ty.storing_raw_ptr.of_which.none.{vis}"));
                }
            }
            if matches!(tcx.def_kind(did), DefKind::Struct | DefKind::Union) {
                count_ptr_fields(tcx, did, &mut ptr, &mut sites);
            }
            match tcx.def_kind(did) {
                // An inherent `impl T`: the crate's own API on its own type,
                // as opposed to satisfying someone's trait. Under `--ffibox`
                // the self type's role in the convention says which surface
                // the block is -- the layout type's own API, or one of its
                // handles'.
                DefKind::Impl { of_trait: false } => {
                    let self_vis = impl_self_vis(tcx, did);
                    tree_bump(&mut ptr, &mut sites, tcx, did,
                              &format!("ty.impl_block.{self_vis}"));
                    let self_adt = match tcx
                        .type_of(did)
                        .instantiate_identity()
                        .skip_norm_wip()
                        .kind()
                    {
                        ty::TyKind::Adt(d, _) => Some(d.did()),
                        _ => None,
                    };
                    let shape = self_adt
                        .and_then(|d| facts.get(&d))
                        .and_then(|f| f.ffibox_shape);
                    let arm = match shape {
                        Some(shape) if is_ffibox() => format!("ffibox.{shape}"),
                        _ => "other".to_string(),
                    };
                    tree_bump(&mut ptr, &mut sites, tcx, did,
                              &format!("ty.impl_block.of_which.{arm}.{self_vis}"));
                }
                DefKind::Impl { of_trait: true } => {
                    let tr_did = tcx.impl_trait_ref(did).skip_binder().def_id;
                    let self_vis = impl_self_vis(tcx, did);
                    tree_bump(&mut ptr, &mut sites, tcx, did,
                              &format!("ty.impl_trait.{self_vis}"));
                    // Whose trait it is. A local one the crate declared is a
                    // shape it chose; a std or framework one it adopted.
                    let whose = if is_std_crate(tcx, tr_did) {
                        Some("std")
                    } else if tr_did.is_local() {
                        Some("local")
                    } else if is_ffibox() && is_ffibox_crate(tcx, tr_did) {
                        Some("ffibox")
                    } else {
                        None
                    };
                    if let Some(whose) = whose {
                        tree_bump(&mut ptr, &mut sites, tcx, did,
                                  &format!("ty.impl_trait.of_which.{whose}.{self_vis}"));
                    }
                    // Of those, the ones a `#[derive]` wrote. Nobody typed
                    // them, and on these crates they are most of the `std`
                    // arm, so a reader comparing vocabularies without this
                    // share is reading how many derives each crate spells.
                    if tcx.is_automatically_derived(did) {
                        tree_bump(&mut ptr, &mut sites, tcx, did,
                                  &format!("ty.impl_trait.of_which.derived.{self_vis}"));
                    }
                    // `TrivialClone` is a compiler-internal marker that
                    // `#[derive(Clone)]` emits as an `unsafe impl`. It asserts
                    // nothing the author wrote, and on libgit2-bindings it is
                    // 206 of 477, so counting it would make the counter mostly
                    // derive expansions.
                    if tcx.item_name(tr_did).as_str() != "TrivialClone"
                        && tcx.impl_trait_header(did).safety.is_unsafe()
                    {
                        tree_bump(&mut ptr, &mut sites, tcx, did,
                                  "ty.impl_trait.of_which.unsafe");
                    }
                    // `unsafe impl Send` / `Sync` on any type, the crate-wide
                    // claim that memory it reaches is thread-safe.
                    if tcx.crate_name(tr_did.krate).as_str() == "core"
                        && tcx.impl_trait_header(did).safety.is_unsafe()
                    {
                        if let n @ ("Send" | "Sync") = tcx.item_name(tr_did).as_str() {
                            let n = n.to_lowercase();
                            tree_bump(&mut ptr, &mut sites, tcx, did,
                                      &format!("ty.impl_trait.of_which.send_sync.{n}.{self_vis}"));
                        }
                    }
                    // ffibox's vocabulary, split by whether the impl was
                    // generated. ffibox ships `define_ctype!` and the
                    // `impl_c*!` family, so an impl either carries expansion
                    // context or was typed out.
                    if is_ffibox() && is_ffibox_crate(tcx, tr_did) {
                        let n = tcx.item_name(tr_did);
                        if FFIBOX_TRAITS.iter().any(|(t, _)| *t == n.as_str()) {
                            let how = if from_ffibox_macro(tcx, tcx.def_span(did)) {
                                "macro"
                            } else {
                                "handwritten"
                            };
                            tree_bump(&mut ptr, &mut sites, tcx, did,
                                      &format!("ty.impl_trait.of_which.ffibox.of_which.{n}.{how}"));
                        }
                    }
                }
                _ => {}
            }
        }

        if is_ffibox() {
            count_cell_mentions(tcx, &mut ptr, &mut sites);
        }

        for owner in tcx.hir_body_owners() {
            let did = owner.to_def_id();
            let in_ffi = in_ffi_export(tcx, did);
            let exported = did.as_local().is_some_and(|l| tcx.effective_visibilities(()).is_exported(l));
            let blocks_before = c.unsafe_blocks;
            {
                let typeck = tcx.typeck(owner);
                let body = tcx.hir_body_owned_by(owner);
                let mut v = BodyVisitor {
                    ptr: &mut ptr,
                    tcx,
                    typeck,
                    depth: 0,
                    in_ffi,
                    c: &mut c,
                    sites: &mut sites,
                };
                v.visit_body(body);
            }
            let body_had_unsafe = c.unsafe_blocks > blocks_before;
            // Signature analysis (fns only).
            if matches!(tcx.def_kind(did), DefKind::Fn | DefKind::AssocFn) {
                let sig = tcx.fn_sig(did).skip_binder().skip_binder();
                let safe = !sig.safety().is_unsafe();
                // Every fn the crate defines, the methods of its trait impls
                // included. A method implementing another crate's trait is
                // still this crate's code: that crate fixed the signature's
                // shape, not what the body does, and `impl Drop for Foo` is
                // where a wrapper's unsafe free lives. A foreign DECLARATION
                // is excluded already, by having no body to walk.
                //
                // Counting them makes the family sensitive to boilerplate a
                // macro wrote -- `#[derive]`, `bitflags!`, ffibox's
                // `define_ctype!` -- which on these crates is the larger part
                // of it. That is not a reason to drop them: what a macro
                // emitted is compiled into this crate and runs like a
                // hand-written method, the grounds the unsafe-block metrics
                // already stand on. It is a reason to say which is which, so
                // `fn.total.of_which.macro` carries the share and a reader
                // after the hand-written total subtracts it.
                {
                    let vis = if exported { "pub" } else { "priv" };
                    let safety = if safe { "safe" } else { "unsafe" };
                    let site = counter_site(tcx, tcx.def_span(did));
                    let bump = |ptr: &mut PtrTally, sites: &mut Sites, k: String| {
                        *ptr.entry(k.clone()).or_default() += 1;
                        sites.add(k, site.clone());
                    };
                    bump(&mut ptr, &mut sites, format!("fn.{safety}.{vis}"));
                    // The denominator, emitted rather than derived: the tree's
                    // derived totals are scalars, and this one has to carry
                    // the same {pub,priv} split as its numerators for
                    // `fn.safe.pub / fn.total.pub` to be a ratio at all.
                    bump(&mut ptr, &mut sites, format!("fn.total.{vis}"));
                    if tcx.def_span(did).from_expansion() {
                        bump(&mut ptr, &mut sites,
                             format!("fn.total.of_which.macro.{vis}"));
                    }
                    // Counted on the safe arm only. With
                    // `unsafe_op_in_unsafe_fn` denied every `unsafe fn` doing
                    // anything raw has a block by construction, so counting
                    // it there would measure the lint, not the code.
                    if safe && body_had_unsafe {
                        bump(&mut ptr, &mut sites,
                             format!("fn.safe.of_which.with_unsafe.{vis}"));
                    }

                    // Raw pointers the signature takes and returns, split
                    // from the `*c_void` ones, with the seam share carrying
                    // the same safety and visibility so it can be subtracted.
                    //
                    // Only bare and std pointers: a struct that happens to
                    // embed one is not pointer work for the caller, who never
                    // touches it.
                    //
                    // Taking is the hazard. A safe fn that TAKES a raw
                    // pointer lets a caller pass anything with no `unsafe` at
                    // the call site; one that RETURNS a raw pointer still
                    // forces the caller to write `unsafe` before it means
                    // anything.
                    //
                    // A position in a trait impl's method goes to
                    // `fn_sig_trait_impl`
                    // instead, both directions in one counter. The crate did
                    // not choose to put a raw pointer there: the trait fixed
                    // the signature, one declaration dictating the position in
                    // every impl of it, and no consumer of the safe API is
                    // routed to it -- ffibox's `CDrop::c_drop(NonNull<T>)` is
                    // the strategy that exists so that a consumer never holds
                    // a pointer. Mixing those into `fn_sig_arg` makes the hazard
                    // count move with how many types a lifecycle trait is
                    // implemented for. The direction is dropped because it
                    // says nothing once the signature is not the crate's:
                    // what is left is "the trait's shape reaches a pointer
                    // here".
                    let seam = is_seam_fn(tcx, did);
                    // The trait whose declaration fixed the signature, when
                    // the method is in a trait impl: whose vocabulary it is
                    // decides which share below the position joins.
                    let impl_trait = tcx.opt_parent(did).and_then(|parent| {
                        matches!(tcx.def_kind(parent), DefKind::Impl { of_trait: true })
                            .then(|| tcx.impl_trait_ref(parent).skip_binder().def_id)
                    });
                    let in_trait_impl = impl_trait.is_some();
                    // The same three arms as `ty.impl_trait.of_which`, read
                    // the same way: a std trait the crate adopted, one it
                    // declared itself, or the ffibox convention's. A trait
                    // from a fourth crate joins none of them, as there.
                    let whose = impl_trait.and_then(|tr| {
                        if is_std_crate(tcx, tr) {
                            Some("std")
                        } else if tr.is_local() {
                            Some("local")
                        } else if is_ffibox() && is_ffibox_crate(tcx, tr) {
                            Some("ffibox")
                        } else {
                            None
                        }
                    });
                    // Which of ffibox's traits, named from the vocabulary so
                    // the breakdown is a closed set the registry can carry.
                    // A trait ffibox adds and this list does not have is in
                    // the `ffibox` arm and in no per-trait leaf, exactly as
                    // in `ty.impl_trait.of_which.ffibox`.
                    let ffibox_trait = impl_trait
                        .filter(|_| is_ffibox())
                        .and_then(|tr| {
                            let n = tcx.item_name(tr);
                            FFIBOX_TRAITS
                                .iter()
                                .find(|(t, _)| *t == n.as_str())
                                .map(|(t, _)| *t)
                        });
                    let mut ins = Vec::new();
                    for t in sig.inputs() {
                        raw_pointees(tcx, *t, &mut ins);
                    }
                    let mut outs = Vec::new();
                    raw_pointees(tcx, sig.output(), &mut outs);
                    for (found, pos) in [(ins, "fn_sig_arg"), (outs, "fn_sig_ret")] {
                        let pos = if in_trait_impl { "fn_sig_trait_impl" } else { pos };
                        for pointee in found {
                            bump(&mut ptr, &mut sites,
                                 format!("raw_ptr.{pos}.{safety}.{vis}"));
                            // The denominator, emitted rather than derived:
                            // the positions the crate CHOSE, so
                            // `fn_sig_trait_impl` is
                            // outside it for the reason it exists -- a trait
                            // fixed those, and a reader comparing crates would
                            // be reading how often a trait is implemented.
                            if !in_trait_impl {
                                bump(&mut ptr, &mut sites,
                                     format!("raw_ptr.total.{safety}.{vis}"));
                            }
                            if seam {
                                bump(&mut ptr, &mut sites,
                                     format!("raw_ptr.{pos}.of_which.seam.{safety}.{vis}"));
                            }
                            // A `*c_void` is a raw pointer with its pointee
                            // erased, so it is a SHARE of the position rather
                            // than a family beside it: a reader asking how
                            // many raw pointers a signature carries should not
                            // have to add two trees, and one asking how many
                            // of them are typed subtracts this.
                            if is_c_void(tcx, pointee) {
                                bump(&mut ptr, &mut sites,
                                     format!("raw_ptr.{pos}.of_which.void.{safety}.{vis}"));
                            }
                            // Whose trait put the pointer there. Only on
                            // `fn_sig_trait_impl`: the other two positions are
                            // the crate's own by construction, so the arm
                            // would say nothing. It is what makes the family
                            // readable without `--sites` -- on
                            // libgit2-bindings every one of its positions is
                            // an ffibox lifecycle policy, and on git2-rs they
                            // are a local `Binding` trait's, which the bare
                            // figure cannot tell apart.
                            if in_trait_impl {
                                if let Some(whose) = whose {
                                    bump(&mut ptr, &mut sites,
                                         format!("raw_ptr.{pos}.of_which.{whose}.{safety}.{vis}"));
                                }
                                // The per-trait leaf carries no safety or
                                // visibility split: a trait method's are the
                                // trait declaration's, one spelling dictating
                                // every impl, so splitting them would only
                                // restate the parent.
                                if let Some(t) = ffibox_trait {
                                    bump(&mut ptr, &mut sites,
                                         format!("raw_ptr.{pos}.of_which.ffibox.of_which.{t}"));
                                }
                            }
                        }
                    }

                    // The ffibox primitives the signature carries: whether
                    // the vocabulary actually crosses the interface.
                    //
                    // A share of the signature rather than a family beside
                    // the safe/unsafe partition, and `arg` and `ret` are
                    // `raw_ptr.fn_sig_arg` and `fn_sig_ret`'s positions under
                    // their short names: one vocabulary for where a type
                    // sits in a signature, whether the type is a raw pointer
                    // or the primitive that replaced one. These are MENTIONS,
                    // so a fn taking two `CBox` bumps twice and the record is
                    // not a share of `fn.total`.
                    if is_ffibox() {
                        for (ts, pos) in [
                            (sig.inputs().to_vec(), "arg"),
                            (vec![sig.output()], "ret"),
                        ] {
                            for t in ts {
                                if let ty::TyKind::Adt(d, _) = t.kind() {
                                    if let Some((name, _)) = ffibox_primitive(tcx, d.did()) {
                                        bump(&mut ptr, &mut sites,
                                             format!("fn.sig.of_which.ffibox.{pos}.{name}.{vis}"));
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        // Crate-wide code LoC — the denominator. Built from the COMPILED crate
        // (the union of HIR definition spans), not from the raw file text.
        //
        // Reading the text counted every line physically present, including
        // items `cfg` removed before HIR: an inline `#[cfg(test)] mod tests`
        // put its lines in the denominator while its bodies — never compiled
        // under `cargo build` — could reach no numerator, so the unsafe ratio
        // read low in proportion to test coverage. A definition that did not
        // survive `cfg` has no `DefId`, so unioning def spans excludes it by
        // construction, and generalises to every `#[cfg(..)]`-disabled item
        // (feature gates, platform gates) rather than special-casing `test`.
        //
        // Two details make the union tight:
        //  * `source_callsite()` maps a macro-expanded def back to its
        //    invocation, so generated items are charged to the `define_ctype!`
        //    line that produced them rather than to ffibox's source.
        //  * CONTAINERS (`mod` / `impl` / `trait` / `extern` blocks) contribute
        //    only their opening and closing lines, never their full span: a
        //    container's span still covers the text of items `cfg` stripped out
        //    of it (the crate-root module's span is the whole file), so
        //    unioning it whole would reinstate exactly what this is removing.
        //    Their members are separate definitions and bring their own bodies.
        //  * BODIES are unioned separately, because `def_span` on a fn is its
        //    SIGNATURE span, not the item's. Definitions alone counted headers
        //    and no statements -- 4208 lines where git2's source has 20990,
        //    which read as an 83% unsafe ratio.
        //
        // The line set is per file and deduplicated, so items sharing a line
        // (or several defs from one macro invocation) count it once. The
        // blank / `//`-comment filter is the same one `unsafe_block_code_lines`
        // applies, so numerator and denominator stay apples-to-apples.
        {
            let sm = tcx.sess.source_map();
            // file (keyed by its source-map start offset) -> covered 1-based lines
            let mut covered: HashMap<u32, HashSet<usize>> = HashMap::new();
            for ld in tcx.hir_crate_items(()).definitions() {
                let did = ld.to_def_id();
                let container = matches!(
                    tcx.def_kind(did),
                    DefKind::Mod | DefKind::Impl { .. } | DefKind::Trait | DefKind::ForeignMod
                );
                let sp = tcx.def_span(did).source_callsite();
                let lo = sm.lookup_char_pos(sp.lo());
                let hi = sm.lookup_char_pos(sp.hi());
                // Local crate only (imported files carry `src == None`), and
                // skip the pathological span that straddles two files.
                if lo.file.src.is_none() || lo.file.start_pos != hi.file.start_pos {
                    continue;
                }
                let e = covered.entry(lo.file.start_pos.0).or_default();
                if container {
                    e.insert(lo.line);
                    e.insert(hi.line);
                } else {
                    e.extend(lo.line..=hi.line);
                }
            }
            // Bodies: fn / const / static initializers and closures. Same
            // `cfg` guarantee -- a stripped item owns no body -- and the same
            // dedup, so a body overlapping its own signature line counts once.
            for owner in tcx.hir_body_owners() {
                let sp = tcx.hir_body_owned_by(owner).value.span.source_callsite();
                let lo = sm.lookup_char_pos(sp.lo());
                let hi = sm.lookup_char_pos(sp.hi());
                if lo.file.src.is_none() || lo.file.start_pos != hi.file.start_pos {
                    continue;
                }
                covered
                    .entry(lo.file.start_pos.0)
                    .or_default()
                    .extend(lo.line..=hi.line);
            }
            for sf in sm.files().iter() {
                let (Some(src), Some(set)) = (&sf.src, covered.get(&sf.start_pos.0)) else {
                    continue;
                };
                c.code_lines += src
                    .lines()
                    .enumerate()
                    .filter(|(i, l)| {
                        let t = l.trim();
                        set.contains(&(i + 1)) && !t.is_empty() && !t.starts_with("//")
                    })
                    .count() as u64;
            }
        }
        println!(
            "{{\"crate\":\"{}\",\"test\":{},\"counts\":{},\"sites\":{}}}",
            krate,
            is_test_build(),
            ptr_json(if is_test_build() {
                let fns = *ptr.get("fn.total.pub").unwrap_or(&0)
                    + *ptr.get("fn.total.priv").unwrap_or(&0);
                tests_into_tree(&mut ptr, &c, fns)
            } else {
                mirror_into_tree(&mut ptr, &c)
            }),
            sites.json()
        );
        Compilation::Continue
    }
}

fn main() {
    let mut args: Vec<String> = std::env::args().collect();
    if !args
        .iter()
        .any(|a| a == "--sysroot" || a.starts_with("--sysroot="))
    {
        // `SYSROOT` env (set to the *nightly* sysroot) wins; else ask rustc.
        let sysroot = std::env::var("SYSROOT").unwrap_or_else(|_| {
            let out = std::process::Command::new("rustc")
                .args(["--print", "sysroot"])
                .output()
                .expect("run rustc --print sysroot");
            String::from_utf8(out.stdout).unwrap().trim().to_string()
        });
        args.push("--sysroot".into());
        args.push(sysroot);
    }
    rustc_driver::compiler_entrypoint(&args, &mut MetricsCallbacks);
}
