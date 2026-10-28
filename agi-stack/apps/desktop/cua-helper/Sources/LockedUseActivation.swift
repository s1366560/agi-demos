import Darwin
import Foundation
import Security

enum LockedUseActivationError: Error { case unavailable, expired, invalidPeer, invalidRequest }

struct LockedUseActivationRequest: Codable, Equatable {
    let requestID: String
    let generation: String
    let arguments: [String]
    let ownerUID: UInt32

    var payload: [String: Any] {
        ["request_id": requestID, "generation": generation, "arguments": arguments, "owner_uid": ownerUID]
    }
    func matches(_ value: [String: Any]) -> Bool {
        value["request_id"] as? String == requestID && value["generation"] as? String == generation
            && value["arguments"] as? [String] == arguments
            && (value["owner_uid"] as? NSNumber)?.uint32Value == ownerUID
    }

    static func parseCommand(_ values: [String]) throws -> (LockedUseActivationRequest, URL) {
        guard let delimiter = values.firstIndex(of: "--activation"), values.count == delimiter + 5,
              delimiter >= 2, let owner = UInt32(values[delimiter + 4]), owner > 0,
              UUID(uuidString: values[delimiter + 2]) != nil,
              !values[delimiter + 3].isEmpty, values[delimiter + 3].utf8.count <= 128,
              values[delimiter + 1].hasPrefix("/") else { throw LockedUseActivationError.invalidRequest }
        let arguments = Array(values.prefix(delimiter))
        guard (arguments[1] == "install" && arguments.count == 6 && UInt32(arguments[5]) == owner)
            || (arguments[1] == "uninstall" && arguments.count == 2) else {
            throw LockedUseActivationError.invalidRequest
        }
        return (LockedUseActivationRequest(requestID: values[delimiter + 2], generation: values[delimiter + 3],
            arguments: arguments, ownerUID: owner), URL(fileURLWithPath: values[delimiter + 1]))
    }
}

enum LockedUseActivationSocket {
    static func address(_ url: URL) throws -> sockaddr_un {
        guard url.path.utf8.count < 104 else { throw LockedUseActivationError.invalidRequest }
        var address = sockaddr_un(); address.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(url.path.utf8)
        withUnsafeMutableBytes(of: &address.sun_path) { $0.copyBytes(from: bytes) }
        return address
    }
    static func configure(_ fd: Int32) {
        var noSignal: Int32 = 1
        _ = setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size))
        _ = fcntl(fd, F_SETFD, FD_CLOEXEC)
    }
    static func signedPeer(_ fd: Int32, uid: UInt32, identifier: String, team: String) -> Bool {
        var peerUID: uid_t = 0, peerGID: gid_t = 0
        guard getpeereid(fd, &peerUID, &peerGID) == 0, peerUID == uid else { return false }
        var audit = audit_token_t(), length = socklen_t(MemoryLayout<audit_token_t>.size)
        guard getsockopt(fd, SOL_LOCAL, LOCAL_PEERTOKEN, &audit, &length) == 0,
              length == MemoryLayout<audit_token_t>.size else { return false }
        let attributes = [kSecGuestAttributeAudit as String: Data(bytes: &audit, count: Int(length))] as CFDictionary
        let text = "identifier \"\(identifier)\" and anchor apple generic and certificate leaf[subject.OU] = \"\(team)\""
        var code: SecCode?, requirement: SecRequirement?
        guard SecRequirementCreateWithString(text as CFString, [], &requirement) == errSecSuccess,
              SecCodeCopyGuestWithAttributes(nil, attributes, [], &code) == errSecSuccess,
              let code = code, SecCodeCheckValidity(code, [], requirement) == errSecSuccess else { return false }
        return true
    }
}

/// The privileged installer must keep a live, authenticated connection to the
/// exact helper request. A cancelled request cannot be replayed by a late dialog.
final class LockedUseActivationClient {
    private var descriptor: Int32 = -1
    private let request: LockedUseActivationRequest
    private var sequence = 0

    init(socketURL: URL, request: LockedUseActivationRequest,
         verifyPeer: (Int32) -> Bool) throws {
        self.request = request
        var directory = stat(), socketInfo = stat()
        guard lstat(socketURL.deletingLastPathComponent().path, &directory) == 0,
              directory.st_mode & S_IFMT == S_IFDIR, directory.st_uid == request.ownerUID,
              directory.st_mode & 0o777 == 0o700,
              lstat(socketURL.path, &socketInfo) == 0, socketInfo.st_mode & S_IFMT == S_IFSOCK,
              socketInfo.st_uid == request.ownerUID, socketInfo.st_mode & 0o777 == 0o600 else {
            throw LockedUseActivationError.unavailable
        }
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw LockedUseActivationError.unavailable }
        var adopted = false
        defer { if !adopted { close(fd) } }
        LockedUseActivationSocket.configure(fd)
        _ = fcntl(fd, F_SETFL, O_NONBLOCK)
        var address = try LockedUseActivationSocket.address(socketURL)
        let status = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        if status != 0 {
            guard errno == EINPROGRESS else { throw LockedUseActivationError.unavailable }
            var ready = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
            var failure: Int32 = 0, length = socklen_t(MemoryLayout<Int32>.size)
            guard poll(&ready, 1, 1000) > 0,
                  getsockopt(fd, SOL_SOCKET, SO_ERROR, &failure, &length) == 0, failure == 0 else {
                throw LockedUseActivationError.unavailable
            }
        }
        guard verifyPeer(fd) else { throw LockedUseActivationError.invalidPeer }
        descriptor = fd
        do { try exchange("claim") }
        catch { descriptor = -1; throw error }
        adopted = true
    }
    deinit { if descriptor >= 0 { close(descriptor) } }

    func check() throws { try exchange("check") }

    private func exchange(_ operation: String) throws {
        guard descriptor >= 0 else { throw LockedUseActivationError.unavailable }
        var payload = request.payload
        payload["operation"] = operation; payload["sequence"] = sequence
        do {
            try LockedUseWire.write(payload, fd: descriptor)
            let response = try LockedUseWire.read(descriptor, timeout: 1)
            guard response["ok"] as? Bool == true,
                  response["request_id"] as? String == request.requestID,
                  response["generation"] as? String == request.generation,
                  response["sequence"] as? Int == sequence else { throw LockedUseActivationError.expired }
            sequence += 1
        } catch { throw LockedUseActivationError.expired }
    }
}
