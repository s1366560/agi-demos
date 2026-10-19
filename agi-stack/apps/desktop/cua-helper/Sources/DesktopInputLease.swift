import Darwin
import Foundation
import Security

/// One OS lock for this authenticated user's login session, shared through an
/// inherited open-file description by the worker and its signed watchdog.
enum DesktopInputLease {
    static func path() throws -> String {
        var session: SecuritySessionId = 0
        guard SessionGetInfo(callerSecuritySession, &session, nil) == errSecSuccess else {
            throw ActionError.failure(kind: "input_lease_unavailable", message: "cannot identify the login session")
        }
        let length = confstr(_CS_DARWIN_USER_TEMP_DIR, nil, 0)
        guard length > 1, length < 4096 else {
            throw ActionError.failure(kind: "input_lease_unavailable", message: "cannot locate the private OS temporary directory")
        }
        var buffer = [CChar](repeating: 0, count: length)
        guard confstr(_CS_DARWIN_USER_TEMP_DIR, &buffer, length) == length else {
            throw ActionError.failure(kind: "input_lease_unavailable", message: "cannot locate the private OS temporary directory")
        }
        return URL(fileURLWithPath: String(cString: buffer), isDirectory: true)
            .appendingPathComponent("memstack-cua-input-\(getuid())-\(session).lock").path
    }
    static func openDescriptor() throws -> Int32 {
        let value = try path()
        let descriptor = open(value, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, mode_t(0o600))
        guard descriptor >= 0 else {
            throw ActionError.failure(kind: "input_lease_unavailable", message: "cannot open the desktop input lock")
        }
        do { try verify(descriptor); return descriptor }
        catch { close(descriptor); throw error }
    }
    static func verify(_ descriptor: Int32) throws {
        var opened = stat(), named = stat()
        guard fstat(descriptor, &opened) == 0, lstat(try path(), &named) == 0,
              opened.st_uid == getuid(), opened.st_mode & S_IFMT == S_IFREG,
              opened.st_mode & 0o777 == 0o600, opened.st_nlink == 1,
              named.st_mode & S_IFMT == S_IFREG,
              opened.st_dev == named.st_dev, opened.st_ino == named.st_ino else {
            throw ActionError.failure(kind: "input_lease_unavailable", message: "desktop input lock identity or permissions changed")
        }
    }
    static func acquire(_ descriptor: Int32) -> Bool {
        (try? verify(descriptor)) != nil && flock(descriptor, LOCK_EX | LOCK_NB) == 0
    }
    static func release(_ descriptor: Int32) { _ = flock(descriptor, LOCK_UN) }
}
