// SPDX-License-Identifier: MIT
// Shared /proc/stat source for core discovery and CPU refresh. The Android
// reader blocks in stdin between requests; this client has no sampling thread.
use std::fs::File;
use std::io::{self, Read, Write};
use std::net::TcpListener;
use std::os::fd::{AsRawFd, OwnedFd};
use std::os::unix::net::UnixStream;
use std::process::{Child, Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

const MAX_SNAPSHOT: usize = 65536;
const START_TIMEOUT: Duration = Duration::from_secs(15);
const SAMPLE_TIMEOUT: Duration = Duration::from_secs(2);
const RETRY_DELAY: Duration = Duration::from_secs(1);

#[derive(Default)]
struct Source {
    session: Option<Session>,
    connected_once: bool,
    last_error: Option<(Instant, io::ErrorKind, String)>,
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

/// Fixed read-only categories, multiplexed over the same persistent session.
pub fn request(kind: &str) -> io::Result<String> {
    String::from_utf8(request_bytes(kind)?).map_err(|_| invalid("non-UTF8 snapshot"))
}

pub fn request_bytes(kind: &str) -> io::Result<Vec<u8>> {
    if kind.len() > 4095 || kind.contains(['\n', '\r', '\0']) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid resource command",
        ));
    }
    if !matches!(
        kind,
        "stat" | "processes" | "processes-v2" | "threads" | "telemetry" | "thermals"
    ) && !(kind.starts_with("meta ")
        || kind.starts_with("read ")
        || kind.starts_with("list ")
        || kind.starts_with("link "))
    {
        return Err(invalid("unknown telemetry request"));
    }
    let mut source = SOURCE
        .get_or_init(|| Mutex::new(Source::default()))
        .lock()
        .map_err(|_| io::Error::other("CPU source lock poisoned"))?;
    if source.session.is_none() {
        if let Some((time, kind, message)) = &source.last_error {
            if time.elapsed() < RETRY_DELAY {
                return Err(io::Error::new(*kind, message.clone()));
            }
        }
        // Several categories share this source. Do not make each one launch a
        // 15-second authorization attempt after an established session breaks.
        let timeout = if source.connected_once {
            SAMPLE_TIMEOUT
        } else {
            START_TIMEOUT
        };
        match Session::connect(timeout) {
            Ok(session) => {
                source.session = Some(session);
                source.connected_once = true;
                source.last_error = None;
            }
            Err(error) => {
                source.last_error = Some((Instant::now(), error.kind(), error.to_string()));
                return Err(error);
            }
        }
    }
    let result = source.session.as_mut().unwrap().sample_bytes(kind);
    if let Err(error) = &result {
        if source.session.as_ref().is_some_and(|s| s.remote_error) {
            return result;
        }
        // Discard the whole session; the next refresh reconnects on demand.
        // Never serve an earlier snapshot after a timeout or disconnect.
        source.session = None;
        source.last_error = Some((Instant::now(), error.kind(), error.to_string()));
    }
    result
}

static SOURCE: OnceLock<Mutex<Source>> = OnceLock::new();

pub fn disconnect() {
    if let Some(source) = SOURCE.get() {
        if let Ok(mut source) = source.lock() {
            source.session = None;
        }
    }
}

struct Session {
    child: Option<Child>,
    input: Option<Box<dyn Write + Send>>,
    output: File,
    remote_error: bool,
}

