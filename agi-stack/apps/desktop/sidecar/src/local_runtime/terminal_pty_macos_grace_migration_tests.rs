//! Graceful shutdown must retain members that migrate between group scans.

use super::*;
use std::{
    io::Read,
    os::{fd::AsRawFd, unix::net::UnixStream, unix::process::CommandExt},
    process::{Child, Command},
    sync::atomic::{AtomicBool, Ordering},
};

static HANGUP_RECEIVED: AtomicBool = AtomicBool::new(false);

extern "C" fn receive_hangup(_: libc::c_int) {
    HANGUP_RECEIVED.store(true, Ordering::Relaxed);
}

struct RetainedTree {
    leader: i32,
    member: i32,
    barrier: i32,
    descendant: i32,
}

impl Drop for RetainedTree {
    fn drop(&mut self) {
        for group in [self.leader, self.member, self.barrier] {
            if group <= 1 {
                continue;
            }
            for pid in group_members(group).unwrap_or_default().into_iter().chain([
                self.member,
                self.barrier,
                self.descendant,
            ]) {
                // SAFETY: the direct leader stays unreaped until the final wait.
                if pid > 1 && unsafe { libc::getsid(pid) } == self.leader {
                    unsafe { libc::kill(pid, libc::SIGKILL) };
                }
            }
        }
        // SAFETY: this is our retained direct child, never a recyclable PID.
        unsafe {
            libc::kill(self.leader, libc::SIGKILL);
            libc::waitpid(self.leader, std::ptr::null_mut(), 0);
        }
    }
}

