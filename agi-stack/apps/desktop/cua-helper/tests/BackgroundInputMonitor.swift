import AppKit
import CoreGraphics

/// Independent observer for the fixture test. It never posts input or changes focus.
@main
enum BackgroundInputMonitor {
    static func state() -> [String: Any] {
        let point = CGEvent(source: nil)?.location ?? .zero
        // Compare modifier state, including left/right device bits. WindowServer
        // may add high transport/provenance bits after an explicit test injection.
        let modifierMask: UInt64 = 0x00ff_ffff & ~CGEventFlags.maskNonCoalesced.rawValue
        return [
            "frontmost_pid": NSWorkspace.shared.frontmostApplication?.processIdentifier ?? -1,
            "x": point.x, "y": point.y,
            "hid_flags": CGEventSource.flagsState(.hidSystemState).rawValue & modifierMask,
            "combined_flags": CGEventSource.flagsState(.combinedSessionState).rawValue & modifierMask,
            "left": CGEventSource.buttonState(.hidSystemState, button: .left),
            "right": CGEventSource.buttonState(.hidSystemState, button: .right),
            "middle": CGEventSource.buttonState(.hidSystemState, button: .center),
            "combined_left": CGEventSource.buttonState(.combinedSessionState, button: .left),
            "combined_right": CGEventSource.buttonState(.combinedSessionState, button: .right),
            "combined_middle": CGEventSource.buttonState(.combinedSessionState, button: .center),
            "held_key_codes": (UInt16(0)...127).filter {
                CGEventSource.keyState(.hidSystemState, key: $0)
            },
            "shift": CGEventSource.keyState(.hidSystemState, key: 56),
            "command": CGEventSource.keyState(.hidSystemState, key: 55),
            "option": CGEventSource.keyState(.hidSystemState, key: 58),
            "control": CGEventSource.keyState(.hidSystemState, key: 59),
        ]
    }
    static func main() {
        if CommandLine.arguments.count == 4, CommandLine.arguments[1] == "--windows-at",
           let x = Double(CommandLine.arguments[2]), let y = Double(CommandLine.arguments[3]) {
            let point = CGPoint(x: x, y: y)
            let windows = (CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                kCGNullWindowID) as? [[String: Any]] ?? []).compactMap { window -> [String: Any]? in
                    guard let raw = window[kCGWindowBounds as String] as? [String: Any],
                          let bounds = CGRect(dictionaryRepresentation: raw as CFDictionary),
                          bounds.contains(point) else { return nil }
                    return ["pid": window[kCGWindowOwnerPID as String] ?? 0,
                        "window": window[kCGWindowNumber as String] ?? 0,
                        "x": bounds.minX, "y": bounds.minY, "width": bounds.width,
                        "height": bounds.height, "layer": window[kCGWindowLayer as String] ?? 0]
                }
            if let bytes = try? JSONSerialization.data(withJSONObject: windows) {
                FileHandle.standardOutput.write(bytes); FileHandle.standardOutput.write(Data([10]))
            }
            return
        }
        if CommandLine.arguments.count == 3, CommandLine.arguments[1] == "--visible-windows",
           let pid = Int32(CommandLine.arguments[2]) {
            let windows = (CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                kCGNullWindowID) as? [[String: Any]] ?? []).filter {
                    ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid
                }.compactMap { window -> [String: Any]? in
                    guard let raw = window[kCGWindowBounds as String] as? [String: Any],
                          let bounds = CGRect(dictionaryRepresentation: raw as CFDictionary) else { return nil }
                    return ["x": bounds.minX, "y": bounds.minY, "width": bounds.width,
                        "height": bounds.height, "layer": window[kCGWindowLayer as String] ?? 0]
                }
            if let bytes = try? JSONSerialization.data(withJSONObject: windows) {
                FileHandle.standardOutput.write(bytes); FileHandle.standardOutput.write(Data([10]))
            }
            return
        }
        if CommandLine.arguments.contains("--snapshot") {
            if let bytes = try? JSONSerialization.data(withJSONObject: state(), options: .sortedKeys) {
                FileHandle.standardOutput.write(bytes); FileHandle.standardOutput.write(Data([10]))
            }
            return
        }
        var previous: Data?
        func sample() {
            guard let bytes = try? JSONSerialization.data(withJSONObject: state(), options: .sortedKeys),
                  bytes != previous else { return }
            previous = bytes
            FileHandle.standardOutput.write(bytes); FileHandle.standardOutput.write(Data([10]))
        }
        sample()
        let timer = Timer.scheduledTimer(withTimeInterval: 0.005, repeats: true) { _ in
            MainActor.assumeIsolated { sample() }
        }
        RunLoop.main.add(timer, forMode: .common)
        RunLoop.main.run()
    }
}