impl Drop for Session {
    fn drop(&mut self) {
        // Closing stdin lets rish close the remote reader's input on EOF.
        self.input.take();
        if let Some(child) = &mut self.child {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

impl Session {
    fn connect(timeout: Duration) -> io::Result<Self> {
        let home = std::env::var_os("HOME").ok_or_else(|| io::Error::other("HOME is unset"))?;
        let rish = std::env::var_os("LIVECD_RESOURCES_RISH")
            .or_else(|| std::env::var_os("MC_RISH"))
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| std::path::PathBuf::from(home).join(".local/lib/shizuku/rish"));
        // This path is also used by livecd-resources-setup. It contains
        // only a kernel-provided numeric UID, never shell-interpolated input.
        let path = format!(
            "/data/local/tmp/livecd-resources-{}/stat-reader-v1",
            unsafe { libc::getuid() }
        );
        let listener = TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0))?;
        let port = listener.local_addr()?.port();
        let mut random = [0; 32];
        File::open("/dev/urandom")?.read_exact(&mut random)?;
        let token: String = random.iter().map(|b| format!("{b:02x}")).collect();
        // Only a numeric port, numeric UID and generated hex token enter the
        // shell command. The reader detaches after connecting, then the Java
        // client exits; only native processes remain during collection.
        let helper = format!("if [ -x {path} ]; then exec {path} --connect {port} {token}; else printf 'MC_STAT_START_ERROR reader-not-installed\\n'; fi");
        let (diagnostics, writer) = UnixStream::pair()?;
        let writer_copy = writer.try_clone()?;
        let mut command = Command::new("/system/bin/sh");
        command
            .arg(rish)
            .arg("-c")
            .arg(helper)
            .env("RISH_APPLICATION_ID", "com.termux")
            .env("RISH_PRESERVE_ENV", "0")
            .env_remove("LD_PRELOAD")
            .env_remove("LD_LIBRARY_PATH")
            .stdin(Stdio::null())
            .stdout(Stdio::from(OwnedFd::from(writer)))
            .stderr(Stdio::from(OwnedFd::from(writer_copy)));
        let child = command.spawn()?;
        drop(command);
        let mut session = Self {
            child: Some(child),
            input: None,
            output: File::from(OwnedFd::from(diagnostics)),
            remote_error: false,
        };
        let deadline = Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "Shizuku reader startup timed out",
                ));
            }
            let mut fds = [
                libc::pollfd {
                    fd: listener.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                },
                libc::pollfd {
                    fd: session.output.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                },
            ];
            let ready = unsafe {
                libc::poll(
                    fds.as_mut_ptr(),
                    2,
                    remaining.as_millis().max(1).min(i32::MAX as u128) as i32,
                )
            };
            if ready < 0 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(error);
            }
            if fds[0].revents & libc::POLLIN != 0 {
                let (mut stream, _) = listener.accept()?;
                stream.set_nodelay(true)?;
                stream.set_read_timeout(Some(remaining.min(Duration::from_millis(200))))?;
                let mut supplied = [0; 65];
                if stream.read_exact(&mut supplied).is_err()
                    || &supplied[..64] != token.as_bytes()
                    || supplied[64] != b'\n'
                {
                    continue;
                }
                stream.set_read_timeout(None)?;
                session.output = File::from(OwnedFd::from(stream.try_clone()?));
                session.input = Some(Box::new(stream));
                session.greeting(deadline)?;
                if let Some(mut child) = session.child.take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                return Ok(session);
            }
            if fds[1].revents != 0 {
                let line = session.line(deadline)?;
                if line.starts_with("MC_STAT_START_ERROR ") {
                    return Err(io::Error::new(
                        io::ErrorKind::NotFound,
                        "reader is missing; run livecd-resources-setup",
                    ));
                }
                if std::env::var_os("LIVECD_RESOURCES_DEBUG").is_some() {
                    eprintln!("Shizuku: {line}");
                }
            }
        }
    }

    #[cfg(test)]
    fn start(mut command: Command, timeout: Duration) -> io::Result<Self> {
        let (output, peer) = UnixStream::pair()?;
        let peer_copy = peer.try_clone()?;
        let child = command
            .stdin(Stdio::piped())
            // Shizuku+ can deliver command stdout through rish's stderr.
            .stdout(Stdio::from(OwnedFd::from(peer)))
            .stderr(Stdio::from(OwnedFd::from(peer_copy)))
            .spawn()?;
        // Command retains its supplied Stdio handles after spawn. Close the
        // parent's writer copies now so a child that exits before READY yields
        // EOF, rather than keeping our own socket artificially open.
        drop(command);
        let mut session = Self {
            child: Some(child),
            input: None,
            output: File::from(OwnedFd::from(output)),
            remote_error: false,
        };
        session.input = session
            .child
            .as_mut()
            .unwrap()
            .stdin
            .take()
            .map(|input| Box::new(input) as Box<dyn Write + Send>);
        session.greeting(Instant::now() + timeout)?;
        Ok(session)
    }

    fn greeting(&mut self, deadline: Instant) -> io::Result<()> {
        for _ in 0..20 {
            let line = self.line(deadline)?;
            if line.starts_with("MC_STAT_START_ERROR ") {
                return Err(io::Error::new(
                    io::ErrorKind::NotFound,
                    "reader is missing; run livecd-resources-setup",
                ));
            }
            if let Some(identity) = line.strip_prefix("MC_STAT_READY_V1 pid=") {
                let (pid, uid) = identity
                    .split_once(" uid=")
                    .ok_or_else(|| invalid("invalid reader identity"))?;
                let _: u32 = pid.parse().map_err(|_| invalid("invalid reader PID"))?;
                let uid: u32 = uid.parse().map_err(|_| invalid("invalid reader UID"))?;
                if uid != 2000 && uid != 0 {
                    return Err(invalid("CPU reader must run as shell or root"));
                }
                return Ok(());
            }
            // Bounded startup diagnostics are retained for troubleshooting.
            eprintln!("LiveCD resources Shizuku: {line}");
        }
        Err(invalid(
            "missing CPU reader greeting; run livecd-resources-setup",
        ))
    }

    fn exact(&mut self, bytes: &mut [u8], deadline: Instant) -> io::Result<()> {
        let mut offset = 0;
        while offset < bytes.len() {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "Shizuku CPU reader timed out",
                ));
            }
            let mut fd = libc::pollfd {
                fd: self.output.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            };
            let ready = unsafe {
                libc::poll(
                    &mut fd,
                    1,
                    remaining.as_millis().max(1).min(i32::MAX as u128) as i32,
                )
            };
            if ready < 0 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(error);
            }
            if ready == 0 {
                continue;
            }
            match self.output.read(&mut bytes[offset..]) {
                Ok(0) => {
                    return Err(io::Error::new(
                        io::ErrorKind::UnexpectedEof,
                        "Shizuku CPU reader disconnected",
                    ))
                }
                Ok(n) => offset += n,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => (),
                Err(e) => return Err(e),
            }
        }
        Ok(())
    }

    fn line(&mut self, deadline: Instant) -> io::Result<String> {
        let mut line = Vec::new();
        while line.len() < 4096 {
            let mut byte = [0];
            self.exact(&mut byte, deadline)?;
            if byte[0] == b'\n' {
                return String::from_utf8(line).map_err(|_| invalid("non-UTF8 reader header"));
            }
            line.push(byte[0]);
        }
        Err(invalid("CPU reader header too long"))
    }

    #[cfg(test)]
    fn sample(&mut self) -> io::Result<String> {
        self.sample_kind("stat")
    }

    #[cfg(test)]
    fn sample_kind(&mut self, kind: &str) -> io::Result<String> {
        String::from_utf8(self.sample_bytes(kind)?).map_err(|_| invalid("non-UTF8 snapshot"))
    }

    fn sample_bytes(&mut self, command: &str) -> io::Result<Vec<u8>> {
        self.remote_error = false;
        let kind = command.split_whitespace().next().unwrap_or_default();
        let deadline = Instant::now() + SAMPLE_TIMEOUT;
        self.input
            .as_mut()
            .ok_or_else(|| io::Error::other("reader input closed"))?
            .write_all(format!("{command}\n").as_bytes())?;
        let line = self.line(deadline)?;
        let direct = line.starts_with("MC_DATA_V3 ");
        let error_frame =
            line.starts_with("MC_DATA_V2 error ") || line.starts_with("MC_DATA_V3 error ");
        let v2_prefix = format!(
            "MC_DATA_V{} {} ",
            if direct { 3 } else { 2 },
            if error_frame { "error" } else { kind }
        );
        let (length_field, checksum) = if let Some(fields) = line.strip_prefix(&v2_prefix) {
            let (length, checksum) = fields
                .split_once(' ')
                .ok_or_else(|| invalid("missing frame checksum"))?;
            (
                length,
                Some(
                    checksum
                        .parse::<u32>()
                        .map_err(|_| invalid("invalid frame checksum"))?,
                ),
            )
        } else {
            let prefix = if kind == "stat" {
                "MC_STAT_V1 ".to_owned()
            } else {
                format!("MC_DATA_V1 {kind} ")
            };
            (
                line.strip_prefix(&prefix)
                    .ok_or_else(|| invalid(format!("reader failed: {line}")))?,
                None,
            )
        };
        let length: usize = length_field
            .parse()
            .map_err(|_| invalid("invalid snapshot size"))?;
        let maximum = if kind == "stat" {
            MAX_SNAPSHOT
        } else {
            8 * 1024 * 1024
        };
        if length >= maximum || (kind == "stat" && length == 0) {
            return Err(invalid("snapshot size outside bounds"));
        }
        let mut bytes = vec![0; length];
        if let Some(checksum) = checksum {
            if direct {
                self.exact(&mut bytes, deadline)?;
            } else {
                self.input.as_mut().unwrap().write_all(b"ack\n")?;
                for chunk in bytes.chunks_mut(2048) {
                    self.exact(chunk, deadline)?;
                    self.input.as_mut().unwrap().write_all(b"ack\n")?;
                }
            }
            let actual = bytes.iter().fold(2166136261u32, |hash, byte| {
                (hash ^ *byte as u32).wrapping_mul(16777619)
            });
            if actual != checksum {
                return Err(invalid("telemetry checksum mismatch"));
            }
        } else {
            if length >= 4096 {
                return Err(invalid(
                    "reader protocol is obsolete; run livecd-resources-setup",
                ));
            }
            self.exact(&mut bytes, deadline)?;
        }
        if error_frame {
            self.remote_error = true;
            let error = std::str::from_utf8(&bytes)
                .ok()
                .and_then(|s| s.parse::<i32>().ok())
                .filter(|e| *e > 0 && *e < 4096)
                .unwrap_or(libc::EIO);
            return Err(io::Error::from_raw_os_error(error));
        }
        if kind == "stat" {
            validate(std::str::from_utf8(&bytes).map_err(|_| invalid("non-UTF8 CPU snapshot"))?)?;
        }
        Ok(bytes)
    }
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

