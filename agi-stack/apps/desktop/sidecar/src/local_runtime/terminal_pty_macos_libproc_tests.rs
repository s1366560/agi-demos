//! Verify libproc's zero-return ambiguity against the real macOS wrapper.

use super::*;

#[test]
fn real_empty_group_clears_stale_errno_before_zero_success() {
    // SAFETY: errno is thread-local; no valid macOS PID/group reaches i32::MAX.
    unsafe { *libc::__error() = libc::EPERM };
    assert!(group_members(i32::MAX)
        .expect("empty group is success")
        .is_empty());
    assert_eq!(unsafe { *libc::__error() }, 0);
}

#[test]
fn real_libproc_zero_failure_keeps_immediately_captured_errno() {
    let mut buffer = 0_i32;
    let result = libproc_call(|| {
        // SAFETY: the pointer owns four bytes; deliberately requesting one byte
        // exercises the real kernel ENOMEM response for an undersized PID buffer.
        let written = unsafe { libc::proc_listpids(2, 0, (&mut buffer as *mut i32).cast(), 1) };
        assert_eq!(written, 0, "libproc translates syscall failure to zero");
        written
    });
    assert_eq!(
        result.expect_err("enumeration failed").raw_os_error(),
        Some(libc::ENOMEM)
    );
}

#[test]
fn positive_short_bsd_info_is_invalid_data_even_with_stale_permission_errno() {
    let error = process_info_with(|_, _| {
        // SAFETY: this simulates a malformed adapter response without writing a struct.
        unsafe { *libc::__error() = libc::EPERM };
        1
    })
    .expect_err("partial structure must never be assumed initialized");
    assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    assert!(error.to_string().contains("returned 1 bytes"));
    assert_eq!(error.raw_os_error(), None);
}

#[test]
fn zero_bsd_info_without_errno_is_an_explicit_invalid_response() {
    let error = process_info_with(|_, _| 0).expect_err("zero is not a complete BSD structure");
    assert_eq!(error.kind(), io::ErrorKind::InvalidData);
}

#[test]
fn real_missing_process_remains_a_structural_exit_observation() {
    assert!(process_info(i32::MAX).expect("missing PID").is_none());
}

#[test]
fn bsd_info_permission_failure_is_not_suppressed() {
    let error = process_info_with(|_, _| {
        // SAFETY: simulates libproc's documented failure return convention.
        unsafe { *libc::__error() = libc::EPERM };
        0
    })
    .expect_err("permission failure remains visible");
    assert_eq!(error.raw_os_error(), Some(libc::EPERM));
}
