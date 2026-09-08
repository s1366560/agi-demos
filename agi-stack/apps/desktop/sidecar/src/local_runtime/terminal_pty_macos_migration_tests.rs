//! A real setpgid barrier exercises membership changes between snapshot and signal.

use super::*;
use std::{
    io::{Read, Write},
    os::{fd::AsRawFd, unix::net::UnixStream},
};

struct RetainedSession {
    leader: i32,
    member: i32,
    descendant: i32,
}

impl Drop for RetainedSession {
    fn drop(&mut self) {
        // Successful cleanup may already have reaped indirect children. Revalidate
        // their current session before fallback signalling so reused PIDs are skipped.
        for pid in group_members(self.member)
            .unwrap_or_default()
            .into_iter()
            .chain([self.member, self.descendant])
        {
            // SAFETY: the retained leader prevents reuse of this session identity.
            if pid > 1 && unsafe { libc::getsid(pid) } == self.leader {
                unsafe { libc::kill(pid, libc::SIGKILL) };
            }
        }
        // SAFETY: the direct leader remains unreaped, retaining its numeric identity.
        unsafe {
            libc::kill(-self.leader, libc::SIGKILL);
            libc::kill(self.leader, libc::SIGKILL);
            libc::waitpid(self.leader, std::ptr::null_mut(), 0);
        }
    }
}

#[test]
fn real_member_moving_after_snapshot_is_terminated_before_cleanup_succeeds() {
    let (mut pid_reader, pid_writer) = UnixStream::pair().expect("PID pipe");
    let (gate_reader, mut gate_writer) = UnixStream::pair().expect("migration gate");
    let (mut ready_reader, ready_writer) = UnixStream::pair().expect("migration receipt");
    pid_reader
        .set_read_timeout(Some(Duration::from_secs(5)))
        .expect("PID deadline");
    ready_reader
        .set_read_timeout(Some(Duration::from_secs(5)))
        .expect("migration deadline");
    let pid_fd = pid_writer.as_raw_fd();
    let gate_fd = gate_reader.as_raw_fd();
    let ready_fd = ready_writer.as_raw_fd();
    // SAFETY: after fork, children execute only async-signal-safe syscalls and never
    // return to the multi-threaded Rust test harness. The parent retains the leader.
    let leader = unsafe {
        let leader = libc::fork();
        if leader == 0 {
            if libc::setsid() == -1 {
                libc::_exit(90);
            }
            let member = libc::fork();
            if member < 0 {
                libc::_exit(91);
            }
            if member == 0 {
                let mut byte = 0_u8;
                if libc::read(gate_fd, (&mut byte as *mut u8).cast(), 1) != 1
                    || libc::setpgid(0, 0) == -1
                {
                    libc::_exit(92);
                }
                let descendant = libc::fork();
                if descendant < 0 {
                    libc::_exit(94);
                }
                if descendant > 0
                    && libc::write(
                        ready_fd,
                        (&descendant as *const i32).cast(),
                        mem::size_of::<i32>(),
                    ) != mem::size_of::<i32>() as isize
                {
                    libc::_exit(95);
                }
            } else if libc::write(
                pid_fd,
                (&member as *const i32).cast(),
                mem::size_of::<i32>(),
            ) != mem::size_of::<i32>() as isize
            {
                libc::_exit(93);
            }
            loop {
                libc::pause();
            }
        }
        leader
    };
    assert!(leader > 1, "fork retained session leader");
    let mut owned = RetainedSession {
        leader,
        member: leader,
        descendant: 0,
    };
    let mut bytes = [0; mem::size_of::<i32>()];
    pid_reader.read_exact(&mut bytes).expect("owned member PID");
    let member = i32::from_ne_bytes(bytes);
    owned.member = member;
    assert!(group_members(leader)
        .expect("initial group")
        .contains(&member));
    let mut migrated = false;
    let cleanup = terminate_owned_group_after_snapshot(leader, leader, |group, members| {
        if group == leader && !migrated {
            assert!(
                members.contains(&member),
                "snapshot includes the live member"
            );
            gate_writer.write_all(b"x").expect("allow setpgid");
            let mut descendant = [0; mem::size_of::<i32>()];
            ready_reader
                .read_exact(&mut descendant)
                .expect("setpgid and descendant fork completed");
            owned.descendant = i32::from_ne_bytes(descendant);
            assert!(!members.contains(&owned.descendant));
            assert_eq!(unsafe { libc::getpgid(owned.descendant) }, member);
            assert_eq!(unsafe { libc::getpgid(member) }, member);
            assert_eq!(unsafe { libc::getsid(member) }, leader);
            migrated = true;
        }
    });
    let mut live = true;
    for _ in 0..100 {
        live = [member, owned.descendant].into_iter().any(|pid| {
            process_info(pid)
                .expect("inspect migrated group member")
                .is_some_and(|info| info.pbi_status != libc::SZOMB)
        });
        if !live {
            break;
        }
        thread::sleep(Duration::from_millis(5));
    }
    // Inspect before the guard's fallback cleanup: success must establish exit itself.
    drop(owned);
    assert!(migrated, "test exercised the snapshot-to-setpgid race");
    cleanup.expect("cleanup follows the verified owned member into its new group");
    assert!(
        !live,
        "successful cleanup must not leave the migrated group alive"
    );
}
