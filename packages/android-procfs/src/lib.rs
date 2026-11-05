// SPDX-License-Identifier: MIT
//! Request-driven Android resource snapshots, shared by native clients.
mod client;

use std::ffi::{c_char, CStr};
use std::io;

/// Return an owned, NUL-terminated snapshot and its byte length (excluding NUL).
/// Returns zero on success or an errno value. No previous sample is returned on
/// failure. The caller releases successful results with android_procfs_free.
///
/// # Safety
/// `category` must be a C string; `data` and `length` must be writable pointers.
#[no_mangle]
pub unsafe extern "C" fn android_procfs_snapshot(
    category: *const c_char,
    data: *mut *mut c_char,
    length: *mut usize,
) -> libc::c_int {
    if category.is_null() || data.is_null() || length.is_null() {
        return libc::EINVAL;
    }
    *data = std::ptr::null_mut();
    *length = 0;
    let Ok(category) = CStr::from_ptr(category).to_str() else {
        return libc::EINVAL;
    };
    let result = client::request(category);
    match result {
        Ok(snapshot) => {
            let size = snapshot.len();
            let allocation = libc::malloc(size + 1).cast::<c_char>();
            if allocation.is_null() {
                return libc::ENOMEM;
            }
            std::ptr::copy_nonoverlapping(snapshot.as_ptr(), allocation.cast::<u8>(), size);
            *allocation.add(size) = 0;
            *data = allocation;
            *length = size;
            0
        }
        Err(error) => error.raw_os_error().unwrap_or(match error.kind() {
            io::ErrorKind::TimedOut => libc::ETIMEDOUT,
            io::ErrorKind::NotFound => libc::ENOENT,
            io::ErrorKind::PermissionDenied => libc::EACCES,
            io::ErrorKind::InvalidInput => libc::EINVAL,
            io::ErrorKind::Unsupported => libc::ENOTSUP,
            _ => libc::EIO,
        }),
    }
}

/// # Safety
/// `data` must be NULL or a result of android_procfs_snapshot, freed once.
#[no_mangle]
pub unsafe extern "C" fn android_procfs_free(data: *mut c_char) {
    libc::free(data.cast());
}
