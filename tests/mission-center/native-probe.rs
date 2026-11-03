// Run as an example in the pinned Magpie workspace; see docs/mission-center.
use magpie_platform::{cpu::CpuCache, processes::{ProcessCache, ProcessManager}, DataCacheTypes};
use magpie_platform::{gpus::GpuCache, memory::MemoryCache};
use magpie_platform_linux::DataCacheTypes as Android;
use std::{process::{Child, Command}, thread::sleep, time::Duration};

struct Fixture(Child);
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn main() {
    let mut cpu = <Android as DataCacheTypes>::CpuCache::new();
    let mut processes = <Android as DataCacheTypes>::ProcessCache::new();
    let manager = <Android as DataCacheTypes>::ProcessManager::new();
    let mut memory = <Android as DataCacheTypes>::MemoryCache::new();
    memory.refresh();
    assert!(memory.memory().mem_total > 10 * 1024 * 1024 * 1024);
    println!("system_ram_total={} system_ram_available={}", memory.memory().mem_total, memory.memory().mem_available);
    let mut gpus = <Android as DataCacheTypes>::GpuCache::new();
    gpus.refresh();
    for gpu in gpus.cached_entries().values() {
        println!("gpu={:?} temperature={:?} usage={:?} max_clock_mhz={:?} clock_mhz={:?}", gpu.device_name, gpu.temperature_c, gpu.utilization_percent, gpu.max_clock_speed_mhz, gpu.clock_speed_mhz);
        assert!(gpu.temperature_c.is_some());
    }
    assert!(!gpus.cached_entries().is_empty());
    let workload = std::env::var("MC_TEST_WORKLOAD").expect("Set MC_TEST_WORKLOAD to the compiled workload.c executable");
    let mut fixture = Fixture(Command::new(workload).spawn().unwrap());
    let pid = fixture.0.id();
    let ticks = || {
        let text = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
        let fields: Vec<_> = text[text.rfind(')').unwrap() + 2..].split_whitespace().collect();
        fields[11].parse::<u64>().unwrap() + fields[12].parse::<u64>().unwrap()
    };
    for sample in 0..4 {
        processes.refresh();
        cpu.refresh();
        let info = cpu.cached();
        assert!(info.sample_error.is_none(), "{:?}", info.sample_error);
        assert_eq!(info.core_usage_percent.len(), 8);
        assert!(info.total_usage_percent.is_finite());
        let process = processes.cached_entries().get(&pid).expect("Termux workload missing");
        assert!(processes.cached_entries().contains_key(&1));
        assert!(processes.cached_entries().values().any(|p| p.name == "system_server"));
        println!("visible_processes={} cpu_temperature={:?}", processes.cached_entries().len(), info.temperature_celsius);
        println!("sample={sample} whole_cpu={:.3} cores={:?} workload_pid={pid} workload_cpu={:.3} rss={} state={:?}",
                 info.total_usage_percent, info.core_usage_percent, process.usage_stats.cpu_usage,
                 process.usage_stats.memory_usage, process.state());
        assert!(process.usage_stats.memory_usage > 0);
        if sample > 0 { assert!(process.usage_stats.cpu_usage > 10.); }
        sleep(Duration::from_secs(2));
    }
    manager.suspend_processes(vec![pid]);
    sleep(Duration::from_millis(200));
    let before = ticks();
    sleep(Duration::from_secs(1));
    assert_eq!(before, ticks(), "SIGSTOP failed to freeze native process");
    println!("SIGSTOP ticks_frozen={before}");
    manager.continue_processes(vec![pid]);
    sleep(Duration::from_secs(1));
    assert!(ticks() > before, "SIGCONT failed to resume native process");
    manager.terminate_processes(vec![pid]);
    for _ in 0..20 {
        if fixture.0.try_wait().unwrap().is_some() { break; }
        sleep(Duration::from_millis(100));
    }
    assert!(fixture.0.try_wait().unwrap().is_some(), "SIGTERM failed");
    println!("PASS CPU data, eight cores, process CPU/RSS, SIGSTOP, SIGCONT and SIGTERM");
}
