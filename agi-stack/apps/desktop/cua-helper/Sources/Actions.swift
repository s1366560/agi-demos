// Actions.swift — input synthesis and AX-side mutations. Element-first like the
// reference client: element_index targets come from the latest app state;
// coordinates are window-relative fallbacks (docs/cua/ analysis section 3.1).

import AppKit
import ApplicationServices
import CoreGraphics

enum ActionError: Error {
    case failure(kind: String, message: String, extra: [String: Any] = [:])
}

enum Actions {
    static var session: NativeSession?
    static var snapshot: Snapshot?

    static func checkpoint() throws {
        guard let session = session, let snapshot = snapshot else {
            throw ActionError.failure(kind: "stale_element", message: "a current snapshot is required")
        }
        try session.cancellation.check()
        try NativeScreenState.requireUnlocked()
        guard snapshot.inputGeneration == session.inputGeneration else {
            throw ActionError.failure(kind: "stale_input_generation", message: "observe the target after resuming input")
        }
        if session.inputMode == .foreground { try TargetPolicy.requireFocused(snapshot.app, window: snapshot.window) }
        try SyntheticInput.shared.bind(session, app: snapshot.app, window: snapshot.window)
        try session.cancellation.check()
        try NativeScreenState.requireUnlocked()
        if session.inputMode == .foreground { try TargetPolicy.requireFocused(snapshot.app, window: snapshot.window) }
    }
    static func wait(_ seconds: Double) throws {
        let deadline = Date().addingTimeInterval(seconds)
        repeat {
            try checkpoint()
            Thread.sleep(forTimeInterval: min(0.02, max(0, deadline.timeIntervalSinceNow)))
        } while Date() < deadline
    }
    static func validatePoint(_ x: Double, _ y: Double) throws {
        guard let window = snapshot?.window, x.isFinite, y.isFinite,
              x >= 0, y >= 0, x <= window.frame.width, y <= window.frame.height else {
            throw ActionError.failure(kind: "invalid_params", message: "coordinates must lie inside the observed window")
        }
    }

    /// Post-action settle wait so the next observation is fresh, mirroring the
    /// reference runtime (~1 s, extended while loading indicators are visible).
    static let defaultSettleSeconds: Double = 1.0

    static func click(app: ResolvedApp, elementIndex: Int?, x: Double?, y: Double?, button: String, clickCount: Int, keyChord: String?, duration: Double?) throws {
        try checkpoint()
        let point = try resolveTarget(app: app, elementIndex: elementIndex, x: x, y: y)
        guard ["left", "right", "middle"].contains(button), (1...3).contains(clickCount),
              duration == nil || (duration!.isFinite && duration! >= 0 && duration! <= 5) else {
            throw ActionError.failure(kind: "invalid_params", message: "invalid mouse button, count, or duration")
        }
        let mask = try chordFlags(keyChord)
        let (downType, upType, cgButton) = mouseTypes(button)
        let hold = min(max(duration ?? 0, 0), 5.0)
        if let move = CGEvent(mouseEventSource: SyntheticInput.shared.source, mouseType: .mouseMoved,
            mouseCursorPosition: point, mouseButton: cgButton) {
            try SyntheticInput.shared.post(move)
            try wait(0.05)
        }
        var mouseDown = false
        func post(_ type: CGEventType, _ state: Int64) throws {
            guard let event = CGEvent(mouseEventSource: SyntheticInput.shared.source, mouseType: type, mouseCursorPosition: point, mouseButton: cgButton) else {
                throw ActionError.failure(kind: "input_error", message: "cannot create mouse event")
            }
            event.setIntegerValueField(.mouseEventClickState, value: state)
            event.flags = mask
            try SyntheticInput.shared.post(event)
        }

        defer { if mouseDown { try? post(upType, 1) } }
        for count in 1...clickCount {
            try checkpoint()
            try post(downType, Int64(count)); mouseDown = true
            if hold > 0 { try wait(hold) }
            try post(upType, Int64(count)); mouseDown = false
            if count < clickCount { try wait(0.12) }
        }
    }

