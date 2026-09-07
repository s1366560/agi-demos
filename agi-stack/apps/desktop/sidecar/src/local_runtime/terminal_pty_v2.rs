//! Retained terminal resources. Blocking PTY work never runs on an async executor worker.
//!
//! The reaper owns the generation until the OS resource owner has actually joined. Dropping
//! the UI/socket handle requests cancellation; it does not detach ownership of the resources.

use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, SyncSender, TrySendError},
        Arc,
    },
};

use tokio::sync::{mpsc as async_mpsc, oneshot, watch};

use super::platform_plugin_authority_v2::ActivePlatformPluginGenerationLeaseV2;

const COMMAND_CAPACITY: usize = 32;
const INPUT_LIMIT: usize = 64 * 1024;
type DrainResult = Result<(), String>;

pub(super) enum TerminalPtyCommandV2 {
    Input(Vec<u8>),
    Resize { cols: u16, rows: u16 },
}

pub(super) struct TerminalPtyV2 {
    shutdown: Arc<AtomicBool>,
    commands: SyncSender<TerminalPtyCommandV2>,
    output: async_mpsc::Receiver<String>,
    ready: Option<oneshot::Receiver<DrainResult>>,
    completion: watch::Receiver<Option<DrainResult>>,
}

impl TerminalPtyV2 {
    pub(super) fn start(
        cwd: PathBuf,
        generation: Option<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    ) -> Result<Self, String> {
        let (commands, command_rx) = mpsc::sync_channel(COMMAND_CAPACITY);
        let (output_tx, output) = async_mpsc::channel(32);
        let (ready_tx, ready) = oneshot::channel();
        let (complete_tx, completion) = watch::channel(None);
        let shutdown = Arc::new(AtomicBool::new(false));
        let owner_shutdown = Arc::clone(&shutdown);
        // This independent reaper survives handle/future cancellation. It never drops a live
        // OS-thread JoinHandle: generation release is ordered strictly after join returns.
        tokio::task::spawn_blocking(move || {
            let owner = std::thread::Builder::new()
                .name("terminal-pty-v2".to_owned())
                .spawn(move || platform::run(cwd, owner_shutdown, command_rx, output_tx, ready_tx));
            let result = match owner {
                Ok(owner) => owner
                    .join()
                    .unwrap_or_else(|_| Err("terminal PTY owner panicked".to_owned())),
                Err(error) => Err(format!("terminal PTY owner could not start: {error}")),
            };
            if let Err(error) = &result {
                tracing::error!(%error, "terminal PTY resource owner completed with an error");
            }
            drop(generation);
            let _ = complete_tx.send(Some(result));
        });
        Ok(Self {
            shutdown,
            commands,
            output,
            ready: Some(ready),
            completion,
        })
    }

    pub(super) async fn ready(&mut self) -> DrainResult {
        let receiver = self
            .ready
            .take()
            .ok_or_else(|| "terminal readiness already consumed".to_owned())?;
        receiver
            .await
            .map_err(|_| "terminal PTY initialization ended".to_owned())?
    }

    pub(super) fn try_input(&self, data: Vec<u8>) -> DrainResult {
        if data.len() > INPUT_LIMIT {
            self.shutdown();
            return Err("terminal input exceeds bounded capacity".to_owned());
        }
        self.send(TerminalPtyCommandV2::Input(data))
    }

    pub(super) fn try_resize(&self, cols: u16, rows: u16) -> DrainResult {
        self.send(TerminalPtyCommandV2::Resize { cols, rows })
    }

    fn send(&self, command: TerminalPtyCommandV2) -> DrainResult {
        if self.shutdown.load(Ordering::Acquire) {
            return Err("terminal PTY is retired".to_owned());
        }
        self.commands.try_send(command).map_err(|error| {
            self.shutdown();
            match error {
                TrySendError::Full(_) => "terminal command queue is full".to_owned(),
                TrySendError::Disconnected(_) => "terminal PTY is closed".to_owned(),
            }
        })
    }

    pub(super) async fn output(&mut self) -> Option<String> {
        self.output.recv().await
    }

    pub(super) fn shutdown(&self) {
        self.shutdown.store(true, Ordering::Release);
    }

