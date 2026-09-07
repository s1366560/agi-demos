//! ConPTY shutdown keeps output draining while ClosePseudoConsole is running.
//! The common reaper retains the generation until this owner and both I/O workers finish.

use super::{DrainResult, TerminalPtyCommandV2};
use portable_pty::{native_pty_system, Child, CommandBuilder, MasterPty, PtySize};
use std::{
    io::{Read, Write},
    os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, RecvTimeoutError, SyncSender},
        Arc,
    },
    thread::{self, JoinHandle},
    time::Duration,
};
use tokio::sync::{mpsc as async_mpsc, oneshot};
use windows_sys::Win32::{
    Foundation::{
        DuplicateHandle, DUPLICATE_SAME_ACCESS, ERROR_NOT_FOUND, WAIT_FAILED, WAIT_OBJECT_0,
    },
    System::{
        Threading::{GetCurrentProcess, GetCurrentThread, TerminateProcess, WaitForSingleObject},
        IO::CancelSynchronousIo,
    },
};

const TICK: Duration = Duration::from_millis(10);
type Reader = Box<dyn Read + Send>;
type Writer = Box<dyn Write + Send>;

pub(super) fn run(
    cwd: PathBuf,
    shutdown: Arc<AtomicBool>,
    commands: Receiver<TerminalPtyCommandV2>,
    output: async_mpsc::Sender<String>,
    ready: oneshot::Sender<DrainResult>,
) -> DrainResult {
    // Start workers before allocating ConPTY or a child: thread creation failure must not
    // leave a live pseudoconsole without an output drainer.
    let (reader_tx, reader_rx) = mpsc::sync_channel::<Reader>(1);
    let reader_stop = Arc::clone(&shutdown);
    let reader = thread::Builder::new()
        .name("terminal-conpty-reader".to_owned())
        .spawn(move || read_output(reader_rx, reader_stop, output))
        .map_err(|error| format!("start ConPTY reader: {error}"))?;
    let (writer_tx, writer_rx) = mpsc::sync_channel::<Writer>(1);
    let (input_tx, input_rx) = mpsc::sync_channel::<Vec<u8>>(32);
    let (handle_tx, handle_rx) = mpsc::sync_channel(1);
    let writer_stop = Arc::clone(&shutdown);
    let writer = match thread::Builder::new()
        .name("terminal-conpty-writer".to_owned())
        .spawn(move || {
            let handle = duplicate_current_thread();
            let admitted = handle.is_ok();
            let _ = handle_tx.send(handle);
            if !admitted {
                return Err("ConPTY writer thread handle unavailable".to_owned());
            }
            write_input(writer_rx, input_rx, writer_stop)
        }) {
        Ok(writer) => writer,
        Err(error) => {
            drop(reader_tx);
            let _ = reader.join();
            return Err(format!("start ConPTY writer: {error}"));
        }
    };
    let mut resources = Resources {
        master: None,
        child: None,
    };
    let handle = handle_rx
        .recv()
        .map_err(|_| "ConPTY writer initialization ended".to_owned())
        .and_then(|value| value);
    let mut ready = Some(ready);
    let operation = match handle.as_ref() {
        Ok(_) => std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            initialize_and_run(
                cwd,
                &shutdown,
                commands,
                &input_tx,
                reader_tx,
                writer_tx,
                &reader,
                &writer,
                &mut resources,
                &mut ready,
            )
        }))
        .unwrap_or_else(|_| Err("ConPTY owner panicked".to_owned())),
        Err(error) => {
            drop(reader_tx);
            drop(writer_tx);
            Err(error.clone())
        }
    };
    if let Some(ready) = ready.take() {
        let _ = ready.send(operation.clone());
    }
    shutdown.store(true, Ordering::Release);
    drop(input_tx);
    // CancelSynchronousIo only requests cancellation, including a possible NOT_FOUND race
    // before WriteFile starts. Keep requesting until the real worker exits, then join it.
    let mut failures = Vec::new();
    if let Ok(handle) = handle {
        let mut cancellation_error = None;
        while !writer.is_finished() {
            // SAFETY: this owned, duplicated thread handle remains live until after join.
            if unsafe { CancelSynchronousIo(handle.as_raw_handle()) } == 0 {
                let error = std::io::Error::last_os_error();
                if error.raw_os_error() != Some(ERROR_NOT_FOUND as i32)
                    && cancellation_error.is_none()
                {
                    tracing::error!(%error, "terminal ConPTY writer cancellation remains pending");
                    cancellation_error = Some(format!("cancel ConPTY writer: {error}"));
                }
            }
            thread::sleep(TICK);
        }
        if let Some(error) = cancellation_error {
            failures.push(error);
        }
    }
    collect_worker(writer, "writer", &mut failures);
    // Closing ConPTY can synchronously emit output on pre-24H2 Windows. The reader MUST
    // remain alive and drain/discard it until EOF; canceling it here can deadlock close.
    if let Some(child) = resources.child.as_mut() {
        terminate_child(child.as_mut(), &mut failures);
    }
    drop(resources.master.take());
    collect_worker(reader, "reader", &mut failures);
    if let Some(mut child) = resources.child.take() {
        confirm_child_exit(child.as_mut(), &mut failures);
    }
    if let Err(error) = operation {
        failures.insert(0, error);
    }
    if failures.is_empty() {
        Ok(())
    } else {
        Err(failures.join("; "))
    }
}

