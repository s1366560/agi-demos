//! Real Unix PTY tests: no mocked reader/child can stand in for cancellation of OS I/O.
#![cfg(unix)]

use super::*;
use std::time::Duration;

async fn ready_terminal() -> TerminalPtyV2 {
    let mut terminal = TerminalPtyV2::start(std::env::temp_dir(), None).expect("start owner");
    tokio::time::timeout(Duration::from_secs(5), terminal.ready())
        .await
        .expect("initialization deadline")
        .expect("PTY ready");
    terminal
}

async fn drain_terminal(terminal: &TerminalPtyV2) {
    tokio::time::timeout(Duration::from_secs(5), terminal.drain())
        .await
        .expect("real resources must finish")
        .expect("cleanup succeeds");
}

#[tokio::test]
async fn unix_real_pty_idle_reader_is_cancelled_and_joined() {
    let terminal = ready_terminal().await;
    terminal.shutdown();
    drain_terminal(&terminal).await;
    drain_terminal(&terminal).await;
    assert!(terminal.try_input(b"must not run\n".to_vec()).is_err());
}

#[tokio::test]
async fn unix_real_pty_output_backpressure_does_not_block_shutdown() {
    let terminal = ready_terminal().await;
    terminal.try_input(b"yes\n".to_vec()).expect("send command");
    // Deliberately never read the bounded output channel.
    tokio::time::sleep(Duration::from_millis(250)).await;
    drain_terminal(&terminal).await;
}

#[tokio::test]
async fn unix_full_input_queue_is_an_error_and_retires_instead_of_silently_dropping() {
    let terminal = ready_terminal().await;
    terminal
        .try_input(b"sleep 60\n".to_vec())
        .expect("start foreground child");
    tokio::time::sleep(Duration::from_millis(100)).await;
    let mut rejected = false;
    for _ in 0..128 {
        if terminal.try_input(vec![b'x'; INPUT_LIMIT]).is_err() {
            rejected = true;
            break;
        }
    }
    assert!(rejected, "bounded input must reject overload");
    drain_terminal(&terminal).await;
}

#[tokio::test]
async fn unix_drop_handle_still_reaps_worker_with_child_holding_slave() {
    let terminal = ready_terminal().await;
    terminal
        .try_input(b"sleep 60\n".to_vec())
        .expect("start foreground child");
    tokio::time::sleep(Duration::from_millis(100)).await;
    let mut completion = terminal.completion.clone();
    drop(terminal);
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if let Some(result) = completion.borrow_and_update().clone() {
                return result;
            }
            completion.changed().await.expect("reaper remains alive");
        }
    })
    .await
    .expect("drop requests real cleanup")
    .expect("cleanup completes");
}

#[tokio::test]
async fn unix_cancel_before_readiness_drains_even_if_init_has_started() {
    let terminal = TerminalPtyV2::start(std::env::temp_dir(), None).expect("start owner");
    terminal.shutdown();
    let result = tokio::time::timeout(Duration::from_secs(5), terminal.drain())
        .await
        .expect("cancel drains");
    if let Err(error) = result {
        assert!(error.contains("cancelled"));
    }
}

#[tokio::test]
async fn unix_bad_working_directory_init_failure_still_finishes_cleanup() {
    let mut terminal = TerminalPtyV2::start(
        std::env::temp_dir().join(format!("absent-terminal-{}", uuid::Uuid::new_v4())),
        None,
    )
    .expect("start owner");
    assert!(terminal.ready().await.is_err());
    assert!(
        tokio::time::timeout(Duration::from_secs(5), terminal.drain())
            .await
            .expect("failed init drains")
            .is_err()
    );
}

#[derive(Debug)]
struct FailingChild {
    exited: Arc<AtomicBool>,
    attempted: Arc<AtomicBool>,
    dropped: Arc<AtomicBool>,
}

impl portable_pty::ChildKiller for FailingChild {
    fn kill(&mut self) -> std::io::Result<()> {
        self.attempted.store(true, Ordering::Release);
        Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "injected kill failure",
        ))
    }
    fn clone_killer(&self) -> Box<dyn portable_pty::ChildKiller + Send + Sync> {
        Box::new(Self {
            exited: Arc::clone(&self.exited),
            attempted: Arc::clone(&self.attempted),
            dropped: Arc::clone(&self.dropped),
        })
    }
}

impl portable_pty::Child for FailingChild {
    fn try_wait(&mut self) -> std::io::Result<Option<portable_pty::ExitStatus>> {
        Ok(self
            .exited
            .load(Ordering::Acquire)
            .then(|| portable_pty::ExitStatus::with_exit_code(0)))
    }
    fn wait(&mut self) -> std::io::Result<portable_pty::ExitStatus> {
        if self.exited.load(Ordering::Acquire) {
            Ok(portable_pty::ExitStatus::with_exit_code(0))
        } else {
            Err(std::io::Error::new(
                std::io::ErrorKind::Interrupted,
                "injected wait failure",
            ))
        }
    }
    fn process_id(&self) -> Option<u32> {
        None
    }
}
impl Drop for FailingChild {
    fn drop(&mut self) {
        self.dropped.store(true, Ordering::Release);
    }
}

