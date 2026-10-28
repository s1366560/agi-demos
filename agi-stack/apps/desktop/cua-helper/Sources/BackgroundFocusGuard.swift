import AppKit
import ApplicationServices
import Darwin

/// The two notification recipients are deliberately separate: field 73 is the
/// process taking focus; field 40 is the process receiving the notification.
struct BackgroundFocusState {
    struct Pending: Equatable {
        let process: Int32
        let owner: Int32
        let receiver: Int32
        var returned = false
    }
    private(set) var pending: Pending?
    mutating func lost(process: Int32, owner: Int32, receiver: Int32) {
        guard process != receiver else { clear(); return }
        pending = Pending(process: process, owner: owner, receiver: receiver)
    }
    mutating func returned(receiver: Int32) -> Bool {
        guard var value = pending, !value.returned, value.receiver == receiver else { return false }
        value.returned = true; pending = value; return true
    }
    func keyboardRecipient(process: Int32) -> Int32? {
        guard let value = pending, value.process == process else { return nil }
        return value.receiver
    }
    mutating func foregroundChanged(to process: Int32, target: Int32) -> Bool {
        clear()
        return process == target
    }
    mutating func clear() { pending = nil }
}

/// Per-lease isolation. The run-loop context outlives its callbacks but does not
/// retain this owner, so dropping the owner also tears down every event tap.
final class BackgroundFocusGuard {
    private let context: Context
    init(route: InputRoute, session: NativeSession, eventTag: Int64,
         onInvalidated: @escaping (String) -> Void) throws {
        context = Context(route: route, session: session, tag: eventTag, onInvalidated: onInvalidated)
        try context.start()
    }
    func check() throws { try context.check() }
    func stop() { context.stop() }
    deinit { stop() }

