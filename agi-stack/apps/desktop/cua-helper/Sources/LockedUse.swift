import AppKit
import ApplicationServices
import CryptoKit
import Foundation
import Security

/// Runtime implementation kept behind the isolated native acceptance entry point.
/// The ordinary capability remains unverified until that supported configuration
/// has been exercised; no credential is read or synthesized.
final class LockedUseCoordinator {
    static let shared = LockedUseCoordinator()
    private var guardian: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var listener: Int32 = -1
    private var brokerURL: URL?
    private var generation: UUID?
    private let lock = NSLock()
    private var expires = Date.distantPast
    private var attempted = false
    private var activeRun: String?
    private var renewal: DispatchSourceTimer?
    private let channelLock = NSLock()

    static var configurationURL: URL {
        URL(fileURLWithPath: "/Library/Application Support/MemStack/ComputerUse/locked-use.plist")
    }
    func probe() -> [String: Any] {
        let config = NSDictionary(contentsOf: Self.configurationURL) as? [String: Any]
        return ["state": "unverified", "installed": config != nil,
                "accessibility": AXIsProcessTrusted(),
                "supported_os": ProcessInfo.processInfo.operatingSystemVersion.majorVersion >= 14,
                "reason": "isolated native unlock, coverage, physical-input, and crash acceptance is required"]
    }

    func begin(runID: String, guardianURL: URL, socketURL: URL) throws {
        guard !runID.isEmpty, guardian == nil, AXIsProcessTrusted(),
              socketURL.path.utf8.count < 104 else {
            throw ActionError.failure(kind: "locked_use_unavailable", message: "lock continuity preconditions failed")
        }
        let child = Process()
        let incoming = Pipe(); let outgoing = Pipe()
        child.executableURL = guardianURL
        child.standardInput = incoming; child.standardOutput = outgoing; child.standardError = FileHandle.standardError
        try child.run()
        guardian = child; input = incoming.fileHandleForWriting; output = outgoing.fileHandleForReading
        let secret = UUID().uuidString + UUID().uuidString
        let nonce = UUID().uuidString
        let initialized = try request("initialize", ["secret": secret, "nonce": nonce])
        guard initialized["nonce"] as? String == nonce,
              initialized["proof"] as? String == IpcServer.proof(secret: secret, nonce: nonce) else {
            end(); throw ActionError.failure(kind: "authentication_failed", message: "guardian authentication failed")
        }
        let ready = try request("begin_guard", ["ttl_seconds": 10.0, "source_pid": Int64(getpid())])
        guard ready["ready"] as? Bool == true,
              ready["covered_displays"] as? Int == NSScreen.screens.count else {
            end(); throw ActionError.failure(kind: "coverage_failed", message: "guardian did not cover every display")
        }
        activeRun = runID
        listener = socket(AF_UNIX, SOCK_STREAM, 0)
        guard listener >= 0 else { end(); throw ActionError.failure(kind: "native_error", message: "cannot create authorization broker") }
        var address = sockaddr_un(); address.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(socketURL.path.utf8)
        withUnsafeMutableBytes(of: &address.sun_path) { $0.copyBytes(from: bytes) }
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(listener, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard bound == 0, listen(listener, 4) == 0 else {
            end(); throw ActionError.failure(kind: "native_error", message: "cannot bind authorization broker")
        }
        chmod(socketURL.path, 0o600)
        brokerURL = socketURL
        let identifier = UUID()
        lock.lock(); generation = identifier; lock.unlock()
        let fd = listener
        Thread { [weak self] in self?.acceptLoop(fd, generation: identifier) }.start()
        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue(label: "memstack.cua.guardian.renew"))
        timer.schedule(deadline: .now() + 2, repeating: 2)
        timer.setEventHandler { [weak self] in
            guard let self = self else { return }
            do { _ = try self.request("renew_guard", [:]) } catch { self.end() }
        }
        timer.resume(); renewal = timer
    }

