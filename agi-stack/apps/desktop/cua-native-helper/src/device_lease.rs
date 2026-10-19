//! Native session mutex, shared by independent helpers but never used as an RPC channel.
use crate::backend::{NativeError, Result};
fn unavailable() -> NativeError {
    NativeError::new(
        "capability_unsupported",
        "private native device lease is unavailable",
    )
}
fn busy() -> NativeError {
    NativeError::new(
        "desktop_busy",
        "another native helper owns this device session",
    )
}

#[cfg(target_os = "linux")]
pub struct DeviceLease(std::fs::File);
#[cfg(target_os = "linux")]
impl DeviceLease {
    pub fn acquire() -> Result<Self> {
        Self::scope("resources")
    }
    pub fn input() -> Result<Self> {
        Self::scope("input")
    }
    fn scope(kind: &str) -> Result<Self> {
        use sha2::{Digest, Sha256};
        use std::os::unix::{
            fs::{DirBuilderExt, MetadataExt, OpenOptionsExt},
            io::AsRawFd,
        };
        let uid = unsafe { libc::geteuid() };
        let endpoint = if let Some(display) = std::env::var_os("WAYLAND_DISPLAY") {
            let runtime = std::env::var_os("XDG_RUNTIME_DIR").ok_or_else(unavailable)?;
            let socket = std::path::PathBuf::from(runtime).join(display);
            let socket = socket.canonicalize().map_err(|_| unavailable())?;
            format!("wayland:{}", socket.display())
        } else {
            let display = std::env::var("DISPLAY").map_err(|_| unavailable())?;
            // All X11 screens of one display share keyboard/pointer ownership.
            let number = display
                .rsplit_once(':')
                .ok_or_else(unavailable)?
                .1
                .split('.')
                .next()
                .ok_or_else(unavailable)?
                .parse::<u32>()
                .map_err(|_| unavailable())?;
            format!("x11:{number}")
        };
        let root = std::path::PathBuf::from("/tmp").join(format!("memstack-cua-device-{uid}"));
        match std::fs::DirBuilder::new().mode(0o700).create(&root) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(_) => return Err(unavailable()),
        }
        let metadata = std::fs::symlink_metadata(&root).map_err(|_| unavailable())?;
        if !metadata.is_dir() || metadata.uid() != uid || metadata.mode() & 0o7777 != 0o700 {
            return Err(unavailable());
        }
        let name = format!(
            "{:x}.lock",
            Sha256::digest(format!("{endpoint}:{kind}").as_bytes())
        );
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(root.join(name))
            .map_err(|_| unavailable())?;
        let metadata = file.metadata().map_err(|_| unavailable())?;
        if !metadata.is_file()
            || metadata.uid() != uid
            || metadata.nlink() != 1
            || metadata.mode() & 0o7777 != 0o600
        {
            return Err(unavailable());
        }
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(busy());
        }
        Ok(Self(file))
    }
}
#[cfg(target_os = "linux")]
impl Drop for DeviceLease {
    fn drop(&mut self) {
        use std::os::unix::io::AsRawFd;
        let _ = unsafe { libc::flock(self.0.as_raw_fd(), libc::LOCK_UN) };
    }
}

#[cfg(target_os = "windows")]
pub struct DeviceLease {
    handle: windows::Win32::Foundation::HANDLE,
    thread: u32,
}
// HANDLE access is serialized; acquisition/release stays on the owning native thread.
#[cfg(target_os = "windows")]
unsafe impl Send for DeviceLease {}
#[cfg(target_os = "windows")]
impl DeviceLease {
    pub fn acquire() -> Result<Self> {
        Self::scope("resources")
    }
    pub fn input() -> Result<Self> {
        Self::scope("input")
    }
    fn scope(kind: &str) -> Result<Self> {
        use windows::{
            core::{PCWSTR, PWSTR},
            Win32::{
                Foundation::{
                    CloseHandle, LocalFree, HANDLE, HLOCAL, WAIT_ABANDONED, WAIT_OBJECT_0,
                },
                Security::{Authorization::*, *},
                System::Threading::*,
            },
        };
        unsafe {
            let mut token = HANDLE::default();
            OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token)
                .map_err(|_| unavailable())?;
            let mut length = 0;
            let _ = GetTokenInformation(token, TokenUser, None, 0, &mut length);
            let mut buffer = vec![0u64; (length as usize).div_ceil(8)];
            let result = GetTokenInformation(
                token,
                TokenUser,
                Some(buffer.as_mut_ptr().cast()),
                length,
                &mut length,
            );
            let _ = CloseHandle(token);
            result.map_err(|_| unavailable())?;
            let user = &*buffer.as_ptr().cast::<TOKEN_USER>();
            let mut sid = PWSTR::null();
            ConvertSidToStringSidW(user.User.Sid, &mut sid).map_err(|_| unavailable())?;
            let sid_text = sid.to_string().map_err(|_| unavailable());
            let _ = LocalFree(Some(HLOCAL(sid.0.cast())));
            let sid_text = sid_text?;
            let name = format!("Local\\MemStackCuaDevice-{kind}-{sid_text}")
                .encode_utf16()
                .chain([0])
                .collect::<Vec<_>>();
            let acl = format!("D:P(A;;GA;;;{sid_text})")
                .encode_utf16()
                .chain([0])
                .collect::<Vec<_>>();
            let mut descriptor = PSECURITY_DESCRIPTOR::default();
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                PCWSTR(acl.as_ptr()),
                SDDL_REVISION_1,
                &mut descriptor,
                None,
            )
            .map_err(|_| unavailable())?;
            let attributes = SECURITY_ATTRIBUTES {
                nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
                lpSecurityDescriptor: descriptor.0,
                bInheritHandle: false.into(),
            };
            let handle = CreateMutexW(Some(&attributes), false, PCWSTR(name.as_ptr()));
            let _ = LocalFree(Some(HLOCAL(descriptor.0)));
            let handle = handle.map_err(|_| unavailable())?;
            let wait = WaitForSingleObject(handle, 0);
            if wait != WAIT_OBJECT_0 && wait != WAIT_ABANDONED {
                let _ = CloseHandle(handle);
                return Err(busy());
            }
            Ok(Self {
                handle,
                thread: GetCurrentThreadId(),
            })
        }
    }
}
#[cfg(target_os = "windows")]
impl Drop for DeviceLease {
    fn drop(&mut self) {
        unsafe {
            if windows::Win32::System::Threading::GetCurrentThreadId() == self.thread {
                let _ = windows::Win32::System::Threading::ReleaseMutex(self.handle);
            }
            let _ = windows::Win32::Foundation::CloseHandle(self.handle);
        }
    }
}