#[test]
fn grace_follows_a_member_that_moves_and_exits_between_group_scans() {
    let (mut pid_reader, pid_writer) = UnixStream::pair().expect("initial process IDs");
    let (mut ready_reader, ready_writer) = UnixStream::pair().expect("migration receipt");
    pid_reader
        .set_read_timeout(Some(Duration::from_secs(5)))
        .expect("initial process deadline");
    ready_reader
        .set_read_timeout(Some(Duration::from_secs(5)))
        .expect("migration deadline");
    let pid_fd = pid_writer.as_raw_fd();
    let ready_fd = ready_writer.as_raw_fd();
    // SAFETY: forked children only execute async-signal-safe syscalls and lock-free
    // atomic operations, and never return to the multithreaded Rust harness.
    let leader = unsafe {
        let leader = libc::fork();
        if leader == 0 {
            if libc::setsid() == -1 {
                libc::_exit(90);
            }
            let mut child_action = mem::MaybeUninit::<libc::sigaction>::zeroed().assume_init();
            child_action.sa_sigaction = libc::SIG_DFL;
            if libc::sigemptyset(&mut child_action.sa_mask) == -1
                || libc::sigaction(libc::SIGCHLD, &child_action, std::ptr::null_mut()) == -1
            {
                libc::_exit(102);
            }
            let mut blocked = mem::MaybeUninit::<libc::sigset_t>::zeroed().assume_init();
            if libc::sigemptyset(&mut blocked) == -1
                || libc::sigaddset(&mut blocked, libc::SIGHUP) == -1
                || libc::sigprocmask(libc::SIG_BLOCK, &blocked, std::ptr::null_mut()) == -1
            {
                libc::_exit(91);
            }
            let member = libc::fork();
            if member < 0 {
                libc::_exit(92);
            }
            if member == 0 {
                let mut unblocked = mem::MaybeUninit::<libc::sigset_t>::zeroed().assume_init();
                if libc::signal(
                    libc::SIGHUP,
                    receive_hangup as *const () as libc::sighandler_t,
                ) == libc::SIG_ERR
                    || libc::sigemptyset(&mut unblocked) == -1
                {
                    libc::_exit(93);
                }
                while !HANGUP_RECEIVED.load(Ordering::Relaxed) {
                    libc::sigsuspend(&unblocked);
                }
                if libc::setpgid(0, 0) == -1 {
                    libc::_exit(101);
                }
                let descendant = libc::fork();
                if descendant < 0 {
                    libc::_exit(94);
                }
                if descendant == 0 {
                    if libc::signal(libc::SIGHUP, libc::SIG_IGN) == libc::SIG_ERR
                        || libc::signal(libc::SIGTERM, libc::SIG_IGN) == libc::SIG_ERR
                        || libc::sigprocmask(libc::SIG_UNBLOCK, &blocked, std::ptr::null_mut())
                            == -1
                    {
                        libc::_exit(95);
                    }
                    let pid = libc::getpid();
                    if libc::write(ready_fd, (&pid as *const i32).cast(), mem::size_of::<i32>())
                        != mem::size_of::<i32>() as isize
                    {
                        libc::_exit(96);
                    }
                    loop {
                        libc::pause();
                    }
                }
                // The leader deliberately never waits for this member. Its zombie
                // retains the migrated pgid while the descendant remains alive.
                libc::_exit(0);
            }
            let barrier = libc::fork();
            if barrier < 0 {
                libc::_exit(97);
            }
            if barrier == 0 {
                loop {
                    libc::pause();
                }
            }
            if libc::setpgid(barrier, barrier) == -1 {
                libc::_exit(98);
            }
            // Scan the lower-numbered group first. On the second sweep its hook
            // moves this member before its old, higher-numbered group is listed.
            let session = libc::getpid();
            let source_group = if barrier > session { barrier } else { session };
            if libc::setpgid(member, source_group) == -1 {
                libc::_exit(100);
            }
            let pids = [member, barrier];
            if libc::write(pid_fd, pids.as_ptr().cast(), mem::size_of_val(&pids))
                != mem::size_of_val(&pids) as isize
            {
                libc::_exit(99);
            }
            loop {
                libc::pause();
            }
        }
        leader
    };
    assert!(leader > 1, "fork retained session leader");
    let mut tree = RetainedTree {
        leader,
        member: 0,
        barrier: 0,
        descendant: 0,
    };
    let mut bytes = [0_u8; mem::size_of::<i32>()];
    pid_reader.read_exact(&mut bytes).expect("member PID");
    tree.member = i32::from_ne_bytes(bytes);
    pid_reader
        .read_exact(&mut bytes)
        .expect("barrier group PID");
    tree.barrier = i32::from_ne_bytes(bytes);
    let source_group = leader.max(tree.barrier);
    let trigger_group = leader.min(tree.barrier);
    let mut source_group_seen = false;
    let mut migrated = false;
    let mut old_group_was_empty = false;
    let started = Instant::now();
    let cleanup = terminate_owned_groups_after_snapshot(
        [leader, tree.barrier],
        leader,
        TERMINAL_EXIT_GRACE,
        |group, members| {
            if group == source_group && !source_group_seen {
                assert!(members.contains(&tree.member), "first scan owns the member");
                source_group_seen = true;
            } else if group == source_group && migrated {
                old_group_was_empty |= !members.contains(&tree.member);
            }
            if group != trigger_group || !source_group_seen || migrated {
                return;
            }
            // One complete sweep recorded the member. Trigger migration before
            // the second sweep enumerates its old group, which will no longer
            // contain it: only the retained member identity can find the new group.
            assert_eq!(unsafe { libc::kill(tree.member, libc::SIGHUP) }, 0);
            ready_reader
                .read_exact(&mut bytes)
                .expect("descendant installed ignored hangup and termination signals");
            tree.descendant = i32::from_ne_bytes(bytes);
            let deadline = Instant::now() + Duration::from_secs(5);
            while process_info(tree.member)
                .expect("inspect migrated parent")
                .is_some_and(|info| info.pbi_status != libc::SZOMB)
                && Instant::now() < deadline
            {
                thread::sleep(Duration::from_millis(1));
            }
            assert!(process_info(tree.member)
                .expect("migrated parent remains retained")
                .is_some_and(|info| info.pbi_status == libc::SZOMB));
            assert_eq!(unsafe { libc::getpgid(tree.descendant) }, tree.member);
            // Darwin excludes zombies from getsid even while libproc's explicit
            // zombie query can still expose their retained process identity/pgid.
            assert_eq!(unsafe { libc::getsid(tree.member) }, -1);
            assert_eq!(io::Error::last_os_error().raw_os_error(), Some(libc::ESRCH));
            assert_eq!(unsafe { libc::kill(tree.descendant, libc::SIGHUP) }, 0);
            assert_eq!(unsafe { libc::kill(tree.descendant, libc::SIGTERM) }, 0);
            assert!(process_info(tree.descendant)
                .expect("inspect signal-resistant descendant")
                .is_some_and(|info| info.pbi_status != libc::SZOMB));
            migrated = true;
        },
    );
    let descendant_alive = process_info(tree.descendant)
        .expect("inspect descendant before fallback cleanup")
        .is_some_and(|info| info.pbi_status != libc::SZOMB);
    drop(tree);
    cleanup.expect("both retained groups and the migrated group finish");
    assert!(migrated, "HUP exercised migration and parent exit");
    assert!(
        old_group_was_empty,
        "the old group no longer exposes the member"
    );
    assert!(started.elapsed() >= TERMINAL_EXIT_GRACE);
    assert!(
        !descendant_alive,
        "cleanup must not release a surviving descendant"
    );
}

struct RetainedChild(Child);

impl RetainedChild {
    fn start() -> Self {
        let mut command = Command::new("/bin/sh");
        command.args(["-c", "exec sleep 60"]);
        // SAFETY: the child executes only the async-signal-safe setsid before exec.
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() == -1 {
                    Err(io::Error::last_os_error())
                } else {
                    Ok(())
                }
            });
        }
        Self(command.spawn().expect("spawn retained private session"))
    }

    fn pid(&self) -> i32 {
        i32::try_from(self.0.id()).expect("native child PID")
    }

    fn is_alive(&self) -> bool {
        process_info(self.pid())
            .expect("inspect retained private child")
            .is_some_and(|info| info.pbi_status != libc::SZOMB)
    }
}

