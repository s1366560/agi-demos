import Darwin
import Foundation

// The focused runner omits input/AX sources. This is only their shared error
// carrier; the production broker, filesystem operations and socket are compiled.
#if LOCKED_USE_BROKER_TESTS
enum ActionError: Error {
    case failure(kind: String, message: String, extra: [String: Any] = [:])
}

@main
enum LockedUseBrokerTestMain {
    static func main() {
        do { try LockedUseBrokerTests.run() }
        catch { fputs("LockedUseBrokerTests failed: \(error)\n", stderr); exit(1) }
    }
}
#endif

enum LockedUseBrokerTests {
    static func fixture() throws -> URL {
        var template = Array((NSTemporaryDirectory() + "cua-br.XXXXXX").utf8CString)
        guard let path = mkdtemp(&template) else { throw LockedUseWireError.closed }
        return URL(fileURLWithPath: String(cString: path), isDirectory: true)
    }

    static func withFixture(_ operation: (URL) throws -> Void) throws {
        let root = try fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        try operation(root)
    }

    static func info(_ url: URL) -> stat {
        var value = stat()
        precondition(lstat(url.path, &value) == 0)
        return value
    }

    static func absent(_ url: URL) -> Bool {
        var value = stat()
        return lstat(url.path, &value) < 0 && errno == ENOENT
    }

    static func contents(_ url: URL) throws -> String {
        try String(contentsOf: url, encoding: .utf8)
    }

    static func rejects(_ operation: () throws -> Void) {
        do { try operation(); preconditionFailure("unsafe broker setup was accepted") }
        catch {}
    }

    static func rawSocket(_ url: URL, listening: Bool) -> Int32 {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        precondition(fd >= 0)
        var address = sockaddr_un(); address.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutableBytes(of: &address.sun_path) { $0.copyBytes(from: Array(url.path.utf8)) }
        let result = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        precondition(result == 0)
        if listening { precondition(listen(fd, 4) == 0) }
        return fd
    }

    static func run() throws {
        try withFixture(missingDirectory)
        try withFixture(invalidDirectories)
        try withFixture(invalidSocketObjects)
        try withFixture(staleAndLiveSockets)
        try withFixture(setupFailures)
        try withFixture(replacementCleanup)
        try withFixture(concurrentSetup)
        try withFixture(nonAppleProbe)
        try withFixture(descriptorLifetime)
        print("LOCKED_USE_BROKER_FILESYSTEM_OK (9 groups)")
    }

    static func missingDirectory(_ root: URL) throws {
        let url = root.appendingPathComponent("private/a.sock")
        let broker = try LockedUseBroker(socketURL: url, approve: { false })
        defer { broker.stop() }
        var directory = stat(), socketInfo = stat()
        precondition(lstat(url.deletingLastPathComponent().path, &directory) == 0)
        precondition(directory.st_mode & 0o777 == 0o700 && directory.st_uid == getuid())
        precondition(lstat(url.path, &socketInfo) == 0 && socketInfo.st_mode & S_IFMT == S_IFSOCK)
        precondition(socketInfo.st_mode & 0o777 == 0o600)
        broker.stop(); broker.stop()
        precondition(lstat(url.path, &socketInfo) < 0 && errno == ENOENT)
        precondition(rmdir(url.deletingLastPathComponent().path) == 0)
        let recreated = try LockedUseBrokerSocket(url: url)
        recreated.close()
        // Only the final private leaf is forbidden from being a symlink.
        let alias = root.appendingPathComponent("alias")
        precondition(symlink(root.path, alias.path) == 0)
        let throughParentAlias = try LockedUseBrokerSocket(url: alias.appendingPathComponent("valid/a.sock"))
        throughParentAlias.close()
    }

