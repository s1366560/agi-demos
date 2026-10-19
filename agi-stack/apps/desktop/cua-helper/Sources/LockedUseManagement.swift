import AppKit
import Foundation
import Security

enum LockedUseManagement {
    static func install(_ install: Bool) throws -> [String: Any] {
        let executable = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
        let root: URL
        if Bundle.main.bundleURL.pathExtension == "app", let resources = Bundle.main.resourceURL {
            root = resources.appendingPathComponent("locked-use")
        } else {
            root = executable.deletingLastPathComponent().appendingPathComponent("locked-use")
        }
        let installer = root.appendingPathComponent("memstack-cua-lock-installer")
        guard FileManager.default.isExecutableFile(atPath: installer.path) else {
            throw ActionError.failure(kind: "unsupported", message: "the signed lock continuity installer is not packaged")
        }
        let paths: [(URL, String)] = [(installer, "ai.agistack.desktop.cua.lock-installer"),
            (executable, "ai.agistack.desktop.cua-helper"),
            (root.appendingPathComponent("MemStackComputerUseAuthorizationPlugin.bundle"),
             "ai.agistack.desktop.cua.authorization-plugin")]
        var expectedTeam: String?
        for (path, identifier) in paths {
            var code: SecStaticCode?; var information: CFDictionary?
            guard SecStaticCodeCreateWithPath(path as CFURL, [], &code) == errSecSuccess, let code = code,
                  SecStaticCodeCheckValidity(code, [], nil) == errSecSuccess,
                  SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &information) == errSecSuccess,
                  let metadata = information as? [String: Any],
                  metadata[kSecCodeInfoIdentifier as String] as? String == identifier,
                  let team = metadata[kSecCodeInfoTeamIdentifier as String] as? String, !team.isEmpty,
                  expectedTeam == nil || expectedTeam == team else {
                throw ActionError.failure(kind: "unverified", message: "stable matching component signatures are required before administrator authorization")
            }
            expectedTeam = team
        }
        let directory = URL(fileURLWithPath: "/tmp/agi-cua-lock-\(getuid())", isDirectory: true)
        if install {
            if FileManager.default.fileExists(atPath: directory.path) {
                let values = try directory.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey])
                let attributes = try FileManager.default.attributesOfItem(atPath: directory.path)
                guard values.isSymbolicLink != true, values.isDirectory == true,
                      (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
                      (attributes[.posixPermissions] as? NSNumber)?.intValue == 0o700 else {
                    throw ActionError.failure(kind: "permission_required", message: "lock broker directory is not private")
                }
            } else {
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                    attributes: [.posixPermissions: 0o700])
            }
        }
        let arguments = install
            ? [installer.path, "install", root.appendingPathComponent("MemStackComputerUseAuthorizationPlugin.bundle").path,
               executable.path, directory.appendingPathComponent("authorization.sock").path, String(getuid())]
            : [installer.path, "uninstall"]
        // Only fixed executable arguments enter this administrator flow. No user
        // content or command text is accepted from a tool request.
        let command = arguments.map { "'" + $0.replacingOccurrences(of: "'", with: "'\\''") + "'" }.joined(separator: " ")
        let source = """
        on administer(commandText)
            return do shell script commandText with administrator privileges
        end administer
        """
        let script = NSAppleScript(source: source)!
        let event = NSAppleEventDescriptor(eventClass: 0x61736372, eventID: 0x70736272,
            targetDescriptor: NSAppleEventDescriptor.currentProcess(), returnID: -1, transactionID: 0)
        event.setParam(NSAppleEventDescriptor(string: "administer"), forKeyword: 0x736E616D)
        let list = NSAppleEventDescriptor.list(); list.insert(NSAppleEventDescriptor(string: command), at: 1)
        event.setParam(list, forKeyword: 0x2D2D2D2D)
        var error: NSDictionary?
        let result = script.executeAppleEvent(event, error: &error)
        guard error == nil else {
            throw ActionError.failure(kind: "permission_required", message: "administrator authorization was not completed")
        }
        return ["installed": install, "enabled": false, "state": "unverified", "result": result.stringValue ?? ""]
    }
}
