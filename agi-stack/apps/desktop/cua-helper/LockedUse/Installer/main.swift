import Foundation
import Security
import Darwin

let support = URL(fileURLWithPath: "/Library/Application Support/MemStack/ComputerUse", isDirectory: true)
let destination = URL(fileURLWithPath: "/Library/Security/SecurityAgentPlugins/MemStackComputerUseAuthorizationPlugin.bundle")
let remoteRight = "ai.agistack.desktop.cua.locked-use"
let screenRight = "system.login.screensaver"
let configuration = support.appendingPathComponent("locked-use.plist")

func readRight(_ name: String) throws -> [String: Any] {
    var value: CFDictionary?
    guard AuthorizationRightGet(name, &value) == errSecSuccess,
          let dictionary = value as? [String: Any] else { throw InstallError.failure("cannot read authorization rule") }
    return dictionary
}
func setRight(_ name: String, _ value: [String: Any]) throws {
    var authorization: AuthorizationRef?
    guard AuthorizationCreate(nil, nil, [], &authorization) == errSecSuccess,
          let authorization = authorization else { throw InstallError.failure("cannot create authorization") }
    defer { AuthorizationFree(authorization, []) }
    guard AuthorizationRightSet(authorization, name, value as CFDictionary, nil, nil, nil) == errSecSuccess else {
        throw InstallError.failure("cannot update authorization rule")
    }
}
func optionalRight(_ name: String) throws -> [String: Any]? {
    var value: CFDictionary?
    let status = AuthorizationRightGet(name, &value)
    if status == errAuthorizationDenied { return nil }
    guard status == errSecSuccess, let result = value as? [String: Any] else {
        throw InstallError.failure("cannot inspect authorization rule")
    }
    return result
}
func replaceRight(_ name: String, _ value: [String: Any]?) throws {
    if let value = value { try setRight(name, value); return }
    guard try optionalRight(name) != nil else { return }
    var authorization: AuthorizationRef?
    guard AuthorizationCreate(nil, nil, [], &authorization) == errSecSuccess,
          let authorization = authorization else { throw InstallError.failure("cannot create authorization") }
    defer { AuthorizationFree(authorization, []) }
    guard AuthorizationRightRemove(authorization, name) == errSecSuccess else {
        throw InstallError.failure("cannot remove authorization rule")
    }
}
func signingTeam(_ source: URL, expectedID: String) throws -> String {
    var code: SecStaticCode?; var information: CFDictionary?
    guard SecStaticCodeCreateWithPath(source as CFURL, [], &code) == errSecSuccess, let code = code,
          SecStaticCodeCheckValidity(code, [], nil) == errSecSuccess,
          SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &information) == errSecSuccess,
          let info = information as? [String: Any],
          let team = info[kSecCodeInfoTeamIdentifier as String] as? String, !team.isEmpty,
          info[kSecCodeInfoIdentifier as String] as? String == expectedID else {
        throw InstallError.failure("a stable component signature is required")
    }
    return team
}
func verifiedRequirement(_ source: URL) throws -> String {
    var code: SecStaticCode?; var information: CFDictionary?
    guard SecStaticCodeCreateWithPath(source as CFURL, [], &code) == errSecSuccess, let code = code,
          SecStaticCodeCheckValidity(code, [], nil) == errSecSuccess,
          SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &information) == errSecSuccess,
          let info = information as? [String: Any],
          let team = info[kSecCodeInfoTeamIdentifier as String] as? String, !team.isEmpty,
          info[kSecCodeInfoIdentifier as String] as? String == "ai.agistack.desktop.cua-helper" else {
        throw InstallError.failure("a stable signed helper identity is required")
    }
    return "identifier \"ai.agistack.desktop.cua-helper\" and anchor apple generic and certificate leaf[subject.OU] = \"\(team)\""
}
func safeBundle(_ url: URL) throws {
    guard Bundle(url: url)?.bundleIdentifier == "ai.agistack.desktop.cua.authorization-plugin" else {
        throw InstallError.failure("unexpected authorization plugin")
    }
    var code: SecStaticCode?
    guard SecStaticCodeCreateWithPath(url as CFURL, [], &code) == errSecSuccess,
          let code = code, SecStaticCodeCheckValidity(code, [], nil) == errSecSuccess else {
        throw InstallError.failure("plugin signature is invalid")
    }
    let enumerator = FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.isSymbolicLinkKey])
    while let entry = enumerator?.nextObject() as? URL {
        if try entry.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink == true {
            throw InstallError.failure("plugin contains a symbolic link")
        }
    }
}
func protectBundle(_ url: URL) throws {
    let enumerator = FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey])
    var entries = [url]
    while let entry = enumerator?.nextObject() as? URL { entries.append(entry) }
    for entry in entries {
        let values = try entry.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard values.isSymbolicLink != true else { throw InstallError.failure("copied plugin contains a symbolic link") }
        let executable = entry.lastPathComponent == "MemStackComputerUseAuthorizationPlugin"
        try FileManager.default.setAttributes([.ownerAccountID: 0, .groupOwnerAccountID: 0,
            .posixPermissions: values.isDirectory == true || executable ? 0o755 : 0o644], ofItemAtPath: entry.path)
    }
    try safeBundle(url)
}

