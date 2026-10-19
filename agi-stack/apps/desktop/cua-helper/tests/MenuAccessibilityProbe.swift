import AppKit
import ApplicationServices

/// Read only: creates its own status item and reads only its own AX tree.
@main
enum MenuAccessibilityProbe {
    static func main() throws {
        if CommandLine.arguments == [CommandLine.arguments[0], "--input-watchdog"] { InputWatchdogWorker.run() }
        let application = NSApplication.shared
        application.setActivationPolicy(.accessory)
        let owner = Dictionary(uniqueKeysWithValues: Sessions.ownerFields.map { ($0, "menu-probe-" + $0) })
        let session = try Sessions.shared.begin("menu-probe", owner: owner)
        NativePresentation.shared.update(session, phase: "idle", target: ["app_id": "owned-menu-probe",
            "display_name": ProcessInfo.processInfo.processName, "process_id": getpid(), "identity_digest": "owned-test-process"])
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
            let app = AXUIElementCreateApplication(getpid())
            var result: [String: Any] = ["process_id": getpid(), "activation_policy": "accessory", "input_performed": false]
            for attribute in ["AXExtrasMenuBar", "AXMenuBar", "AXChildren"] {
                var raw: CFTypeRef?
                let error = AXUIElementCopyAttributeValue(app, attribute as CFString, &raw)
                var nodes: [[String: Any]] = []
                if let elements = raw as? [AXUIElement] {
                    for element in elements { collect(element, depth: 0, into: &nodes) }
                } else if let raw = raw, CFGetTypeID(raw) == AXUIElementGetTypeID() {
                    collect(unsafeBitCast(raw, to: AXUIElement.self), depth: 0, into: &nodes)
                }
                result[attribute] = ["error_code": error.rawValue, "nodes": nodes]
            }
            if let raw = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]),
               let text = String(data: raw, encoding: .utf8) { print(text) }
            Sessions.shared.end(session.id)
            exit(0)
        }
        application.run()
    }
    static func collect(_ element: AXUIElement, depth: Int, into nodes: inout [[String: Any]]) {
        guard depth < 4, nodes.count < 40 else { return }
        var value: [String: Any] = ["depth": depth]
        for field in ["AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXValue"] {
            if let text = AxEngine.copyString(element, field) { value[field] = String(text.prefix(160)) }
        }
        value["frame"] = NSStringFromRect(AxEngine.elementFrame(element))
        value["actions"] = AxEngine.copyActionNames(element)
        nodes.append(value)
        for child in AxEngine.copyArray(element, "AXChildren") ?? [] { collect(child, depth: depth + 1, into: &nodes) }
    }
}
