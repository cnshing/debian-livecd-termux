#[path = "../../../packages/android-procfs/src/source.rs"]
mod proc_stat;

fn main() -> std::io::Result<()> {
    let requests = std::env::args().nth(1).unwrap_or_else(|| "2".into()).parse::<usize>().unwrap();
    let kind = std::env::args().nth(2).unwrap_or_else(|| "stat".into());
    for i in 0..requests {
        let start = std::time::Instant::now();
        let result = if kind == "stat" { proc_stat::read() } else { proc_stat::request(&kind) };
        match result {
            Ok(snapshot) if kind == "stat" => println!("request={} latency_us={} bytes={} cores={} {}", i + 1, start.elapsed().as_micros(), snapshot.len(), snapshot.lines().filter(|line| line.strip_prefix("cpu").is_some_and(|rest| rest.starts_with(|c: char| c.is_ascii_digit()))).count(), snapshot.lines().next().unwrap()),
            Ok(snapshot) if kind == "processes" => {
                let rows: Vec<_> = snapshot.lines().map(|line| line.split('\t').collect::<Vec<_>>()).collect();
                assert!(rows.iter().all(|row| row.len() == 6 && row[0] == "P"), "bad row lengths: {:?}", rows.iter().filter(|row| row.len() != 6 || row[0] != "P").map(|row| (row.len(), row.first().map(|s| &s[..s.len().min(100)]))).take(5).collect::<Vec<_>>());
                assert!(rows.iter().any(|row| row[1] == "1"));
                assert!(rows.len() > 100);
                let foreign = rows.iter().filter(|row| row[2].parse::<u32>().unwrap() != unsafe { libc::getuid() }).count();
                assert!(foreign > 100);
                let system_server = rows.iter().any(|row| proc_stat::unhex(row[3]).unwrap().contains("(system_server)"));
                assert!(system_server);
                println!("request={} category={kind} latency_us={} bytes={} processes={} foreign_uid={} init=true system_server=true", i + 1, start.elapsed().as_micros(), snapshot.len(), rows.len(), foreign);
            }
            Ok(snapshot) => {
                let cpu = proc_stat::thermal(&snapshot, &["cpu", "cpuss"]);
                let gpu = proc_stat::thermal(&snapshot, &["gpu", "gpuss"]);
                println!("request={} category={kind} latency_us={} bytes={} cpu_temp={cpu:?} gpu_temp={gpu:?}", i + 1, start.elapsed().as_micros(), snapshot.len());
                for line in snapshot.lines().filter(|line| !line.starts_with("thermal")) { println!("{line}"); }
                assert!(cpu.is_some());
            }
            Err(e) => println!("request={} error={e}", i + 1),
        }
        if i + 1 < requests {
            let milliseconds = std::env::var("MC_TEST_INTERVAL_MS").ok().and_then(|s| s.parse().ok()).unwrap_or(2000);
            std::thread::sleep(std::time::Duration::from_millis(milliseconds));
        }
    }
    Ok(())
}