fn validate(snapshot: &str) -> io::Result<()> {
    let mut lines = snapshot.lines();
    if !lines
        .next()
        .is_some_and(|line| line.starts_with("cpu ") && valid_ticks(line))
    {
        return Err(invalid("missing aggregate CPU counters"));
    }
    let mut cores = 0;
    let mut previous = None;
    for line in lines.take_while(|line| line.starts_with("cpu")) {
        let label = line.split_whitespace().next().unwrap_or_default();
        let id = label
            .strip_prefix("cpu")
            .and_then(|id| id.parse::<u32>().ok());
        if id.is_none() || previous.is_some_and(|prev| id.unwrap() <= prev) || !valid_ticks(line) {
            return Err(invalid("invalid per-core CPU counters"));
        }
        previous = id;
        cores += 1;
    }
    if cores == 0 {
        return Err(invalid("missing per-core CPU counters"));
    }
    Ok(())
}

fn valid_ticks(line: &str) -> bool {
    let fields: Vec<_> = line.split_whitespace().skip(1).collect();
    fields.len() >= 8 && fields.iter().all(|field| field.parse::<u64>().is_ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = "cpu  10 0 5 80 1 2 2 0 0 0\ncpu0 10 0 5 80 1 2 2 0 0 0\nbtime 123\n";

    fn fake(script: &str) -> Session {
        let shell = if cfg!(target_os = "android") {
            "/system/bin/sh"
        } else {
            "/bin/sh"
        };
        let mut command = Command::new(shell);
        command.arg("-c").arg(format!(
            "printf 'MC_STAT_READY_V1 pid=1 uid=2000\\n' >&2; {script}"
        ));
        Session::start(command, START_TIMEOUT).unwrap()
    }

    #[test]
    fn validates_live_counter_shape() {
        assert!(validate(SAMPLE).is_ok());
        assert!(validate(&SAMPLE.replace("cpu0", "cpu7")).is_ok()); // offline cores
        for text in [
            "",
            "cpu  1 2\n",
            "cpu  0 0 0 0 0 0 0 0\n",
            "cpu  x 0 0 0 0 0 0 0\ncpu0 0 0 0 0 0 0 0 0\n",
        ] {
            assert!(validate(text).is_err());
        }
    }

    #[test]
    fn validates_hex_and_thermal_units() {
        assert_eq!(unhex("610062").unwrap(), "a\0b");
        assert!(unhex("a").is_err());
        assert!(unhex("zz").is_err());
        let snapshot = "thermal\t637075302d757372\t40500\nthermal\t677075\t38000\n";
        assert_eq!(thermal(snapshot, &["cpu"]), Some(40.5));
        assert_eq!(thermal(snapshot, &["gpu"]), Some(38.0));
        assert_eq!(thermal(snapshot, &["battery"]), None);
    }

    #[test]
    fn reads_category_frames_and_rejects_wrong_category() {
        let mut session = fake("read request; printf 'MC_DATA_V1 processes 4\\nabc\\n'");
        assert_eq!(session.sample_kind("processes").unwrap(), "abc\n");
        let mut session = fake("read request; printf 'MC_DATA_V1 telemetry 4\\nabc\\n'");
        assert!(session.sample_kind("processes").is_err());
    }

    #[test]
    fn acknowledges_v2_frames_and_rejects_bad_checksums() {
        let body = "abc\n";
        let checksum = body.bytes().fold(2166136261u32, |hash, byte| {
            (hash ^ byte as u32).wrapping_mul(16777619)
        });
        let mut session = fake(&format!("read request; printf 'MC_DATA_V2 processes 4 {checksum}\\n'; read ack; test \"$ack\" = ack || exit 1; printf 'abc\\n'; read ack"));
        assert_eq!(session.sample_kind("processes").unwrap(), body);
        let mut session = fake("read request; printf 'MC_DATA_V2 processes 4 0\\n'; read ack; printf 'abc\\n'; read ack");
        assert_eq!(
            session.sample_kind("processes").unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
    }

    #[test]
    fn direct_frames_preserve_binary_data_without_acknowledgments() {
        let body = b"abc\0\n";
        let checksum = body.iter().fold(2166136261u32, |hash, byte| {
            (hash ^ *byte as u32).wrapping_mul(16777619)
        });
        let mut session = fake(&format!(
            "read request; printf 'MC_DATA_V3 read 5 {checksum}\\n'; printf 'abc\\000\\n'"
        ));
        assert_eq!(session.sample_bytes("read /proc/1/cmdline").unwrap(), body);
    }

    #[test]
    fn file_errors_leave_the_transport_usable() {
        let checksum = b"13".iter().fold(2166136261u32, |hash, byte| {
            (hash ^ *byte as u32).wrapping_mul(16777619)
        });
        let mut session = fake(&format!("read request; printf 'MC_DATA_V3 error 2 {checksum}\\n13'; read request; printf 'MC_DATA_V1 processes 4\\nabc\\n'"));
        assert_eq!(
            session
                .sample_bytes("read /proc/1/io")
                .unwrap_err()
                .raw_os_error(),
            Some(libc::EACCES)
        );
        assert!(session.remote_error);
        assert_eq!(session.sample_kind("processes").unwrap(), "abc\n");
        assert!(!session.remote_error);
    }

    #[test]
    fn rejects_command_injection_before_starting_a_reader() {
        assert_eq!(
            request_bytes("read /proc/stat\nquit").unwrap_err().kind(),
            io::ErrorKind::InvalidInput
        );
    }

    #[test]
    fn persistent_session_handles_stderr_and_split_frames() {
        let mut session = fake(&format!(
            "while read request; do printf 'MC_STAT_V1 '; printf '{}\\n'; printf '{}'; done",
            SAMPLE.len(),
            SAMPLE
        ));
        assert_eq!(session.sample().unwrap(), SAMPLE);
        assert_eq!(session.sample().unwrap(), SAMPLE);
    }

    #[test]
    fn rejects_oversize_and_helper_errors() {
        for header in [
            "MC_STAT_V1 65536",
            "MC_STAT_V1 0",
            "MC_STAT_V1 nope",
            "MC_STAT_ERROR_V1 errno=13",
        ] {
            let mut session = fake(&format!("read request; printf '{header}\\n'"));
            assert_eq!(
                session.sample().unwrap_err().kind(),
                io::ErrorKind::InvalidData
            );
        }
    }

    #[test]
    fn detects_eof_and_truncated_snapshot() {
        let mut session = fake("read request; printf 'MC_STAT_V1 100\\nshort'");
        assert_eq!(
            session.sample().unwrap_err().kind(),
            io::ErrorKind::UnexpectedEof
        );
    }

    #[test]
    fn bounds_wait_for_nonresponding_reader() {
        let mut session = fake("read request; read another_request");
        let start = Instant::now();
        assert_eq!(
            session.sample().unwrap_err().kind(),
            io::ErrorKind::TimedOut
        );
        assert!(start.elapsed() < Duration::from_secs(4));
    }

    #[test]
    fn startup_exit_closes_the_transport_without_waiting_for_timeout() {
        let shell = if cfg!(target_os = "android") {
            "/system/bin/sh"
        } else {
            "/bin/sh"
        };
        let mut command = Command::new(shell);
        command.args(["-c", "exit 1"]);
        let started = Instant::now();
        let error = Session::start(command, Duration::from_secs(3))
            .err()
            .unwrap();
        assert_eq!(error.kind(), io::ErrorKind::UnexpectedEof);
        assert!(started.elapsed() < Duration::from_secs(2));
    }
}