    /// Opens exactly one short authorization attempt and submits loginwindow AX.
    /// A non-secret sentinel forces an authorization evaluation; the custom
    /// mechanism must independently allow the current run.
    func unlock(runID: String) throws {
        guard activeRun == runID else {
            throw ActionError.failure(kind: "permission_required", message: "the guarded run does not match")
        }
        lock.lock(); attempted = false; expires = Date().addingTimeInterval(5); lock.unlock()
        defer { lock.lock(); expires = .distantPast; lock.unlock() }
        guard let app = NSWorkspace.shared.runningApplications.first(where: { $0.bundleIdentifier == "com.apple.loginwindow" }) else {
            throw ActionError.failure(kind: "locked_use_unavailable", message: "loginwindow is unavailable")
        }
        let root = AXUIElementCreateApplication(app.processIdentifier)
        let elements = walk(root, depth: 0)
        guard let field = elements.first(where: {
            AxEngine.copyString($0, kAXIdentifierAttribute as String) == "UserPasswordTextField"
        }) else {
            throw ActionError.failure(kind: "locked_use_unavailable", message: "the supported loginwindow password field is absent")
        }
        var settable = DarwinBoolean(false)
        guard AXUIElementIsAttributeSettable(field, kAXValueAttribute as CFString, &settable) == .success,
              settable.boolValue,
              AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString,
                                           UUID().uuidString as CFString) == .success else {
            throw ActionError.failure(kind: "locked_use_unavailable", message: "loginwindow rejected the authorization sentinel")
        }
        _ = AXUIElementSetAttributeValue(field, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        guard let down = CGEvent(keyboardEventSource: SyntheticInput.shared.source, virtualKey: 0x24, keyDown: true),
              let up = CGEvent(keyboardEventSource: SyntheticInput.shared.source, virtualKey: 0x24, keyDown: false) else {
            throw ActionError.failure(kind: "input_error", message: "cannot create authorization submit input")
        }
        try SyntheticInput.shared.post(down)
        defer { SyntheticInput.shared.release(up) }
        try SyntheticInput.shared.post(up)
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            if (CGSessionCopyCurrentDictionary() as? [String: Any])?["CGSSessionScreenIsLocked"] as? Bool == false { return }
            Thread.sleep(forTimeInterval: 0.05)
        }
        throw ActionError.failure(kind: "locked_use_unavailable", message: "native unlock verification timed out")
    }
    func end() {
        renewal?.cancel(); renewal = nil
        lock.lock(); expires = .distantPast; activeRun = nil; generation = nil; lock.unlock()
        if listener >= 0 { shutdown(listener, SHUT_RDWR); close(listener); listener = -1 }
        if let brokerURL = brokerURL { unlink(brokerURL.path) }
        brokerURL = nil
        // EOF forces guardian relock. Do not kill a guardian before native lock is confirmed.
        try? input?.close()
        input = nil; output = nil; guardian = nil
    }
    private func walk(_ element: AXUIElement, depth: Int) -> [AXUIElement] {
        guard depth < 12 else { return [] }
        var result = [element]
        for child in (AxEngine.copyArray(element, kAXChildrenAttribute as String) ?? []).prefix(100) {
            result += walk(child, depth: depth + 1)
            if result.count > 1000 { break }
        }
        return result
    }
    private func acceptLoop(_ fd: Int32, generation identifier: UUID) {
        while true {
            lock.lock(); let alive = generation == identifier; lock.unlock()
            if !alive { return }
            let peer = accept(fd, nil, nil)
            if peer < 0 { return }
            let approvedPeer = appleAuthorizationHost(peer)
            lock.lock()
            let allow = approvedPeer && !attempted && Date() < expires && activeRun != nil
            if allow { attempted = true }
            lock.unlock()
            let data = Data((allow ? "ALLOW" : "DENY").utf8)
            _ = data.withUnsafeBytes { write(peer, $0.baseAddress, $0.count) }
            close(peer)
        }
    }
    private func appleAuthorizationHost(_ fd: Int32) -> Bool {
        var audit = audit_token_t(); var length = socklen_t(MemoryLayout<audit_token_t>.size)
        guard getsockopt(fd, SOL_LOCAL, LOCAL_PEERTOKEN, &audit, &length) == 0 else { return false }
        let token = Data(bytes: &audit, count: Int(length))
        let attrs = [kSecGuestAttributeAudit as String: token] as CFDictionary
        var code: SecCode?; var requirement: SecRequirement?
        guard SecCodeCopyGuestWithAttributes(nil, attrs, [], &code) == errSecSuccess,
              let code = code,
              SecRequirementCreateWithString("anchor apple" as CFString, [], &requirement) == errSecSuccess,
              SecCodeCheckValidity(code, [], requirement) == errSecSuccess else { return false }
        var staticCode: SecStaticCode?
        guard SecCodeCopyStaticCode(code, [], &staticCode) == errSecSuccess,
              let staticCode = staticCode else { return false }
        var info: CFDictionary?
        guard SecCodeCopySigningInformation(staticCode, [], &info) == errSecSuccess else { return false }
        let id = (info as? [String: Any])?[kSecCodeInfoIdentifier as String] as? String
        return ["com.apple.authorizationhost", "com.apple.SecurityAgent"].contains(id ?? "")
    }
    private func request(_ method: String, _ params: [String: Any]) throws -> [String: Any] {
        channelLock.lock(); defer { channelLock.unlock() }
        guard let input = input, let output = output else { throw IpcError.protocolError("guardian closed") }
        let data = encodeJson(["jsonrpc": "2.0", "id": 1, "method": method, "params": params])
        try input.write(contentsOf: encodeFrame(data))
        guard let header = try output.read(upToCount: 4), header.count == 4 else { throw IpcError.protocolError("guardian closed") }
        let size = header.withUnsafeBytes { UInt32(littleEndian: $0.loadUnaligned(as: UInt32.self)) }
        guard size <= 4096, let data = try output.read(upToCount: Int(size)), data.count == size,
              let value = (try JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let result = value["result"] as? [String: Any] else { throw IpcError.protocolError("guardian response invalid") }
        if result["error"] != nil { throw IpcError.protocolError("guardian rejected the lease") }
        return result
    }
}
