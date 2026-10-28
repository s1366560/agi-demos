import Darwin
import Foundation

/// Owns only the broker's socket inode. The private directory may survive stop
/// and may be recreated on the next initialization if the OS removed it.
final class LockedUseBrokerSocket {
    struct Operations {
        var permissions: (Int32, String) -> Int32 = { directory, name in
            fchmodat(directory, name, 0o600, AT_SYMLINK_NOFOLLOW)
        }
        var listen: (Int32) -> Int32 = { Darwin.listen($0, 4) }
    }

    private struct Identity {
        let device: dev_t
        let inode: ino_t
        init(_ value: stat) { device = value.st_dev; inode = value.st_ino }
        func matches(_ value: stat) -> Bool { device == value.st_dev && inode == value.st_ino }
    }

    let descriptor: Int32
    private let name: String
    private let identity: Identity
    private let lock = NSLock()
    private var directory: Int32
    private var stopped = false
    private var closed = false

    init(url: URL, operations: Operations = Operations()) throws {
        let prepared = try Self.prepare(url, operations: operations)
        descriptor = prepared.0; directory = prepared.1
        identity = prepared.2; name = url.lastPathComponent
    }

    deinit { close() }

    var isActive: Bool {
        lock.lock(); defer { lock.unlock() }
        return !stopped
    }

    /// The accept thread owns close(). Shutdown wakes it without allowing an
    /// unrelated descriptor to reuse its number while accept is still pending.
    func stop() {
        lock.lock(); defer { lock.unlock() }
        guard !stopped else { return }
        stopped = true
        shutdown(descriptor, SHUT_RDWR)
        // A competing setup must never make stop wait. It will either preserve
        // this live socket or remove it as stale after the listener closes.
        if flock(directory, LOCK_EX | LOCK_NB) == 0 {
            Self.removeOwnedSocket(directory, name: name, identity: identity)
            flock(directory, LOCK_UN)
        }
        Darwin.close(directory); directory = -1
    }

    /// Called by the accept thread even if its weak broker reference expired.
    func close() {
        stop()
        lock.lock(); defer { lock.unlock() }
        guard !closed else { return }
        closed = true
        Darwin.close(descriptor)
    }