    pub(super) async fn drain(&self) -> DrainResult {
        self.shutdown();
        let mut completion = self.completion.clone();
        loop {
            if let Some(result) = completion.borrow_and_update().clone() {
                return result;
            }
            completion
                .changed()
                .await
                .map_err(|_| "terminal PTY reaper ended without completion".to_owned())?;
        }
    }
}

impl Drop for TerminalPtyV2 {
    fn drop(&mut self) {
        self.shutdown();
    }
}

#[cfg(unix)]
mod platform {
    use super::{DrainResult, TerminalPtyCommandV2};
    use portable_pty::{native_pty_system, Child, CommandBuilder, MasterPty, PtySize};
    use std::{
        io::{self, Read, Write},
        path::PathBuf,
        sync::{
            atomic::{AtomicBool, Ordering},
            mpsc::{Receiver, TryRecvError},
            Arc,
        },
        time::Duration,
    };
    use tokio::sync::{mpsc, oneshot};

    struct Resources {
        child: Option<Box<dyn Child + Send + Sync>>,
        master: Option<Box<dyn MasterPty + Send>>,
        reader: Option<Box<dyn Read + Send>>,
        writer: Option<Box<dyn Write + Send>>,
    }

    impl Resources {
        fn close(&mut self) -> DrainResult {
            let mut failures = Vec::new();
            if let Some(child) = self.child.as_mut() {
                // Do not signal a naturally exited/reaped shell: its numeric group id may
                // already be reusable. The pump itself never reaps the child.
                let mut can_signal_groups = false;
                let mut exited = match child.try_wait() {
                    Ok(Some(_)) => true,
                    Err(error) if error.raw_os_error() == Some(libc::ECHILD) => true,
                    Err(error) => {
                        record_failure(&mut failures, format!("try_wait: {error}"));
                        false
                    }
                    Ok(None) => {
                        can_signal_groups = true;
                        false
                    }
                };
                if !exited && can_signal_groups {
                    // portable-pty creates a new session. This covers foreground + shell
                    // groups, not ordinary background groups or escaped process trees.
                    let shell_group = child.process_id().and_then(|pid| i32::try_from(pid).ok());
                    let foreground = self
                        .master
                        .as_ref()
                        .and_then(|master| master.process_group_leader());
                    failures.extend(signal_process_groups(foreground, shell_group, |group| {
                        if exited {
                            return Ok(());
                        }
                        // SAFETY: a positive group id comes from the owned PTY/session.
                        if unsafe { libc::kill(-group, libc::SIGKILL) } == 0 {
                            return Ok(());
                        }
                        let error = io::Error::last_os_error();
                        // macOS can report EPERM for a group whose last process just exited.
                        // Suppress only for our direct shell group AND confirmed child exit.
                        // A foreground job's permission failure is still an error.
                        if error.raw_os_error() == Some(libc::EPERM) && Some(group) == shell_group {
                            exited = match child.try_wait() {
                                Ok(Some(_)) => true,
                                Err(wait_error)
                                    if wait_error.raw_os_error() == Some(libc::ECHILD) =>
                                {
                                    true
                                }
                                _ => false,
                            };
                            if exited {
                                return Ok(());
                            }
                        }
                        Err(error)
                    }));
                }
                // Close the PTY before waiting: macOS terminal teardown can keep a
                // killed child in exit until the master descriptors are released.
                // Retain the child and generation owner until reaping is confirmed.
                // Duplicate descriptors share O_NONBLOCK, including the writer's EOT Drop.
                self.writer.take();
                self.reader.take();
                self.master.take();
                if !exited {
                    loop {
                        match child.try_wait() {
                            Ok(Some(_)) => break,
                            Err(error) if error.raw_os_error() == Some(libc::ECHILD) => break,
                            Err(error) => {
                                record_failure(&mut failures, format!("try_wait: {error}"))
                            }
                            Ok(None) => {}
                        }
                        if let Err(error) = child.kill() {
                            record_failure(&mut failures, format!("kill: {error}"));
                        }
                        match child.wait() {
                            Ok(_) => break,
                            // The owned direct child was already reaped by another wait call.
                            Err(error) if error.raw_os_error() == Some(libc::ECHILD) => break,
                            Err(error) => record_failure(&mut failures, format!("wait: {error}")),
                        }
                        // A failed kill/wait is not proof of exit. Retain this owner and the
                        // generation while retrying; never release a possibly live process.
                        std::thread::sleep(Duration::from_millis(20));
                    }
                }
            }
            self.child.take();
            // Unix duplicate descriptors share O_NONBLOCK, including the writer's EOT Drop.
            self.writer.take();
            self.reader.take();
            self.master.take();
            if failures.is_empty() {
                Ok(())
            } else {
                Err(failures.join("; "))
            }
        }
    }

