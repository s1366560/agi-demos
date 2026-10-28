import AppKit
import Foundation
import Security

enum LockedUseManagement {
    static var helperURL: URL { URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL }
    static var componentRoot: URL {
        if Bundle.main.bundleURL.pathExtension == "app", let resources = Bundle.main.resourceURL {
            return resources.appendingPathComponent("locked-use")
        }
        return helperURL.deletingLastPathComponent().appendingPathComponent("locked-use")
    }
    static var installedPlugin: URL {
        URL(fileURLWithPath: "/Library/Security/SecurityAgentPlugins/MemStackComputerUseAuthorizationPlugin.bundle")
    }
    static var socketURL: URL {
        URL(fileURLWithPath: "/tmp/agi-cua-lock-\(getuid())/authorization.sock")
    }
    static func componentTeam() throws -> String {
        let components: [(URL, String)] = [
            (helperURL, "ai.agistack.desktop.cua-helper"),
            (componentRoot.appendingPathComponent("memstack-cua-guardian"), "ai.agistack.desktop.cua.guardian"),
            (componentRoot.appendingPathComponent("memstack-cua-lock-installer"), "ai.agistack.desktop.cua.lock-installer"),
            (componentRoot.appendingPathComponent("MemStackComputerUseAuthorizationPlugin.bundle"), "ai.agistack.desktop.cua.authorization-plugin")]
        var expected: String?
        for (url, identifier) in components {
            guard let team = LockedUseSigning.team(url, identifier: identifier), expected == nil || expected == team else {
                throw ActionError.failure(kind: "permission_required", message: "stable_matching_signatures_required")
            }
            expected = team
        }
        return expected!
    }
    static func configuration() throws -> [String: Any] {
        let url = LockedUseCoordinator.configurationURL
        guard !FileManager.default.fileExists(atPath: url.deletingLastPathComponent()
            .appendingPathComponent("install-transaction").path) else {
            throw ActionError.failure(kind: "permission_required", message: "system_component_recovery_required")
        }
        var attributes = stat()
        guard lstat(url.path, &attributes) == 0 else {
            throw ActionError.failure(kind: "permission_required", message: "system_component_install_required")
        }
        guard configurationIsProtected(attributes),
              let config = NSDictionary(contentsOf: url) as? [String: Any],
              (config["owner_uid"] as? NSNumber)?.uint32Value == getuid(),
              config["socket_path"] as? String == socketURL.path,
              let requirementText = config["service_requirement"] as? String else {
            throw ActionError.failure(kind: "permission_required", message: "system_component_configuration_invalid")
        }
        let team = try componentTeam()
        guard LockedUseSigning.team(installedPlugin, identifier: "ai.agistack.desktop.cua.authorization-plugin") == team else {
            throw ActionError.failure(kind: "permission_required", message: "installed_plugin_signature_mismatch")
        }
        var code: SecStaticCode?, requirement: SecRequirement?
        guard SecStaticCodeCreateWithPath(helperURL as CFURL, [], &code) == errSecSuccess, let code = code,
              SecRequirementCreateWithString(requirementText as CFString, [], &requirement) == errSecSuccess,
              SecStaticCodeCheckValidity(code, [], requirement) == errSecSuccess else {
            throw ActionError.failure(kind: "permission_required", message: "installed_helper_requirement_mismatch")
        }
        var screen: CFDictionary?, remote: CFDictionary?
        guard AuthorizationRightGet("system.login.screensaver", &screen) == errSecSuccess,
              AuthorizationRightGet("ai.agistack.desktop.cua.locked-use", &remote) == errSecSuccess,
              let screenRule = screen as? [String: Any], screenRule["class"] as? String == "rule",
              screenRule["k-of-n"] as? Int == 1,
              let rules = screenRule["rule"] as? [String], rules.contains("ai.agistack.desktop.cua.locked-use"),
              rules.contains(where: { $0 != "ai.agistack.desktop.cua.locked-use" }),
              let remoteRule = remote as? [String: Any], remoteRule["class"] as? String == "evaluate-mechanisms",
              remoteRule["mechanisms"] as? [String] == ["MemStackComputerUseAuthorizationPlugin:allow"] else {
            throw ActionError.failure(kind: "permission_required", message: "system_authorization_branch_missing")
        }
        return config
    }
    static func install(_ install: Bool, cancellation: Cancellation, generation: String) throws -> [String: Any] {
        try cancellation.check()
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
            (root.appendingPathComponent("memstack-cua-guardian"), "ai.agistack.desktop.cua.guardian"),
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
                throw ActionError.failure(kind: "permission_required", message: "stable matching component signatures are required before administrator authorization")
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
        let request = LockedUseActivationRequest(requestID: UUID().uuidString, generation: generation,
            arguments: arguments, ownerUID: getuid())
        let team = expectedTeam!
        let activation = try LockedUseActivationBroker(request: request, current: {
            try cancellation.check()
        }, verifyPeer: { descriptor in
            LockedUseActivationSocket.signedPeer(descriptor, uid: 0,
                identifier: "ai.agistack.desktop.cua.lock-installer", team: team)
        })
        defer { activation.stop() }
        let activatedArguments = arguments + ["--activation", activation.socketURL.path,
            request.requestID, request.generation, String(request.ownerUID)]
        // Only fixed executable arguments enter this administrator flow. No user
        // content or command text is accepted from a tool request.
        let command = activatedArguments.map { "'" + $0.replacingOccurrences(of: "'", with: "'\\''") + "'" }.joined(separator: " ")
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
        // Recheck the admitted generation's token. A later session reset must
        // not revive an installation that was cancelled during signature checks.
        try cancellation.check()
        let result = script.executeAppleEvent(event, error: &error)
        try cancellation.check()
        if let error = error { throw installationFailure(error) }
        var status = LockedUseCoordinator.shared.probe()
        status["installed"] = install; status["enabled"] = false; status["result"] = result.stringValue ?? ""
        return status
    }

    static func configurationIsProtected(_ attributes: stat) -> Bool {
        (attributes.st_mode & S_IFMT) == S_IFREG && attributes.st_uid == 0
            && attributes.st_mode & 0o022 == 0
    }

    static func installationFailure(_ error: NSDictionary) -> ActionError {
        let code = (error[NSAppleScript.errorNumber] as? NSNumber)?.intValue
        if code == -128 {
            return ActionError.failure(kind: "administrator_authorization_cancelled",
                message: "administrator authorization was cancelled")
        }
        // The script only executes the fixed packaged installer and host-owned
        // paths. Preserve its diagnostic instead of reporting every exit as a
        // missing authorization, including failures after successful elevation.
        let detail = (error[NSAppleScript.errorMessage] as? String) ?? "unknown installation error"
        let number = code.map(String.init) ?? "unknown"
        return ActionError.failure(kind: "locked_use_setup_failed",
            message: "AppleScript error \(number): \(String(detail.prefix(2048)))")
    }
}