    static func invalidDirectories(_ root: URL) throws {
        let directory = root.appendingPathComponent("private"), url = directory.appendingPathComponent("a.sock")
        precondition(mkdir(directory.path, 0o755) == 0)
        rejects { _ = try LockedUseBrokerSocket(url: url) }
        precondition(info(directory).st_mode & 0o777 == 0o755)
        precondition(rmdir(directory.path) == 0)
        try Data("preserve".utf8).write(to: directory)
        rejects { _ = try LockedUseBrokerSocket(url: url) }
        let content = try contents(directory)
        precondition(content == "preserve")
        precondition(unlink(directory.path) == 0)
        let target = root.appendingPathComponent("target")
        precondition(mkdir(target.path, 0o700) == 0 && symlink(target.path, directory.path) == 0)
        rejects { _ = try LockedUseBrokerSocket(url: url) }
        precondition(info(directory).st_mode & S_IFMT == S_IFLNK)
        precondition(absent(target.appendingPathComponent("a.sock")))
    }

    static func invalidSocketObjects(_ root: URL) throws {
        let url = root.appendingPathComponent("a.sock")
        try Data("preserve".utf8).write(to: url)
        rejects { _ = try LockedUseBrokerSocket(url: url) }
        let content = try contents(url)
        precondition(content == "preserve")
        precondition(unlink(url.path) == 0)
        let target = root.appendingPathComponent("target")
        try Data("target".utf8).write(to: target)
        precondition(symlink(target.path, url.path) == 0)
        rejects { _ = try LockedUseBrokerSocket(url: url) }
        precondition(info(url).st_mode & S_IFMT == S_IFLNK)
        let targetContent = try contents(target)
        precondition(targetContent == "target")
    }

    static func staleAndLiveSockets(_ root: URL) throws {
        let url = root.appendingPathComponent("a.sock")
        let stale = rawSocket(url, listening: false)
        close(stale)
        let recovered = try LockedUseBrokerSocket(url: url)
        recovered.close()
        let live = rawSocket(url, listening: true), before = info(url)
        defer { close(live) }
        rejects { _ = try LockedUseBrokerSocket(url: url) }
        precondition(info(url).st_ino == before.st_ino && fcntl(live, F_GETFD) >= 0)
    }

    static func setupFailures(_ root: URL) throws {
        let url = root.appendingPathComponent("a.sock")
        for permissionsFailure in [true, false] {
            var operations = LockedUseBrokerSocket.Operations()
            if permissionsFailure { operations.permissions = { _, _ in errno = EACCES; return -1 } }
            else { operations.listen = { _ in errno = EINVAL; return -1 } }
            rejects { _ = try LockedUseBrokerSocket(url: url, operations: operations) }
            precondition(absent(url), "failed setup left its bound socket behind")
            let retry = try LockedUseBrokerSocket(url: url)
            retry.close()
        }
    }

    static func replacementCleanup(_ root: URL) throws {
        let directory = root.appendingPathComponent("private"), url = directory.appendingPathComponent("a.sock")
        let original = try LockedUseBrokerSocket(url: url)
        precondition(unlink(url.path) == 0)
        let replacement = rawSocket(url, listening: true), replaced = info(url)
        original.close(); original.close()
        precondition(info(url).st_ino == replaced.st_ino && fcntl(replacement, F_GETFD) >= 0)
        close(replacement)
        precondition(unlink(url.path) == 0)
        let moved = root.appendingPathComponent("moved")
        let oldDirectory = try LockedUseBrokerSocket(url: url)
        precondition(rename(directory.path, moved.path) == 0 && mkdir(directory.path, 0o700) == 0)
        try Data("replacement".utf8).write(to: url)
        oldDirectory.close()
        let replacementContent = try contents(url)
        precondition(replacementContent == "replacement")
        precondition(absent(moved.appendingPathComponent("a.sock")))
        precondition(unlink(url.path) == 0)
        // Replacing the socket during a failed chmod must preserve the new file.
        var operations = LockedUseBrokerSocket.Operations()
        operations.permissions = { directoryFD, name in
            precondition(unlinkat(directoryFD, name, 0) == 0)
            precondition(FileManager.default.createFile(atPath: url.path, contents: Data("new".utf8)))
            return -1
        }
        rejects { _ = try LockedUseBrokerSocket(url: url, operations: operations) }
        let newContent = try contents(url)
        precondition(newContent == "new")
        precondition(unlink(url.path) == 0)
        let changedDuringSetup = root.appendingPathComponent("during-setup")
        operations.permissions = { directoryFD, name in
            precondition(fchmodat(directoryFD, name, 0o600, AT_SYMLINK_NOFOLLOW) == 0)
            precondition(rename(directory.path, changedDuringSetup.path) == 0)
            precondition(mkdir(directory.path, 0o700) == 0)
            precondition(FileManager.default.createFile(atPath: url.path, contents: Data("directory replacement".utf8)))
            return 0
        }
        rejects { _ = try LockedUseBrokerSocket(url: url, operations: operations) }
        let directoryReplacementContent = try contents(url)
        precondition(directoryReplacementContent == "directory replacement")
        precondition(absent(changedDuringSetup.appendingPathComponent("a.sock")))
    }