    private static func prepare(_ url: URL, operations: Operations) throws -> (Int32, Int32, Identity) {
        let parent = url.deletingLastPathComponent(), name = url.lastPathComponent
        guard url.path.utf8.count < 104, !name.isEmpty else { throw LockedUseWireError.invalidFrame }
        if mkdir(parent.path, 0o700) != 0 && errno != EEXIST { throw directoryError() }
        // Only the final private component is forbidden from being a symlink.
        // macOS's system /tmp -> /private/tmp parent alias remains supported.
        let directory = open(parent.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard directory >= 0 else { throw directoryError() }
        var fd: Int32 = -1, owned: Identity?
        var adopted = false, locked = false
        defer {
            if !adopted {
                if let owned = owned { removeOwnedSocket(directory, name: name, identity: owned) }
                if fd >= 0 { Darwin.close(fd) }
            }
            if locked { flock(directory, LOCK_UN) }
            if !adopted { Darwin.close(directory) }
        }
        var info = stat()
        guard fstat(directory, &info) == 0, privateDirectory(info) else { throw directoryError() }
        let parentIdentity = Identity(info)
        guard flock(directory, LOCK_EX | LOCK_NB) == 0 else { throw busyError() }
        locked = true
        try checkDirectory(parent, descriptor: directory, identity: parentIdentity)
        try removeStaleSocket(url, directory: directory, parentIdentity: parentIdentity)
        fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw LockedUseWireError.closed }
        var noSignal: Int32 = 1
        guard fcntl(fd, F_SETFD, FD_CLOEXEC) == 0,
              setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size)) == 0 else {
            throw LockedUseWireError.closed
        }
        try checkDirectory(parent, descriptor: directory, identity: parentIdentity)
        var address = address(url)
        let result = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard result == 0 else { throw bindError() }
        // Darwin has no bindat. Pin cleanup to the directory fd, and check the
        // public path on both sides of each setup operation; do not claim these
        // pathname operations are atomic against same-uid directory renames.
        guard fstatat(directory, name, &info, AT_SYMLINK_NOFOLLOW) == 0,
              info.st_mode & S_IFMT == S_IFSOCK, info.st_uid == getuid() else {
            throw LockedUseWireError.invalidFrame
        }
        let socketIdentity = Identity(info); owned = socketIdentity
        try checkDirectory(parent, descriptor: directory, identity: parentIdentity)
        guard operations.permissions(directory, name) == 0 else { throw bindError() }
        try checkDirectory(parent, descriptor: directory, identity: parentIdentity)
        try checkSocket(directory, name: name, identity: socketIdentity)
        guard operations.listen(fd) == 0 else { throw bindError() }
        try checkDirectory(parent, descriptor: directory, identity: parentIdentity)
        try checkSocket(directory, name: name, identity: socketIdentity)
        adopted = true
        return (fd, directory, socketIdentity)
    }

    private static func privateDirectory(_ info: stat) -> Bool {
        info.st_mode & S_IFMT == S_IFDIR && info.st_uid == getuid() && info.st_mode & 0o7777 == 0o700
    }

    private static func checkDirectory(_ url: URL, descriptor: Int32, identity: Identity) throws {
        var path = stat(), pinned = stat()
        guard lstat(url.path, &path) == 0, fstat(descriptor, &pinned) == 0,
              privateDirectory(path), privateDirectory(pinned),
              identity.matches(path), identity.matches(pinned) else { throw directoryError() }
    }

    private static func checkSocket(_ directory: Int32, name: String, identity: Identity) throws {
        var info = stat()
        guard fstatat(directory, name, &info, AT_SYMLINK_NOFOLLOW) == 0, identity.matches(info),
              info.st_mode & S_IFMT == S_IFSOCK, info.st_uid == getuid(),
              info.st_mode & 0o7777 == 0o600 else { throw LockedUseWireError.invalidFrame }
    }

    private static func removeOwnedSocket(_ directory: Int32, name: String, identity: Identity) {
        var info = stat()
        guard fstatat(directory, name, &info, AT_SYMLINK_NOFOLLOW) == 0, identity.matches(info),
              info.st_mode & S_IFMT == S_IFSOCK, info.st_uid == getuid() else { return }
        _ = unlinkat(directory, name, 0)
    }

    private static func removeStaleSocket(_ url: URL, directory: Int32, parentIdentity: Identity) throws {
        var before = stat(), after = stat()
        let name = url.lastPathComponent
        guard fstatat(directory, name, &before, AT_SYMLINK_NOFOLLOW) == 0 else {
            if errno == ENOENT { return }
            throw LockedUseWireError.closed
        }
        guard before.st_mode & S_IFMT == S_IFSOCK, before.st_uid == getuid() else {
            throw LockedUseWireError.invalidFrame
        }
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw LockedUseWireError.closed }
        defer { Darwin.close(fd) }
        guard fcntl(fd, F_SETFL, O_NONBLOCK) == 0 else { throw LockedUseWireError.closed }
        try checkDirectory(url.deletingLastPathComponent(), descriptor: directory, identity: parentIdentity)
        var address = address(url)
        let result = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard result < 0, errno == ECONNREFUSED else { throw busyError() }
        try checkDirectory(url.deletingLastPathComponent(), descriptor: directory, identity: parentIdentity)
        guard fstatat(directory, name, &after, AT_SYMLINK_NOFOLLOW) == 0,
              Identity(before).matches(after), after.st_mode & S_IFMT == S_IFSOCK,
              after.st_uid == getuid() else { throw LockedUseWireError.invalidFrame }
        guard unlinkat(directory, name, 0) == 0 else { throw LockedUseWireError.closed }
    }

    private static func address(_ url: URL) -> sockaddr_un {
        var value = sockaddr_un()
        value.sun_family = sa_family_t(AF_UNIX)
        value.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        withUnsafeMutableBytes(of: &value.sun_path) { $0.copyBytes(from: Array(url.path.utf8)) }
        return value
    }

    private static func directoryError() -> ActionError {
        .failure(kind: "permission_required", message: "the authorization broker directory is not private")
    }
    private static func busyError() -> ActionError {
        .failure(kind: "device_busy", message: "another authorization broker is active")
    }
    private static func bindError() -> ActionError {
        .failure(kind: "native_error", message: "cannot bind authorization broker")
    }
}