    private struct Identity: Equatable {
        let pid: Int32
        let seconds: UInt64
        let microseconds: UInt64
        init?(_ pid: Int32) {
            var info = proc_bsdinfo()
            let size = Int32(MemoryLayout<proc_bsdinfo>.size)
            guard pid > 0, proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, size) == size,
                  info.pbi_uid == getuid(), info.pbi_status != SZOMB else { return nil }
            self.pid = pid; seconds = info.pbi_start_tvsec; microseconds = info.pbi_start_tvusec
        }
        var current: Bool { Identity(pid) == self }
    }

    private final class Context {
        let route: InputRoute
        weak var session: NativeSession?
        let tag: Int64
        let onInvalidated: (String) -> Void
        let lock = NSLock()
        let ready = DispatchSemaphore(value: 0)
        let callbackQueue = DispatchQueue(label: "memstack.cua.focus-invalidation")
        var loop: CFRunLoop?
        var taps: [(CFMachPort, CFRunLoopSource)] = []
        var running = false
        var stopped = false
        var failure: String?
        // These values are only mutated on the event-tap run loop.
        var state = BackgroundFocusState()
        var receiverIdentity: Identity?
        var bridges: [Int32: Identity] = [:]
        var bridgeTaps: [Int32: CFMachPort] = [:]

        init(route: InputRoute, session: NativeSession, tag: Int64,
             onInvalidated: @escaping (String) -> Void) {
            self.route = route; self.session = session; self.tag = tag
            self.onInvalidated = onInvalidated
        }
        static func unavailable(_ reason: String) -> ActionError {
            .failure(kind: "background_focus_guard_unavailable", message: reason)
        }
        func start() throws {
            guard route.mode == .background else {
                throw Self.unavailable("focus isolation requires a background input route")
            }
            do { try validateBinding() } catch {
                invalidate("the background input binding could not be verified")
                throw error
            }
            let worker = Thread { [self] in run() }
            worker.name = "memstack.cua.background-focus"; worker.start()
            guard ready.wait(timeout: .now() + 2) == .success else {
                invalidate("the background focus event taps did not start"); stop()
                throw Self.unavailable("the background focus event taps did not start")
            }
            do { try check() } catch { stop(); throw error }
        }
        func validateBinding() throws {
            guard let session = session, session.inputGeneration == route.generation,
                  session.inputStopPhase == nil else {
                throw ActionError.failure(kind: "stale_input_generation",
                    message: "the background input binding is no longer active")
            }
            try route.validate()
            try BackgroundInputSPI.requireSafeInput()
        }
        func check() throws {
            lock.lock()
            let active = running && !stopped, reason = failure
            let portsReady = taps.count >= 3 && taps.allSatisfy {
                CFMachPortIsValid($0.0) && CGEvent.tapIsEnabled(tap: $0.0)
            }
            lock.unlock()
            guard active, reason == nil else {
                throw Self.unavailable(reason ?? "the background focus guard is stopped")
            }
            do {
                try validateBinding()
                guard portsReady else {
                    recordTapFailure()
                    throw Self.unavailable("a background focus event tap is unavailable")
                }
            } catch {
                invalidate("the background focus binding or event taps became unavailable")
                throw error
            }
        }
        func invalidate(_ reason: String) {
            lock.lock()
            guard failure == nil, !stopped else { lock.unlock(); return }
            failure = reason
            lock.unlock()
            if let session = session, session.inputGeneration == route.generation { session.pause() }
            callbackQueue.async { [onInvalidated] in onInvalidated(reason) }
            stop()
        }
        func stop() {
            lock.lock(); stopped = true; running = false
            let currentLoop = loop, currentTaps = taps
            lock.unlock()
            for (port, _) in currentTaps {
                CGEvent.tapEnable(tap: port, enable: false)
                CFMachPortInvalidate(port)
            }
            if let currentLoop = currentLoop { CFRunLoopStop(currentLoop) }
        }
        var active: Bool {
            lock.lock(); defer { lock.unlock() }; return running && !stopped && failure == nil
        }
        func recordTapFailure() {
            lock.lock(); defer { lock.unlock() }
            if !stopped { BackgroundInputSPI.recordFocusGuardFailure() }
        }
        func run() {
            let currentLoop = CFRunLoopGetCurrent()!
            lock.lock(); loop = currentLoop; let cancelled = stopped; lock.unlock()
            defer {
                lock.lock(); let installed = taps; taps.removeAll(); running = false; loop = nil; lock.unlock()
                for (port, source) in installed {
                    CGEvent.tapEnable(tap: port, enable: false)
                    CFMachPortInvalidate(port)
                    CFRunLoopRemoveSource(currentLoop, source, .commonModes)
                    CFRunLoopSourceInvalidate(source)
                }
                state.clear(); receiverIdentity = nil; bridges.removeAll(); bridgeTaps.removeAll()
            }
            guard !cancelled else { ready.signal(); return }
            do {
                try installSystemTap()
                _ = try installKeyboardTap(route.pid)
                try installMenuTap()
                try discoverBridges()
                lock.lock(); running = !stopped; lock.unlock()
                ready.signal()
                var nextHealthCheck = ProcessInfo.processInfo.systemUptime + 0.25
                while active {
                    CFRunLoopRunInMode(.defaultMode, 0.05, true)
                    if ProcessInfo.processInfo.systemUptime >= nextHealthCheck {
                        try check(); try discoverBridges()
                        nextHealthCheck = ProcessInfo.processInfo.systemUptime + 0.25
                    }
                }
            } catch {
                invalidate("the background focus event taps could not remain active")
                ready.signal()
            }
        }
        @discardableResult func attach(_ port: CFMachPort?) throws -> CFMachPort {
            guard let port = port,
                  let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, port, 0) else {
                if let port = port { CFMachPortInvalidate(port) }
                recordTapFailure()
                throw Self.unavailable("Input Monitoring and Accessibility access are required for background focus isolation")
            }
            lock.lock()
            guard !stopped else { lock.unlock(); CFMachPortInvalidate(port); throw Self.unavailable("the focus guard was stopped") }
            taps.append((port, source)); lock.unlock()
            CFRunLoopAddSource(CFRunLoopGetCurrent(), source, .commonModes)
            CGEvent.tapEnable(tap: port, enable: true)
            guard CGEvent.tapIsEnabled(tap: port) else {
                recordTapFailure()
                throw Self.unavailable("the background focus event tap could not be enabled")
            }
            return port
        }
        func installSystemTap() throws {
            try attach(CGEvent.tapCreate(tap: .cgAnnotatedSessionEventTap, place: .tailAppendEventTap,
                options: .defaultTap, eventsOfInterest: 1 << 21,
                callback: { _, type, event, pointer in
                    guard let pointer = pointer else { return Unmanaged.passUnretained(event) }
                    return Unmanaged<Context>.fromOpaque(pointer).takeUnretainedValue().system(type, event)
                }, userInfo: Unmanaged.passUnretained(self).toOpaque()))
        }
        func installKeyboardTap(_ pid: Int32) throws -> CFMachPort {
            try attach(CGEvent.tapCreateForPid(pid: pid, place: .tailAppendEventTap,
                options: .defaultTap, eventsOfInterest: 0x1c00,
                callback: { _, type, event, pointer in
                    guard let pointer = pointer else { return Unmanaged.passUnretained(event) }
                    return Unmanaged<Context>.fromOpaque(pointer).takeUnretainedValue().keyboard(type, event)
                }, userInfo: Unmanaged.passUnretained(self).toOpaque()))
        }
        func installMenuTap() throws {
            try attach(CGEvent.tapCreateForPid(pid: route.pid, place: .headInsertEventTap,
                options: .defaultTap, eventsOfInterest: 0x0e0000de,
                callback: { _, type, event, pointer in
                    guard let pointer = pointer else { return Unmanaged.passUnretained(event) }
                    return Unmanaged<Context>.fromOpaque(pointer).takeUnretainedValue().menu(type, event)
                }, userInfo: Unmanaged.passUnretained(self).toOpaque()))
        }
        func accepts(_ type: CGEventType, _ event: CGEvent) -> Bool {
            if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
                if active {
                    recordTapFailure()
                    invalidate("macOS disabled a background focus event tap")
                }
                return false
            }
            guard active else { return false }
            guard event.getIntegerValueField(.eventSourceUserData) != tag,
                  event.getIntegerValueField(.eventSourceUnixProcessID) != Int64(getpid()) else { return false }
            do { try validateBinding() } catch {
                invalidate("the background input target is no longer valid"); return false
            }
            return true
        }
        // Caller holds lock. Session checks also reject a pause or generation
        // change that happened while an AX query was in flight.
        var decisionAllowed: Bool {
            running && !stopped && failure == nil &&
                session?.inputGeneration == route.generation && session?.inputStopPhase == nil
        }
        func dropIfActive(_ event: CGEvent) -> Unmanaged<CGEvent>? {
            lock.lock(); defer { lock.unlock() }
            return decisionAllowed ? nil : Unmanaged.passUnretained(event)
        }
        func system(_ type: CGEventType, _ event: CGEvent) -> Unmanaged<CGEvent>? {
            guard accepts(type, event) else { return Unmanaged.passUnretained(event) }
            let receiver = Int32(clamping: event.getIntegerValueField(.eventTargetUnixProcessID))
            let subtype = UInt16(truncatingIfNeeded: event.getIntegerValueField(CGEventField(rawValue: 64)!))
            let process = Int32(clamping: event.getIntegerValueField(CGEventField(rawValue: 73)!))
            // NewFrontProcess is a notification of an already committed
            // global activation. Stop background input; never steal it back.
            if subtype == 2 {
                let targetActivated = state.foregroundChanged(to: process, target: route.pid)
                receiverIdentity = nil
                if targetActivated { invalidate("target_became_foreground") }
                return Unmanaged.passUnretained(event)
            }
            if subtype == 0x8000 {
                guard receiverIdentity?.current == true else {
                    if state.pending != nil { invalidate("the protected focus recipient changed") }
                    return Unmanaged.passUnretained(event)
                }
                return state.returned(receiver: receiver) ? dropIfActive(event) : Unmanaged.passUnretained(event)
            }
            guard subtype == 0x4000 else { return Unmanaged.passUnretained(event) }
            let owner: Int32
            if process == route.pid { owner = route.pid }
            else if Self.isViewBridge(process) {
                switch bridgeOwnership(process) {
                case .other:
                    removeBridge(process); state.clear(); receiverIdentity = nil
                    return Unmanaged.passUnretained(event)
                case .unknown:
                    if bridges[process] != nil || state.pending?.process == process || receiver == route.pid {
                        invalidate("ViewBridge focus ownership could not be verified")
                    } else {
                        state.clear(); receiverIdentity = nil
                    }
                    return Unmanaged.passUnretained(event)
                case .target: break
                }
                do { try ensureBridge(process) } catch {
                    invalidate("the verified ViewBridge keyboard event tap is unavailable")
                    return Unmanaged.passUnretained(event)
                }
                owner = route.pid
            } else {
                state.clear(); receiverIdentity = nil
                return Unmanaged.passUnretained(event)
            }
            guard receiver != owner, receiver != process else {
                state.clear(); receiverIdentity = nil
                return Unmanaged.passUnretained(event)
            }
            guard let identity = Identity(receiver) else {
                invalidate("the original focus recipient could not be verified")
                return Unmanaged.passUnretained(event)
            }
            receiverIdentity = identity
            state.lost(process: process, owner: owner, receiver: receiver)
            return dropIfActive(event)
        }
        func keyboard(_ type: CGEventType, _ event: CGEvent) -> Unmanaged<CGEvent>? {
            guard accepts(type, event) else { return Unmanaged.passUnretained(event) }
            let process = Int32(clamping: event.getIntegerValueField(.eventTargetUnixProcessID))
            guard let receiver = state.keyboardRecipient(process: process) else { return Unmanaged.passUnretained(event) }
            if process != route.pid {
                guard bridges[process]?.current == true else {
                    invalidate("the bound ViewBridge process changed")
                    return Unmanaged.passUnretained(event)
                }
                switch bridgeOwnership(process) {
                case .other: removeBridge(process); return Unmanaged.passUnretained(event)
                case .unknown:
                    invalidate("ViewBridge keyboard ownership could not be verified")
                    return Unmanaged.passUnretained(event)
                case .target: break
                }
            }
            guard receiver != process, receiverIdentity?.pid == receiver,
                  receiverIdentity?.current == true, let copy = event.copy() else {
                invalidate("the background keyboard recipient could not be verified")
                return Unmanaged.passUnretained(event)
            }
            // Stop acquires this same lock before returning. No old lease can
            // post or commit a drop after stop, even when AX was slow.
            lock.lock(); defer { lock.unlock() }
            guard decisionAllowed else { return Unmanaged.passUnretained(event) }
            copy.postToPid(receiver)
            return nil
        }
        func menu(_ type: CGEventType, _ event: CGEvent) -> Unmanaged<CGEvent>? {
            guard accepts(type, event) else { return Unmanaged.passUnretained(event) }
            let number = event.getIntegerValueField(CGEventField(rawValue: 51)!)
            guard number > 0, number <= Int64(UInt32.max),
                  let windows = CGWindowListCopyWindowInfo(.optionIncludingWindow, UInt32(number)) as? [[String: Any]],
                  let window = windows.first(where: { ($0[kCGWindowNumber as String] as? NSNumber)?.int64Value == number }),
                  let owner = (window[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value else {
                return Unmanaged.passUnretained(event)
            }
            return owner == route.pid ? Unmanaged.passUnretained(event) : dropIfActive(event)
        }
        static func isViewBridge(_ pid: Int32) -> Bool {
            var path = [CChar](repeating: 0, count: Int(MAXPATHLEN) * 4)
            guard proc_pidpath(pid, &path, UInt32(path.count)) > 0 else { return false }
            let value = String(cString: path)
            return value.hasPrefix("/System/Library/") &&
                value.hasSuffix("/ViewBridgeAuxiliary.xpc/Contents/MacOS/ViewBridgeAuxiliary")
        }
        enum BridgeOwnership { case target, other, unknown }
        func bridgeOwnership(_ pid: Int32) -> BridgeOwnership {
            guard Self.isViewBridge(pid), Identity(pid) != nil else { return .unknown }
            let application = AXUIElementCreateApplication(pid)
            // AX belongs to another process. Bound each IPC wait so an
            // unresponsive bridge cannot monopolize the event-tap run loop.
            guard AXUIElementSetMessagingTimeout(application, 0.05) == .success,
                  let focused = AxEngine.copyElement(application, kAXFocusedUIElementAttribute as String),
                  AXUIElementSetMessagingTimeout(focused, 0.05) == .success else { return .unknown }
            var owner: pid_t = 0
            guard AXUIElementGetPid(focused, &owner) == .success, Identity(owner) != nil else { return .unknown }
            // A bridge-owned proxy does not establish its logical app owner.
            if owner == pid { return .unknown }
            if owner != route.pid { return .other }
            guard
                  let window = AxEngine.copyElement(focused, kAXWindowAttribute as String),
                  AXUIElementSetMessagingTimeout(window, 0.05) == .success,
                  let number = BackgroundInputSPI.windowID(window) else { return .unknown }
            return number == route.window ? .target : .other
        }
        func ensureBridge(_ pid: Int32) throws {
            guard let identity = Identity(pid), Self.isViewBridge(pid) else {
                throw Self.unavailable("the ViewBridge process identity is unavailable")
            }
            if let previous = bridges[pid] {
                guard previous == identity else { throw Self.unavailable("the ViewBridge process was replaced") }
                return
            }
            bridgeTaps[pid] = try installKeyboardTap(pid); bridges[pid] = identity
        }
        func removeBridge(_ pid: Int32) {
            bridges.removeValue(forKey: pid)
            if state.pending?.process == pid { state.clear(); receiverIdentity = nil }
            guard let port = bridgeTaps.removeValue(forKey: pid) else { return }
            lock.lock()
            let source = taps.first(where: { CFEqual($0.0, port) })?.1
            taps.removeAll(where: { CFEqual($0.0, port) })
            lock.unlock()
            CGEvent.tapEnable(tap: port, enable: false); CFMachPortInvalidate(port)
            if let source = source {
                CFRunLoopRemoveSource(CFRunLoopGetCurrent(), source, .commonModes)
                CFRunLoopSourceInvalidate(source)
            }
        }
        func discoverBridges() throws {
            let count = proc_listallpids(nil, 0)
            guard count > 0 else { throw Self.unavailable("native process identities could not be enumerated") }
            var pids = [Int32](repeating: 0, count: Int(count) + 32)
            let found = pids.withUnsafeMutableBytes { proc_listallpids($0.baseAddress, Int32($0.count)) }
            guard found > 0 else { throw Self.unavailable("native process identities could not be enumerated") }
            for pid in pids.prefix(min(Int(found), pids.count)) where Self.isViewBridge(pid) {
                switch bridgeOwnership(pid) {
                case .target: try ensureBridge(pid)
                case .other: removeBridge(pid)
                case .unknown:
                    if bridges[pid] != nil {
                        throw Self.unavailable("the bound ViewBridge ownership is no longer verifiable")
                    }
                }
            }
        }
    }
}