do {
    let command = CommandLine.arguments
    guard command.count >= 2 else { throw InstallError.failure("install|uninstall|status is required") }
    if command[1] == "status" {
        print(FileManager.default.fileExists(atPath: configuration.path) ? "installed" : "not_installed")
        exit(0)
    }
    guard geteuid() == 0 else { throw InstallError.failure("administrator authorization is required") }
    let (request, activationSocket) = try LockedUseActivationRequest.parseCommand(command)
    let arguments = request.arguments
    let expectedTeam = try signingTeam(URL(fileURLWithPath: arguments[0]), expectedID: "ai.agistack.desktop.cua.lock-installer")
    let activation = try LockedUseActivationClient(socketURL: activationSocket, request: request,
        verifyPeer: { descriptor in
            LockedUseActivationSocket.signedPeer(descriptor, uid: request.ownerUID,
                identifier: "ai.agistack.desktop.cua-helper", team: expectedTeam)
        })
    if arguments[1] == "install" {
        guard arguments.count == 6, let owner = UInt32(arguments[5]), owner > 0 else {
            throw InstallError.failure("install requires plugin, helper, socket, and owner UID")
        }
        let source = URL(fileURLWithPath: arguments[2])
        let helper = URL(fileURLWithPath: arguments[3])
        let socket = URL(fileURLWithPath: arguments[4])
        guard source.path.hasPrefix("/"), helper.path.hasPrefix("/"), socket.path.utf8.count < 104 else {
            throw InstallError.failure("invalid component paths")
        }
        try safeBundle(source)
        guard try signingTeam(helper, expectedID: "ai.agistack.desktop.cua-helper") == expectedTeam,
              try signingTeam(source, expectedID: "ai.agistack.desktop.cua.authorization-plugin") == expectedTeam else {
            throw InstallError.failure("component signing teams do not match the installer")
        }
        try protectedPath(support)
        try protectedPath(destination.deletingLastPathComponent())
        let requirement = try verifiedRequirement(helper)
        try activation.check()
        try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o755, .ownerAccountID: 0])
        let transaction = LockedUseInstallTransaction(support: support, destination: destination,
            readRight: optionalRight, setRight: replaceRight, validatePlugin: { path in
                try safeBundle(path)
                guard try signingTeam(path, expectedID: "ai.agistack.desktop.cua.authorization-plugin") == expectedTeam else {
                    throw InstallError.failure("plugin signing team changed")
                }
                if path != source { try protectBundle(path) }
            }, authorize: { try activation.check() })
        try transaction.install(source: source, configuration: ["socket_path": socket.path,
            "owner_uid": owner, "service_requirement": requirement])
        print("installed")
    } else if arguments[1] == "uninstall" {
        try protectedPath(support)
        try protectedPath(destination.deletingLastPathComponent())
        try activation.check()
        try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o755, .ownerAccountID: 0])
        let transaction = LockedUseInstallTransaction(support: support, destination: destination,
            readRight: optionalRight, setRight: replaceRight, validatePlugin: safeBundle,
            authorize: { try activation.check() })
        try transaction.uninstall()
        print("uninstalled")
    } else { throw InstallError.failure("unknown installer operation") }
} catch {
    FileHandle.standardError.write(Data("locked-use installer failed: \(error)\n".utf8))
    exit(1)
}
