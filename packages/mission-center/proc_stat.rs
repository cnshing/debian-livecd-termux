// SPDX-License-Identifier: MIT
// Mission Center's adapter to the shared native resource backend.
#[cfg(target_os = "android")]
use std::ffi::{c_char, CString};
use std::io;

#[cfg(target_os = "android")]
#[link(name = "livecd_resources")]
unsafe extern "C" {
    fn livecd_resources_snapshot(
        category: *const c_char,
        data: *mut *mut c_char,
        length: *mut usize,
    ) -> libc::c_int;
    fn livecd_resources_free(data: *mut c_char);
}

fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}

pub fn read() -> io::Result<String> {
    if !cfg!(target_os = "android") {
        return std::fs::read_to_string("/proc/stat");
    }
    request("stat")
}

#[cfg(not(target_os = "android"))]
pub fn request(_kind: &str) -> io::Result<String> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "Android resource category on another platform",
    ))
}

#[cfg(target_os = "android")]
pub fn request(kind: &str) -> io::Result<String> {
    let category = CString::new(kind).map_err(|_| invalid("invalid resource category"))?;
    let mut data = std::ptr::null_mut();
    let mut length = 0;
    let error = unsafe { livecd_resources_snapshot(category.as_ptr(), &mut data, &mut length) };
    if error != 0 {
        return Err(io::Error::from_raw_os_error(error));
    }
    let bytes = unsafe { std::slice::from_raw_parts(data.cast::<u8>(), length) };
    let result = std::str::from_utf8(bytes)
        .map(str::to_owned)
        .map_err(|_| invalid("non-UTF8 resource snapshot"));
    unsafe {
        livecd_resources_free(data);
    }
    result
}

pub fn unhex(value: &str) -> io::Result<String> {
    if value.len() % 2 != 0 {
        return Err(invalid("odd hex field length"));
    }
    let bytes: Result<Vec<u8>, _> = value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let digits = std::str::from_utf8(pair).map_err(|_| invalid("invalid hex field"))?;
            u8::from_str_radix(digits, 16).map_err(|_| invalid("invalid hex field"))
        })
        .collect();
    Ok(String::from_utf8_lossy(&bytes?).into_owned())
}

pub fn thermal(snapshot: &str, prefixes: &[&str]) -> Option<f32> {
    snapshot
        .lines()
        .filter_map(|line| {
            let fields: Vec<_> = line.split('\t').collect();
            if fields.len() != 3 || fields[0] != "thermal" {
                return None;
            }
            let name = unhex(fields[1]).ok()?;
            if !prefixes.iter().any(|prefix| name.starts_with(prefix)) {
                return None;
            }
            let celsius = fields[2].trim().parse::<f32>().ok()? / 1000.;
            (celsius.is_finite() && (-40. ..=150.).contains(&celsius)).then_some(celsius)
        })
        .max_by(|a, b| a.total_cmp(b))
}
