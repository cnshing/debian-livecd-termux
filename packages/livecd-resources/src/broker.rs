// SPDX-License-Identifier: MIT
#[allow(dead_code)]
mod client;
#[allow(dead_code)]
mod source;
use std::io::{self, Read, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::{Arc, Mutex};

fn serve(mut stream: UnixStream, clients: Arc<Mutex<usize>>) -> io::Result<()> {
    let result = (|| loop {
        let mut size = [0; 4];
        stream.read_exact(&mut size)?;
        let size = u32::from_le_bytes(size) as usize;
        if size > 4095 {
            return Err(io::Error::other("oversize request"));
        }
        let mut command = vec![0; size];
        stream.read_exact(&mut command)?;
        let command = std::str::from_utf8(&command).map_err(io::Error::other)?;
        let result = source::request_bytes(command);
        let (error, data) = match result {
            Ok(data) => (0i32, data),
            Err(error) => {
                if std::env::var_os("LIVECD_RESOURCES_DEBUG").is_some() {
                    eprintln!("resources {command}: {error}");
                }
                (
                    error.raw_os_error().unwrap_or(match error.kind() {
                        io::ErrorKind::TimedOut => libc::ETIMEDOUT,
                        io::ErrorKind::NotFound => libc::ENOENT,
                        _ => libc::EIO,
                    }),
                    Vec::new(),
                )
            }
        };
        stream.write_all(&error.to_le_bytes())?;
        stream.write_all(&(data.len() as u32).to_le_bytes())?;
        stream.write_all(&data)?;
    })();
    let mut count = clients.lock().unwrap();
    *count -= 1;
    if *count == 0 {
        source::disconnect();
    }
    result
}

fn main() -> io::Result<()> {
    let directory = client::directory()?;
    // Activation is serialized by the client lock, held through READY.
    let socket = directory.join("socket");
    if UnixStream::connect(&socket).is_ok() {
        return Err(io::Error::other("broker already running"));
    }
    let _ = std::fs::remove_file(&socket);
    let listener = UnixListener::bind(&socket)?;
    io::stdout().write_all(&[1])?;
    io::stdout().flush()?;
    let clients = Arc::new(Mutex::new(0usize));
    for stream in listener.incoming() {
        let stream = stream?;
        if client::same_uid(&stream).is_err() {
            continue;
        }
        *clients.lock().unwrap() += 1;
        let clients = Arc::clone(&clients);
        std::thread::spawn(move || {
            let _ = serve(stream, clients);
        });
    }
    Ok(())
}
