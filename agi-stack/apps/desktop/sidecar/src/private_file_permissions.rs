//! Cross-platform user-private filesystem permissions for desktop state.

use std::{io, path::Path};

#[cfg(unix)]
pub(crate) fn set_private_directory_permissions(path: &Path) -> io::Result<()> {
    use std::os::unix::fs::PermissionsExt;

    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
}

#[cfg(unix)]
pub(crate) fn set_private_file_permissions(path: &Path) -> io::Result<()> {
    use std::os::unix::fs::PermissionsExt;

    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
}

#[cfg(windows)]
pub(crate) fn set_private_directory_permissions(path: &Path) -> io::Result<()> {
    windows_acl::set_current_user_acl(path, true)
}

#[cfg(windows)]
pub(crate) fn set_private_file_permissions(path: &Path) -> io::Result<()> {
    windows_acl::set_current_user_acl(path, false)
}

#[cfg(not(any(unix, windows)))]
pub(crate) fn set_private_directory_permissions(_path: &Path) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "private directory permissions are unsupported on this platform",
    ))
}

#[cfg(not(any(unix, windows)))]
pub(crate) fn set_private_file_permissions(_path: &Path) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "private file permissions are unsupported on this platform",
    ))
}

#[cfg(all(test, windows))]
pub(crate) fn path_has_current_user_only_acl(path: &Path, directory: bool) -> io::Result<bool> {
    windows_acl::windows_acl_contains_only_current_user(path, directory)
}

#[cfg(windows)]
mod windows_acl {
    use std::{
        ffi::c_void,
        io, iter,
        mem::size_of,
        os::windows::ffi::OsStrExt,
        path::Path,
        ptr::{null, null_mut},
    };

    #[cfg(test)]
    use std::{mem::zeroed, ptr::addr_of};

    use windows_sys::Win32::{
        Foundation::{CloseHandle, GetLastError, ERROR_INSUFFICIENT_BUFFER, GENERIC_ALL, HANDLE},
        Security::Authorization::{SetNamedSecurityInfoW, SE_FILE_OBJECT},
        Security::{
            AddAccessAllowedAceEx, GetLengthSid, GetTokenInformation, InitializeAcl, TokenUser,
            ACCESS_ALLOWED_ACE, ACL, ACL_REVISION, CONTAINER_INHERIT_ACE,
            DACL_SECURITY_INFORMATION, OBJECT_INHERIT_ACE, PROTECTED_DACL_SECURITY_INFORMATION,
            PSID, TOKEN_QUERY, TOKEN_USER,
        },
        System::Threading::{GetCurrentProcess, OpenProcessToken},
    };

    #[cfg(test)]
    use windows_sys::Win32::Security::{
        AclSizeInformation, EqualSid, GetAce, GetAclInformation, GetFileSecurityW,
        GetSecurityDescriptorControl, GetSecurityDescriptorDacl, ACE_HEADER, ACL_SIZE_INFORMATION,
        SE_DACL_PROTECTED,
    };
    #[cfg(test)]
    use windows_sys::Win32::System::SystemServices::ACCESS_ALLOWED_ACE_TYPE;

    const SUCCESS: u32 = 0;

    pub(super) fn set_current_user_acl(path: &Path, directory: bool) -> io::Result<()> {
        with_current_user_sid(|sid| {
            let acl_byte_len = acl_byte_len(sid)?;
            let mut acl_storage = aligned_storage(acl_byte_len);
            let acl = acl_storage.as_mut_ptr().cast::<ACL>();
            let ace_flags = if directory {
                OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE
            } else {
                0
            };

            // SAFETY: `acl_storage` is pointer-aligned, writable, and at least `acl_byte_len`
            // bytes long. `sid` points into the live token-information buffer owned by
            // `with_current_user_sid` for the duration of this closure.
            if unsafe { InitializeAcl(acl, acl_byte_len as u32, ACL_REVISION) } == 0 {
                return Err(io::Error::last_os_error());
            }
            // SAFETY: `acl` was initialized above and has enough capacity for one access ACE
            // containing the validated current-user SID.
            if unsafe { AddAccessAllowedAceEx(acl, ACL_REVISION, ace_flags, GENERIC_ALL, sid) } == 0
            {
                return Err(io::Error::last_os_error());
            }

            let wide_path = wide_path(path)?;
            // SAFETY: `wide_path` is a live, NUL-terminated UTF-16 path; the ACL and SID-backed
            // buffers remain live for the call. Null owner/group/SACL pointers mean those fields
            // are intentionally left unchanged.
            let status = unsafe {
                SetNamedSecurityInfoW(
                    wide_path.as_ptr(),
                    SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                    null_mut(),
                    null_mut(),
                    acl,
                    null(),
                )
            };
            if status == SUCCESS {
                Ok(())
            } else {
                Err(io::Error::from_raw_os_error(status as i32))
            }
        })
    }

