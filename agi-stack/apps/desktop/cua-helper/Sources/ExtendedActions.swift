import AppKit
import ApplicationServices

/// Held input is session owned; SyntheticInput also supervises crash recovery.
final class HeldInput {
    static let shared = HeldInput()
    private let lock = NSLock()
    private var keys: [String: [CGKeyCode: CGEventFlags]] = [:]
    private var drags: [String: CGPoint] = [:]
    func key(sessionID: String, name: String, code: CGKeyCode, flags: CGEventFlags, down: Bool) throws {
        lock.lock(); defer { lock.unlock() }
        guard !keys.contains(where: { $0.key != sessionID && !$0.value.isEmpty }) else {
            throw ActionError.failure(kind: "input_busy", message: "another session owns held input")
        }
        var next = keys[sessionID] ?? [:]
        if down {
            guard keys[sessionID]?[code] == nil else {
                throw ActionError.failure(kind: "invalid_params", message: "this key is already held")
            }
            next[code] = flags
        } else {
            guard next.removeValue(forKey: code) != nil else {
                throw ActionError.failure(kind: "invalid_params", message: "this session does not own the held key")
            }
        }
        let heldFlags = next.values.reduce(CGEventFlags()) { $0.union($1) }
        guard let event = CGEvent(keyboardEventSource: SyntheticInput.shared.source, virtualKey: code, keyDown: down) else {
            throw ActionError.failure(kind: "input_error", message: "cannot create keyboard event")
        }
        event.flags = heldFlags
        try SyntheticInput.shared.post(event, keyDown: down, ownedFlags: flags)
        keys[sessionID] = next
    }
    func drag(sessionID: String, phase: String, point: CGPoint) throws {
        lock.lock(); defer { lock.unlock() }
        if phase != "begin" && drags[sessionID] == nil {
            throw ActionError.failure(kind: "invalid_params", message: "begin the drag first")
        }
        if phase == "begin" && (!drags.isEmpty) {
            throw ActionError.failure(kind: "input_busy", message: "another drag is still active")
        }
        let type: CGEventType = phase == "begin" ? .leftMouseDown : phase == "end" ? .leftMouseUp : .leftMouseDragged
        guard let event = CGEvent(mouseEventSource: SyntheticInput.shared.source, mouseType: type, mouseCursorPosition: point, mouseButton: .left) else {
            throw ActionError.failure(kind: "input_error", message: "cannot create drag event")
        }
        try SyntheticInput.shared.post(event)
        if phase == "end" { drags[sessionID] = nil } else { drags[sessionID] = point }
    }
    func release(_ id: String) {
        lock.lock(); defer { lock.unlock() }
        for (code, _) in keys.removeValue(forKey: id) ?? [:] {
            let event = CGEvent(keyboardEventSource: SyntheticInput.shared.source, virtualKey: code, keyDown: false)
            event?.flags = []
            SyntheticInput.shared.release(event)
        }
        if let point = drags.removeValue(forKey: id) {
            SyntheticInput.shared.release(CGEvent(mouseEventSource: SyntheticInput.shared.source, mouseType: .leftMouseUp,
                mouseCursorPosition: point, mouseButton: .left))
        }
    }
    func releaseAll() {
        lock.lock(); let ids = Set(keys.keys).union(drags.keys); lock.unlock()
        ids.forEach(release)
    }
}

extension Actions {
    static func extended(_ kind: String, action: [String: Any], app: ResolvedApp) throws {
        try checkpoint()
        guard let session = session, let snapshot = snapshot else { return }
        switch kind {
        case "key_down", "key_up":
            guard let key = action["key"] as? String, let code = Keycodes.keycode(for: key) else {
                throw ActionError.failure(kind: "invalid_params", message: "a supported key name is required")
            }
            try HeldInput.shared.key(sessionID: session.id, name: key, code: code,
                flags: modifierFlag(key.lowercased()) ?? [], down: kind == "key_down")
        case "move", "drag_step":
            guard let x = action["x"] as? Double, let y = action["y"] as? Double else {
                throw ActionError.failure(kind: "invalid_params", message: "x and y are required")
            }
            try validatePoint(x, y)
            let point = CGPoint(x: snapshot.window.frame.minX + x, y: snapshot.window.frame.minY + y)
            if kind == "move" {
                if let move = CGEvent(mouseEventSource: SyntheticInput.shared.source, mouseType: .mouseMoved,
                    mouseCursorPosition: point, mouseButton: .left) { try SyntheticInput.shared.post(move) }
            } else {
                guard let phase = action["phase"] as? String, ["begin", "move", "end"].contains(phase) else {
                    throw ActionError.failure(kind: "invalid_params", message: "drag phase must be begin, move, or end")
                }
                try HeldInput.shared.drag(sessionID: session.id, phase: phase, point: point)
            }
        case "select_text":
            guard let index = action["element_index"] as? Int,
                  let record = snapshot.records[index], let text = action["text"] as? String, !text.isEmpty,
                  let value = AxEngine.copyString(record.axElement, kAXValueAttribute as String) else {
                throw ActionError.failure(kind: "invalid_params", message: "select_text requires a text element and text")
            }
            let range = try selectionRange(value: value, text: text,
                prefix: action["prefix"] as? String, suffix: action["suffix"] as? String,
                cursor: action["cursor"] as? String ?? "select")
            var cfRange = CFRange(location: range.location, length: range.length)
            guard let selection = AXValueCreate(.cfRange, &cfRange),
                  AXUIElementSetAttributeValue(record.axElement, kAXSelectedTextRangeAttribute as CFString,
                                               selection) == .success else {
                throw ActionError.failure(kind: "unsupported", message: "this control does not expose text selection")
            }
        default: throw ActionError.failure(kind: "invalid_params", message: "unknown extended action")
        }
    }

    static func selectionRange(value: String, text: String, prefix: String?, suffix: String?, cursor: String) throws -> NSRange {
        guard ["select", "before", "after"].contains(cursor) else {
            throw ActionError.failure(kind: "invalid_params", message: "cursor must be select, before, or after")
        }
        let content = value as NSString
        var matches: [NSRange] = []
        var offset = 0
        while offset < content.length {
            let found = content.range(of: text, options: [],
                range: NSRange(location: offset, length: content.length - offset))
            if found.location == NSNotFound { break }
            let before = content.substring(to: found.location)
            let after = content.substring(from: found.location + found.length)
            if (prefix == nil || before.hasSuffix(prefix!)) && (suffix == nil || after.hasPrefix(suffix!)) {
                matches.append(found)
            }
            offset = found.location + max(1, found.length)
        }
        guard matches.count == 1, let found = matches.first else {
            throw ActionError.failure(kind: "ambiguous_text", message: "text must identify exactly one range")
        }
        return NSRange(location: cursor == "after" ? found.location + found.length : found.location,
                       length: cursor == "select" ? found.length : 0)
    }
}