struct Resources {
    master: Option<Box<dyn MasterPty + Send>>,
    child: Option<Box<dyn Child + Send + Sync>>,
}

#[allow(clippy::too_many_arguments)]
fn initialize_and_run(
    cwd: PathBuf,
    shutdown: &AtomicBool,
    commands: Receiver<TerminalPtyCommandV2>,
    input: &SyncSender<Vec<u8>>,
    reader_tx: SyncSender<Reader>,
    writer_tx: SyncSender<Writer>,
    reader: &JoinHandle<DrainResult>,
    writer: &JoinHandle<DrainResult>,
    resources: &mut Resources,
    ready: &mut Option<oneshot::Sender<DrainResult>>,
) -> DrainResult {
    if shutdown.load(Ordering::Acquire) {
        return Ok(());
    }
    if !std::fs::metadata(&cwd)
        .map_err(|error| format!("terminal working directory: {error}"))?
        .is_dir()
    {
        return Err("terminal working directory is not a directory".to_owned());
    }
    let pair = native_pty_system()
        .openpty(PtySize {
            rows: 32,
            cols: 120,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|error| format!("open ConPTY: {error}"))?;
    let slave = pair.slave;
    resources.master = Some(pair.master);
    let master = resources.master.as_ref().ok_or("ConPTY master missing")?;
    reader_tx
        .send(
            master
                .try_clone_reader()
                .map_err(|error| format!("clone ConPTY reader: {error}"))?,
        )
        .map_err(|_| "ConPTY reader unavailable".to_owned())?;
    writer_tx
        .send(
            master
                .take_writer()
                .map_err(|error| format!("take ConPTY writer: {error}"))?,
        )
        .map_err(|_| "ConPTY writer unavailable".to_owned())?;
    if shutdown.load(Ordering::Acquire) {
        return Ok(());
    }
    let shell = std::env::var("SHELL").unwrap_or_else(|_| "cmd.exe".to_owned());
    let mut command = CommandBuilder::new(shell);
    command.cwd(cwd);
    resources.child = Some(
        slave
            .spawn_command(command)
            .map_err(|error| format!("spawn terminal: {error}"))?,
    );
    drop(slave);
    if let Some(ready) = ready.take() {
        if ready.send(Ok(())).is_err() {
            shutdown.store(true, Ordering::Release);
        }
    }
    while !shutdown.load(Ordering::Acquire) {
        if reader.is_finished() || writer.is_finished() {
            break;
        }
        if resources
            .child
            .as_mut()
            .ok_or("ConPTY child missing")?
            .try_wait()
            .map_err(|error| format!("poll terminal child: {error}"))?
            .is_some()
        {
            break;
        }
        match commands.recv_timeout(TICK) {
            Ok(TerminalPtyCommandV2::Input(data)) => {
                if shutdown.load(Ordering::Acquire) {
                    break;
                }
                input
                    .try_send(data)
                    .map_err(|_| "ConPTY input queue unavailable".to_owned())?;
            }
            Ok(TerminalPtyCommandV2::Resize { cols, rows }) => {
                if shutdown.load(Ordering::Acquire) {
                    break;
                }
                master
                    .resize(PtySize {
                        cols,
                        rows,
                        pixel_width: 0,
                        pixel_height: 0,
                    })
                    .map_err(|error| format!("resize ConPTY: {error}"))?;
            }
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => break,
        }
    }
    Ok(())
}

fn read_output(
    source: Receiver<Reader>,
    shutdown: Arc<AtomicBool>,
    output: async_mpsc::Sender<String>,
) -> DrainResult {
    let Ok(mut reader) = source.recv() else {
        return Ok(());
    };
    let mut buffer = [0_u8; 4096];
    let mut failure = None;
    loop {
        match reader.read(&mut buffer) {
            Ok(0) => return failure.map_or(Ok(()), Err),
            Ok(size) => {
                if shutdown.load(Ordering::Acquire) {
                    continue;
                }
                let mut text = String::from_utf8_lossy(&buffer[..size]).into_owned();
                loop {
                    if shutdown.load(Ordering::Acquire) {
                        break;
                    }
                    match output.try_send(text) {
                        Ok(()) => break,
                        Err(async_mpsc::error::TrySendError::Full(value)) => {
                            text = value;
                            thread::sleep(TICK);
                        }
                        Err(async_mpsc::error::TrySendError::Closed(_)) => {
                            shutdown.store(true, Ordering::Release);
                            break;
                        }
                    }
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::BrokenPipe => {
                return failure.map_or(Ok(()), Err)
            }
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => {
                if failure.is_none() {
                    tracing::error!(%error, "terminal ConPTY output drain remains pending");
                    failure = Some(format!("read ConPTY: {error}"));
                }
                shutdown.store(true, Ordering::Release);
                // Do not abandon the drainer while the master still owns an output pipe.
                // Persistent failures retain ownership instead of claiming EOF or teardown.
                thread::sleep(TICK);
            }
        }
    }
}

fn write_input(
    source: Receiver<Writer>,
    input: Receiver<Vec<u8>>,
    shutdown: Arc<AtomicBool>,
) -> DrainResult {
    let Ok(mut writer) = source.recv() else {
        return Ok(());
    };
    while !shutdown.load(Ordering::Acquire) {
        match input.recv_timeout(TICK) {
            Ok(bytes) => {
                if shutdown.load(Ordering::Acquire) {
                    break;
                }
                if let Err(error) = writer.write_all(&bytes).and_then(|()| writer.flush()) {
                    if shutdown.load(Ordering::Acquire) && error.raw_os_error() == Some(995) {
                        return Ok(());
                    }
                    return Err(format!("write ConPTY: {error}"));
                }
            }
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => break,
        }
    }
    Ok(())
}

fn duplicate_current_thread() -> Result<OwnedHandle, String> {
    let mut handle = std::ptr::null_mut();
    // SAFETY: pseudo-handles refer to this live process/thread; DuplicateHandle writes a
    // new independently owned handle, which is closed exactly once by OwnedHandle.
    let ok = unsafe {
        DuplicateHandle(
            GetCurrentProcess(),
            GetCurrentThread(),
            GetCurrentProcess(),
            &mut handle,
            0,
            0,
            DUPLICATE_SAME_ACCESS,
        )
    };
    if ok == 0 {
        return Err(format!(
            "duplicate ConPTY writer thread: {}",
            std::io::Error::last_os_error()
        ));
    }
    // SAFETY: successful DuplicateHandle returned a fresh, valid owned handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(handle) })
}

fn terminate_child(child: &mut (dyn Child + Send + Sync), failures: &mut Vec<String>) {
    if matches!(child.try_wait(), Ok(Some(_))) {
        return;
    }
    if let Some(handle) = child.as_raw_handle() {
        // SAFETY: the child owns this live process handle throughout this call.
        if unsafe { TerminateProcess(handle, 1) } == 0 {
            let error = std::io::Error::last_os_error();
            if !matches!(child.try_wait(), Ok(Some(_))) {
                failures.push(format!("terminate ConPTY child: {error}"));
            }
        }
    } else if let Err(error) = child.kill() {
        failures.push(format!("terminate ConPTY child: {error}"));
    }
}

fn confirm_child_exit(child: &mut (dyn Child + Send + Sync), failures: &mut Vec<String>) {
    let mut reported = false;
    let mut wait_reported = false;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return,
            Ok(None) => {}
            Err(error) if !reported => {
                tracing::error!(%error, "terminal ConPTY child exit remains unconfirmed");
                failures.push(format!("poll ConPTY child exit: {error}"));
                reported = true;
            }
            Err(_) => {}
        }
        if let Some(handle) = child.as_raw_handle() {
            // SAFETY: the child remains owned until this loop proves process termination.
            // A signaled process handle is sufficient even if exit-code retrieval fails.
            let outcome = unsafe { WaitForSingleObject(handle, 100) };
            if outcome == WAIT_FAILED && !wait_reported {
                let error = std::io::Error::last_os_error();
                tracing::error!(%error, "terminal ConPTY process wait remains pending");
                failures.push(format!("wait ConPTY process handle: {error}"));
                wait_reported = true;
            }
            if outcome == WAIT_OBJECT_0 {
                if let Err(error) = child.wait() {
                    failures.push(format!("read terminated ConPTY child status: {error}"));
                }
                return;
            }
        }
        // An OS error is not evidence of process exit. Keep ownership and the enclosing
        // generation lease; never turn a timeout or failed wait into successful cleanup.
        thread::sleep(TICK);
    }
}

fn collect_worker(worker: JoinHandle<DrainResult>, label: &str, failures: &mut Vec<String>) {
    match worker.join() {
        Ok(Ok(())) => {}
        Ok(Err(error)) => failures.push(error),
        Err(_) => failures.push(format!("ConPTY {label} panicked")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writer_handle_is_independently_owned() {
        let handle = duplicate_current_thread().expect("duplicate live thread");
        assert!(!handle.as_raw_handle().is_null());
    }

    #[test]
    fn cancelled_initialization_joins_workers_without_opening_console() {
        let shutdown = Arc::new(AtomicBool::new(true));
        let (_command_tx, commands) = mpsc::sync_channel(1);
        let (output, _output_rx) = async_mpsc::channel(1);
        let (ready, ready_rx) = oneshot::channel();
        assert!(run(std::env::temp_dir(), shutdown, commands, output, ready).is_ok());
        assert!(ready_rx
            .blocking_recv()
            .expect("readiness completion")
            .is_ok());
    }

    #[test]
    fn missing_working_directory_fails_before_console_spawn() {
        let shutdown = Arc::new(AtomicBool::new(false));
        let (_command_tx, commands) = mpsc::sync_channel(1);
        let (output, _output_rx) = async_mpsc::channel(1);
        let (ready, ready_rx) = oneshot::channel();
        let cwd = std::env::temp_dir().join(format!(
            "conpty-missing-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system clock")
                .as_nanos()
        ));
        assert!(run(cwd, shutdown, commands, output, ready).is_err());
        assert!(ready_rx
            .blocking_recv()
            .expect("readiness completion")
            .is_err());
    }

    #[test]
    fn live_console_shutdown_drains_with_unconsumed_output() {
        let shutdown = Arc::new(AtomicBool::new(false));
        let owner_shutdown = Arc::clone(&shutdown);
        let (command_tx, commands) = mpsc::sync_channel(4);
        let (output, _output_rx) = async_mpsc::channel(1);
        let (ready, ready_rx) = oneshot::channel();
        let (done_tx, done_rx) = mpsc::sync_channel(1);
        let owner = thread::spawn(move || {
            let result = run(
                std::env::temp_dir(),
                owner_shutdown,
                commands,
                output,
                ready,
            );
            let _ = done_tx.send(result);
        });
        ready_rx
            .blocking_recv()
            .expect("readiness")
            .expect("console started");
        // More than the UI output channel can hold. Teardown must switch the reader from
        // backpressure to discard/drain before ClosePseudoConsole waits for final output.
        command_tx
            .send(TerminalPtyCommandV2::Input(
                b"for /L %i in (1,1,1000) do @echo conpty-drain-test\r\n".to_vec(),
            ))
            .expect("input admitted");
        thread::sleep(Duration::from_millis(100));
        shutdown.store(true, Ordering::Release);
        done_rx
            .recv_timeout(Duration::from_secs(15))
            .expect("actual ConPTY cleanup completed")
            .expect("ConPTY cleanup succeeded");
        owner.join().expect("owner joined");
    }
}