    static func concurrentSetup(_ root: URL) throws {
        let url = root.appendingPathComponent("a.sock"), resultLock = NSLock()
        var winners: [LockedUseBrokerSocket] = [], failures = 0
        DispatchQueue.concurrentPerform(iterations: 12) { _ in
            do {
                let endpoint = try LockedUseBrokerSocket(url: url)
                resultLock.lock(); winners.append(endpoint); resultLock.unlock()
            } catch {
                resultLock.lock(); failures += 1; resultLock.unlock()
            }
        }
        precondition(winners.count == 1 && failures == 11)
        winners.forEach { $0.close() }
        precondition(absent(url))
        // Holding the setup lock must make initialization and stop bounded.
        let active = try LockedUseBrokerSocket(url: url)
        let holder = open(root.path, O_RDONLY | O_DIRECTORY)
        precondition(holder >= 0 && flock(holder, LOCK_EX | LOCK_NB) == 0)
        let start = ProcessInfo.processInfo.systemUptime
        rejects { _ = try LockedUseBrokerSocket(url: url) }
        active.close()
        precondition(ProcessInfo.processInfo.systemUptime - start < 1)
        precondition(!absent(url))
        flock(holder, LOCK_UN); close(holder)
        let next = try LockedUseBrokerSocket(url: url)
        next.close()
    }

    static func nonAppleProbe(_ root: URL) throws {
        let url = root.appendingPathComponent("a.sock"), resultLock = NSLock()
        var approvals = 0
        let broker = try LockedUseBroker(socketURL: url, approve: {
            resultLock.lock(); approvals += 1; resultLock.unlock(); return true
        })
        defer { broker.stop() }
        let before = info(url)
        rejects { _ = try LockedUseBrokerSocket(url: url) }
        let probe = socket(AF_UNIX, SOCK_STREAM, 0)
        defer { close(probe) }
        var address = sockaddr_un(); address.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutableBytes(of: &address.sun_path) { $0.copyBytes(from: Array(url.path.utf8)) }
        let connected = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(probe, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        precondition(connected == 0)
        var ready = pollfd(fd: probe, events: Int16(POLLIN), revents: 0)
        precondition(poll(&ready, 1, 1000) > 0)
        var bytes = [UInt8](repeating: 0, count: 4)
        precondition(read(probe, &bytes, bytes.count) == 4 && String(decoding: bytes, as: UTF8.self) == "DENY")
        resultLock.lock(); let count = approvals; resultLock.unlock()
        precondition(count == 0 && info(url).st_ino == before.st_ino)
    }

    static func descriptorLifetime(_ root: URL) throws {
        let url = root.appendingPathComponent("a.sock")
        for _ in 0..<50 {
            var broker: LockedUseBroker? = try LockedUseBroker(socketURL: url, approve: { false })
            broker!.stop(); broker!.stop(); broker = nil
            let replacement = try LockedUseBrokerSocket(url: url)
            Thread.sleep(forTimeInterval: 0.001)
            precondition(fcntl(replacement.descriptor, F_GETFD) >= 0 && !absent(url))
            replacement.close()
        }
        // Releasing the owner before or after the accept thread starts must
        // stop it; the thread must not retain the broker indefinitely.
        for _ in 0..<20 {
            var broker: LockedUseBroker? = try LockedUseBroker(socketURL: url, approve: { false })
            weak let released = broker
            broker = nil
            precondition(released == nil && absent(url))
        }
    }
}