impl Drop for RetainedChild {
    fn drop(&mut self) {
        // This is std::process::Child, whose kill is SIGKILL, not portable-pty's
        // SIGHUP helper. The direct child has never been reaped before this point.
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn transient_cleanup_error_retains_real_child_until_retry_confirms_exit() {
    let child = RetainedChild::start();
    let pid = child.pid();
    let mut groups =
        OwnedProcessGroups::new([pid], pid, Duration::from_secs(60)).expect("owned groups");
    assert!(!groups.poll(&mut |_, _| {}).expect("initial live sweep"));
    assert!(groups.known_members.contains(&pid));
    assert!(child.is_alive());
    let mut polls = 0;
    let deadline = Instant::now() + Duration::from_secs(5);
    let result = finish_with_retries(|| {
        assert!(
            Instant::now() < deadline,
            "cleanup retries must eventually finish"
        );
        polls += 1;
        if polls == 1 {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "injected owned group inspection failure",
            ));
        }
        if polls == 2 {
            assert!(child.is_alive(), "an error cannot establish process exit");
            assert!(
                groups.known_members.contains(&pid),
                "retry retains ownership"
            );
            groups.graceful_deadline = Instant::now();
        }
        groups.poll(&mut |_, _| {})
    });
    assert!(
        polls >= 3,
        "a live sweep requires a later exit confirmation"
    );
    assert!(
        !child.is_alive(),
        "completion must precede fallback cleanup"
    );
    assert!(result
        .expect_err("the earlier error remains observable after cleanup")
        .to_string()
        .contains("injected owned group inspection failure"));
}

#[test]
fn foreign_session_is_not_signalled_or_retained_by_cleanup_retries() {
    let owner = RetainedChild::start();
    let foreign = RetainedChild::start();
    let mut groups = OwnedProcessGroups::new([foreign.pid()], owner.pid(), Duration::ZERO)
        .expect("candidate process group");
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut polls = 0;
    let result = finish_with_retries(|| {
        assert!(
            Instant::now() < deadline,
            "foreign resources cannot block cleanup"
        );
        polls += 1;
        groups.poll(&mut |_, _| {})
    });
    assert_eq!(
        polls, 2,
        "reject the foreign group, then confirm no owned resources"
    );
    assert!(result
        .expect_err("the foreign identity remains observable")
        .to_string()
        .contains("outside the owned session"));
    assert!(
        foreign.is_alive(),
        "ownership rejection must not signal the foreign child"
    );
    assert!(
        owner.is_alive(),
        "the unrelated retained owner remains alive"
    );
    terminate_owned_group(foreign.pid(), foreign.pid()).expect("explicit foreign-owner cleanup");
    terminate_owned_group(owner.pid(), owner.pid()).expect("explicit owner cleanup");
}

#[test]
fn unverified_or_reused_zombie_identity_cannot_extend_owned_groups() {
    let owner = RetainedChild::start();
    let mut candidate = RetainedChild::start();
    candidate
        .0
        .kill()
        .expect("stop candidate without reaping it");
    let deadline = Instant::now() + Duration::from_secs(5);
    let zombie = loop {
        if let Some(info) = process_info(candidate.pid()).expect("inspect retained candidate") {
            if info.pbi_status == libc::SZOMB {
                break info;
            }
        }
        assert!(
            Instant::now() < deadline,
            "candidate must become a retained zombie"
        );
        thread::sleep(Duration::from_millis(1));
    };
    for mismatch in 0..4 {
        let mut groups =
            OwnedProcessGroups::new([owner.pid()], owner.pid(), Duration::from_secs(60))
                .expect("retained owner group");
        groups.known_members.insert(candidate.pid());
        if mismatch != 0 {
            let mut identity = MemberIdentity::from_info(&zombie);
            match mismatch {
                1 => identity.started_seconds ^= 1,
                2 => identity.started_microseconds ^= 1,
                3 => identity.user = identity.user.wrapping_add(1),
                _ => unreachable!(),
            }
            groups.verified_members.insert(candidate.pid(), identity);
        }
        assert!(!groups
            .sweep(&mut |_, _| {}, false)
            .expect("read-only identity sweep"));
        assert!(
            owner.is_alive(),
            "identity inspection must not signal the owner"
        );
        assert!(
            !groups.groups.contains(&candidate.pid()),
            "unverified or stale zombie identity cannot grant its process group"
        );
        assert!(!groups.verified_members.contains_key(&candidate.pid()));
    }
    terminate_owned_group(owner.pid(), owner.pid()).expect("explicit owner cleanup");
}
