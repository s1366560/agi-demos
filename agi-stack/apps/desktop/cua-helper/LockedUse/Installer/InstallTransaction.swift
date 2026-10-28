import Darwin
import Foundation

/// Files are prepared before the authorization branch becomes reachable. A
/// durable rollback copy is kept until commit; the next administrator operation
/// recovers an interrupted change without replacing unrelated system branches.
final class LockedUseInstallTransaction {
    enum Failure: Error { case invalidState(String), busy }
    let support: URL
    let destination: URL
    let owner: UInt32
    let readRight: (String) throws -> [String: Any]?
    let setRight: (String, [String: Any]?) throws -> Void
    let validatePlugin: (URL) throws -> Void
    let checkpoint: (String) throws -> Void
    let authorize: () throws -> Void
    let screenRight = "system.login.screensaver"
    let remoteRight = "ai.agistack.desktop.cua.locked-use"
    private var configuration: URL { support.appendingPathComponent("locked-use.plist") }
    private var directory: URL { support.appendingPathComponent("install-transaction", isDirectory: true) }
    private var journal: URL { directory.appendingPathComponent("rollback.plist") }
    private var oldPlugin: URL { directory.appendingPathComponent("previous.bundle") }
    private var newPlugin: URL { directory.appendingPathComponent("next.bundle") }

    init(support: URL, destination: URL, owner: UInt32 = 0,
         readRight: @escaping (String) throws -> [String: Any]?,
         setRight: @escaping (String, [String: Any]?) throws -> Void,
         validatePlugin: @escaping (URL) throws -> Void,
         authorize: @escaping () throws -> Void = {},
         checkpoint: @escaping (String) throws -> Void = { _ in }) {
        self.support = support; self.destination = destination; self.owner = owner
        self.readRight = readRight; self.setRight = setRight
        self.validatePlugin = validatePlugin; self.checkpoint = checkpoint
        self.authorize = authorize
    }

    func install(source: URL, configuration value: [String: Any]) throws {
        try exclusively { try installLocked(source: source, configuration: value) }
    }

