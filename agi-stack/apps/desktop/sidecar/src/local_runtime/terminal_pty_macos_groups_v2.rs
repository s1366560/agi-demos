//! macOS group termination with explicit process lifecycle and ownership checks.
//!
//! XNU killpg1 filters SZOMB members and returns EPERM when none remain. Signal
//! individual live processes instead: real permission failures remain errors.
//! The caller retains its unreaped session leader throughout this operation,
//! preventing reuse of the owned session id, and closes all PTY master handles.

use std::{
    collections::{BTreeMap, BTreeSet},
    io, mem, thread,
    time::{Duration, Instant},
};

const TERMINAL_EXIT_GRACE: Duration = Duration::from_millis(200);

/// Verify the initial members before closing the terminal requests EOF/hangup.
/// Give the shell a bounded opportunity to release its history lock before forced cleanup.
/// Process inspection never reaps the retained leader; foreground and migrated
/// groups remain owned until every live member has exited or has been killed.
/// With valid owned group/session identities, both Ok and Err return only after
/// cleanup is confirmed. Err preserves non-EPERM failures observed before
/// recovery. Raw EPERM is the XNU exit race and is dropped once no live member
/// remains. Repeated inspection failures keep this call and its owner alive.
/// Confirmed foreign sessions are excluded without signalling them.
pub(super) fn finish_owned_groups(
    groups: impl IntoIterator<Item = i32>,
    session: i32,
    release_terminal: impl FnOnce(),
) -> io::Result<()> {
    let mut groups = OwnedProcessGroups::new(groups, session, TERMINAL_EXIT_GRACE)?;
    let mut release_terminal = Some(release_terminal);
    finish_with_retries(|| {
        if release_terminal.is_some() {
            // A complete inspection must precede hangup: unverified members could
            // otherwise move, fork and exit while an earlier read error is pending.
            // This inspection never signals, even if the owner was descheduled.
            groups.sweep(&mut |_, _| {}, false)?;
            release_terminal
                .take()
                .expect("terminal release is pending")();
            groups.graceful_deadline = Instant::now() + TERMINAL_EXIT_GRACE;
        }
        groups.poll(&mut |_, _| {})
    })
}

fn finish_with_retries(mut poll: impl FnMut() -> io::Result<bool>) -> io::Result<()> {
    let mut failures = BTreeSet::new();
    loop {
        match poll() {
            Ok(true) => {
                return if failures.is_empty() {
                    Ok(())
                } else {
                    Err(io::Error::other(
                        failures.into_iter().collect::<Vec<_>>().join("; "),
                    ))
                };
            }
            Ok(false) => {}
            Err(error) => {
                // Raw EPERM is the XNU exit race. Do not keep it once a later
                // sweep confirms the owned group is empty. Every other error,
                // including a foreign-session rejection, stays on the result.
                if !super::pty_cleanup_error_remains_after_exit(&error) {
                    tracing::debug!(%error, "owned PTY group signal raced member exit");
                } else if failures.insert(error.to_string()) {
                    tracing::error!(%error, "owned PTY group cleanup is still pending");
                }
            }
        }
        // An inspection or signal failure is not proof that the owned resources
        // have exited. Keep their state and the unreaped leader until verified.
        thread::sleep(Duration::from_millis(5));
    }
}

#[cfg(test)]
pub(super) fn terminate_owned_group(group: i32, session: i32) -> io::Result<()> {
    terminate_owned_group_after_snapshot(group, session, |_, _| {})
}

#[cfg(test)]
fn terminate_owned_group_after_snapshot(
    group: i32,
    session: i32,
    after_snapshot: impl FnMut(i32, &[i32]),
) -> io::Result<()> {
    terminate_owned_groups_after_snapshot([group], session, Duration::ZERO, after_snapshot)
}

#[cfg(test)]
fn terminate_owned_groups_after_snapshot(
    groups: impl IntoIterator<Item = i32>,
    session: i32,
    grace: Duration,
    mut after_snapshot: impl FnMut(i32, &[i32]),
) -> io::Result<()> {
    let mut groups = OwnedProcessGroups::new(groups, session, grace)?;
    loop {
        if groups.poll(&mut after_snapshot)? {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(5));
    }
}

struct OwnedProcessGroups {
    groups: BTreeSet<i32>,
    known_members: BTreeSet<i32>,
    verified_members: BTreeMap<i32, MemberIdentity>,
    session: i32,
    graceful_deadline: Instant,
}

#[derive(Clone, PartialEq, Eq)]
struct MemberIdentity {
    started_seconds: u64,
    started_microseconds: u64,
    user: u32,
}

