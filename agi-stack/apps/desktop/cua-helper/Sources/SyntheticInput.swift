import CoreGraphics
import Foundation

/// Acknowledgement precedes every key/button down, including short clicks and
/// Unicode insertion. Neither a finally block nor a signal handler can handle
/// SIGKILL; the independently signed helper process owns that recovery path.
final class SyntheticInput {
    static let shared = SyntheticInput()
    private let eventTag = Int64.random(in: 1...Int64.max)
    lazy var source = OwnedEventSource.make(tag: eventTag)
    private var external: ExternalInputState?
    private let lock = NSLock()
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var timer: DispatchSourceTimer?
    private var claim = InputClaim()
    private var sequence: UInt64 = 0
    private var failed = false
    private var leaseDescriptor: Int32 = -1

    /// Clipboard rollback may fall back to the surviving worker only once the
    /// writer has exited; two live processes must never race to restore it.
    var watchdogStopped: Bool {
        lock.lock(); let child = process; lock.unlock()
        guard let child = child else { return false }
        let deadline = ProcessInfo.processInfo.systemUptime + 0.25
        while child.isRunning && ProcessInfo.processInfo.systemUptime < deadline {
            Thread.sleep(forTimeInterval: 0.01)
        }
        return !child.isRunning
    }

    func beginInputLease(_ sessionID: String) throws {
        lock.lock(); defer { lock.unlock() }
        guard !failed else { throw unavailable() }
        if let owner = claim.inputSessionID, owner != sessionID {
            throw ActionError.failure(kind: "device_busy", message: "another session owns desktop input")
        }
        if claim.inputSessionID == sessionID {
            guard process?.isRunning == true else { fail(); throw unavailable() }
            return
        }
        var next = claim; next.inputSessionID = sessionID
        _ = try sync(next)
    }
    func endInputLease(_ sessionID: String) {
        lock.lock(); defer { lock.unlock() }
        guard claim.inputSessionID == sessionID else { return }
        var next = claim; next.inputSessionID = nil
        do { _ = try sync(next) } catch { fail() }
    }
    func clipboard(_ command: ClipboardCommand) throws -> ClipboardReceipt {
        lock.lock(); defer { lock.unlock() }
        if let owner = claim.inputSessionID, owner != command.sessionID {
            throw ActionError.failure(kind: "device_busy", message: "another session owns desktop input")
        }
        var next = claim; next.inputSessionID = command.sessionID
        let reply = try sync(next, clipboard: command)
        guard let receipt = reply.clipboard else { throw ClipboardFiles.failure("clipboard_unavailable") }
        return receipt
    }

    func registerDirectory(_ directory: URL) {
        lock.lock(); defer { lock.unlock() }
        var next = claim
        next.artifactDirectories.append(directory.path)
        do { try sync(next) } catch { fail() }
    }
    func forgetDirectory(_ directory: URL) {
        lock.lock(); defer { lock.unlock() }
        var next = claim
        next.artifactDirectories.removeAll { $0 == directory.path }
        do { try sync(next) } catch { fail() }
    }

