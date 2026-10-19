import AppKit
import Darwin
import Foundation

enum ActionError: Error {
    case failure(kind: String, message: String)
}

/// Explicit test-only HID-source simulation. This is not physical keyboard evidence.
@main
enum ForeignInputSimulation {
    static func main() throws {
        let arguments = Array(CommandLine.arguments.dropFirst())
        if arguments == ["lease-probe"] {
            let descriptor = try DesktopInputLease.openDescriptor()
            defer { close(descriptor) }
            guard DesktopInputLease.acquire(descriptor) else { print("device_busy"); exit(3) }
            DesktopInputLease.release(descriptor); print("available"); return
        }
        guard arguments.count == 1, let pid = Int32(arguments[0]),
              let target = NSRunningApplication(processIdentifier: pid),
              target.bundleIdentifier == "ai.memstack.cua.fixture",
              NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,
              let source = CGEventSource(stateID: .hidSystemState) else { exit(2) }
        source.userData = -781_421
        source.localEventsSuppressionInterval = 0
        func shift(_ down: Bool) {
            guard let event = CGEvent(keyboardEventSource: source, virtualKey: 56, keyDown: down) else { exit(4) }
            event.setIntegerValueField(.eventSourceUserData, value: source.userData)
            event.flags = down ? CGEventFlags(rawValue: CGEventFlags.maskShift.rawValue | 0x2) : []
            event.post(tap: .cghidEventTap)
        }
        shift(true)
        defer { shift(false) }
        Thread.sleep(forTimeInterval: 0.15)
        FileHandle.standardOutput.write(Data("simulated-foreign-shift-held\n".utf8))
        var descriptor = pollfd(fd: STDIN_FILENO, events: Int16(POLLIN), revents: 0)
        // Bound the simulation even if its test runner exits unexpectedly.
        _ = poll(&descriptor, 1, 5_000)
    }
}
