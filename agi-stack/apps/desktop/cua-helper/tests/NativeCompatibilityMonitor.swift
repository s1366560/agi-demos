import AppKit
import CoreGraphics

/// Read-only observer. A real workspace notification and window visibility
/// transition are both required to identify a Space transition in acceptance.
@main
enum NativeCompatibilityMonitor {
    static func main() {
        let application = NSApplication.shared
        application.setActivationPolicy(.prohibited)
        application.finishLaunching()
        guard CommandLine.arguments.count == 4,
              let targetPID = Int32(CommandLine.arguments[1]),
              let targetWindow = UInt32(CommandLine.arguments[2]),
              let helperPID = Int32(CommandLine.arguments[3]) else { exit(2) }
        var spaceEpoch = 0
        var previous: Data?
        var lastPublished = -Double.infinity
        func sample() {
            let session = CGSessionCopyCurrentDictionary() as? [String: Any]
            let windowList = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID)
                as? [[String: Any]]
            let visible = windowList ?? []
            let targetVisible = visible.contains {
                ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == targetPID &&
                ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == targetWindow
            }
            let cursors = visible.filter {
                guard ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == helperPID,
                      let raw = $0[kCGWindowBounds as String] as? [String: Any],
                      let rect = CGRect(dictionaryRepresentation: raw as CFDictionary) else { return false }
                return rect.width == 24 && rect.height == 28 &&
                    ($0[kCGWindowLayer as String] as? Int) == 0
            }
            var value: [String: Any] = [
                "space_epoch": spaceEpoch, "target_visible": targetVisible,
                "cursor_count": cursors.count,
                "windows_available": windowList != nil, "session_available": session != nil,
                "screen_locked": session?["CGSSessionScreenIsLocked"] as? Bool ?? false,
                "on_console": session?[kCGSessionOnConsoleKey as String] as? Bool ?? false,
                "frontmost_pid": NSWorkspace.shared.frontmostApplication?.processIdentifier ?? -1,
            ]
            let now = ProcessInfo.processInfo.systemUptime
            guard let state = try? JSONSerialization.data(withJSONObject: value, options: .sortedKeys),
                  state != previous || now - lastPublished >= 0.25 else { return }
            previous = state; lastPublished = now
            value["observed_uptime"] = now
            value["observed_at"] = Date().timeIntervalSince1970
            guard let data = try? JSONSerialization.data(withJSONObject: value, options: .sortedKeys) else { return }
            FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
        }
        let observer = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.activeSpaceDidChangeNotification, object: nil, queue: .main) { _ in
                MainActor.assumeIsolated { spaceEpoch += 1; sample() }
            }
        sample()
        let timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { _ in
            MainActor.assumeIsolated { sample() }
        }
        RunLoop.main.add(timer, forMode: .common)
        withExtendedLifetime(observer) { application.run() }
    }
}