    static func drag(app: ResolvedApp, fromX: Double, fromY: Double, toX: Double, toY: Double) throws {
        try checkpoint()
        try validatePoint(fromX, fromY); try validatePoint(toX, toY)
        let windowOrigin = try frontWindowOrigin(app: app)
        let from = CGPoint(x: windowOrigin.x + fromX, y: windowOrigin.y + fromY)
        let to = CGPoint(x: windowOrigin.x + toX, y: windowOrigin.y + toY)

        guard let down = CGEvent(mouseEventSource: SyntheticInput.shared.source, mouseType: .leftMouseDown, mouseCursorPosition: from, mouseButton: .left) else {
            throw ActionError.failure(kind: "input_error", message: "cannot create mouse event")
        }
        var mouseDown = false
        defer {
            if mouseDown, let up = CGEvent(mouseEventSource: SyntheticInput.shared.source, mouseType: .leftMouseUp,
                                           mouseCursorPosition: to, mouseButton: .left) {
                SyntheticInput.shared.release(up)
            }
        }
        try SyntheticInput.shared.post(down)
        mouseDown = true
        try wait(0.05)
        let steps = 12
        for step in 1...steps {
            let t = Double(step) / Double(steps)
            let point = CGPoint(
                x: from.x + (to.x - from.x) * t,
                y: from.y + (to.y - from.y) * t
            )
            guard let move = CGEvent(mouseEventSource: SyntheticInput.shared.source, mouseType: .leftMouseDragged, mouseCursorPosition: point, mouseButton: .left) else { continue }
            try SyntheticInput.shared.post(move)
            try wait(0.016)
        }
        guard let up = CGEvent(mouseEventSource: SyntheticInput.shared.source, mouseType: .leftMouseUp, mouseCursorPosition: to, mouseButton: .left) else {
            throw ActionError.failure(kind: "input_error", message: "cannot create mouse event")
        }
        try SyntheticInput.shared.post(up)
        mouseDown = false
    }

    static func typeText(_ text: String) throws {
        guard !text.isEmpty else { return }
        guard text.utf8.count <= 1_000_000 else {
            throw ActionError.failure(kind: "invalid_params", message: "text exceeds the input budget")
        }
        for character in text {
            try checkpoint()
            let utf16 = Array(String(character).utf16)
            guard let down = CGEvent(keyboardEventSource: SyntheticInput.shared.source, virtualKey: 0, keyDown: true),
                  let up = CGEvent(keyboardEventSource: SyntheticInput.shared.source, virtualKey: 0, keyDown: false) else {
                throw ActionError.failure(kind: "input_error", message: "cannot create keyboard event")
            }
            down.keyboardSetUnicodeString(stringLength: utf16.count, unicodeString: utf16)
            up.keyboardSetUnicodeString(stringLength: utf16.count, unicodeString: utf16)
            // Unicode insertion is literal. A prior chord must not leave its
            // Command/Control flags on characters and turn them into shortcuts.
            down.flags = []; up.flags = []
            try SyntheticInput.shared.post(down, ownedFlags: [], literalText: true)
            defer { SyntheticInput.shared.release(up) }
            try SyntheticInput.shared.post(up)
            try wait(0.008)
        }
    }