    fn with_current_user_sid<T>(action: impl FnOnce(PSID) -> io::Result<T>) -> io::Result<T> {
        let mut token = null_mut();
        // SAFETY: `token` is a valid out pointer. The pseudo process handle is owned by Windows
        // and must not be closed; the returned token handle is wrapped immediately below.
        if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
            return Err(io::Error::last_os_error());
        }
        let token = OwnedHandle(token);
        let mut required_bytes = 0_u32;
        // SAFETY: a zero-length probe with a null output buffer is the documented way to obtain
        // the TOKEN_USER byte count.
        let probe =
            unsafe { GetTokenInformation(token.0, TokenUser, null_mut(), 0, &mut required_bytes) };
        if probe != 0
            || unsafe { GetLastError() } != ERROR_INSUFFICIENT_BUFFER
            || required_bytes < size_of::<TOKEN_USER>() as u32
        {
            return Err(io::Error::last_os_error());
        }
        let mut token_information = aligned_storage(required_bytes as usize);
        // SAFETY: the aligned buffer has at least `required_bytes` writable bytes and remains
        // live through the callback.
        if unsafe {
            GetTokenInformation(
                token.0,
                TokenUser,
                token_information.as_mut_ptr().cast::<c_void>(),
                required_bytes,
                &mut required_bytes,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: GetTokenInformation successfully initialized a TOKEN_USER at the beginning of
        // the aligned output buffer.
        let token_user = unsafe { &*token_information.as_ptr().cast::<TOKEN_USER>() };
        if token_user.User.Sid.is_null() || unsafe { GetLengthSid(token_user.User.Sid) } == 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "current Windows token does not contain a valid user SID",
            ));
        }
        action(token_user.User.Sid)
    }

    fn acl_byte_len(sid: PSID) -> io::Result<usize> {
        // SAFETY: the caller provides a SID validated by GetTokenInformation/GetLengthSid.
        let sid_len = unsafe { GetLengthSid(sid) } as usize;
        let byte_len = size_of::<ACL>()
            .checked_add(size_of::<ACCESS_ALLOWED_ACE>() - size_of::<u32>())
            .and_then(|prefix| prefix.checked_add(sid_len))
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidData, "Windows ACL is too large")
            })?;
        u32::try_from(byte_len)
            .map(|_| byte_len)
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "Windows ACL is too large"))
    }

    fn aligned_storage(byte_len: usize) -> Vec<usize> {
        vec![0; byte_len.div_ceil(size_of::<usize>())]
    }

    fn wide_path(path: &Path) -> io::Result<Vec<u16>> {
        let encoded = path
            .as_os_str()
            .encode_wide()
            .chain(iter::once(0))
            .collect::<Vec<_>>();
        if encoded.len() == 1 || encoded[..encoded.len() - 1].contains(&0) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Windows path contains an embedded NUL",
            ));
        }
        Ok(encoded)
    }

    struct OwnedHandle(HANDLE);

    impl Drop for OwnedHandle {
        fn drop(&mut self) {
            // SAFETY: this wrapper owns the token handle returned by OpenProcessToken exactly once.
            unsafe {
                CloseHandle(self.0);
            }
        }
    }

    #[cfg(test)]
    pub(super) fn windows_acl_contains_only_current_user(
        path: &Path,
        directory: bool,
    ) -> io::Result<bool> {
        let wide_path = wide_path(path)?;
        let mut required_bytes = 0_u32;
        // SAFETY: this is the documented zero-length query for the security descriptor size.
        unsafe {
            GetFileSecurityW(
                wide_path.as_ptr(),
                DACL_SECURITY_INFORMATION,
                null_mut(),
                0,
                &mut required_bytes,
            );
        }
        if required_bytes == 0 {
            return Err(io::Error::last_os_error());
        }
        let mut descriptor = aligned_storage(required_bytes as usize);
        // SAFETY: `descriptor` is aligned and has the required writable size.
        if unsafe {
            GetFileSecurityW(
                wide_path.as_ptr(),
                DACL_SECURITY_INFORMATION,
                descriptor.as_mut_ptr().cast::<c_void>(),
                required_bytes,
                &mut required_bytes,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        let security_descriptor = descriptor.as_mut_ptr().cast::<c_void>();
        let mut control = 0_u16;
        let mut revision = 0_u32;
        // SAFETY: the descriptor was initialized by GetFileSecurityW.
        if unsafe { GetSecurityDescriptorControl(security_descriptor, &mut control, &mut revision) }
            == 0
            || control & SE_DACL_PROTECTED == 0
        {
            return Ok(false);
        }
        let mut present = 0;
        let mut defaulted = 0;
        let mut acl = null_mut();
        // SAFETY: all output pointers are valid and the descriptor remains live.
        if unsafe {
            GetSecurityDescriptorDacl(security_descriptor, &mut present, &mut acl, &mut defaulted)
        } == 0
            || present == 0
            || acl.is_null()
        {
            return Ok(false);
        }
        // SAFETY: zeroed is a valid initial byte state for this plain Windows data structure.
        let mut size_information: ACL_SIZE_INFORMATION = unsafe { zeroed() };
        // SAFETY: `acl` came from the validated descriptor and the output structure is writable.
        if unsafe {
            GetAclInformation(
                acl,
                (&mut size_information as *mut ACL_SIZE_INFORMATION).cast::<c_void>(),
                size_of::<ACL_SIZE_INFORMATION>() as u32,
                AclSizeInformation,
            )
        } == 0
            || size_information.AceCount != 1
        {
            return Ok(false);
        }
        let mut ace = null_mut();
        // SAFETY: the ACL reports one ACE, so index zero is valid.
        if unsafe { GetAce(acl, 0, &mut ace) } == 0 || ace.is_null() {
            return Ok(false);
        }
        // SAFETY: every ACE begins with a live ACE_HEADER inside the validated ACL.
        let header = unsafe { &*ace.cast::<ACE_HEADER>() };
        if u32::from(header.AceType) != ACCESS_ALLOWED_ACE_TYPE {
            return Ok(false);
        }
        // SAFETY: the validated ACE type above is ACCESS_ALLOWED_ACE_TYPE.
        let allowed_ace = unsafe { &*ace.cast::<ACCESS_ALLOWED_ACE>() };
        let expected_flags = if directory {
            (OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE) as u8
        } else {
            0
        };
        if allowed_ace.Mask != GENERIC_ALL || allowed_ace.Header.AceFlags != expected_flags {
            return Ok(false);
        }
        let ace_sid = addr_of!(allowed_ace.SidStart).cast_mut().cast::<c_void>();
        with_current_user_sid(|current_sid| {
            // SAFETY: both pointers refer to live, validated SIDs during this call.
            Ok(unsafe { EqualSid(current_sid, ace_sid) } != 0)
        })
    }
}

#[cfg(all(test, windows))]
mod tests {
    use std::{fs, path::PathBuf};

    use super::{
        path_has_current_user_only_acl as inspect_private_acl, set_private_directory_permissions,
        set_private_file_permissions,
    };

    struct TestDirectory(PathBuf);

    impl TestDirectory {
        fn create() -> Self {
            let path =
                std::env::temp_dir().join(format!("agistack-private-acl-{}", uuid::Uuid::new_v4()));
            fs::create_dir(&path).expect("create Windows ACL test directory");
            Self(path)
        }
    }

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn windows_vault_acl_contains_only_current_user() {
        let root = TestDirectory::create();
        set_private_directory_permissions(&root.0).expect("secure test directory");
        assert!(inspect_private_acl(&root.0, true).expect("inspect directory ACL"));

        let file = root.0.join("vault-record.db");
        fs::write(&file, b"encrypted fixture").expect("write test file");
        set_private_file_permissions(&file).expect("secure test file");
        assert!(inspect_private_acl(&file, false).expect("inspect file ACL"));
    }

    #[test]
    fn windows_acl_rejects_missing_target() {
        let root = TestDirectory::create();
        let missing_directory = root.0.join("missing-directory");
        let missing_file = root.0.join("missing-file");

        assert!(set_private_directory_permissions(&missing_directory).is_err());
        assert!(set_private_file_permissions(&missing_file).is_err());
    }
}
