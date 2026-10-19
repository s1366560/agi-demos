//! Pins an OS-reported parent process and its image; private IPC never supplies a PID.
use crate::backend::{NativeError, Result};
fn error() -> NativeError {
    NativeError::new(
        "guardian_parent_unavailable",
        "native parent identity could not be pinned",
    )
}

#[cfg(target_os = "linux")]
pub struct Parent {
    fd: std::os::fd::OwnedFd,
    pid: i32,
    created: u64,
}
#[cfg(target_os = "linux")]
impl Parent {
    fn creation(pid: i32) -> Result<u64> {
        let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).map_err(|_| error())?;
        stat.rsplit_once(')')
            .and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse().ok())
            .ok_or_else(error)
    }
    pub fn current() -> Result<Self> {
        use std::os::{fd::FromRawFd, unix::fs::MetadataExt};
        let pid = unsafe { libc::getppid() };
        let own = std::fs::metadata("/proc/self/exe").map_err(|_| error())?;
        let parent = std::fs::metadata(format!("/proc/{pid}/exe")).map_err(|_| error())?;
        if pid <= 1 || own.dev() != parent.dev() || own.ino() != parent.ino() {
            return Err(error());
        }
        let created = Self::creation(pid)?;
        let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) } as i32;
        if fd < 0 {
            return Err(error());
        }
        let fd = unsafe { std::os::fd::OwnedFd::from_raw_fd(fd) };
        if Self::creation(pid)? != created || unsafe { libc::getppid() } != pid {
            return Err(error());
        }
        Ok(Self { fd, pid, created })
    }
    pub fn alive(&self) -> bool {
        use std::os::fd::AsRawFd;
        let mut poll = libc::pollfd {
            fd: self.fd.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        (unsafe { libc::poll(&mut poll, 1, 0) }) == 0
    }
    pub fn terminate(&self) {
        use std::os::fd::AsRawFd;
        if !self.alive() || Self::creation(self.pid).ok() != Some(self.created) {
            return;
        }
        unsafe {
            libc::syscall(
                libc::SYS_pidfd_send_signal,
                self.fd.as_raw_fd(),
                libc::SIGTERM,
                std::ptr::null::<libc::siginfo_t>(),
                0,
            );
        }
        for _ in 0..40 {
            if !self.alive() {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
        unsafe {
            libc::syscall(
                libc::SYS_pidfd_send_signal,
                self.fd.as_raw_fd(),
                libc::SIGKILL,
                std::ptr::null::<libc::siginfo_t>(),
                0,
            );
        }
        for _ in 0..40 {
            if !self.alive() {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }
}

#[cfg(target_os = "windows")]
pub struct Parent {
    handle: windows::Win32::Foundation::HANDLE,
    created: u64,
}
#[cfg(target_os = "windows")]
impl Parent {
    pub fn current() -> Result<Self> {
        use windows::Win32::{Foundation::*, System::Threading::*};
        #[repr(C)]
        struct Entry {
            size: u32,
            usage: u32,
            pid: u32,
            heap: usize,
            module: u32,
            threads: u32,
            parent: u32,
            priority: i32,
            flags: u32,
            name: [u16; 260],
        }
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn CreateToolhelp32Snapshot(flags: u32, pid: u32) -> HANDLE;
            fn Process32FirstW(snapshot: HANDLE, entry: *mut Entry) -> i32;
            fn Process32NextW(snapshot: HANDLE, entry: *mut Entry) -> i32;
        }
        unsafe {
            let snapshot = CreateToolhelp32Snapshot(2, 0);
            if snapshot == INVALID_HANDLE_VALUE {
                return Err(error());
            }
            let mut entry: Entry = std::mem::zeroed();
            entry.size = std::mem::size_of::<Entry>() as u32;
            let mut found = 0;
            let mut result = Process32FirstW(snapshot, &mut entry);
            while result != 0 {
                if entry.pid == GetCurrentProcessId() {
                    found = entry.parent;
                    break;
                }
                result = Process32NextW(snapshot, &mut entry);
            }
            let _ = CloseHandle(snapshot);
            if found == 0 {
                return Err(error());
            }
            let handle = OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | PROCESS_SYNCHRONIZE,
                false,
                found,
            )
            .map_err(|_| error())?;
            let result = (|| {
                let mut name = vec![0u16; 32768];
                let mut length = name.len() as u32;
                QueryFullProcessImageNameW(
                    handle,
                    PROCESS_NAME_WIN32,
                    windows::core::PWSTR(name.as_mut_ptr()),
                    &mut length,
                )
                .map_err(|_| error())?;
                let parent =
                    std::path::PathBuf::from(String::from_utf16_lossy(&name[..length as usize]))
                        .canonicalize()
                        .map_err(|_| error())?;
                let own = std::env::current_exe()
                    .map_err(|_| error())?
                    .canonicalize()
                    .map_err(|_| error())?;
                if parent != own {
                    return Err(error());
                }
                let mut created = FILETIME::default();
                let mut exit = created;
                let mut kernel = created;
                let mut user = created;
                GetProcessTimes(handle, &mut created, &mut exit, &mut kernel, &mut user)
                    .map_err(|_| error())?;
                Ok(Self {
                    handle,
                    created: (created.dwHighDateTime as u64) << 32 | created.dwLowDateTime as u64,
                })
            })();
            if result.is_err() {
                let _ = CloseHandle(handle);
            }
            result
        }
    }
    pub fn alive(&self) -> bool {
        (unsafe { windows::Win32::System::Threading::WaitForSingleObject(self.handle, 0) })
            == windows::Win32::Foundation::WAIT_TIMEOUT
    }
    pub fn terminate(&self) {
        use windows::Win32::{Foundation::*, System::Threading::*};
        unsafe {
            let mut created = FILETIME::default();
            let mut exit = created;
            let mut kernel = created;
            let mut user = created;
            if GetProcessTimes(self.handle, &mut created, &mut exit, &mut kernel, &mut user)
                .is_err()
                || ((created.dwHighDateTime as u64) << 32 | created.dwLowDateTime as u64)
                    != self.created
            {
                return;
            }
            // Windows has no POSIX TERM for a console-less native helper. The private
            // EOF/fence is its graceful request; TerminateProcess is the bounded kill.
            if WaitForSingleObject(self.handle, 200) == WAIT_TIMEOUT {
                let _ = TerminateProcess(self.handle, 70);
                let _ = WaitForSingleObject(self.handle, 200);
            }
        }
    }
}
#[cfg(target_os = "windows")]
impl Drop for Parent {
    fn drop(&mut self) {
        unsafe {
            let _ = windows::Win32::Foundation::CloseHandle(self.handle);
        }
    }
}
