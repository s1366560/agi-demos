import Darwin
import Foundation

enum LockedUseInstallerTests {
    static let remote = "ai.agistack.desktop.cua.locked-use"
    static let screen = "system.login.screensaver"
    static func child(_ arguments: [String]) throws {
        let root = URL(fileURLWithPath: arguments[2], isDirectory: true)
        let point = arguments[3]
        if point.hasPrefix("concurrent-") {
            do {
                let change = transaction(root)
                switch point {
                case "concurrent-install":
                    try change.install(source: root.appendingPathComponent("source.bundle"), configuration: ["version": "new"])
                case "concurrent-recover": try change.recover()
                case "concurrent-uninstall": try change.uninstall()
                default: preconditionFailure("unexpected transaction fixture operation")
                }
            } catch LockedUseInstallTransaction.Failure.busy { _exit(75) }
            _exit(71)
        }
        let change = transaction(root, checkpoint: { if $0 == point { _exit(70) } })
        try change.install(source: root.appendingPathComponent("source.bundle"), configuration: ["version": "new"])
        _exit(71)
    }
    static func transaction(_ root: URL, authorize: @escaping () throws -> Void = {},
                            checkpoint: @escaping (String) throws -> Void = { _ in }) -> LockedUseInstallTransaction {
        let rights = root.appendingPathComponent("rights.plist")
        return LockedUseInstallTransaction(support: root.appendingPathComponent("support"),
            destination: root.appendingPathComponent("installed.bundle"), owner: getuid(),
            readRight: { name in try read(rights)[name] as? [String: Any] },
            setRight: { name, value in
                var state = try read(rights); state[name] = value
                try save(state, rights)
            }, validatePlugin: { path in
                let content = try String(contentsOf: path.appendingPathComponent("executable"), encoding: .utf8)
                precondition(["old", "new"].contains(content))
            }, authorize: authorize, checkpoint: checkpoint)
    }
    static func read(_ path: URL) throws -> [String: Any] {
        try PropertyListSerialization.propertyList(from: Data(contentsOf: path), format: nil) as! [String: Any]
    }
    static func save(_ value: [String: Any], _ path: URL) throws {
        try PropertyListSerialization.data(fromPropertyList: value, format: .xml, options: 0).write(to: path, options: .atomic)
    }
    static func fixture() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("memstack-locked-install-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        for folder in ["support", "source.bundle", "installed.bundle"] {
            try FileManager.default.createDirectory(at: root.appendingPathComponent(folder), withIntermediateDirectories: false)
        }
        try Data("old".utf8).write(to: root.appendingPathComponent("installed.bundle/executable"))
        try Data("new".utf8).write(to: root.appendingPathComponent("source.bundle/executable"))
        try save(["version": "old"], root.appendingPathComponent("support/locked-use.plist"))
        try save([screen: ["class": "rule", "k-of-n": 1, "rule": [remote, "authenticate-session-owner"]],
            remote: ["class": "evaluate-mechanisms", "mechanisms": ["previous:allow"]]], root.appendingPathComponent("rights.plist"))
        return root
    }
    static func run() throws {
        try protectedSystemPaths()
        for point in ["prepared", "deactivated", "plugin_replaced", "configured", "activated"] {
            let root = try fixture()
            defer { try? FileManager.default.removeItem(at: root) }
            let child = Process()
            child.executableURL = Bundle.main.executableURL!
            child.arguments = ["--install-transaction-child", root.path, point]
            try child.run(); child.waitUntilExit()
            precondition(child.terminationStatus == 70, "fixture must terminate at the requested installation step")
            // An administrator changed an unrelated branch while our process was
            // absent. Recovery must preserve it, even when restoring an upgrade.
            let rightsPath = root.appendingPathComponent("rights.plist")
            var rights = try read(rightsPath), rule = rights[screen] as! [String: Any]
            rule["rule"] = (rule["rule"] as! [String]) + ["third-party-owner-unlock"]
            rights[screen] = rule; try save(rights, rightsPath)
            try transaction(root).recover()
            let recovered = try read(rightsPath)
            precondition((recovered[screen] as! [String: Any])["rule"] as! [String]
                == [remote, "authenticate-session-owner", "third-party-owner-unlock"])
            precondition((recovered[remote] as! [String: Any])["mechanisms"] as! [String] == ["previous:allow"])
            let previousConfiguration = try read(root.appendingPathComponent("support/locked-use.plist"))
            precondition(previousConfiguration["version"] as? String == "old")
            let binary = try String(contentsOf: root.appendingPathComponent("installed.bundle/executable"), encoding: .utf8)
            precondition(binary == "old")
            precondition(!FileManager.default.fileExists(atPath: root.appendingPathComponent("support/install-transaction").path))
        }
        let root = try fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        let change = transaction(root)
        try change.install(source: root.appendingPathComponent("source.bundle"), configuration: ["version": "new"])
        let committed = try read(root.appendingPathComponent("support/locked-use.plist"))
        precondition(committed["version"] as? String == "new")
        try change.uninstall()
        let remaining = try read(root.appendingPathComponent("rights.plist"))
        precondition(remaining[remote] == nil)
        precondition((remaining[screen] as! [String: Any])["rule"] as! [String] == ["authenticate-session-owner"])
        precondition(!FileManager.default.fileExists(atPath: root.appendingPathComponent("installed.bundle").path))
        precondition(!FileManager.default.fileExists(atPath: root.appendingPathComponent("support/locked-use.plist").path))
        // A failed first installation must remove its new files and its right,
        // leaving the ordinary owner-authentication branch intact.
        enum ExpectedFailure: Error { case interrupted }
        let firstInstall = transaction(root, checkpoint: { point in
            if point == "configured" { throw ExpectedFailure.interrupted }
        })
        do {
            try firstInstall.install(source: root.appendingPathComponent("source.bundle"), configuration: ["version": "new"])
            preconditionFailure("injected installation failure was ignored")
        } catch ExpectedFailure.interrupted {}
        let freshRollback = try read(root.appendingPathComponent("rights.plist"))
        precondition(freshRollback[remote] == nil)
        precondition((freshRollback[screen] as! [String: Any])["rule"] as! [String] == ["authenticate-session-owner"])
        precondition(!FileManager.default.fileExists(atPath: root.appendingPathComponent("installed.bundle").path))
        precondition(!FileManager.default.fileExists(atPath: root.appendingPathComponent("support/locked-use.plist").path))
        try firstInstall.recover()
        try concurrentOperations()
        try untrustedLockFiles()
        print("LOCKED_USE_INSTALL_RECOVERY_OK")
    }

    private static func protectedSystemPaths() throws {
        // Inspect the actual installation ancestors without creating files or
        // requesting administrator authorization. A decimal 0022 mask wrongly
        // rejects the standard root-owned 0755 system directories.
        for path in ["/Library/Application Support", "/Library/Security/SecurityAgentPlugins",
                     "/Library/Application Support/memstack-test-" + UUID().uuidString] {
            try protectedPath(URL(fileURLWithPath: path, isDirectory: true))
        }
        for path in ["/tmp", FileManager.default.homeDirectoryForCurrentUser.path] {
            do {
                try protectedPath(URL(fileURLWithPath: path, isDirectory: true))
                preconditionFailure("an untrusted installation ancestor was accepted")
            } catch InstallError.failure {}
        }
    }

    private static func concurrentOperations() throws {
        for operation in ["install", "recover", "uninstall"] {
            let root = try fixture()
            defer { try? FileManager.default.removeItem(at: root) }
            let first = transaction(root, checkpoint: { point in
                guard point == "prepared" else { return }
                let child = Process()
                child.executableURL = Bundle.main.executableURL!
                child.arguments = ["--install-transaction-child", root.path, "concurrent-" + operation]
                try child.run(); child.waitUntilExit()
                precondition(child.terminationStatus == 75,
                    "another process must not recover or replace an active installation")
            })
            try first.install(source: root.appendingPathComponent("source.bundle"), configuration: ["version": "new"])
            let installed = try read(root.appendingPathComponent("support/locked-use.plist"))
            precondition(installed["version"] as? String == "new")
            let binary = try String(contentsOf: root.appendingPathComponent("installed.bundle/executable"), encoding: .utf8)
            precondition(binary == "new")
            let rights = try read(root.appendingPathComponent("rights.plist"))
            precondition((rights[screen] as! [String: Any])["rule"] as! [String]
                == [remote, "authenticate-session-owner"])
            // A completed transaction releases the kernel lock for a new process.
            let child = Process()
            child.executableURL = Bundle.main.executableURL!
            child.arguments = ["--install-transaction-child", root.path, "prepared"]
            try child.run(); child.waitUntilExit()
            precondition(child.terminationStatus == 70)
            try transaction(root).recover()
            let recovered = try read(root.appendingPathComponent("support/locked-use.plist"))
            precondition(recovered["version"] as? String == "new")
        }
    }

    private static func untrustedLockFiles() throws {
        for type in ["symlink", "hardlink", "public"] {
            let root = try fixture()
            defer { try? FileManager.default.removeItem(at: root) }
            let lock = root.appendingPathComponent("support/installation.lock")
            let other = root.appendingPathComponent("other-file")
            try Data("untouched".utf8).write(to: other)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: other.path)
            if type == "symlink" {
                try FileManager.default.createSymbolicLink(at: lock, withDestinationURL: other)
            } else if type == "hardlink" {
                try FileManager.default.linkItem(at: other, to: lock)
            } else {
                try Data().write(to: lock)
                try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: lock.path)
            }
            do {
                try transaction(root).uninstall()
                preconditionFailure("an untrusted installation lock was accepted")
            } catch LockedUseInstallTransaction.Failure.invalidState {}
            let previous = try read(root.appendingPathComponent("support/locked-use.plist"))
            precondition(previous["version"] as? String == "old")
            let contents = try String(contentsOf: other, encoding: .utf8)
            precondition(contents == "untouched")
        }
    }
}