    private func installLocked(source: URL, configuration value: [String: Any]) throws {
        try authorize()
        try recoverLocked()
        try validatePlugin(source)
        let current = try screen()
        let rules = current["rule"] as! [String]
        try authorize()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
            attributes: [.posixPermissions: 0o700, .ownerAccountID: owner])
        do {
            var rollback: [String: Any] = ["had_branch": rules.contains(remoteRight),
                "had_plugin": FileManager.default.fileExists(atPath: destination.path)]
            if let previous = try readRight(remoteRight) { rollback["remote_right"] = previous }
            if FileManager.default.fileExists(atPath: configuration.path) {
                try regular(configuration)
                rollback["configuration"] = try Data(contentsOf: configuration)
            }
            if rollback["had_plugin"] as? Bool == true {
                try authorize()
                try validatePlugin(destination)
                try authorize()
                try FileManager.default.copyItem(at: destination, to: oldPlugin)
                try authorize()
                try validatePlugin(oldPlugin)
            }
            try authorize()
            try FileManager.default.copyItem(at: source, to: newPlugin)
            try authorize()
            try validatePlugin(newPlugin)
            try authorize()
            try persist(rollback, to: journal)
            try checkpoint("prepared")
            try authorize()
            try deactivate()
            try authorize()
            try remove(configuration)
            try checkpoint("deactivated")
            try authorize()
            try remove(destination)
            try authorize()
            try FileManager.default.copyItem(at: newPlugin, to: destination)
            try authorize()
            try validatePlugin(destination)
            try checkpoint("plugin_replaced")
            try authorize()
            try persist(value, to: configuration)
            try authorize()
            try setRight(remoteRight, ["class": "evaluate-mechanisms",
                "mechanisms": ["MemStackComputerUseAuthorizationPlugin:allow"], "shared": false])
            try checkpoint("configured")
            var activation = try screen()
            activation["rule"] = [remoteRight] + (activation["rule"] as! [String]).filter { $0 != remoteRight }
            try authorize()
            try setRight(screenRight, activation)
            try checkpoint("activated")
            // Mark the new installation committed before removing rollback data.
            // A failed cleanup is retried, never interpreted as a failed install.
            rollback["committed"] = true
            try authorize()
            try persist(rollback, to: journal)
        } catch {
            do { try recoverLocked() }
            catch { throw Failure.invalidState("installation rollback requires administrator retry: \(error)") }
            throw error
        }
        try? FileManager.default.removeItem(at: directory)
    }

    func recover() throws {
        try exclusively { try recoverLocked() }
    }

    private func recoverLocked() throws {
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        try protectedDirectory(directory)
        // Before the journal is written, neither the installed files nor the
        // authorization database has changed, so staged copies can be discarded.
        guard FileManager.default.fileExists(atPath: journal.path) else {
            try FileManager.default.removeItem(at: directory); return
        }
        try regular(journal)
        guard let rollback = try PropertyListSerialization.propertyList(
            from: Data(contentsOf: journal), format: nil) as? [String: Any],
              let hadPlugin = rollback["had_plugin"] as? Bool,
              let hadBranch = rollback["had_branch"] as? Bool else {
            throw Failure.invalidState("invalid rollback journal")
        }
        if rollback["committed"] as? Bool == true {
            try FileManager.default.removeItem(at: directory); return
        }
        try deactivate()
        try remove(configuration)
        if hadPlugin {
            try validatePlugin(oldPlugin)
            try remove(destination)
            try FileManager.default.copyItem(at: oldPlugin, to: destination)
            try validatePlugin(destination)
        } else { try remove(destination) }
        if let data = rollback["configuration"] as? Data {
            guard let previous = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else {
                throw Failure.invalidState("invalid prior configuration")
            }
            try persist(previous, to: configuration)
        }
        try setRight(remoteRight, rollback["remote_right"] as? [String: Any])
        if hadBranch {
            guard hadPlugin, rollback["configuration"] is Data,
                  rollback["remote_right"] is [String: Any] else {
                throw Failure.invalidState("prior installation was incomplete; ordinary unlock is preserved")
            }
            var current = try screen()
            current["rule"] = [remoteRight] + (current["rule"] as! [String]).filter { $0 != remoteRight }
            try setRight(screenRight, current)
        }
        try FileManager.default.removeItem(at: directory)
    }

    func uninstall() throws {
        try exclusively { try uninstallLocked() }
    }

    private func uninstallLocked() throws {
        try authorize()
        try recoverLocked()
        try authorize()
        try deactivate()
        try authorize()
        try remove(configuration)
        try authorize()
        try setRight(remoteRight, nil)
        if FileManager.default.fileExists(atPath: destination.path) {
            try validatePlugin(destination)
            try authorize()
            try remove(destination)
        }
    }

    private func exclusively(_ operation: () throws -> Void) throws {
        try authorize()
        let parent = open(support.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard parent >= 0 else { throw Failure.invalidState("cannot open installation directory") }
        defer { close(parent) }
        var parentInfo = stat()
        guard fstat(parent, &parentInfo) == 0, parentInfo.st_uid == owner,
              parentInfo.st_mode & S_IFMT == S_IFDIR, parentInfo.st_mode & 0o022 == 0 else {
            throw Failure.invalidState("installation directory is not protected")
        }
        try authorize()
        let descriptor = openat(parent, "installation.lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { throw Failure.invalidState("cannot open installation lock") }
        defer { close(descriptor) }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_uid == owner,
              info.st_mode & S_IFMT == S_IFREG, info.st_mode & 0o077 == 0, info.st_nlink == 1 else {
            throw Failure.invalidState("installation lock is not private")
        }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            if errno == EWOULDBLOCK { throw Failure.busy }
            throw Failure.invalidState("cannot acquire installation lock")
        }
        defer { _ = flock(descriptor, LOCK_UN) }
        // Keep this inode after unlock. Unlinking it would let a later process
        // lock a replacement while an earlier process still holds the old file.
        // Kernel ownership releases the lock even if an installer is killed.
        try operation()
    }
    private func screen() throws -> [String: Any] {
        guard let value = try readRight(screenRight), value["class"] as? String == "rule",
              value["k-of-n"] as? Int == 1, let rules = value["rule"] as? [String],
              !rules.filter({ $0 != remoteRight }).isEmpty else {
            throw Failure.invalidState("ordinary screensaver authorization branches are required")
        }
        return value
    }
    private func deactivate() throws {
        var value = try screen()
        let rules = value["rule"] as! [String]
        if rules.contains(remoteRight) {
            value["rule"] = rules.filter { $0 != remoteRight }
            try setRight(screenRight, value)
        }
    }
    private func protectedDirectory(_ url: URL) throws {
        var info = stat()
        guard lstat(url.path, &info) == 0, info.st_uid == owner,
              info.st_mode & S_IFMT == S_IFDIR, info.st_mode & 0o077 == 0 else {
            throw Failure.invalidState("rollback directory is not private")
        }
    }
    private func regular(_ url: URL) throws {
        var info = stat()
        guard lstat(url.path, &info) == 0, info.st_uid == owner,
              info.st_mode & S_IFMT == S_IFREG, info.st_mode & 0o022 == 0 else {
            throw Failure.invalidState("configuration is not protected")
        }
    }
    private func persist(_ value: [String: Any], to url: URL) throws {
        if FileManager.default.fileExists(atPath: url.path) { try regular(url) }
        let data = try PropertyListSerialization.data(fromPropertyList: value, format: .xml, options: 0)
        try data.write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: url == configuration ? 0o644 : 0o600,
            .ownerAccountID: owner], ofItemAtPath: url.path)
        // The system plugin reads the committed configuration as root; no
        // credentials or user content are stored in this transaction directory.
        let fd = open(url.path, O_RDONLY | O_NOFOLLOW)
        guard fd >= 0 else { throw Failure.invalidState("cannot sync configuration") }
        defer { close(fd) }
        guard fsync(fd) == 0 else { throw Failure.invalidState("cannot sync configuration") }
    }
    private func remove(_ url: URL) throws {
        if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }
    }
}
