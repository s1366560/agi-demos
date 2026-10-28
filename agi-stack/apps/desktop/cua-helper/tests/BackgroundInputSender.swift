import AppKit
import Carbon
import CoreGraphics

/// An explicit external-input simulation for the disposable foreground guard.
/// It does not stand in for real physical-keyboard acceptance.
@main
enum BackgroundInputSender {
    static func main() {
        guard (2...3).contains(CommandLine.arguments.count),
              let pid = Int32(CommandLine.arguments[1]),
              NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,
              NSRunningApplication(processIdentifier: pid)?.bundleIdentifier == "ai.memstack.cua.guard-fixture",
              !CGEventSource.keyState(.hidSystemState, key: 56),
              let source = CGEventSource(stateID: .hidSystemState),
              let down = CGEvent(keyboardEventSource: source, virtualKey: 56, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: 56, keyDown: false) else {
            exit(2)
        }
        if CommandLine.arguments.last == "--secure" {
            guard EnableSecureEventInput() == noErr else { exit(3) }
            defer { _ = DisableSecureEventInput() }
            FileHandle.standardOutput.write(Data("ready\n".utf8))
            _ = readLine()
            return
        }
        source.userData = -91
        down.setIntegerValueField(.eventSourceUserData, value: -91)
        up.setIntegerValueField(.eventSourceUserData, value: -91)
        down.type = .flagsChanged; down.flags = CGEventFlags(rawValue: CGEventFlags.maskShift.rawValue | 0x2)
        up.type = .flagsChanged; up.flags = []
        down.post(tap: .cghidEventTap)
        defer { up.post(tap: .cghidEventTap) }
        FileHandle.standardOutput.write(Data("ready\n".utf8))
        _ = readLine()
    }
}
