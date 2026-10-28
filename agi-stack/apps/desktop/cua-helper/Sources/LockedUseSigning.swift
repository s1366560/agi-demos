import Foundation
import Security

enum LockedUseSigning {
    static func metadata(_ url: URL, identifier: String) -> [String: Any]? {
        var code: SecStaticCode?, information: CFDictionary?
        guard SecStaticCodeCreateWithPath(url as CFURL, [], &code) == errSecSuccess, let code = code,
              SecStaticCodeCheckValidity(code, [], nil) == errSecSuccess,
              SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &information) == errSecSuccess,
              let metadata = information as? [String: Any],
              metadata[kSecCodeInfoIdentifier as String] as? String == identifier,
              let team = metadata[kSecCodeInfoTeamIdentifier as String] as? String, !team.isEmpty else { return nil }
        return metadata
    }
    static func team(_ url: URL, identifier: String) -> String? {
        metadata(url, identifier: identifier)?[kSecCodeInfoTeamIdentifier as String] as? String
    }
    static func process(_ identity: LockedUseProcessIdentity, identifier: String, team: String) -> Bool {
        guard identity.alive else { return false }
        var code: SecCode?, requirement: SecRequirement?
        let attributes = [kSecGuestAttributePid as String: NSNumber(value: identity.pid)] as CFDictionary
        let text = "identifier \"\(identifier)\" and anchor apple generic and certificate leaf[subject.OU] = \"\(team)\""
        guard SecRequirementCreateWithString(text as CFString, [], &requirement) == errSecSuccess,
              SecCodeCopyGuestWithAttributes(nil, attributes, [], &code) == errSecSuccess,
              let code = code, SecCodeCheckValidity(code, [], requirement) == errSecSuccess else { return false }
        return identity.alive
    }
}
