import AppKit
import ApplicationServices
import Darwin

enum NativeInputMode: String, Codable { case background, foreground }

struct InputRectangle: Codable, Equatable {
    let x: Double, y: Double, width: Double, height: Double
    init(_ frame: CGRect) { x = frame.minX; y = frame.minY; width = frame.width; height = frame.height }
    var frame: CGRect { CGRect(x: x, y: y, width: width, height: height) }
}

/// A PID is insufficient across a crash: its birth identity and exact WindowServer
/// window travel with every acknowledged input claim, including watchdog recovery.
struct InputRoute: Codable, Equatable {
    let mode: NativeInputMode
    let generation: String
    let pid: Int32
    let startSeconds: UInt64
    let startMicroseconds: UInt64
    let window: UInt32
    let windowID: String
    let bounds: InputRectangle

    init(session: NativeSession, app: ResolvedApp, window: NativeWindow) throws {
        guard let process = Self.process(app.pid), let captureID = window.captureID,
              window.frame.width > 0, window.frame.height > 0 else {
            throw ActionError.failure(kind: "background_input_unavailable", message: "the target has no verified native window")
        }
        if let identity = window.identity {
            guard identity.windowID == captureID, identity.process.pid == app.pid,
                  identity.process.startSeconds == process.pbi_start_tvsec,
                  identity.process.startMicroseconds == process.pbi_start_tvusec else {
                throw ActionError.failure(kind: "stale_input_target", message: "the observed native window identity changed")
            }
        }
        mode = session.inputMode; generation = session.inputGeneration; pid = app.pid
        startSeconds = process.pbi_start_tvsec; startMicroseconds = process.pbi_start_tvusec
        self.window = captureID; windowID = window.id; bounds = InputRectangle(window.frame)
        try validate()
    }
    private static func process(_ pid: Int32) -> proc_bsdinfo? {
        var info = proc_bsdinfo()
        let size = Int32(MemoryLayout<proc_bsdinfo>.size)
        guard pid > 0, proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, size) == size,
              info.pbi_uid == getuid(), info.pbi_status != SZOMB else { return nil }
        return info
    }
    func currentFrame() throws -> CGRect {
        guard let info = Self.process(pid), info.pbi_start_tvsec == startSeconds,
              info.pbi_start_tvusec == startMicroseconds,
              let entries = CGWindowListCopyWindowInfo(.optionIncludingWindow, window) as? [[String: Any]],
              let entry = entries.first(where: {
                  ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == window &&
                  ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid
              }), let rawBounds = entry[kCGWindowBounds as String] as? [String: Any],
              let frame = CGRect(dictionaryRepresentation: rawBounds as CFDictionary) else {
            throw ActionError.failure(kind: "stale_input_target", message: "the bound input process or window no longer exists")
        }
        return frame
    }
    func validate() throws {
        _ = try currentFrame()
        if mode == .background { try BackgroundInputSPI.requireAvailable() }
    }
    func post(_ event: CGEvent, bindWindow: Bool = true) throws {
        try validate()
        if mode == .foreground { event.post(tap: .cghidEventTap); return }
        if bindWindow { BackgroundInputSPI.setTargetWindow(event, window) }
        event.setIntegerValueField(.mouseEventWindowUnderMousePointer, value: Int64(window))
        event.setIntegerValueField(.mouseEventWindowUnderMousePointerThatCanHandleThisEvent, value: Int64(window))
        switch event.type {
        case .mouseMoved, .leftMouseDown, .leftMouseUp, .leftMouseDragged,
             .rightMouseDown, .rightMouseUp, .rightMouseDragged,
             .otherMouseDown, .otherMouseUp, .otherMouseDragged, .scrollWheel:
            // WindowServer converts this window-local top-left point to the
            // bottom-left NSEvent.locationInWindow delivered to AppKit.
            let point = CGPoint(x: event.location.x - bounds.x,
                y: event.location.y - bounds.y)
            try BackgroundInputSPI.setWindowLocation(event, point)
            event.setIntegerValueField(.mouseEventSubtype, value: 3)
        default: break
        }
        event.postToPid(pid)
    }
}

