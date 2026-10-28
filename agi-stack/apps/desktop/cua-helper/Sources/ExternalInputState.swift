import CoreGraphics
import Foundation

struct ExternalInputObservation {
    let type: CGEventType
    let point: CGPoint
    let targetPID: Int32
    let window: UInt32
    var isPointer: Bool {
        [.mouseMoved, .leftMouseDown, .leftMouseUp, .leftMouseDragged,
         .rightMouseDown, .rightMouseUp, .rightMouseDragged,
         .otherMouseDown, .otherMouseUp, .otherMouseDragged, .scrollWheel].contains(type)
    }
}

/// Observe source-tag membership, not aggregate HID state, to preserve a
/// person's or another controller's same-key/button takeover.
final class ExternalInputState {
    let tag: Int64
    private let lock = NSLock()
    private var keys = Set<UInt16>()
    private var buttons = Set<UInt32>()
    private var tap: CFMachPort?
    private var thread: Thread?
    private var runLoop: CFRunLoop?
    private var active = true
    private let onInput: ((ExternalInputObservation) -> Void)?
    private let onInterruption: (() -> Void)?
    private let callbackQueue = DispatchQueue(label: "memstack.cua.user-input")
    private var notificationQueued = false
    private var pending: [ExternalInputObservation] = []
    init(tag: Int64, onInput: ((ExternalInputObservation) -> Void)? = nil,
         onInterruption: (() -> Void)? = nil) throws {
        self.tag = tag
        self.onInput = onInput
        self.onInterruption = onInterruption
        let mask = [CGEventType.keyDown, .keyUp, .flagsChanged,
            .mouseMoved, .leftMouseDragged, .rightMouseDragged, .otherMouseDragged, .scrollWheel,
            .leftMouseDown, .leftMouseUp, .rightMouseDown, .rightMouseUp,
            .otherMouseDown, .otherMouseUp].reduce(CGEventMask(0)) { $0 | (1 << $1.rawValue) }
        guard let tap = CGEvent.tapCreate(tap: .cghidEventTap, place: .headInsertEventTap,
            options: .listenOnly, eventsOfInterest: mask,
            callback: { _, type, event, context in
                guard let context = context else { return Unmanaged.passUnretained(event) }
                Unmanaged<ExternalInputState>.fromOpaque(context).takeUnretainedValue().receive(type, event)
                return Unmanaged.passUnretained(event)
            }, userInfo: Unmanaged.passUnretained(self).toOpaque()) else {
            throw ActionError.failure(kind: "input_tracking_permission_required", message: "Input Monitoring access is required for safe input ownership")
        }
        self.tap = tap
        let ready = DispatchSemaphore(value: 0)
        let thread = Thread { [weak self] in
            guard let self = self, let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0) else { ready.signal(); return }
            self.lock.lock(); self.runLoop = CFRunLoopGetCurrent(); self.lock.unlock()
            CFRunLoopAddSource(CFRunLoopGetCurrent(), source, .commonModes)
            CGEvent.tapEnable(tap: tap, enable: true)
            ready.signal()
            while CFMachPortIsValid(tap) { CFRunLoopRunInMode(.defaultMode, 0.1, true) }
            _ = self
        }
        self.thread = thread; thread.name = "memstack.cua.external-input"; thread.start()
        guard ready.wait(timeout: .now() + 1) == .success,
              CFMachPortIsValid(tap), CGEvent.tapIsEnabled(tap: tap) else {
            stop()
            throw ActionError.failure(kind: "input_tracking_unavailable", message: "safe input tracking failed to start")
        }
        lock.lock()
        // No owned event can be posted before this initializer returns.
        // Seed existing holds after the tap is live; callbacks queued during
        // this read replay afterwards, eliminating the startup observation gap.
        keys = Set((UInt16(0)...127).filter { CGEventSource.keyState(.hidSystemState, key: $0) })
        buttons = Set([CGMouseButton.left, .right, .center].filter {
            CGEventSource.buttonState(.hidSystemState, button: $0)
        }.map { $0.rawValue })
        lock.unlock()
    }
    func stop() {
        lock.lock(); active = false; pending.removeAll()
        let loop = runLoop, port = tap; tap = nil; lock.unlock()
        if let port = port { CFMachPortInvalidate(port) }
        if let loop = loop { CFRunLoopStop(loop) }
    }
    deinit { stop() }
    func key(_ code: UInt16) -> Bool { lock.lock(); defer { lock.unlock() }; return keys.contains(code) }
    func button(_ raw: UInt32) -> Bool { lock.lock(); defer { lock.unlock() }; return buttons.contains(raw) }
    var flags: CGEventFlags {
        lock.lock(); defer { lock.unlock() }
        var flags: CGEventFlags = []
        for code in keys { flags.formUnion(OwnedEventSource.modifierFlags(code)) }
        return flags
    }
    private func receive(_ type: CGEventType, _ event: CGEvent) {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            lock.lock(); let wasActive = active; lock.unlock()
            guard wasActive else { return }
            // Restoring the tap cannot recover missed input. Background leases
            // pause and release before tracking is allowed to resume.
            onInterruption?()
            lock.lock(); let port = active ? tap : nil; lock.unlock()
            if let port = port, CFMachPortIsValid(port) { CGEvent.tapEnable(tap: port, enable: true) }
            return
        }
        guard event.getIntegerValueField(.eventSourceUserData) != tag else { return }
        lock.lock(); defer { lock.unlock() }
        guard active else { return }
        if onInput != nil {
            let observation = ExternalInputObservation(type: type, point: event.location,
                targetPID: Int32(clamping: event.getIntegerValueField(.eventTargetUnixProcessID)),
                window: UInt32(clamping: event.getIntegerValueField(.mouseEventWindowUnderMousePointer)))
            if type == .mouseMoved { pending.removeAll { $0.type == .mouseMoved } }
            if pending.count == 128 { pending.removeFirst() }
            pending.append(observation)
            if !notificationQueued {
                notificationQueued = true
                callbackQueue.async { [weak self] in self?.drain() }
            }
        }
        let rawCode = event.getIntegerValueField(.keyboardEventKeycode)
        let rawButton = event.getIntegerValueField(.mouseEventButtonNumber)
        switch type {
        case .keyDown where (0...127).contains(rawCode): keys.insert(UInt16(rawCode))
        case .keyUp where (0...127).contains(rawCode): keys.remove(UInt16(rawCode))
        case .flagsChanged:
            guard (0...127).contains(rawCode) else { return }
            let code = UInt16(rawCode)
            let mask: UInt64
            // Device-side modifier bits from IOKit's public IOLLEvent.h.
            switch code {
            case 56: mask = 0x2
            case 60: mask = 0x4
            case 59: mask = 0x1
            case 62: mask = 0x2000
            case 55: mask = 0x8
            case 54: mask = 0x10
            case 58: mask = 0x20
            case 61: mask = 0x40
            case 57: mask = CGEventFlags.maskAlphaShift.rawValue
            case 63: mask = CGEventFlags.maskSecondaryFn.rawValue
            default: mask = 0
            }
            if mask != 0 && event.flags.rawValue & mask != 0 { keys.insert(code) } else { keys.remove(code) }
        case .leftMouseDown, .rightMouseDown, .otherMouseDown:
            if (0...2).contains(rawButton) { buttons.insert(UInt32(rawButton)) }
        case .leftMouseUp, .rightMouseUp, .otherMouseUp:
            if (0...2).contains(rawButton) { buttons.remove(UInt32(rawButton)) }
        default: break
        }
    }
    private func drain() {
        while true {
            lock.lock()
            guard active, !pending.isEmpty else { notificationQueued = false; lock.unlock(); return }
            let next = pending.removeFirst(); lock.unlock()
            onInput?(next)
        }
    }
}