    /// xdotool-style chord: "a", "Return", "ctrl+shift+t", "super+c", "KP_0".
    static func pressKey(_ chord: String, duration: Double?) throws {
        try checkpoint()
        guard duration == nil || (duration!.isFinite && duration! >= 0 && duration! <= 5) else {
            throw ActionError.failure(kind: "invalid_params", message: "duration must be between zero and five seconds")
        }
        let parts = chord.split(separator: "+", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        guard let keyName = parts.last else {
            throw ActionError.failure(kind: "invalid_params", message: "key is required")
        }
        let modifiers = parts.dropLast()
        var flags: CGEventFlags = []
        for modifier in modifiers {
            guard let mask = modifierFlag(modifier.lowercased()) else {
                throw ActionError.failure(kind: "invalid_params", message: "unknown modifier '\(modifier)'")
            }
            flags.insert(mask)
        }
        guard let code = Keycodes.keycode(for: keyName) else {
            throw ActionError.failure(kind: "invalid_params", message: "unknown key '\(keyName)'")
        }
        if let modifier = modifierFlag(keyName.lowercased()) { flags.insert(modifier) }
        let hold = min(max(duration ?? 0, 0), 5.0)
        guard let down = CGEvent(keyboardEventSource: SyntheticInput.shared.source, virtualKey: code, keyDown: true),
              let up = CGEvent(keyboardEventSource: SyntheticInput.shared.source, virtualKey: code, keyDown: false) else {
            throw ActionError.failure(kind: "input_error", message: "cannot create keyboard event")
        }
        down.flags = flags
        up.flags = flags
        try SyntheticInput.shared.post(down, keyDown: true, ownedFlags: flags)
        defer { SyntheticInput.shared.release(up) }
        if hold > 0 { try wait(hold) }
    }

    static func scroll(elementIndex: Int?, x: Double?, y: Double?, app: ResolvedApp, direction: String, pages: Double) throws {
        try checkpoint()
        guard pages.isFinite, pages > 0, pages <= 50,
              ["up", "down", "left", "right"].contains(direction) else {
            throw ActionError.failure(kind: "invalid_params", message: "invalid scroll direction or pages")
        }
        let point: CGPoint
        if let index = elementIndex {
            let record = try requireElement(app: app, index: index)
            point = CGPoint(x: record.frame.midX, y: record.frame.midY)
        } else if let x = x, let y = y {
            try validatePoint(x, y)
            let origin = try frontWindowOrigin(app: app)
            point = CGPoint(x: origin.x + x, y: origin.y + y)
        } else {
            guard let window = snapshot?.window else {
                throw ActionError.failure(kind: "stale_element", message: "refresh the observed window")
            }
            point = CGPoint(x: window.frame.midX, y: window.frame.midY)
        }
        // Move the pointer to the scroll target first so the event lands there.
        if let move = CGEvent(mouseEventSource: SyntheticInput.shared.source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left) {
            try SyntheticInput.shared.post(move)
            try wait(0.03)
        }
        let normalized = direction
        let linesPerPage = 20.0
        let magnitude = Int32(max(1, pages * linesPerPage))
        var wheel1: Int32 = 0   // vertical: positive scrolls up
        var wheel2: Int32 = 0   // horizontal: positive scrolls right
        switch normalized {
        case "up": wheel1 = magnitude
        case "down": wheel1 = -magnitude
        case "left": wheel2 = -magnitude
        case "right": wheel2 = magnitude
        default:
            throw ActionError.failure(kind: "invalid_params", message: "direction must be up, down, left, or right")
        }
        guard let event = CGEvent(scrollWheelEvent2Source: SyntheticInput.shared.source, units: .line, wheelCount: 2, wheel1: wheel1, wheel2: wheel2, wheel3: 0) else {
            throw ActionError.failure(kind: "input_error", message: "cannot create scroll event")
        }
        // Targeted background motion deliberately leaves the physical pointer
        // unchanged, so a new wheel event must carry the selected location.
        event.location = point
        try SyntheticInput.shared.post(event)
    }

    static func setValue(app: ResolvedApp, elementIndex: Int, value: String) throws {
        let record = try requireElement(app: app, index: elementIndex)
        let result = AXUIElementSetAttributeValue(record.axElement, kAXValueAttribute as CFString, value as CFTypeRef)
        guard result == .success else {
            throw ActionError.failure(
                kind: "ax_error",
                message: "set_value failed (code \(result.rawValue)); element may not be editable",
                extra: ["ax_code": result.rawValue]
            )
        }
    }

    static func secondaryAction(app: ResolvedApp, elementIndex: Int, action: String) throws {
        let record = try requireElement(app: app, index: elementIndex)
        let match = record.actions.first {
            $0.caseInsensitiveCompare(action) == .orderedSame
        }
        guard let actionName = match else {
            throw ActionError.failure(
                kind: "invalid_params",
                message: "element \(elementIndex) does not expose action '\(action)'",
                extra: ["available_actions": record.actions]
            )
        }
        let result = AXUIElementPerformAction(record.axElement, actionName as CFString)
        guard result == .success else {
            throw ActionError.failure(kind: "ax_error", message: "perform action failed (code \(result.rawValue))")
        }
    }

    /// Pasteboard paste with prior-contents restore, matching the reference
    /// paste contract (text/md/html; restore previous clipboard contents).
    static func paste(app: ResolvedApp, text: String, format: String) throws {
        try checkpoint()
        guard ["text", "md", "html"].contains(format) else {
            throw ActionError.failure(kind: "invalid_params", message: "format must be text, md, or html")
        }
        guard let session = session else { throw ClipboardFiles.failure("clipboard_unavailable") }
        let result = try NativeClipboard.write(text: text, format: format, session: session)
        guard let handle = result["handle"] as? String else { throw ClipboardFiles.failure("clipboard_unavailable") }
        defer { _ = try? NativeClipboard.release(handle: handle, sessionID: session.id) }
        try wait(0.05)
        try pressKey("super+v", duration: nil)
        try wait(0.4)
    }

    // MARK: target resolution

    private static func requireElement(app: ResolvedApp, index: Int) throws -> ElementRecord {
        try checkpoint()
        guard let record = snapshot?.records[index] else {
            throw ActionError.failure(
                kind: "stale_element",
                message: "element index \(index) is not valid; call get_app_state to refresh"
            )
        }
        var pid: pid_t = 0
        guard AXUIElementGetPid(record.axElement, &pid) == .success, pid == app.pid,
              AxEngine.copyString(record.axElement, kAXRoleAttribute as String) != nil else {
            throw ActionError.failure(kind: "stale_element", message: "element no longer belongs to the target process")
        }
        return record
    }

    private static func resolveTarget(app: ResolvedApp, elementIndex: Int?, x: Double?, y: Double?) throws -> CGPoint {
        if let index = elementIndex {
            let record = try requireElement(app: app, index: index)
            return CGPoint(x: record.frame.midX, y: record.frame.midY)
        }
        guard let x = x, let y = y else {
            throw ActionError.failure(kind: "invalid_params", message: "click requires element_index or x/y")
        }
        try validatePoint(x, y)
        let origin = try frontWindowOrigin(app: app)
        return CGPoint(x: origin.x + x, y: origin.y + y)
    }

    private static func frontWindowOrigin(app: ResolvedApp) throws -> CGPoint {
        guard let window = snapshot?.window, snapshot?.app.pid == app.pid else {
            throw ActionError.failure(kind: "stale_element", message: "refresh the observed window")
        }
        return window.frame.origin
    }

    private static func mouseTypes(_ button: String) -> (CGEventType, CGEventType, CGMouseButton) {
        switch button.lowercased() {
        case "r", "right": return (.rightMouseDown, .rightMouseUp, .right)
        case "m", "middle": return (.otherMouseDown, .otherMouseUp, .center)
        default: return (.leftMouseDown, .leftMouseUp, .left)
        }
    }

    private static func chordFlags(_ chord: String?) throws -> CGEventFlags {
        guard let chord = chord, !chord.isEmpty else { return [] }
        var flags: CGEventFlags = []
        for part in chord.split(separator: "+") {
            guard let mask = modifierFlag(part.trimmingCharacters(in: .whitespaces).lowercased()) else {
                throw ActionError.failure(kind: "invalid_params", message: "unknown modifier '\(part)'")
            }
            flags.insert(mask)
        }
        return flags
    }

    static func modifierFlag(_ name: String) -> CGEventFlags? {
        switch name {
        case "super", "cmd", "command", "meta": return .maskCommand
        case "ctrl", "control": return .maskControl
        case "alt", "option": return .maskAlternate
        case "shift": return .maskShift
        case "fn": return .maskSecondaryFn
        default: return nil
        }
    }
}

/// Virtual-key codes (HID usage values). xdotool-style names; `super` = Command.
enum Keycodes {
    static let map: [String: UInt16] = [
        "ctrl": 0x3B, "control": 0x3B, "shift": 0x38, "alt": 0x3A, "option": 0x3A,
        "super": 0x37, "cmd": 0x37, "command": 0x37, "fn": 0x3F,
        "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06,
        "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E,
        "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
        "6": 0x16, "5": 0x17, "=": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C,
        "0": 0x1D, "]": 0x1E, "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23,
        "l": 0x25, "j": 0x26, "'": 0x27, "k": 0x28, ";": 0x29, "\\": 0x2A, ",": 0x2B,
        "/": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F, "`": 0x32, "space": 0x31,
        "return": 0x24, "enter": 0x24, "tab": 0x30, "escape": 0x35, "delete": 0x33,
        "backspace": 0x33, "forwarddelete": 0x75, "home": 0x73, "end": 0x77,
        "pageup": 0x74, "pagedown": 0x79, "up": 0x7E, "down": 0x7D, "left": 0x7B,
        "right": 0x7C, "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60,
        "f6": 0x61, "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67,
        "f12": 0x6F, "kp_0": 0x52, "kp_1": 0x53, "kp_2": 0x54, "kp_3": 0x55,
        "kp_4": 0x56, "kp_5": 0x57, "kp_6": 0x58, "kp_7": 0x59, "kp_8": 0x5B,
        "kp_9": 0x5C, "kp_enter": 0x4C,
    ]

    static func keycode(for name: String) -> UInt16? {
        map[name.lowercased()]
    }
}
