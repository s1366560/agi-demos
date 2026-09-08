//! macOS group termination with explicit process lifecycle and ownership checks.
//!
//! XNU killpg1 filters SZOMB members and returns EPERM when none remain. Signal
//! individual live processes instead: real permission failures remain errors.
//! The caller retains its unreaped session leader throughout this operation,
//! preventing reuse of the owned session id, and closes all PTY master handles.

use std::{io, mem, thread, time::Duration};

pub(super) fn terminate_owned_group(group: i32, session: i32) -> io::Result<()> {
    if group <= 1 || session <= 1 {
        return Err(io::Error::other("invalid owned PTY process group/session"));
    }
    loop {
        let mut active = false;
        for pid in group_members(group)? {
            let Some(info) = process_info(pid)? else {
                continue;
            };
            if info.pbi_status == libc::SZOMB {
                continue;
            }
            // Revalidate each numeric PID immediately before signalling. The retained
            // session leader prevents this session identity from being recycled.
            // SAFETY: getsid/geteuid take no pointers and only inspect process state.
            let actual_session = unsafe { libc::getsid(pid) };
            if actual_session == -1 {
                let error = io::Error::last_os_error();
                if error.raw_os_error() == Some(libc::ESRCH) {
                    continue;
                }
                return Err(error);
            }
            if actual_session != session
                || info.pbi_pgid != group as u32
                || info.pbi_uid != unsafe { libc::geteuid() }
            {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "PTY group member is outside the owned user/session",
                ));
            }
            active = true;
            // SAFETY: the positive PID was validated against the retained session.
            if unsafe { libc::kill(pid, libc::SIGKILL) } == -1 {
                let error = io::Error::last_os_error();
                if error.raw_os_error() != Some(libc::ESRCH) {
                    return Err(error);
                }
            }
        }
        if !active {
            return Ok(());
        }
        // Enumerate again after exit so children forked during the snapshot are also
        // covered. Never report completion while an owned live member remains.
        thread::sleep(Duration::from_millis(5));
    }
}

fn group_members(group: i32) -> io::Result<Vec<i32>> {
    let mut members = vec![0_i32; 32];
    loop {
        let bytes = i32::try_from(members.len() * mem::size_of::<i32>())
            .map_err(|_| io::Error::other("PTY group membership exceeds buffer limit"))?;
        // PROC_PGRP_ONLY is the libproc selector declared in sys/proc_info.h.
        // SAFETY: the initialized, aligned vector owns the supplied writable range.
        let written =
            unsafe { libc::proc_listpids(2, group as u32, members.as_mut_ptr().cast(), bytes) };
        if written < 0 {
            return Err(io::Error::last_os_error());
        }
        if written == bytes {
            members.resize(members.len() * 2, 0);
            continue;
        }
        members.truncate(written as usize / mem::size_of::<i32>());
        members.retain(|pid| *pid > 1);
        return Ok(members);
    }
}

fn process_info(pid: i32) -> io::Result<Option<libc::proc_bsdinfo>> {
    let mut info = mem::MaybeUninit::<libc::proc_bsdinfo>::zeroed();
    let bytes = mem::size_of::<libc::proc_bsdinfo>() as i32;
    // SAFETY: the output pointer owns exactly the requested struct-sized buffer.
    let written = unsafe {
        libc::proc_pidinfo(
            pid,
            libc::PROC_PIDTBSDINFO,
            0,
            info.as_mut_ptr().cast(),
            bytes,
        )
    };
    if written == bytes {
        // SAFETY: libproc returned the complete initialized structure.
        return Ok(Some(unsafe { info.assume_init() }));
    }
    let error = io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ESRCH) {
        Ok(None)
    } else {
        Err(error)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{io::Read, os::unix::process::CommandExt, process::Command};

    fn session_child(script: &str) -> std::process::Child {
        let mut command = Command::new("/bin/sh");
        command.arg("-c").arg(script);
        // SAFETY: only the async-signal-safe setsid syscall executes after fork.
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() == -1 {
                    Err(io::Error::last_os_error())
                } else {
                    Ok(())
                }
            });
        }
        command.spawn().expect("spawn owned session")
    }

    #[test]
    fn real_zombie_group_completes_without_ambiguous_group_signal() {
        let mut child = session_child("exit 0");
        let pid = child.id() as i32;
        let mut status = mem::MaybeUninit::<libc::siginfo_t>::zeroed();
        // SAFETY: this is our retained child; WNOWAIT observes exit without reaping.
        assert_eq!(
            unsafe {
                libc::waitid(
                    libc::P_PID,
                    child.id(),
                    status.as_mut_ptr(),
                    libc::WEXITED | libc::WNOWAIT,
                )
            },
            0
        );
        // Reproduce the kernel condition that broke the old PTY cleanup.
        assert_eq!(unsafe { libc::kill(-pid, libc::SIGKILL) }, -1);
        assert_eq!(io::Error::last_os_error().raw_os_error(), Some(libc::EPERM));
        let result = terminate_owned_group(pid, pid);
        let exit = child.wait().expect("reap retained child");
        result.expect("zombie-only group has no live resources");
        assert!(exit.success());
    }

    #[test]
    fn real_foreign_session_is_rejected_without_signalling_then_owned_group_is_reaped() {
        let mut child = session_child("exec sleep 60");
        let pid = child.id() as i32;
        let rejected = terminate_owned_group(pid, pid + 1);
        let alive = child.try_wait().expect("inspect retained child").is_none();
        let cleanup = terminate_owned_group(pid, pid);
        child.wait().expect("reap owned child");
        assert_eq!(
            rejected.expect_err("foreign session").kind(),
            io::ErrorKind::PermissionDenied
        );
        assert!(alive, "ownership rejection must not signal the child");
        cleanup.expect("owned member is terminated");
    }

    #[test]
    fn real_large_owned_group_is_fully_enumerated_and_terminated() {
        let marker = std::env::temp_dir().join(format!("pty-group-{}", uuid::Uuid::new_v4()));
        let script = format!(
            "i=0; while [ $i -lt 40 ]; do sleep 60 & i=$((i+1)); done; echo ready > '{}'; wait",
            marker.display()
        );
        let mut child = session_child(&script);
        let pid = child.id() as i32;
        let mut ready = false;
        for _ in 0..500 {
            let mut content = String::new();
            if let Ok(mut file) = std::fs::File::open(&marker) {
                file.read_to_string(&mut content)
                    .expect("read child marker");
            }
            if content == "ready\n" {
                ready = true;
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
        let members = group_members(pid);
        let cleanup = terminate_owned_group(pid, pid);
        child.wait().expect("reap shell after group termination");
        let _ = std::fs::remove_file(&marker);
        assert!(ready, "all foreground group members started");
        assert!(members.expect("enumerate group").len() > 32);
        cleanup.expect("every live group member terminated");
    }
}