impl MemberIdentity {
    fn from_info(info: &libc::proc_bsdinfo) -> Self {
        Self {
            started_seconds: info.pbi_start_tvsec,
            started_microseconds: info.pbi_start_tvusec,
            user: info.pbi_uid,
        }
    }
}

impl OwnedProcessGroups {
    fn new(
        groups: impl IntoIterator<Item = i32>,
        session: i32,
        grace: Duration,
    ) -> io::Result<Self> {
        let groups = groups.into_iter().collect::<BTreeSet<_>>();
        if groups.is_empty() || groups.iter().any(|group| *group <= 1) || session <= 1 {
            return Err(io::Error::other("invalid owned PTY process group/session"));
        }
        Ok(Self {
            groups,
            known_members: BTreeSet::new(),
            verified_members: BTreeMap::new(),
            session,
            graceful_deadline: Instant::now() + grace,
        })
    }

    fn poll(&mut self, after_snapshot: &mut impl FnMut(i32, &[i32])) -> io::Result<bool> {
        self.sweep(after_snapshot, Instant::now() >= self.graceful_deadline)
    }

    fn sweep(
        &mut self,
        after_snapshot: &mut impl FnMut(i32, &[i32]),
        force_exit: bool,
    ) -> io::Result<bool> {
        let mut active = false;
        let previous_groups = self.groups.clone();
        for group in self.groups.clone() {
            let members = group_members(group)?;
            after_snapshot(group, &members);
            self.known_members.extend(members);
        }
        let mut remaining_members = BTreeSet::new();
        for pid in self.known_members.clone() {
            let Some(info) = process_info(pid)? else {
                self.verified_members.remove(&pid);
                continue;
            };
            let identity = MemberIdentity::from_info(&info);
            if info.pbi_status == libc::SZOMB {
                // Darwin getsid rejects zombies. Only a member verified while live,
                // with the same birth time and user, can extend our tracked groups.
                if self.verified_members.get(&pid) == Some(&identity) {
                    self.groups.insert(member_group(&info)?);
                }
                self.verified_members.remove(&pid);
                continue;
            }
            // Revalidate each numeric PID immediately before signalling. The retained
            // session leader prevents this session identity from being recycled.
            // SAFETY: getsid/geteuid take no pointers and only inspect process state.
            let actual_session = unsafe { libc::getsid(pid) };
            if actual_session == -1 {
                let error = io::Error::last_os_error();
                if error.raw_os_error() == Some(libc::ESRCH) {
                    // A verified member may have become a zombie between the BSD
                    // info and getsid calls. Inspect it again before releasing it.
                    if self.verified_members.get(&pid) == Some(&identity) {
                        remaining_members.insert(pid);
                        active = true;
                    }
                    continue;
                }
                // XNU getsid can return EPERM once the member has exited or the
                // PID has been reused. Re-read identity before treating it as a
                // permission failure on a process we still own.
                if error.raw_os_error() == Some(libc::EPERM) && !self.still_owned(pid, &identity)? {
                    continue;
                }
                return Err(error);
            }
            if actual_session != self.session {
                // An inspected foreign identity is a reused PID/group, not an
                // unconfirmed owned process. Never signal it or wait for its exit.
                self.known_members.remove(&pid);
                self.verified_members.remove(&pid);
                if let Ok(group) = i32::try_from(info.pbi_pgid) {
                    self.groups.remove(&group);
                }
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "PTY group member is outside the owned session",
                ));
            }
            if info.pbi_uid != unsafe { libc::geteuid() } {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "owned PTY group member has a different user",
                ));
            }
            // Job control can move a snapshotted member into a new group before
            // inspection. Follow that group only after verifying the retained session
            // and user, so cleanup also covers children forked after the migration.
            let owned_identity = identity.clone();
            self.verified_members.insert(pid, identity);
            self.groups.insert(member_group(&info)?);
            remaining_members.insert(pid);
            active = true;
            if !force_exit {
                continue;
            }
            // SAFETY: the positive PID was validated against the retained session.
            if unsafe { libc::kill(pid, libc::SIGKILL) } == -1 {
                let error = io::Error::last_os_error();
                if error.raw_os_error() == Some(libc::EPERM)
                    && !self.still_owned(pid, &owned_identity)?
                {
                    remaining_members.remove(&pid);
                    continue;
                }
                if error.raw_os_error() != Some(libc::ESRCH) {
                    return Err(error);
                }
            }
        }
        self.known_members = remaining_members;
        // Enumerate again after exit so children forked during the snapshot are also
        // covered. Never report completion while an owned live member remains.
        Ok(!active && self.groups == previous_groups)
    }

    /// True when `pid` is still the same live process observed at the start of this sweep.
    /// A zombie cannot be signalled; the retained leader reaps it.
    fn still_owned(&mut self, pid: i32, identity: &MemberIdentity) -> io::Result<bool> {
        match process_info(pid)? {
            Some(info)
                if info.pbi_status != libc::SZOMB
                    && MemberIdentity::from_info(&info) == *identity =>
            {
                Ok(true)
            }
            _ => {
                self.verified_members.remove(&pid);
                self.known_members.remove(&pid);
                Ok(false)
            }
        }
    }
}

