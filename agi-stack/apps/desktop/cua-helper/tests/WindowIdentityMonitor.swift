import AppKit
import ApplicationServices
import Darwin

/// Read-only diagnostics for AX enumeration across real Space/lock transitions.
/// Only the explicitly supplied process is queried; no events or activation occur.
@main
enum WindowIdentityMonitor {
    typealias GetWindow = @convention(c) (AXUIElement, UnsafeMutablePointer<CGWindowID>) -> AXError

    static func main() {
        guard CommandLine.arguments.count == 2, let pid = pid_t(CommandLine.arguments[1]), pid > 0,
              let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "_AXUIElementGetWindow") else { exit(2) }
        let getWindow = unsafeBitCast(symbol, to: GetWindow.self)
        let app = AXUIElementCreateApplication(pid)
        var retained: [AXUIElement] = []
        var previous: Data?
        func describe(_ element: AXUIElement) -> [String: Any] {
            var nativeID: CGWindowID = 0, owner: pid_t = 0
            var role: CFTypeRef?
            let windowError = getWindow(element, &nativeID)
            let pidError = AXUIElementGetPid(element, &owner)
            let roleError = AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &role)
            return ["native_window_id": nativeID, "window_error": windowError.rawValue,
                "pid": owner, "pid_error": pidError.rawValue, "role_error": roleError.rawValue,
                "role": role as? String ?? "", "retained_index": retained.firstIndex {
                    CFEqual($0, element)
                } ?? -1]
        }
        func sample() {
            var process = proc_bsdinfo()
            let size = Int32(MemoryLayout<proc_bsdinfo>.size)
            let processOK = proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &process, size) == size
            var raw: CFTypeRef?
            let error = AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &raw)
            let current = raw as? [AXUIElement] ?? []
            let listed = current.map(describe)
            for element in current where !retained.contains(where: { CFEqual($0, element) }) {
                retained.append(element)
            }
            let windows = CGWindowListCopyWindowInfo(.optionAll, kCGNullWindowID) as? [[String: Any]]
            let native = (windows ?? []).filter {
                ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid
            }.map { entry -> [String: Any] in
                ["native_window_id": entry[kCGWindowNumber as String] ?? 0,
                 "on_screen": entry[kCGWindowIsOnscreen as String] ?? false]
            }
            var value: [String: Any] = ["pid": pid, "process_available": processOK,
                "start_seconds": process.pbi_start_tvsec, "start_microseconds": process.pbi_start_tvusec,
                "ax_windows_error": error.rawValue, "ax_windows": listed,
                "retained_windows": retained.map(describe), "native_windows": native,
                "native_windows_available": windows != nil]
            guard let state = try? JSONSerialization.data(withJSONObject: value, options: .sortedKeys),
                  state != previous else { return }
            previous = state
            value["observed_uptime"] = ProcessInfo.processInfo.systemUptime
            value["observed_at"] = Date().timeIntervalSince1970
            guard let data = try? JSONSerialization.data(withJSONObject: value, options: .sortedKeys) else { return }
            FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
            if !processOK { exit(0) }
        }
        sample()
        let timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { _ in
            MainActor.assumeIsolated { sample() }
        }
        RunLoop.main.add(timer, forMode: .common)
        RunLoop.main.run()
    }
}
