import AppKit
import ApplicationServices
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
    private weak var session: NativeSession?
    private var activationPoint: CGPoint?
    private var activatedRoute: InputRoute?
    private var focusGuard: BackgroundFocusGuard?

    func bind(_ session: NativeSession, app: ResolvedApp, window: NativeWindow) throws {
        let route = try InputRoute(session: session, app: app, window: window)
        let point = SyntheticFocus.activationPoint(window.element)
        lock.lock(); defer { lock.unlock() }
        try session.cancellation.check()
        if let owner = claim.inputSessionID, owner != session.id {
            throw ActionError.failure(kind: "device_busy", message: "another session owns desktop input")
        }
        if claim.route != route || claim.inputSessionID != session.id {
            guard claim.keys.isEmpty, claim.buttons.isEmpty else {
                throw ActionError.failure(kind: "input_target_busy", message: "release held input before changing the target")
            }
            focusGuard?.stop(); focusGuard = nil
            if let previous = claim.route { SyntheticFocus.deactivate(previous, tag: eventTag) }
            var next = claim; next.route = route; next.inputSessionID = session.id
            _ = try sync(next)
            activatedRoute = nil
        }
        self.session = session; activationPoint = point
        if route.mode == .background && focusGuard == nil {
            do {
                focusGuard = try BackgroundFocusGuard(route: route, session: session, eventTag: eventTag) { [weak session] reason in
                    guard let session = session, session.inputGeneration == route.generation else { return }
                    IpcServer.pauseForInputFailure(session.id, reason: reason)
                }
                BackgroundInputSPI.recordFocusGuardReady()
            } catch {
                if case ActionError.failure(let kind, _, _) = error,
                   kind == "background_focus_guard_unavailable" {
                    BackgroundInputSPI.recordFocusGuardFailure()
                }
                throw error
            }
        }
    }
    func prepareFocus() throws {
        lock.lock()
        let route = claim.route, point = activationPoint, alreadyActivated = activatedRoute == claim.route
        let currentSession = session, guardLease = focusGuard
        lock.unlock()
        try currentSession?.cancellation.check()
        guard let route = route, let currentSession = currentSession else { throw unavailable() }
        guard route.mode == .background else { return }
        try BackgroundInputSPI.requireSafeInput()
        guard let guardLease = guardLease else { throw unavailable() }
        try guardLease.check()
        if !alreadyActivated {
            guard let point = point, point.x.isFinite, point.y.isFinite, route.bounds.frame.contains(point) else {
                throw ActionError.failure(kind: "background_focus_unavailable",
                    message: "the target window does not expose a valid native activation point")
            }
            try activate(route, session: currentSession, guardLease: guardLease)
            // AXActivationPoint belongs to the window, not the requested
            // control. Zero-count mouse events establish its local key focus.
            // They retain the same acknowledged down/up recovery as user input.
            let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown,
                mouseCursorPosition: point, mouseButton: .left)
            let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp,
                mouseCursorPosition: point, mouseButton: .left)
            guard let down = down, let up = up else { throw unavailable() }
            down.setIntegerValueField(.mouseEventClickState, value: 0)
            up.setIntegerValueField(.mouseEventClickState, value: 0)
            down.flags = []; up.flags = []
            defer { release(up) }
            try post(down)
            try post(up)
            lock.lock()
            if claim.route == route { activatedRoute = route }
            lock.unlock()
        }
    }
    private func activate(_ route: InputRoute, session: NativeSession,
                          guardLease: BackgroundFocusGuard) throws {
        lock.lock(); defer { lock.unlock() }
        guard claim.route == route, claim.inputSessionID == session.id,
              self.session === session, focusGuard === guardLease else { throw unavailable() }
        try session.cancellation.check()
        try guardLease.check()
        // Stop/release use this same lock. A previous action cannot post a
        // delayed application-local activation after their cleanup returns.
        try SyntheticFocus.activate(route, tag: eventTag)
    }
    func releaseSession(_ id: String, phase: String, reason: String? = nil) {
        lock.lock(); defer { lock.unlock() }
        guard claim.inputSessionID == id else { return }
        focusGuard?.stop(); focusGuard = nil
        let current = claim
        var next = claim; next.keys.removeAll(); next.buttons.removeAll()
        var releasedKeys: [UInt16] = [], releasedButtons: [UInt32] = []
        if let external = external {
            let flags = InputRelease.flags(next, external: external)
            for code in current.keys.keys where InputRelease.key(code, flags: flags,
                source: source, external: external, route: current.route) { releasedKeys.append(code) }
            for (button, point) in current.buttons where InputRelease.button(button, point: point,
                flags: flags, source: source, external: external, route: current.route) { releasedButtons.append(button) }
        }
        do { _ = try sync(next, releasedKeys: releasedKeys, releasedButtons: releasedButtons) } catch { fail() }
        if let route = current.route { SyntheticFocus.deactivate(route, tag: eventTag) }
        if let session = session { NativeInputPresentation.shared.update(session, route: current.route, phase: phase, reason: reason) }
    }
    private func externalInput(_ observation: ExternalInputObservation) {
        lock.lock(); let current = session, route = claim.route; lock.unlock()
        guard let current = current, let route = route, current.inputStopPhase == nil else { return }
        if route.mode == .background {
            if observation.isPointer {
                // Hit-test the visible WindowServer stack. A background window
                // behind the person's active app must not claim that app's input.
                guard InputWindowVisibility.visible(route, at: observation.point) else { return }
            } else {
                guard NSWorkspace.shared.frontmostApplication?.processIdentifier == route.pid,
                      let focused = AxEngine.copyElement(AXUIElementCreateApplication(route.pid), kAXFocusedWindowAttribute as String),
                      BackgroundInputSPI.windowID(focused) == route.window else { return }
            }
        }
        guard current.inputGeneration == route.generation, current.pause() else { return }
        IpcServer.pauseForExternalInput(current.id)
    }
    private func externalTrackingInterrupted() {
        lock.lock(); let current = session, route = claim.route; lock.unlock()
        guard let current = current, route?.mode == .background,
              current.inputGeneration == route?.generation, current.pause() else { return }
        IpcServer.pauseForInputFailure(current.id, reason: "input_tracking_interrupted")
    }

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
        focusGuard?.stop(); focusGuard = nil
        var next = claim
        if next.lockedUse == nil { next.inputSessionID = nil }
        if let route = claim.route { SyntheticFocus.deactivate(route, tag: eventTag) }
        // A hardware-held foreground key may still be deferred in the child.
        // Keep its immutable route until the child accepts a new empty claim.
        session = nil; activatedRoute = nil; activationPoint = nil
        do { _ = try sync(next) } catch { fail() }
        external?.stop(); external = nil
    }
    func prepareLockedUse(_ sessionID: String) throws -> (identity: LockedUseProcessIdentity, tag: Int64) {
        try beginInputLease(sessionID)
        lock.lock(); defer { lock.unlock() }
        guard let child = process, let identity = LockedUseProcessIdentity.current(child.processIdentifier) else {
            throw unavailable()
        }
        return (identity, eventTag)
    }
    func armLockedUse(_ supervision: LockedUseSupervisionClaim) throws {
        lock.lock(); defer { lock.unlock() }
        guard claim.inputSessionID == supervision.binding.sessionID else { throw unavailable() }
        var next = claim; next.lockedUse = supervision
        _ = try sync(next)
    }
    func clearLockedUse(_ binding: LockedUseBinding) {
        lock.lock(); defer { lock.unlock() }
        guard claim.lockedUse?.binding == binding else { return }
        var next = claim; next.lockedUse = nil
        if session == nil { next.inputSessionID = nil }
        do { _ = try sync(next) } catch { fail() }
    }
    /// The loginwindow submit is the only global input outside an application
    /// route. Its exact Return down is acknowledged by the independent watchdog
    /// before posting; a crashed submit therefore retains ordinary key recovery.
    func submitLockedUseUnlock(_ binding: LockedUseBinding) throws {
        lock.lock(); defer { lock.unlock() }
        guard claim.lockedUse?.binding == binding,
              claim.lockedUse?.valid(now: ProcessInfo.processInfo.systemUptime) == true,
              claim.keys.isEmpty, claim.buttons.isEmpty else { throw unavailable() }
        var next = claim; next.route = nil
        _ = try sync(next)
        guard let down = CGEvent(keyboardEventSource: source, virtualKey: 0x24, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: 0x24, keyDown: false) else { throw unavailable() }
        down.setIntegerValueField(.eventSourceUserData, value: eventTag)
        up.setIntegerValueField(.eventSourceUserData, value: eventTag)
        next.keys[0x24] = 0; _ = try sync(next)
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        next.keys.removeValue(forKey: 0x24)
        _ = try sync(next, releasedKeys: [0x24])
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
        let child = Process()
        let writer = Pipe(), reader = Pipe()
        child.executableURL = executable
        child.arguments = ["--input-watchdog"]
        child.terminationHandler = { _ in
            LockedUseCoordinator.shared.revokeImmediately(reason: "input_watchdog_exited")
        }
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
        if next.inputSessionID != nil && external == nil {
            external = try ExternalInputState(tag: eventTag,
                onInput: { [weak self] observation in self?.externalInput(observation) },
                onInterruption: { [weak self] in self?.externalTrackingInterrupted() })
        }
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
        focusGuard?.stop(); focusGuard = nil
        timer?.cancel(); timer = nil
        try? input?.close(); input = nil
        try? output?.close(); output = nil
        // Closing the inherited input invokes child recovery. If the child
        // itself failed, release our mirror without touching hardware holds.
        if let external = external {
            var remaining = claim; remaining.keys.removeAll(); remaining.buttons.removeAll()
            let flags = InputRelease.flags(remaining, external: external)
            for code in claim.keys.keys {
                _ = InputRelease.key(code, flags: flags, source: source, external: external, route: claim.route)
            }
            for (button, point) in claim.buttons {
                _ = InputRelease.button(button, point: point, flags: flags, source: source, external: external, route: claim.route)
            }
        }
        // Keep the inherited lock descriptor open while input ownership is
        // unresolved. The surviving child releases it after recovery; if that
        // child died, the worker retains exclusivity until it terminates.
    }
    func post(_ event: CGEvent, keyDown: Bool? = nil, ownedFlags explicit: CGEventFlags? = nil,
              literalText: Bool = false) throws {
        lock.lock(); defer { lock.unlock() }
        guard let route = claim.route else {
            throw ActionError.failure(kind: "input_target_required", message: "bind a target before sending input")
        }
        event.setIntegerValueField(.eventSourceUserData, value: eventTag)
        let operation: CGEventType
        if event.type == .flagsChanged {
            guard let down = keyDown else {
                throw ActionError.failure(kind: "input_error", message: "modifier input requires an explicit down/up phase")
            }
            operation = down ? .keyDown : .keyUp
        } else { operation = event.type }
        let release = [.keyUp, .leftMouseUp, .rightMouseUp, .otherMouseUp].contains(operation)
        if !release {
            try session?.cancellation.check()
            try NativeScreenState.requireUnlocked()
            if route.mode == .background {
                try BackgroundInputSPI.requireSafeInput()
                guard let focusGuard = focusGuard else { throw unavailable() }
                try focusGuard.check()
            }
        }
        var next = claim
        switch operation {
        case .keyDown:
            let code = UInt16(event.getIntegerValueField(.keyboardEventKeycode))
            guard next.keys[code] == nil else { throw ActionError.failure(kind: "input_busy", message: "this key is already held") }
            let inherited = external.map { InputRelease.flags(claim, external: $0) } ?? []
            next.keys[code] = Self.ownedFlags(code: code, flags: event.flags,
                inherited: inherited, explicit: explicit).rawValue
            try sync(next)
            if let external = external, !literalText { event.flags.formUnion(InputRelease.flags(next, external: external)) }
            try route.post(event)
        case .leftMouseDown, .rightMouseDown, .otherMouseDown:
            let button = UInt32(event.getIntegerValueField(.mouseEventButtonNumber))
            guard next.buttons[button] == nil else { throw ActionError.failure(kind: "input_busy", message: "this button is already held") }
            next.buttons[button] = InputPoint(x: event.location.x, y: event.location.y)
            try sync(next)
            if let external = external { event.flags.formUnion(InputRelease.flags(next, external: external)) }
            try route.post(event)
        case .keyUp:
            let code = UInt16(event.getIntegerValueField(.keyboardEventKeycode))
            guard next.keys.removeValue(forKey: code) != nil else { return }
            // A physical takeover of the same key is left down. The watchdog
            // defers its owned release until hardware sends the matching up.
            var released = false
            if let external = external, route.mode == .background || !external.key(code) {
                let flags = InputRelease.flags(next, external: external)
                // Preserve event flags when no release adjustment is required.
                if event.flags != flags { event.flags = flags }
                try route.post(event)
                released = true
            }
            do { try sync(next, releasedKeys: released ? [code] : []) } catch { fail(); throw error }
        case .leftMouseUp, .rightMouseUp, .otherMouseUp:
            let button = UInt32(event.getIntegerValueField(.mouseEventButtonNumber))
            guard next.buttons.removeValue(forKey: button) != nil else { return }
            var released = false
            if let external = external, route.mode == .background || !external.button(button) {
                event.flags.formUnion(InputRelease.flags(next, external: external))
                try route.post(event)
                released = true
            }
            do { try sync(next, releasedButtons: released ? [button] : []) } catch { fail(); throw error }
        case .leftMouseDragged, .rightMouseDragged, .otherMouseDragged:
            let button = UInt32(event.getIntegerValueField(.mouseEventButtonNumber))
            guard next.buttons[button] != nil else { throw ActionError.failure(kind: "input_error", message: "drag has no owned button") }
            next.buttons[button] = InputPoint(x: event.location.x, y: event.location.y)
            try sync(next)
            if let external = external { event.flags.formUnion(InputRelease.flags(next, external: external)) }
            try route.post(event)
        default:
            guard !failed else { throw unavailable() }
            if let external = external { event.flags.formUnion(InputRelease.flags(next, external: external)) }
            try route.post(event)
        }
        if let session = session {
            let mouse = [.mouseMoved, .leftMouseDown, .leftMouseUp, .leftMouseDragged,
                .rightMouseDown, .rightMouseUp, .rightMouseDragged,
                .otherMouseDown, .otherMouseUp, .otherMouseDragged, .scrollWheel].contains(operation)
            NativeInputPresentation.shared.update(session, route: route,
                phase: !claim.keys.isEmpty || !claim.buttons.isEmpty ? "holding" : release ? "released" : mouse ? "moving" : "idle",
                point: mouse ? event.location : nil, keys: Array(claim.keys.keys), buttons: Array(claim.buttons.keys))
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