fn member_group(info: &libc::proc_bsdinfo) -> io::Result<i32> {
    i32::try_from(info.pbi_pgid)
        .ok()
        .filter(|group| *group > 1)
        .ok_or_else(|| io::Error::other("owned PTY member has an invalid group"))
}

fn group_members(group: i32) -> io::Result<Vec<i32>> {
    let mut members = vec![0_i32; 32];
    loop {
        let bytes = i32::try_from(members.len() * mem::size_of::<i32>())
            .map_err(|_| io::Error::other("PTY group membership exceeds buffer limit"))?;
        // PROC_PGRP_ONLY is the libproc selector declared in sys/proc_info.h.
        // SAFETY: the initialized, aligned vector owns the supplied writable range.
        let written = libproc_call(|| unsafe {
            libc::proc_listpids(2, group as u32, members.as_mut_ptr().cast(), bytes)
        })?;
        if written == bytes as usize {
            members.resize(members.len() * 2, 0);
            continue;
        }
        members.truncate(written / mem::size_of::<i32>());
        members.retain(|pid| *pid > 1);
        return Ok(members);
    }
}

fn libproc_call(call: impl FnOnce() -> i32) -> io::Result<usize> {
    // libproc maps syscall failure to zero, which also represents an empty list.
    // errno is thread-local; capture it before any other call or formatting.
    // SAFETY: __error returns this thread's valid errno storage on macOS.
    unsafe { *libc::__error() = 0 };
    let written = call();
    let error = unsafe { *libc::__error() };
    if written < 0 || (written == 0 && error != 0) {
        return Err(if error == 0 {
            io::Error::other("libproc failed without errno")
        } else {
            io::Error::from_raw_os_error(error)
        });
    }
    Ok(written as usize)
}

fn process_info(pid: i32) -> io::Result<Option<libc::proc_bsdinfo>> {
    process_info_with(|buffer, bytes| {
        // XNU PROC_PIDTBSDINFO arg=1 includes retained zombies. Their birth time
        // and pgid remain readable even though getsid returns ESRCH after exit.
        // https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/proc_info.c#L2046-L2051
        // SAFETY: the caller owns the complete initialized output buffer.
        unsafe { libc::proc_pidinfo(pid, libc::PROC_PIDTBSDINFO, 1, buffer, bytes) }
    })
}

fn process_info_with(
    call: impl FnOnce(*mut libc::c_void, i32) -> i32,
) -> io::Result<Option<libc::proc_bsdinfo>> {
    let mut info = mem::MaybeUninit::<libc::proc_bsdinfo>::zeroed();
    let bytes = mem::size_of::<libc::proc_bsdinfo>();
    match libproc_call(|| call(info.as_mut_ptr().cast(), bytes as i32)) {
        Ok(written) if written == bytes => {
            // SAFETY: libproc returned the complete initialized structure.
            Ok(Some(unsafe { info.assume_init() }))
        }
        Ok(written) => Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("libproc BSD info returned {written} bytes; expected {bytes}"),
        )),
        Err(error) if error.raw_os_error() == Some(libc::ESRCH) => Ok(None),
        Err(error) => Err(error),
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
    fn raw_eperm_is_not_retained_after_the_group_is_confirmed_empty() {
        let mut polls = 0;
        let result = finish_with_retries(|| {
            polls += 1;
            if polls == 1 {
                Err(io::Error::from_raw_os_error(libc::EPERM))
            } else {
                Ok(true)
            }
        });
        assert_eq!(polls, 2);
        result.expect("exiting member EPERM does not fail confirmed cleanup");
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

#[cfg(test)]
#[path = "terminal_pty_macos_migration_tests.rs"]
mod migration_tests;

#[cfg(test)]
#[path = "terminal_pty_macos_libproc_tests.rs"]
mod libproc_tests;

#[cfg(test)]
#[path = "terminal_pty_macos_grace_migration_tests.rs"]
mod grace_migration_tests;
