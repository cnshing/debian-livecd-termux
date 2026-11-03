//! Runs Serein's own audio engine against the local PulseAudio, with no Discord connection.
//! `build.sh` supplies activity.rs, audio.rs, audio/echo.rs and diagnostics.rs unchanged from
//! the pinned release, apart from the recorded target substitution. Keeps no audio.
pub type Frame = [f32; 960];
mod activity;
pub mod audio;
mod diagnostics;

use cpal::traits::{DeviceTrait, HostTrait};
use model::voice_settings::Processing;
use std::time::{Duration, Instant};

fn name(device: Option<cpal::Device>) -> String {
	device.map_or("(none)".to_owned(), |device| device.to_string())
}

fn main() {
	let seconds: u64 = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(0);
	let host = cpal::default_host();
	println!("host: {:?}", host.id());
	println!("default input: {}", name(host.default_input_device()));
	println!("default output: {}", name(host.default_output_device()));
	match audio::devices() {
		Ok(list) => {
			for (id, device) in &list.inputs {
				println!("listed input: {device} [{id}]");
			}
		}
		Err(error) => println!("devices error: {error}"),
	}
	if seconds == 0 {
		return;
	}

	let preview = audio::Audio::preview(audio::Devices::default(), |result| {
		println!("engine: {result:?}");
	})
	.expect("preview thread");
	// Studio bypasses echo cancellation and denoising, which would remove a test tone.
	preview.set_processing(Processing::studio());
	// Preview loops the input to the speaker; silence that to prevent feedback.
	preview.set_gain(100, 0);
	preview.set_ready(true);

	let start = Instant::now();
	for second in 1..=seconds {
		let mut peak = -100.0_f32;
		while start.elapsed() < Duration::from_secs(second) {
			std::thread::sleep(Duration::from_millis(100));
			peak = peak.max(preview.preview_level_db());
		}
		println!(
			"t={second}s ready={} microphone_unavailable={} default={} peak_db={peak}",
			preview.is_ready(),
			preview.microphone_unavailable(),
			name(host.default_input_device()),
		);
	}
	let _ = preview.shutdown().recv_timeout(Duration::from_secs(3));
}
