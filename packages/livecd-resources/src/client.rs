// SPDX-License-Identifier: MIT
use std::cell::RefCell;
use std::io::{self, Read, Write};
use std::os::fd::{AsRawFd, OwnedFd};
use std::os::unix::process::CommandExt;
use std::os::unix::{fs::PermissionsExt, net::UnixStream};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::Duration;

pub fn directory() -> io::Result<PathBuf> {
    let home = std::env::var_os("HOME").ok_or_else(|| io::Error::other("HOME unset"))?;
    let directory = PathBuf::from(home).join(".cache/livecd-resources/run");
    std::fs::create_dir_all(&directory)?;
    let metadata = std::fs::symlink_metadata(&directory)?;
    use std::os::unix::fs::MetadataExt;
    if !metadata.is_dir() || metadata.uid() != unsafe { libc::getuid() } {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "invalid resource socket directory",
        ));
    }
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))?;
    Ok(directory)
}

pub fn same_uid(stream: &UnixStream) -> io::Result<()> {
    let mut credentials: libc::ucred = unsafe { std::mem::zeroed() };
    let mut size = std::mem::size_of_val(&credentials) as libc::socklen_t;
    if unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            (&mut credentials as *mut libc::ucred).cast(),
            &mut size,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    if credentials.uid != unsafe { libc::getuid() } {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "resource peer has another UID",
        ));
    }
    Ok(())
}

fn connect() -> io::Result<UnixStream> {
    let directory = directory()?;
    let socket = directory.join("socket");
    let result = match UnixStream::connect(&socket) {
        Ok(stream) => stream,
        Err(_) => {
            // Serialize activation. The broker signals readiness over a socket;
            // no timer or retry loop samples resources while waiting for it.
            let lock = std::fs::OpenOptions::new()
                .create(true)
                .truncate(false)
                .write(true)
                .open(directory.join("lock"))?;
            if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX) } != 0 {
                return Err(io::Error::last_os_error());
            }
            match UnixStream::connect(&socket) {
                Ok(stream) => stream,
                Err(_) => {
                    let (mut ready, writer) = UnixStream::pair()?;
                    ready.set_read_timeout(Some(Duration::from_secs(15)))?;
                    let prefix = std::env::var_os("PREFIX")
                        .map(PathBuf::from)
                        .unwrap_or_else(|| PathBuf::from("/data/data/com.termux/files/usr"));
                    let mut child = Command::new(prefix.join("libexec/livecd-resources/broker"))
                        .process_group(0)
                        .env_remove("LD_PRELOAD")
                        .env_remove("LD_LIBRARY_PATH")
                        .stdin(Stdio::null())
                        .stdout(Stdio::from(OwnedFd::from(writer)))
                        .stderr(if std::env::var_os("LIVECD_RESOURCES_DEBUG").is_some() {
                            Stdio::from(
                                std::fs::OpenOptions::new()
                                    .create(true)
                                    .append(true)
                                    .open(directory.join("broker.log"))?,
                            )
                        } else {
                            Stdio::null()
                        })
                        .spawn()?;
                    let mut byte = [0];
                    if let Err(error) = ready.read_exact(&mut byte) {
                        let _ = child.kill();
                        let _ = child.wait();
                        return Err(error);
                    }
                    if byte != [1] {
                        return Err(io::Error::other("resource broker did not start"));
                    }
                    // Reap the detached broker if this client survives its exit.
                    std::thread::spawn(move || {
                        let _ = child.wait();
                    });
                    UnixStream::connect(&socket)?
                }
            }
        }
    };
    same_uid(&result)?;
    result.set_read_timeout(Some(Duration::from_secs(20)))?;
    result.set_write_timeout(Some(Duration::from_secs(2)))?;
    Ok(result)
}

pub fn request(command: &str) -> io::Result<Vec<u8>> {
    if command.len() > 4095 || command.contains(['\n', '\r', '\0']) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid resource command",
        ));
    }
    // A thread-local connection avoids locks inherited from vanished threads
    // after fork. The broker serializes all privileged requests centrally.
    thread_local! { static SESSION: RefCell<(u32, Option<UnixStream>)> = const { RefCell::new((0, None)) }; }
    SESSION.with(|cell| {
        let mut state = cell.borrow_mut();
        let pid = std::process::id();
        if state.0 != pid {
            *state = (pid, None);
        }
        let session = &mut state.1;
        if session.is_none() {
            *session = Some(connect()?);
        }
        let stream = session.as_mut().unwrap();
        let mut remote_error = false;
        let result = (|| {
            stream.write_all(&(command.len() as u32).to_le_bytes())?;
            stream.write_all(command.as_bytes())?;
            let mut header = [0; 8];
            stream.read_exact(&mut header)?;
            let error = i32::from_le_bytes(header[..4].try_into().unwrap());
            let size = u32::from_le_bytes(header[4..].try_into().unwrap()) as usize;
            if size > 8 * 1024 * 1024 {
                return Err(io::Error::other("oversize resource reply"));
            }
            if error != 0 {
                remote_error = true;
                return Err(io::Error::from_raw_os_error(error));
            }
            let mut data = vec![0; size];
            stream.read_exact(&mut data)?;
            Ok(data)
        })();
        if result.is_err() && !remote_error {
            *session = None;
        }
        result
    })
}