    pub(super) fn signal_process_groups(
        foreground: Option<i32>,
        shell_group: Option<i32>,
        mut signal: impl FnMut(i32) -> io::Result<()>,
    ) -> Vec<String> {
        let mut visited = std::collections::BTreeSet::new();
        let mut failures = Vec::new();
        for group in [foreground, shell_group].into_iter().flatten() {
            // The foreground often is the shell itself. A second signal after its exit
            // is not another resource to clean up and must not manufacture a failure.
            if group <= 1 || !visited.insert(group) {
                continue;
            }
            if let Err(error) = signal(group) {
                if error.raw_os_error() != Some(libc::ESRCH) {
                    record_failure(&mut failures, format!("kill process group: {error}"));
                }
            }
        }
        failures
    }

    fn record_failure(failures: &mut Vec<String>, error: String) {
        if !failures.contains(&error) {
            tracing::error!(%error, "terminal PTY cleanup remains pending or failed");
            failures.push(error);
        }
    }

    #[cfg(test)]
    pub(super) fn close_test_child(child: Box<dyn Child + Send + Sync>) -> DrainResult {
        Resources {
            child: Some(child),
            master: None,
            reader: None,
            writer: None,
        }
        .close()
    }

    impl Drop for Resources {
        fn drop(&mut self) {
            if let Err(error) = self.close() {
                tracing::error!(%error, "terminal PTY cleanup failed during drop");
            }
        }
    }

    pub(super) fn run(
        cwd: PathBuf,
        shutdown: Arc<AtomicBool>,
        commands: Receiver<TerminalPtyCommandV2>,
        output: mpsc::Sender<String>,
        ready: oneshot::Sender<DrainResult>,
    ) -> DrainResult {
        let mut resources = Resources {
            child: None,
            master: None,
            reader: None,
            writer: None,
        };
        let initialized = initialize(&mut resources, cwd, &shutdown);
        if let Err(error) = initialized {
            let _ = ready.send(Err(error.clone()));
            let cleanup = resources.close();
            return match cleanup {
                Ok(()) => Err(error),
                Err(cleanup) => Err(format!("{error}; {cleanup}")),
            };
        }
        if ready.send(Ok(())).is_err() {
            shutdown.store(true, Ordering::Release);
        }
        let result = pump(&mut resources, &shutdown, &commands, &output);
        let cleanup = resources.close();
        match (result, cleanup) {
            (Ok(()), result) | (result, Ok(())) => result,
            (Err(error), Err(cleanup)) => Err(format!("{error}; {cleanup}")),
        }
    }

