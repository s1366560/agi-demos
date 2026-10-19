import CoreGraphics
import Foundation
import Security

/// This child uses only an inherited pipe. It survives a killed native worker
/// long enough to release that worker's acknowledged synthetic input claims.
struct InputClaim: Codable, Equatable {
    var keys: [UInt16: UInt64] = [:]
    var buttons: [UInt32: InputPoint] = [:]
    var artifactDirectories: [String] = []
    var inputSessionID: String? = nil
}
struct InputPoint: Codable, Equatable {
    let x: Double
    let y: Double
}
struct InputWatchdogMessage: Codable {
    let id: UInt64
    let parent: Int32?
    let nonce: String?
    let secret: String?
    let claim: InputClaim?
    var clipboard: ClipboardCommand? = nil
    var releasedKeys: [UInt16] = []
    var releasedButtons: [UInt32] = []
    var eventTag: Int64? = nil
}
struct InputWatchdogReply: Codable {
    let id: UInt64
    let proof: String?
    let accepted: Bool
    var clipboard: ClipboardReceipt? = nil
    var error: String? = nil
}

enum InputWatchdogWire {
    static let maximum = 16_384
    static func send<T: Encodable>(_ value: T, fd: Int32) throws {
        let data = try JSONEncoder().encode(value)
        guard data.count <= maximum else { throw IpcError.protocolError("watchdog frame exceeds budget") }
        let flags = fcntl(fd, F_GETFL)
        guard flags >= 0, fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0 else {
            throw IpcError.protocolError("cannot bound watchdog writes")
        }
        let deadline = ProcessInfo.processInfo.systemUptime + 0.5
        let frame = encodeFrame(data)
        try frame.withUnsafeBytes { bytes in
            var offset = 0
            while offset < bytes.count {
                let remaining = deadline - ProcessInfo.processInfo.systemUptime
                guard remaining > 0 else { throw IpcError.protocolError("watchdog write timed out") }
                var descriptor = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
                let ready = poll(&descriptor, 1, Int32(min(remaining * 1000, 100)))
                if ready < 0 && errno == EINTR { continue }
                guard ready >= 0 else { throw IpcError.protocolError("watchdog write poll failed") }
                if ready == 0 { continue }
                let count = write(fd, bytes.baseAddress!.advanced(by: offset), bytes.count - offset)
                if count < 0 && [EINTR, EAGAIN].contains(errno) { continue }
                guard count > 0 else { throw IpcError.protocolError("watchdog pipe closed") }
                offset += count
            }
        }
    }
    static func receive<T: Decodable>(_ type: T.Type, fd: Int32, timeout: Double) throws -> T {
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        func readBytes(_ count: Int) throws -> Data {
            var output = Data()
            while output.count < count {
                let remaining = deadline - ProcessInfo.processInfo.systemUptime
                guard remaining > 0 else { throw IpcError.protocolError("watchdog response timed out") }
                var descriptor = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
                let ready = poll(&descriptor, 1, Int32(min(remaining * 1000, 500)))
                if ready < 0 && errno == EINTR { continue }
                guard ready >= 0 else { throw IpcError.protocolError("watchdog poll failed") }
                if ready == 0 { continue }
                var buffer = [UInt8](repeating: 0, count: count - output.count)
                let received = read(fd, &buffer, buffer.count)
                if received < 0 && errno == EINTR { continue }
                guard received > 0 else { throw IpcError.protocolError("watchdog pipe closed") }
                output.append(contentsOf: buffer.prefix(received))
            }
            return output
        }
        let header = try readBytes(4)
        let size = header.withUnsafeBytes { UInt32(littleEndian: $0.loadUnaligned(as: UInt32.self)) }
        guard size > 0, size <= maximum else { throw IpcError.protocolError("invalid watchdog frame") }
        return try JSONDecoder().decode(type, from: readBytes(Int(size)))
    }
}

enum InputRelease {
    static func flags(_ claim: InputClaim, external: ExternalInputState) -> CGEventFlags {
        claim.keys.reduce(external.flags) {
            $0.union(CGEventFlags(rawValue: $1.value)).union(OwnedEventSource.modifierFlags($1.key))
        }
    }
    static func key(_ code: UInt16, flags: CGEventFlags, source: CGEventSource?, external: ExternalInputState) -> Bool {
        guard !external.key(code) else { return false }
        let event = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false)
        event?.flags = flags
        event?.post(tap: .cghidEventTap)
        return event != nil
    }
    static func button(_ raw: UInt32, point: InputPoint, flags: CGEventFlags, source: CGEventSource?, external: ExternalInputState) -> Bool {
        guard let button = CGMouseButton(rawValue: raw),
              !external.button(raw) else { return false }
        let type: CGEventType = button == .left ? .leftMouseUp : button == .right ? .rightMouseUp : .otherMouseUp
        // Releasing a crashed drag must not warp a pointer the person moved.
        let currentPoint = CGEvent(source: nil)?.location ?? CGPoint(x: point.x, y: point.y)
        let event = CGEvent(mouseEventSource: source, mouseType: type,
            mouseCursorPosition: currentPoint, mouseButton: button)
        event?.flags = flags
        event?.post(tap: .cghidEventTap)
        return event != nil
    }
}