enum OwnedEventSource {
    static func modifierFlags(_ code: UInt16) -> CGEventFlags {
        switch code {
        case 56: return CGEventFlags(rawValue: CGEventFlags.maskShift.rawValue | 0x2)
        case 60: return CGEventFlags(rawValue: CGEventFlags.maskShift.rawValue | 0x4)
        case 59: return CGEventFlags(rawValue: CGEventFlags.maskControl.rawValue | 0x1)
        case 62: return CGEventFlags(rawValue: CGEventFlags.maskControl.rawValue | 0x2000)
        case 55: return CGEventFlags(rawValue: CGEventFlags.maskCommand.rawValue | 0x8)
        case 54: return CGEventFlags(rawValue: CGEventFlags.maskCommand.rawValue | 0x10)
        case 58: return CGEventFlags(rawValue: CGEventFlags.maskAlternate.rawValue | 0x20)
        case 61: return CGEventFlags(rawValue: CGEventFlags.maskAlternate.rawValue | 0x40)
        case 57: return .maskAlphaShift
        case 63: return .maskSecondaryFn
        default: return []
        }
    }
    static func make(tag: Int64) -> CGEventSource? {
        guard let source = CGEventSource(stateID: .privateState) else { return nil }
        source.userData = tag
        source.localEventsSuppressionInterval = 0
        for state in [UInt32(0), 1] {
            source.setLocalEventsFilterDuringSuppressionState(CGEventFilterMask(rawValue: 7),
                state: CGEventSuppressionState(rawValue: state)!)
        }
        return source
    }
}
