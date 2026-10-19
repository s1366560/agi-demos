import Foundation
import Security
import Darwin

let support = URL(fileURLWithPath: "/Library/Application Support/MemStack/ComputerUse", isDirectory: true)
let destination = URL(fileURLWithPath: "/Library/Security/SecurityAgentPlugins/MemStackComputerUseAuthorizationPlugin.bundle")
let remoteRight = "ai.agistack.desktop.cua.locked-use"
let screenRight = "system.login.screensaver"
let configuration = support.appendingPathComponent("locked-use.plist")
let backup = support.appendingPathComponent("screensaver-backup.plist")

enum InstallError: Error { case failure(String) }
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
func write(_ value: [String: Any], at url: URL) throws {
    let data = try PropertyListSerialization.data(fromPropertyList: value, format: .xml, options: 0)
    try data.write(to: url, options: .atomic)
    try FileManager.default.setAttributes([.posixPermissions: 0o644, .ownerAccountID: 0], ofItemAtPath: url.path)
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
func protectedPath(_ path: URL) throws {
    var current = URL(fileURLWithPath: "/", isDirectory: true)
    for component in path.pathComponents.dropFirst() {
        current.appendPathComponent(component)
        var info = stat()
        if lstat(current.path, &info) == 0 {
            guard (info.st_mode & S_IFMT) == S_IFDIR, info.st_uid == 0, (info.st_mode & 0022) == 0 else {
                throw InstallError.failure("installation directory is not protected")
            }
        } else if errno != ENOENT { throw InstallError.failure("cannot inspect installation directory") }
    }
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
    let arguments = CommandLine.arguments
    guard arguments.count >= 2 else { throw InstallError.failure("install|uninstall|status is required") }
    if arguments[1] == "status" {
        print(FileManager.default.fileExists(atPath: configuration.path) ? "installed" : "not_installed")
        exit(0)
    }
    guard geteuid() == 0 else { throw InstallError.failure("administrator authorization is required") }
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
        let expectedTeam = try signingTeam(URL(fileURLWithPath: arguments[0]), expectedID: "ai.agistack.desktop.cua.lock-installer")
        guard try signingTeam(helper, expectedID: "ai.agistack.desktop.cua-helper") == expectedTeam,
              try signingTeam(source, expectedID: "ai.agistack.desktop.cua.authorization-plugin") == expectedTeam else {
            throw InstallError.failure("component signing teams do not match the installer")
        }
        try protectedPath(support)
        try protectedPath(destination.deletingLastPathComponent())
        let requirement = try verifiedRequirement(helper)
        let previous = try readRight(screenRight)
        guard previous["class"] as? String == "rule", previous["k-of-n"] as? Int == 1,
              let rules = previous["rule"] as? [String], !rules.isEmpty else {
            throw InstallError.failure("unsupported screensaver authorization configuration")
        }
        try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o755, .ownerAccountID: 0])
        if FileManager.default.fileExists(atPath: destination.path) {
            try safeBundle(destination); try FileManager.default.removeItem(at: destination)
        }
        try FileManager.default.copyItem(at: source, to: destination)
        try protectBundle(destination)
        if !FileManager.default.fileExists(atPath: backup.path) { try write(previous, at: backup) }
        try write(["socket_path": socket.path, "owner_uid": owner, "service_requirement": requirement], at: configuration)
        try setRight(remoteRight, ["class": "evaluate-mechanisms",
                                  "mechanisms": ["MemStackComputerUseAuthorizationPlugin:allow"], "shared": false])
        var changed = previous
        changed["rule"] = [remoteRight] + rules.filter { $0 != remoteRight }
        do { try setRight(screenRight, changed) } catch {
            try? setRight(screenRight, previous); try? FileManager.default.removeItem(at: configuration); throw error
        }
        print("installed")
    } else if arguments[1] == "uninstall" {
        var rule = try readRight(screenRight)
        guard let rules = rule["rule"] as? [String] else { throw InstallError.failure("unsupported authorization configuration") }
        let remaining = rules.filter { $0 != remoteRight }
        guard !remaining.isEmpty else { throw InstallError.failure("no safe screensaver authorization branch would remain") }
        rule["rule"] = remaining
        try setRight(screenRight, rule)
        if FileManager.default.fileExists(atPath: destination.path) {
            try safeBundle(destination); try FileManager.default.removeItem(at: destination)
        }
        try? FileManager.default.removeItem(at: configuration)
        var authorization: AuthorizationRef?
        if AuthorizationCreate(nil, nil, [], &authorization) == errSecSuccess, let authorization = authorization {
            _ = AuthorizationRightRemove(authorization, remoteRight); AuthorizationFree(authorization, [])
        }
        print("uninstalled")
    } else { throw InstallError.failure("unknown installer operation") }
} catch {
    FileHandle.standardError.write(Data("locked-use installer failed: \(error)\n".utf8))
    exit(1)
}
