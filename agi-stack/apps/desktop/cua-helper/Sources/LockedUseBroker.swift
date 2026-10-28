import Foundation
import Security
import Darwin

/// Only the system authorization hosts may consume one pending authorization.
/// Peer identity is checked from the kernel audit token rather than request text.
final class LockedUseBroker {
    private let endpoint: LockedUseBrokerSocket
    private let approve: () -> Bool
    init(socketURL: URL, approve: @escaping () -> Bool) throws {
        self.approve = approve
        let endpoint = try LockedUseBrokerSocket(url: socketURL)
        self.endpoint = endpoint
        Thread { [weak self, endpoint] in
            defer { endpoint.close() }
            Self.readLoop(endpoint, approve: { self?.approve() ?? false })
        }.start()
    }
    func stop() {
        endpoint.stop()
    }
    deinit { stop() }

    private static func readLoop(_ endpoint: LockedUseBrokerSocket, approve: () -> Bool) {
        let fd = endpoint.descriptor
        while true {
            guard endpoint.isActive else { return }
            let peer = accept(fd, nil, nil)
            guard peer >= 0 else { return }
            var timeout = timeval(tv_sec: 0, tv_usec: 500_000)
            var noSignal: Int32 = 1
            _ = setsockopt(peer, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size))
            _ = setsockopt(peer, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
            let allow = endpoint.isActive && Self.appleAuthorizationHost(peer) && approve()
            let data = Data((allow ? "ALLOW" : "DENY").utf8)
            _ = data.withUnsafeBytes { write(peer, $0.baseAddress, $0.count) }
            close(peer)
        }
    }
    private static func appleAuthorizationHost(_ fd: Int32) -> Bool {
        var audit = audit_token_t(); var length = socklen_t(MemoryLayout<audit_token_t>.size)
        guard getsockopt(fd, SOL_LOCAL, LOCAL_PEERTOKEN, &audit, &length) == 0,
              length == MemoryLayout<audit_token_t>.size else { return false }
        let token = Data(bytes: &audit, count: Int(length))
        let attributes = [kSecGuestAttributeAudit as String: token] as CFDictionary
        var code: SecCode?, requirement: SecRequirement?
        guard SecCodeCopyGuestWithAttributes(nil, attributes, [], &code) == errSecSuccess, let code = code,
              SecRequirementCreateWithString("anchor apple" as CFString, [], &requirement) == errSecSuccess,
              SecCodeCheckValidity(code, [], requirement) == errSecSuccess else { return false }
        var staticCode: SecStaticCode?, information: CFDictionary?
        guard SecCodeCopyStaticCode(code, [], &staticCode) == errSecSuccess, let staticCode = staticCode,
              SecCodeCopySigningInformation(staticCode, [], &information) == errSecSuccess else { return false }
        let id = (information as? [String: Any])?[kSecCodeInfoIdentifier as String] as? String
        return ["com.apple.authorizationhost", "com.apple.SecurityAgent"].contains(id ?? "")
    }
}