enum InputWatchdogWorker {
    private static func terminateOwner(_ parent: Int32) {
        guard getppid() == parent else { return }
        _ = kill(parent, SIGTERM)
        let deadline = ProcessInfo.processInfo.systemUptime + 0.25
        while getppid() == parent && ProcessInfo.processInfo.systemUptime < deadline {
            Thread.sleep(forTimeInterval: 0.01)
        }
        if getppid() == parent { _ = kill(parent, SIGKILL) }
        // An acknowledged down could have been paused just before posting.
        // Stop its owner before the final release, including an unresponsive
        // event/recording thread. Child-parent identity prevents PID reuse.
        while getppid() == parent { Thread.sleep(forTimeInterval: 0.01) }
    }
    private static func signedParent(_ pid: Int32) -> Bool {
        var own: SecCode?, peer: SecCode?, requirement: SecRequirement?
        var ownStatic: SecStaticCode?
        let attributes = [kSecGuestAttributePid as String: NSNumber(value: pid)] as CFDictionary
        guard SecCodeCopySelf([], &own) == errSecSuccess, let own = own,
              SecCodeCopyStaticCode(own, [], &ownStatic) == errSecSuccess, let ownStatic = ownStatic,
              SecCodeCopyDesignatedRequirement(ownStatic, [], &requirement) == errSecSuccess,
              let requirement = requirement,
              SecCodeCopyGuestWithAttributes(nil, attributes, [], &peer) == errSecSuccess,
              let peer = peer else { return false }
        guard SecCodeCheckValidity(peer, [], requirement) == errSecSuccess else { return false }
        var peerStatic: SecStaticCode?, ownInfo: CFDictionary?, peerInfo: CFDictionary?
        guard SecCodeCopyStaticCode(peer, [], &peerStatic) == errSecSuccess, let peerStatic = peerStatic,
              SecCodeCopySigningInformation(ownStatic, [], &ownInfo) == errSecSuccess,
              SecCodeCopySigningInformation(peerStatic, [], &peerInfo) == errSecSuccess,
              let ownHash = (ownInfo as? [String: Any])?[kSecCodeInfoUnique as String] as? Data,
              let peerHash = (peerInfo as? [String: Any])?[kSecCodeInfoUnique as String] as? Data else { return false }
        return ownHash == peerHash
    }
    private static func ownedDirectory(_ value: String) -> URL? {
        let url = URL(fileURLWithPath: value).standardizedFileURL
        let prefix = "memstack-cua-"
        guard url.lastPathComponent.hasPrefix(prefix),
              UUID(uuidString: String(url.lastPathComponent.dropFirst(prefix.count))) != nil,
              url.deletingLastPathComponent().resolvingSymlinksInPath()
                == FileManager.default.temporaryDirectory.resolvingSymlinksInPath(),
              let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
              attributes[.type] as? FileAttributeType == .typeDirectory,
              (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
              (attributes[.posixPermissions] as? NSNumber)?.intValue == 0o700 else { return nil }
        return url
    }
    static func run() -> Never {
        signal(SIGPIPE, SIG_IGN)
        guard (try? DesktopInputLease.verify(STDERR_FILENO)) != nil else { exit(1) }
        let source: CGEventSource
        let external: ExternalInputState
        let parent = getppid()
        do {
            let hello = try InputWatchdogWire.receive(InputWatchdogMessage.self, fd: STDIN_FILENO, timeout: 3)
            guard hello.id == 0, hello.parent == parent, signedParent(parent),
                  let secret = hello.secret, secret.utf8.count >= 32,
                  let eventTag = hello.eventTag, eventTag > 0,
                  let nonce = hello.nonce, nonce.utf8.count >= 16, hello.claim == nil, hello.clipboard == nil else { exit(1) }
            guard let createdSource = OwnedEventSource.make(tag: eventTag) else { exit(1) }
            source = createdSource
            external = try ExternalInputState(tag: eventTag)
            try InputWatchdogWire.send(InputWatchdogReply(id: 0,
                proof: IpcServer.proof(secret: secret, nonce: nonce), accepted: true), fd: STDOUT_FILENO)
        } catch { exit(1) }
        var active = InputClaim()
        var deferred = InputClaim()
        var sequence: UInt64 = 0
        var lease = ProcessInfo.processInfo.systemUptime + 10
        var connected = true
        let clipboard = ClipboardRecovery()
        var leaseHeld = false
        func releaseDeferred() {
            let flags = InputRelease.flags(active, external: external)
            for code in Array(deferred.keys.keys) where InputRelease.key(code, flags: flags, source: source, external: external) {
                deferred.keys[code] = nil
            }
            for (button, point) in deferred.buttons where InputRelease.button(button, point: point, flags: flags, source: source, external: external) {
                deferred.buttons[button] = nil
            }
            if leaseHeld && active.inputSessionID == nil && deferred.keys.isEmpty && deferred.buttons.isEmpty && !clipboard.hasOwnedWrites {
                DesktopInputLease.release(STDERR_FILENO); leaseHeld = false
            }
        }
        while connected || !deferred.keys.isEmpty || !deferred.buttons.isEmpty {
            releaseDeferred()
            if !connected { Thread.sleep(forTimeInterval: 0.02); continue }
            var descriptor = pollfd(fd: STDIN_FILENO, events: Int16(POLLIN), revents: 0)
            let ready = poll(&descriptor, 1, 100)
            if ready < 0 && errno == EINTR { continue }
            if ready == 0 && ProcessInfo.processInfo.systemUptime < lease { continue }
            do {
                guard ready > 0 else { throw IpcError.protocolError("input lease expired") }
                let message = try InputWatchdogWire.receive(InputWatchdogMessage.self, fd: STDIN_FILENO, timeout: 0.5)
                guard message.id == sequence + 1, let claim = message.claim,
                      message.secret == nil, message.nonce == nil, message.parent == nil, message.eventTag == nil,
                      claim.keys.count <= 128, claim.buttons.count <= 3,
                      claim.artifactDirectories.count <= 64,
                      claim.inputSessionID == nil || (claim.inputSessionID!.utf8.count > 0 && claim.inputSessionID!.utf8.count <= 256),
                      (claim.keys.isEmpty && claim.buttons.isEmpty) || claim.inputSessionID != nil,
                      claim.artifactDirectories.allSatisfy({ ownedDirectory($0) != nil }),
                      claim.keys.keys.allSatisfy({ $0 <= 127 }),
                      claim.buttons.allSatisfy({ $0.key <= 2 && $0.value.x.isFinite && $0.value.y.isFinite }) else {
                    throw IpcError.protocolError("invalid input claim")
                }
                guard message.releasedKeys.count <= 128, message.releasedButtons.count <= 3,
                      message.releasedKeys.allSatisfy({ active.keys[$0] != nil && claim.keys[$0] == nil }),
                      message.releasedButtons.allSatisfy({ active.buttons[$0] != nil && claim.buttons[$0] == nil }) else {
                    throw IpcError.protocolError("invalid input release receipt")
                }
                let newKeys = Set(claim.keys.keys).subtracting(active.keys.keys)
                let newButtons = Set(claim.buttons.keys).subtracting(active.buttons.keys)
                let compatibleSession = active.inputSessionID == nil || claim.inputSessionID == nil || active.inputSessionID == claim.inputSessionID
                let requestedLease = claim.inputSessionID != nil
                let acquired = !requestedLease || leaseHeld || DesktopInputLease.acquire(STDERR_FILENO)
                if requestedLease && acquired { leaseHeld = true }
                let available = compatibleSession && acquired && newKeys.allSatisfy {
                    deferred.keys[$0] == nil && !external.key($0)
                } && newButtons.allSatisfy {
                    guard let button = CGMouseButton(rawValue: $0) else { return false }
                    return deferred.buttons[$0] == nil && !external.button(button.rawValue)
                }
                sequence = message.id
                var clipboardReceipt: ClipboardReceipt?
                var operationError: String?
                if available {
                    for (code, flags) in active.keys where claim.keys[code] == nil && !message.releasedKeys.contains(code) { deferred.keys[code] = flags }
                    for (button, point) in active.buttons where claim.buttons[button] == nil && !message.releasedButtons.contains(button) { deferred.buttons[button] = point }
                    active = claim
                    if let command = message.clipboard {
                        do {
                            guard active.inputSessionID == command.sessionID else { throw ClipboardFiles.failure("clipboard_unavailable") }
                            clipboardReceipt = try clipboard.perform(command, directories: active.artifactDirectories)
                        } catch let ActionError.failure(kind, _, _) { operationError = kind }
                        catch { operationError = "clipboard_unavailable" }
                    }
                    releaseDeferred()
                }
                lease = ProcessInfo.processInfo.systemUptime + 10
                try InputWatchdogWire.send(InputWatchdogReply(id: message.id, proof: nil,
                    accepted: available, clipboard: clipboardReceipt,
                    error: operationError ?? (!acquired || !compatibleSession ? "device_busy" : nil)), fd: STDOUT_FILENO)
            } catch {
                let directories = active.artifactDirectories
                deferred.keys.merge(active.keys) { current, _ in current }
                deferred.buttons.merge(active.buttons) { current, _ in current }
                active = InputClaim()
                connected = false
                terminateOwner(parent)
                clipboard.recover()
                releaseDeferred()
                for path in directories {
                    if let owned = ownedDirectory(path) { try? FileManager.default.removeItem(at: owned) }
                }
            }
        }
        if leaseHeld { DesktopInputLease.release(STDERR_FILENO) }
        exit(0)
    }
}