#[test]
fn unix_failed_kill_and_wait_keep_child_owned_until_exit_is_confirmed() {
    let exited = Arc::new(AtomicBool::new(false));
    let attempted = Arc::new(AtomicBool::new(false));
    let dropped = Arc::new(AtomicBool::new(false));
    let child = FailingChild {
        exited: Arc::clone(&exited),
        attempted: Arc::clone(&attempted),
        dropped: Arc::clone(&dropped),
    };
    let worker = std::thread::spawn(|| super::platform::close_test_child(Box::new(child)));
    for _ in 0..100 {
        if attempted.load(Ordering::Acquire) {
            break;
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    assert!(attempted.load(Ordering::Acquire));
    assert!(!worker.is_finished());
    assert!(!dropped.load(Ordering::Acquire));
    exited.store(true, Ordering::Release);
    let error = worker
        .join()
        .expect("resource owner joins")
        .expect_err("earlier failure remains observable");
    assert!(error.contains("kill"));
    assert!(dropped.load(Ordering::Acquire));
}

#[tokio::test]
async fn unix_file_working_directory_is_rejected_before_spawn() {
    let file = std::env::temp_dir().join(format!("terminal-cwd-file-{}", uuid::Uuid::new_v4()));
    std::fs::write(&file, b"not a directory").expect("create fixture file");
    let mut terminal = TerminalPtyV2::start(file.clone(), None).expect("start owner");
    assert!(terminal
        .ready()
        .await
        .expect_err("file is not cwd")
        .contains("not a directory"));
    assert!(
        tokio::time::timeout(Duration::from_secs(5), terminal.drain())
            .await
            .expect("failed init drains")
            .is_err()
    );
    std::fs::remove_file(file).expect("remove fixture");
}

#[test]
fn dropping_a_queued_owner_cancels_before_pty_initialization() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .max_blocking_threads(1)
        .build()
        .expect("test runtime");
    let (entered_tx, entered_rx) = std::sync::mpsc::channel();
    let (unblock_tx, unblock_rx) = std::sync::mpsc::channel();
    let blocker = runtime.spawn_blocking(move || {
        entered_tx.send(()).expect("announce blocker");
        unblock_rx.recv().expect("unblock pool");
    });
    entered_rx.recv().expect("pool occupied");
    runtime.block_on(async {
        let terminal = TerminalPtyV2::start(std::env::temp_dir(), None).expect("queue owner");
        let mut completion = terminal.completion.clone();
        drop(terminal);
        unblock_tx.send(()).expect("release pool");
        blocker.await.expect("blocker finishes");
        let result = tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                if let Some(result) = completion.borrow_and_update().clone() {
                    return result;
                }
                completion.changed().await.expect("reaper completion");
            }
        })
        .await
        .expect("queued cancellation drains");
        assert!(result
            .expect_err("initialization must not begin")
            .contains("initialization cancelled"));
    });
}

#[test]
fn same_foreground_and_shell_group_is_signalled_once_without_hiding_permission_errors() {
    let mut signalled = Vec::new();
    let result = super::platform::signal_process_groups(Some(42), Some(42), |group| {
        signalled.push(group);
        if signalled.len() > 1 {
            Err(std::io::Error::from_raw_os_error(libc::EPERM))
        } else {
            Ok(())
        }
    });
    assert_eq!(signalled, [42]);
    assert!(result.is_empty());
    let denied = super::platform::signal_process_groups(Some(42), Some(43), |_| {
        Err(std::io::Error::from_raw_os_error(libc::EPERM))
    });
    assert!(
        !denied.is_empty(),
        "genuine permission errors remain observable"
    );
}

#[tokio::test]
async fn repeated_real_unix_idle_and_foreground_shutdown_does_not_signal_groups_twice() {
    for iteration in 0..12 {
        let terminal = ready_terminal().await;
        if iteration % 2 == 1 {
            terminal
                .try_input(b"sleep 60\n".to_vec())
                .expect("foreground command");
            tokio::time::sleep(Duration::from_millis(40)).await;
        }
        drain_terminal(&terminal).await;
    }
}

#[tokio::test]
async fn real_unix_shell_natural_exit_is_reaped_without_signalling_its_dead_group() {
    for _ in 0..8 {
        let mut terminal = ready_terminal().await;
        terminal
            .try_input(b"exit\n".to_vec())
            .expect("request ordinary shell exit");
        tokio::time::timeout(Duration::from_secs(5), async {
            while terminal.output().await.is_some() {}
        })
        .await
        .expect("natural EOF reaches output consumer");
        drain_terminal(&terminal).await;
    }
}
