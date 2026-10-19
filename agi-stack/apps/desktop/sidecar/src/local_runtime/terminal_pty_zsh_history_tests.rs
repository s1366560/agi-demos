//! Actual shell cleanup with private startup files and history, never the user's history.

use super::*;
use std::{fs, os::unix::fs::PermissionsExt, time::Duration};

struct ShellFixture {
    root: PathBuf,
    command: PathBuf,
}

impl ShellFixture {
    fn new(script: impl FnOnce(&std::path::Path) -> String) -> Self {
        let root = std::env::temp_dir().join(format!("terminal-shell-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).expect("create private shell fixture");
        let command = root.join("shell");
        fs::write(&command, script(&root)).expect("write shell command");
        fs::set_permissions(&command, fs::Permissions::from_mode(0o700))
            .expect("make shell command executable");
        Self { root, command }
    }

    async fn start(&self) -> TerminalPtyV2 {
        let mut terminal =
            TerminalPtyV2::start_internal(self.root.clone(), None, Some(self.command.clone()))
                .expect("start real shell owner");
        tokio::time::timeout(Duration::from_secs(5), terminal.ready())
            .await
            .expect("shell initialization deadline")
            .expect("real shell ready");
        terminal
    }
}

impl Drop for ShellFixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn shell_quote(path: &std::path::Path) -> String {
    format!("'{}'", path.to_string_lossy().replace('\'', "'\\''"))
}

async fn wait_for_output(terminal: &mut TerminalPtyV2, marker: &str) {
    tokio::time::timeout(Duration::from_secs(10), async {
        let mut output = String::new();
        while !output.contains(marker) {
            output.push_str(
                &terminal
                    .output()
                    .await
                    .expect("real shell remains connected"),
            );
        }
    })
    .await
    .expect("real shell must execute within the original terminal deadline");
}

async fn drain(terminal: &TerminalPtyV2) {
    terminal.shutdown();
    assert!(terminal.try_input(b"must not execute\n".to_vec()).is_err());
    tokio::time::timeout(Duration::from_secs(5), terminal.drain())
        .await
        .expect("owned shell must be reaped within the cleanup deadline")
        .expect("real shell cleanup succeeds");
}

#[tokio::test]
async fn zsh_shutdown_releases_private_history_lock_before_the_next_session() {
    let fixture = ShellFixture::new(|root| {
        let history = root.join("history");
        fs::write(
            root.join(".zshrc"),
            format!(
                "HISTFILE={}\nHISTSIZE=1000\nSAVEHIST=1000\n\
                 setopt SHARE_HISTORY EXTENDED_HISTORY APPEND_HISTORY\nPS1='ready> '\n",
                shell_quote(&history),
            ),
        )
        .expect("write private zsh startup file");
        format!(
            "#!/bin/sh\nexport ZDOTDIR={}\nexec /bin/zsh\n",
            shell_quote(root),
        )
    });
    for _ in 0..2 {
        let mut terminal = fixture.start().await;
        // Input echo contains no complete marker, so only actual printf execution can pass.
        terminal
            .try_input(b"printf '__AGISTACK_%s__\\n' HISTORY_READY\n".to_vec())
            .expect("send actual shell command");
        wait_for_output(&mut terminal, "__AGISTACK_HISTORY_READY__").await;
        drain(&terminal).await;
        assert!(
            fixture.root.join("history").is_file(),
            "private history was used"
        );
        let lock = fs::symlink_metadata(fixture.root.join("history.LOCK"));
        assert!(
            matches!(lock, Err(error) if error.kind() == std::io::ErrorKind::NotFound),
            "shutdown must release even a dangling zsh history lock symlink",
        );
    }
}

#[tokio::test]
async fn shell_ignoring_hangup_and_termination_is_forced_to_exit_after_grace() {
    let fixture = ShellFixture::new(|root| {
        format!(
            "#!/bin/sh\ntrap '' HUP TERM\nprintf '%s\\n' \"$$\" > {}\n\
             printf '__AGISTACK_IGNORE_SIGNALS_READY__\\n'\nwhile :; do :; done\n",
            shell_quote(&root.join("pid")),
        )
    });
    let mut terminal = fixture.start().await;
    wait_for_output(&mut terminal, "__AGISTACK_IGNORE_SIGNALS_READY__").await;
    let pid: i32 = fs::read_to_string(fixture.root.join("pid"))
        .expect("read owned process id")
        .trim()
        .parse()
        .expect("owned process id");
    // SAFETY: signal zero only inspects the process created by this private fixture.
    assert_eq!(unsafe { libc::kill(pid, 0) }, 0);
    drain(&terminal).await;
    assert_eq!(unsafe { libc::kill(pid, 0) }, -1);
    assert_eq!(
        std::io::Error::last_os_error().raw_os_error(),
        Some(libc::ESRCH)
    );
}