    fn initialize(resources: &mut Resources, cwd: PathBuf, shutdown: &AtomicBool) -> DrainResult {
        if shutdown.load(Ordering::Acquire) {
            return Err("terminal initialization cancelled".to_owned());
        }
        let cwd = cwd
            .canonicalize()
            .map_err(|error| format!("terminal cwd: {error}"))?;
        if !cwd.is_dir() {
            return Err("terminal cwd is not a directory".to_owned());
        }
        // portable-pty 0.8.1 rechecks is_dir internally and otherwise selects HOME.
        // This rejects already invalid directories, but does not eliminate that upstream
        // check-to-spawn race. Do not claim directory-FD or strict-cwd confinement here.
        let pair = native_pty_system()
            .openpty(PtySize {
                rows: 32,
                cols: 120,
                pixel_width: 0,
                pixel_height: 0,
            })
            .map_err(|error| error.to_string())?;
        resources.master = Some(pair.master);
        let master = resources.master.as_ref().expect("master just installed");
        let fd = master
            .as_raw_fd()
            .ok_or_else(|| "terminal backend lacks a cancellable descriptor".to_owned())?;
        // SAFETY: fd is borrowed from the owned master and remains open throughout these calls.
        // F_SETFL preserves all existing flags; dup reader/writer descriptors share this setting.
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
        if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
            return Err(io::Error::last_os_error().to_string());
        }
        resources.reader = Some(
            master
                .try_clone_reader()
                .map_err(|error| error.to_string())?,
        );
        resources.writer = Some(master.take_writer().map_err(|error| error.to_string())?);
        if shutdown.load(Ordering::Acquire) {
            return Err("terminal initialization cancelled".to_owned());
        }
        let mut command =
            CommandBuilder::new(std::env::var("SHELL").unwrap_or_else(|_| "/bin/sh".to_owned()));
        command.cwd(cwd);
        resources.child = Some(
            pair.slave
                .spawn_command(command)
                .map_err(|error| error.to_string())?,
        );
        drop(pair.slave);
        Ok(())
    }

    fn pump(
        resources: &mut Resources,
        shutdown: &AtomicBool,
        commands: &Receiver<TerminalPtyCommandV2>,
        output: &mpsc::Sender<String>,
    ) -> DrainResult {
        let mut input = Vec::new();
        let mut input_offset = 0;
        let mut pending_output = None;
        let mut buffer = [0_u8; 4096];
        while !shutdown.load(Ordering::Acquire) {
            if input_offset == input.len() {
                match commands.try_recv() {
                    Ok(TerminalPtyCommandV2::Input(data)) => {
                        input = data;
                        input_offset = 0;
                    }
                    Ok(TerminalPtyCommandV2::Resize { cols, rows }) => {
                        resources
                            .master
                            .as_ref()
                            .expect("initialized master")
                            .resize(PtySize {
                                cols,
                                rows,
                                pixel_width: 0,
                                pixel_height: 0,
                            })
                            .map_err(|error| error.to_string())?;
                    }
                    Err(TryRecvError::Disconnected) => return Ok(()),
                    Err(TryRecvError::Empty) => {}
                }
            }
            if input_offset < input.len() {
                match resources
                    .writer
                    .as_mut()
                    .expect("initialized writer")
                    .write(&input[input_offset..])
                {
                    Ok(0) => return Err("terminal input writer closed".to_owned()),
                    Ok(count) => input_offset += count,
                    Err(error)
                        if matches!(
                            error.kind(),
                            io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                        ) => {}
                    Err(error) => return Err(error.to_string()),
                }
            }
            if let Some(text) = pending_output.take() {
                match output.try_send(text) {
                    Ok(()) => {}
                    Err(mpsc::error::TrySendError::Full(text)) => pending_output = Some(text),
                    Err(mpsc::error::TrySendError::Closed(_)) => return Ok(()),
                }
            }
            if pending_output.is_none() {
                match resources
                    .reader
                    .as_mut()
                    .expect("initialized reader")
                    .read(&mut buffer)
                {
                    Ok(0) => return Ok(()),
                    Ok(count) => {
                        pending_output =
                            Some(String::from_utf8_lossy(&buffer[..count]).into_owned())
                    }
                    Err(error) if error.raw_os_error() == Some(libc::EIO) => return Ok(()),
                    Err(error)
                        if matches!(
                            error.kind(),
                            io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                        ) => {}
                    Err(error) => return Err(error.to_string()),
                }
            }
            // Independent of both bounded channels: shutdown can always interrupt backpressure.
            std::thread::sleep(Duration::from_millis(5));
        }
        Ok(())
    }

    #[cfg(test)]
    mod close_order_tests {
        include!("terminal_pty_close_order_tests.rs");
    }
}

// Windows backend is supplied separately: portable-pty hides its blocking pipe handles.
#[cfg(windows)]
#[path = "terminal_pty_v2_windows.rs"]
mod platform;

#[cfg(test)]
#[path = "terminal_pty_v2_tests.rs"]
mod tests;