/// Private WindowServer API is deliberately confined here. Missing SPI makes
/// background mode unavailable; it never selects global HID injection.
enum BackgroundInputSPI {
    private static let failureLock = NSLock()
    private static var focusGuardFailed = false
    static func recordFocusGuardFailure() {
        failureLock.lock(); focusGuardFailed = true; failureLock.unlock()
    }
    static func recordFocusGuardReady() {
        failureLock.lock(); focusGuardFailed = false; failureLock.unlock()
    }
    private static var focusGuardAvailable: Bool {
        failureLock.lock(); defer { failureLock.unlock() }; return !focusGuardFailed
    }
    private typealias SetLocation = @convention(c) (CGEvent, CGPoint) -> Void
    private typealias GetWindow = @convention(c) (AXUIElement, UnsafeMutablePointer<CGWindowID>) -> AXError
    private typealias SecureInputEnabled = @convention(c) () -> Bool
    private static let graphics = dlopen("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics", RTLD_LAZY | RTLD_LOCAL)
    private static let accessibility = dlopen("/System/Library/Frameworks/ApplicationServices.framework/Frameworks/HIServices.framework/HIServices", RTLD_LAZY | RTLD_LOCAL)
    private static let hitoolbox = dlopen("/System/Library/Frameworks/Carbon.framework/Frameworks/HIToolbox.framework/HIToolbox", RTLD_LAZY | RTLD_LOCAL)
    private static let location: SetLocation? = graphics.flatMap { dlsym($0, "CGEventSetWindowLocation") }
        .map { unsafeBitCast($0, to: SetLocation.self) }
    private static let window: GetWindow? = accessibility.flatMap { dlsym($0, "_AXUIElementGetWindow") }
        .map { unsafeBitCast($0, to: GetWindow.self) }
    private static let secureInput: SecureInputEnabled? = hitoolbox.flatMap { dlsym($0, "IsSecureEventInputEnabled") }
        .map { unsafeBitCast($0, to: SecureInputEnabled.self) }
    static var disabled: Bool { ProcessInfo.processInfo.environment["MEMSTACK_CUA_DISABLE_BACKGROUND_INPUT"] == "1" }
    private static var spiAvailable: Bool { !disabled && location != nil && window != nil && secureInput != nil && NSEvent.EventType(rawValue: 21) != nil }
    static var available: Bool { spiAvailable && focusGuardAvailable }
    static func requireAvailable() throws {
        // A previous event-tap failure remains visible in capabilities, but a
        // new lease can retry after the user restores native permissions.
        guard spiAvailable else {
            throw ActionError.failure(kind: "background_input_unavailable",
                message: disabled ? "background input is disabled by the host" : "this macOS runtime lacks targeted window input support")
        }
    }
    static func requireSafeInput() throws {
        try requireAvailable()
        guard secureInput?() == false else {
            throw ActionError.failure(kind: "secure_input_active", message: "background input is unavailable while Secure Event Input is active")
        }
    }
    static func setWindowLocation(_ event: CGEvent, _ point: CGPoint) throws {
        guard let location = location else { try requireAvailable(); return }
        location(event, point)
    }
    static func setTargetWindow(_ event: CGEvent, _ window: CGWindowID) {
        // AppKit's NSEvent.windowNumber is stored separately from the public
        // window-under-pointer fields. This field is verified by round-tripping
        // an NSEvent.mouseEvent with a known window number through CGEvent.
        event.setIntegerValueField(CGEventField(rawValue: 51)!, value: Int64(window))
    }
    static func windowID(_ element: AXUIElement) -> CGWindowID? {
        var id: CGWindowID = 0
        guard let window = window, window(element, &id) == .success, id != 0 else { return nil }
        return id
    }
    static var support: [String: Any] {
        ["background": ["supported": available,
            "global_button_state_emulation": false,
            "global_activation_suppression": false,
            "drag_button_state": "event_owned_only", "reason": available ? NSNull()
            : (disabled ? "background_input_disabled" : !focusGuardAvailable
                ? "background_focus_guard_unavailable" : "window_input_spi_unavailable") as Any],
         "foreground": ["supported": true, "reason": NSNull()]]
    }
}

enum InputWindowVisibility {
    static func frontWindow(at point: CGPoint) -> (pid: Int32, window: UInt32)? {
        guard point.x.isFinite, point.y.isFinite else { return nil }
        // WindowServer rectangles include transparent system overlays. Native
        // accessibility hit-testing follows the actual interactive surface,
        // including a visible Dock/menu or another window of the same app.
        let system = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(system, 0.05)
        var element: AXUIElement?
        guard AXUIElementCopyElementAtPosition(system, Float(point.x), Float(point.y), &element) == .success,
              let element = element else { return nil }
        AXUIElementSetMessagingTimeout(element, 0.05)
        var pid: pid_t = 0
        guard AXUIElementGetPid(element, &pid) == .success, pid > 0,
              let window = BackgroundInputSPI.windowID(element) else { return nil }
        return (pid, window)
    }
    static func visible(_ route: InputRoute, at point: CGPoint) -> Bool {
        guard let front = frontWindow(at: point) else { return false }
        return front.pid == route.pid && front.window == route.window
    }
}

enum SyntheticFocus {
    static func activationPoint(_ window: AXUIElement) -> CGPoint? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(window, "AXActivationPoint" as CFString, &value) == .success,
              let value = value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
        var point = CGPoint.zero
        guard AXValueGetValue(value as! AXValue, .cgPoint, &point) else { return nil }
        return point
    }
    private static func notification(_ type: UInt, subtype: UInt16, window: UInt32, flags: UInt64,
                                     route: InputRoute, tag: Int64) throws {
        guard let eventType = NSEvent.EventType(rawValue: type),
              let event = NSEvent.otherEvent(with: eventType, location: .zero,
                  modifierFlags: NSEvent.ModifierFlags(rawValue: UInt(flags)), timestamp: 0,
                  windowNumber: Int(window), context: nil, subtype: Int16(bitPattern: subtype),
                  data1: 0, data2: 0)?.cgEvent else {
            throw ActionError.failure(kind: "background_input_unavailable", message: "cannot create a targeted focus notification")
        }
        event.setIntegerValueField(.eventSourceUserData, value: tag)
        try route.post(event, bindWindow: false)
    }
    static func activate(_ route: InputRoute, tag: Int64) throws {
        guard route.mode == .background else { return }
        // Application-local activation and key-focus notifications do not call
        // NSRunningApplication.activate, AXRaise, or change global key focus.
        try notification(13, subtype: 1, window: route.window, flags: 0xc0000, route: route, tag: tag)
    }
    static func returnFocus(_ route: InputRoute, tag: Int64) throws {
        guard route.mode == .background else { return }
        try notification(21, subtype: 0x8000, window: 0, flags: 0, route: route, tag: tag)
    }
    static func deactivate(_ route: InputRoute, tag: Int64) {
        guard route.mode == .background,
              NSWorkspace.shared.frontmostApplication?.processIdentifier != route.pid else { return }
        try? notification(21, subtype: 0x4000, window: 0, flags: 0, route: route, tag: tag)
        try? notification(13, subtype: 2, window: 0, flags: 0, route: route, tag: tag)
    }
}
