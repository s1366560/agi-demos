import AppKit
import Carbon
import CoreGraphics
import Foundation

/// Test-only input-source controller and external native-key simulation.
/// Every mutation is restricted to the disposable foreground guard. This is
/// not evidence of a human physical keyboard; the IME itself remains real.
@main
enum KeyboardInputProbe {
    static func property(_ input: TISInputSource, _ key: CFString) -> AnyObject? {
        guard let raw = TISGetInputSourceProperty(input, key) else { return nil }
        return Unmanaged<AnyObject>.fromOpaque(raw).takeUnretainedValue()
    }

    static func describe(_ input: TISInputSource) -> [String: Any] {
        ["id": property(input, kTISPropertyInputSourceID) as? String ?? "unavailable",
         "name": property(input, kTISPropertyLocalizedName) as? String ?? "unavailable",
         "type": property(input, kTISPropertyInputSourceType) as? String ?? "unavailable",
         "enabled": property(input, kTISPropertyInputSourceIsEnabled) as? Bool ?? false,
         "selected": property(input, kTISPropertyInputSourceIsSelected) as? Bool ?? false,
         "selectable": property(input, kTISPropertyInputSourceIsSelectCapable) as? Bool ?? false]
    }

    static func snapshot() -> [String: Any] {
        var result: [String: Any] = [:]
        if let input = TISCopyCurrentKeyboardInputSource()?.takeRetainedValue() {
            result["input_source"] = describe(input)
        }
        if let layout = TISCopyCurrentKeyboardLayoutInputSource()?.takeRetainedValue() {
            result["keyboard_layout"] = describe(layout)
        }
        return result
    }

    static func write(_ value: [String: Any]) {
        if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
            FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
        }
    }

    static func guardOwnsFocus(_ pid: pid_t) -> Bool {
        NSWorkspace.shared.frontmostApplication?.processIdentifier == pid
            && NSRunningApplication(processIdentifier: pid)?.bundleIdentifier
                == "ai.memstack.cua.guard-fixture"
    }

    static func main() {
        let arguments = CommandLine.arguments
        guard let sources = TISCreateInputSourceList(nil, true)?.takeRetainedValue() as? [TISInputSource] else {
            exit(2)
        }
        if arguments.count == 2, arguments[1] == "--inventory" {
            write(["current": snapshot(), "sources": sources.map(describe)])
            return
        }
        guard arguments.count == 5, arguments[1] == "--allow-own-fixture-input",
              let pid = Int32(arguments[2]), guardOwnsFocus(pid),
              arguments[3] == "--source",
              let original = TISCopyCurrentKeyboardInputSource()?.takeRetainedValue(),
              let selected = sources.first(where: {
                  property($0, kTISPropertyInputSourceID) as? String == arguments[4]
              }),
              property(selected, kTISPropertyInputSourceIsSelectCapable) as? Bool == true else {
            write(["error": "Expected --allow-own-fixture-input GUARD_PID --source INPUT_SOURCE_ID"])
            exit(2)
        }
        let initiallyEnabled = property(selected, kTISPropertyInputSourceIsEnabled) as? Bool == true
        if !initiallyEnabled, TISEnableInputSource(selected) != noErr {
            write(["error": "input_source_enable_failed"]); exit(3)
        }
        defer {
            let restored = TISSelectInputSource(original)
            let disabled = initiallyEnabled ? noErr : TISDisableInputSource(selected)
            write(["restored": restored == noErr, "disabled_temporary_source": disabled == noErr,
                   "current": snapshot()])
        }
        guard TISSelectInputSource(selected) == noErr else {
            write(["error": "input_source_selection_failed"]); return
        }
        write(["ready": true, "original": describe(original), "current": snapshot()])
        while let line = readLine() {
            guard let data = line.data(using: .utf8),
                  let command = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let operation = command["operation"] as? String else {
                write(["error": "invalid_command"]); continue
            }
            if operation == "restore" { return }
            if operation == "snapshot" { write(snapshot()); continue }
            guard operation == "keys", guardOwnsFocus(pid),
                  let codes = command["key_codes"] as? [UInt16], !codes.isEmpty,
                  codes.allSatisfy({ $0 <= 126 }),
                  let source = CGEventSource(stateID: .hidSystemState) else {
                write(["error": "owned_guard_not_frontmost_or_invalid_keys"]); continue
            }
            source.userData = -92
            let flags = CGEventFlags(rawValue: (command["flags"] as? UInt64) ?? 0)
            var sent = 0
            for code in codes {
                guard guardOwnsFocus(pid), !CGEventSource.keyState(.hidSystemState, key: code),
                      let down = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true),
                      let up = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false) else { break }
                down.flags = flags; up.flags = flags
                down.setIntegerValueField(.eventSourceUserData, value: -92)
                up.setIntegerValueField(.eventSourceUserData, value: -92)
                down.post(tap: .cghidEventTap)
                usleep(10_000)
                up.post(tap: .cghidEventTap)
                usleep(90_000)
                sent += 1
            }
            write(["sent": sent, "current": snapshot()])
        }
    }
}
