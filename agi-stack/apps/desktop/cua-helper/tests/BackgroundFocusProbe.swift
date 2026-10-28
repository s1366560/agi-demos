import AppKit
import CoreGraphics

/// Explicit input for the disposable focus fixtures. Never targets another app.
@main
enum BackgroundFocusProbe {
    static func main() {
        guard CommandLine.arguments.count == 3,
              let pid = Int32(CommandLine.arguments[2]),
              let app = NSRunningApplication(processIdentifier: pid),
              ["ai.memstack.cua.background-fixture", "ai.memstack.cua.guard-fixture"]
                .contains(app.bundleIdentifier ?? "") else { exit(2) }
        switch CommandLine.arguments[1] {
        case "activate":
            guard app.activate(options: []) else { exit(3) }
            RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.1))
        case "key":
            guard app.bundleIdentifier == "ai.memstack.cua.guard-fixture",
                  NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,
                  !CGEventSource.keyState(.hidSystemState, key: 0),
                  CGEventSource.flagsState(.hidSystemState).rawValue & 0x00ff_ffff == 0,
                  let source = CGEventSource(stateID: .hidSystemState),
                  let down = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: true),
                  let up = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: false) else { exit(4) }
            source.userData = -92
            down.setIntegerValueField(.eventSourceUserData, value: -92)
            up.setIntegerValueField(.eventSourceUserData, value: -92)
            down.flags = []; up.flags = []
            down.post(tap: .cghidEventTap)
            defer { up.post(tap: .cghidEventTap) }
            Thread.sleep(forTimeInterval: 0.03)
        default: exit(5)
        }
    }
}