    private func unavailable() -> ActionError {
        .failure(kind: "input_watchdog_unavailable", message: "safe synthetic input recovery is unavailable")
    }
    private func connect() throws {
        guard !failed, source != nil else { throw unavailable() }
        if process != nil { return }
        guard let executable = Bundle.main.executableURL else { throw unavailable() }
        if external == nil { external = try ExternalInputState(tag: eventTag) }
        let child = Process()
        let writer = Pipe(), reader = Pipe()
        child.executableURL = executable
        child.arguments = ["--input-watchdog"]
        child.standardInput = writer
        child.standardOutput = reader
        if leaseDescriptor < 0 { leaseDescriptor = try DesktopInputLease.openDescriptor() }
        // Foundation dup2 passes the same open-file description to the child.
        // The private descriptor is a lock, never a shared RPC socket.
        child.standardError = FileHandle(fileDescriptor: leaseDescriptor, closeOnDealloc: false)
        do { try child.run() } catch { failed = true; throw unavailable() }
        input = writer.fileHandleForWriting
        output = reader.fileHandleForReading
        process = child
        let secret = UUID().uuidString + UUID().uuidString
        let nonce = UUID().uuidString
        do {
            try InputWatchdogWire.send(InputWatchdogMessage(id: 0, parent: getpid(),
                nonce: nonce, secret: secret, claim: nil, eventTag: eventTag), fd: input!.fileDescriptor)
            let reply = try InputWatchdogWire.receive(InputWatchdogReply.self, fd: output!.fileDescriptor, timeout: 2)
            guard reply.id == 0, reply.accepted,
                  reply.proof == IpcServer.proof(secret: secret, nonce: nonce) else { throw unavailable() }
        } catch { fail(); throw unavailable() }
        let heartbeat = DispatchSource.makeTimerSource(queue: DispatchQueue(label: "memstack.cua.input-lease"))
        heartbeat.schedule(deadline: .now() + 1, repeating: 1)
        heartbeat.setEventHandler { [weak self] in self?.refresh() }
        heartbeat.resume()
        timer = heartbeat
    }
    @discardableResult
    private func sync(_ next: InputClaim, clipboard: ClipboardCommand? = nil,
                      releasedKeys: [UInt16] = [], releasedButtons: [UInt32] = []) throws -> InputWatchdogReply {
        try connect()
        guard let input = input, let output = output, process?.isRunning == true else {
            fail(); throw unavailable()
        }
        sequence &+= 1
        do {
            try InputWatchdogWire.send(InputWatchdogMessage(id: sequence, parent: nil,
                nonce: nil, secret: nil, claim: next, clipboard: clipboard,
                releasedKeys: releasedKeys, releasedButtons: releasedButtons), fd: input.fileDescriptor)
            let reply = try InputWatchdogWire.receive(InputWatchdogReply.self, fd: output.fileDescriptor, timeout: 0.5)
            guard reply.id == sequence, reply.proof == nil else { throw IpcError.protocolError("watchdog reply mismatch") }
            guard reply.accepted else {
                throw ActionError.failure(kind: reply.error ?? "input_busy", message: "desktop input or the requested resource is owned elsewhere")
            }
            claim = next
            if let error = reply.error { throw ClipboardFiles.failure(error) }
            return reply
        } catch let error as ActionError { throw error }
        catch { fail(); throw unavailable() }
    }
    private func refresh() {
        lock.lock(); defer { lock.unlock() }
        guard process != nil, !failed else { return }
        do { try sync(claim) } catch { fail() }
    }
    private func fail() {
        failed = true
        timer?.cancel(); timer = nil
        try? input?.close(); input = nil
        try? output?.close(); output = nil
        // Closing the inherited input invokes child recovery. If the child
        // itself failed, release our mirror without touching hardware holds.
        if let external = external {
            for code in claim.keys.keys {
                _ = InputRelease.key(code, flags: external.flags, source: source, external: external)
            }
            for (button, point) in claim.buttons {
                _ = InputRelease.button(button, point: point, flags: external.flags, source: source, external: external)
            }
        }
        // Keep the inherited lock descriptor open while input ownership is
        // unresolved. The surviving child releases it after recovery; if that
        // child died, the worker retains exclusivity until it terminates.
    }
    func post(_ event: CGEvent, keyDown: Bool? = nil, ownedFlags explicit: CGEventFlags? = nil) throws {
        lock.lock(); defer { lock.unlock() }
        event.setIntegerValueField(.eventSourceUserData, value: eventTag)
        let operation: CGEventType
        if event.type == .flagsChanged {
            guard let down = keyDown else {
                throw ActionError.failure(kind: "input_error", message: "modifier input requires an explicit down/up phase")
            }
            operation = down ? .keyDown : .keyUp
        } else { operation = event.type }
        var next = claim
        switch operation {
        case .keyDown:
            let code = UInt16(event.getIntegerValueField(.keyboardEventKeycode))
            guard next.keys[code] == nil else { throw ActionError.failure(kind: "input_busy", message: "this key is already held") }
            let inherited = external.map { InputRelease.flags(claim, external: $0) } ?? []
            next.keys[code] = Self.ownedFlags(code: code, flags: event.flags,
                inherited: inherited, explicit: explicit).rawValue
            try sync(next)
            if event.type == .flagsChanged, let external = external { event.flags = InputRelease.flags(next, external: external) }
            event.post(tap: .cghidEventTap)
        case .leftMouseDown, .rightMouseDown, .otherMouseDown:
            let button = UInt32(event.getIntegerValueField(.mouseEventButtonNumber))
            guard next.buttons[button] == nil else { throw ActionError.failure(kind: "input_busy", message: "this button is already held") }
            next.buttons[button] = InputPoint(x: event.location.x, y: event.location.y)
            try sync(next)
            event.post(tap: .cghidEventTap)
        case .keyUp:
            let code = UInt16(event.getIntegerValueField(.keyboardEventKeycode))
            guard next.keys.removeValue(forKey: code) != nil else { return }
            // A physical takeover of the same key is left down. The watchdog
            // defers its owned release until hardware sends the matching up.
            var released = false
            if let external = external, !external.key(code) {
                event.flags = InputRelease.flags(next, external: external)
                event.post(tap: .cghidEventTap)
                released = true
            }
            do { try sync(next, releasedKeys: released ? [code] : []) } catch { fail(); throw error }
        case .leftMouseUp, .rightMouseUp, .otherMouseUp:
            let button = UInt32(event.getIntegerValueField(.mouseEventButtonNumber))
            guard next.buttons.removeValue(forKey: button) != nil else { return }
            var released = false
            if let external = external, !external.button(button) {
                event.flags = InputRelease.flags(next, external: external)
                event.post(tap: .cghidEventTap)
                released = true
            }
            do { try sync(next, releasedButtons: released ? [button] : []) } catch { fail(); throw error }
        case .leftMouseDragged, .rightMouseDragged, .otherMouseDragged:
            let button = UInt32(event.getIntegerValueField(.mouseEventButtonNumber))
            guard next.buttons[button] != nil else { throw ActionError.failure(kind: "input_error", message: "drag has no owned button") }
            next.buttons[button] = InputPoint(x: event.location.x, y: event.location.y)
            try sync(next)
            event.post(tap: .cghidEventTap)
        default:
            guard !failed else { throw unavailable() }
            event.post(tap: .cghidEventTap)
        }
    }
    func release(_ event: CGEvent?) {
        guard let event = event else { return }
        try? post(event, keyDown: false)
    }
    static func ownedFlags(code: UInt16, flags: CGEventFlags, inherited: CGEventFlags,
                           explicit: CGEventFlags? = nil) -> CGEventFlags {
        if let explicit = explicit { return explicit }
        // These are protocol key codes, not semantic key-name classification.
        // A second modifier's event contains the first modifier's flags; only
        // its own bit may survive releasing the first modifier.
        switch code {
        case 54, 55: return .maskCommand
        case 56, 60: return .maskShift
        case 58, 61: return .maskAlternate
        case 59, 62: return .maskControl
        default: return flags.subtracting(inherited)
        }
    }
}
