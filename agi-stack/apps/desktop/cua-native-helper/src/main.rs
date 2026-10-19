mod app_icon;
mod audio_recordings;
#[cfg(any(target_os = "windows", test))]
mod audio_mix;
mod backend;
#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "linux")]
mod linux_audio;
mod protocol;
mod session;
#[cfg(any(target_os = "windows", test))]
mod wave;
#[cfg(target_os = "windows")]
mod windows;
#[cfg(target_os = "windows")]
mod windows_audio;
#[cfg(target_os = "windows")]
mod windows_capture;

#[tokio::main(flavor = "current_thread")]
async fn main() {
    // Isolated native hard-fault fixture; this entry point is absent from release builds.
    #[cfg(all(target_os = "linux", debug_assertions))]
    if std::env::args().any(|argument| argument == "--native-clipboard-grab-fixture") {
        let fixture = crate::input_watchdog::Watchdog::start().expect("native fixture guardian");
        fixture.call("clipboard_write",serde_json::json!({"session_id":"native-fixture", "text":"OWNED_FIXTURE_COPY", "format":"html"})).expect("native fixture write");
        fixture
            .call("clipboard_grab_fixture", serde_json::Value::Null)
            .expect("native grab acknowledgement");
        println!("native_grab_acknowledged");
        loop {
            std::thread::park();
        }
    }
    #[cfg(any(target_os = "linux", target_os = "windows"))]
    if std::env::args().any(|argument| argument == "--input-watchdog") {
        if crate::input_guardian::run().await.is_err() {
            std::process::exit(1);
        }
        return;
    }
    #[cfg(any(target_os = "linux", target_os = "windows"))]
    if std::env::args().any(|argument| argument == "--input-worker") {
        if crate::input_watchdog::worker().is_err() {
            std::process::exit(1);
        }
        return;
    }
    if let Err(error) = protocol::run(backend::platform_backend()).await {
        eprintln!("cua native helper: {error}");
        std::process::exit(2);
    }
}

#[cfg(target_os = "windows")]
mod windows_input;
#[cfg(target_os = "windows")]
mod windows_uia;

#[cfg(target_os = "windows")]
mod windows_clipboard;

#[cfg(target_os = "linux")]
mod linux_text;

#[cfg(target_os = "linux")]
mod linux_eis;
#[cfg(target_os = "linux")]
mod linux_portal;

#[cfg(target_os = "linux")]
mod linux_x11;
#[cfg(target_os = "linux")]
mod linux_x11_capture;

#[cfg(any(target_os = "windows", target_os = "linux"))]
mod device_lease;
#[cfg(any(target_os = "linux", target_os = "windows"))]
mod input_guardian;
#[cfg(any(target_os = "windows", target_os = "linux", test))]
mod input_watchdog;
#[cfg(target_os = "linux")]
mod linux_apps;
#[cfg(target_os = "linux")]
mod linux_clipboard;
#[cfg(target_os = "linux")]
mod linux_clipboard_seat;
#[cfg(target_os = "linux")]
mod linux_clipboard_x11;
#[cfg(target_os = "linux")]
mod linux_tree;
#[cfg(target_os = "linux")]
mod linux_watchdog;
#[cfg(any(target_os = "linux", target_os = "windows"))]
mod parent_process;
#[cfg(target_os = "windows")]
mod windows_apps;
#[cfg(target_os = "windows")]
mod windows_watchdog;

#[cfg(target_os = "linux")]
mod linux_app_icon;
#[cfg(target_os = "windows")]
mod windows_app_icon;
