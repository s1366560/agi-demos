import AppKit
import ApplicationServices
import CryptoKit
import Darwin
import Foundation
import ScreenCaptureKit

// Independent native UI QA driver. Never calls product IPC or grants permissions.
// Build: swiftc -parse-as-library native_menu_driver.swift -o native-menu-driver
// identity --pid PID --executable /absolute/.../Memstack Computer Use.app/Contents/MacOS/cua-helper
// inspect  <identity flags> --start SECONDS:MICROSECONDS [--max-nodes 250]
// press    <identity flags> --start ... --root extras --path 0.1 --expect-role AXMenuItem --expect-label TEXT
// capture  <identity flags> --start ... --window-id ID --output /absolute/new.png
// capture-status <identity flags> --start ... --root extras --path 0 --expect-role AXMenuBarItem --expect-label 'Memstack Computer Use' --output /absolute/new.png
// The identity command only reads libproc metadata. UI commands require the exact
// observed process start identity. Capture includes one helper-owned window;
// capture-status samples only the exact observed helper-owned AX status-item frame.

struct DriverFailure: Error { let code: String; let message: String }
func fail(_ code: String, _ message: String) throws -> Never {
    throw DriverFailure(code: code, message: message)
}
struct Options {
    let command: String
    let values: [String: String]
    init(_ args: [String]) throws {
        guard let first = args.first, ["identity", "inspect", "press", "capture", "capture-status"].contains(first) else {
            try fail("usage", "Commands: identity, inspect, press, capture, capture-status. See source header for flags.")
        }
        command = first
        var result: [String: String] = [:]
        var index = 1
        let allowed = Set(["pid", "executable", "start", "max-nodes", "root", "path", "expect-role", "expect-label", "window-id", "output"])
        while index < args.count {
            let key = args[index]
            guard key.hasPrefix("--"), index + 1 < args.count else { try fail("usage", "Flags require values") }
            let name = String(key.dropFirst(2))
            guard allowed.contains(name), result[name] == nil else { try fail("usage", "Unknown or duplicate flag: \(key)") }
            result[name] = args[index + 1]; index += 2
        }
        values = result
    }
    func required(_ key: String) throws -> String {
        guard let value = values[key], !value.isEmpty else { try fail("usage", "Missing --\(key)") }
        return value
    }
}
struct Identity {
    let pid: pid_t
    let executable: String
    let start: String
    var json: [String: Any] { ["pid": pid, "executable": executable, "start": start] }
    static func read(pid: pid_t, expectedExecutable: String) throws -> Identity {
        var process = proc_bsdinfo()
        let size = MemoryLayout<proc_bsdinfo>.size
        guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &process, Int32(size)) == size else {
            try fail("process-unavailable", "Cannot read exact PID start identity")
        }
        // PROC_PIDPATHINFO_MAXSIZE is a C expression macro unavailable in Swift.
        var path = [CChar](repeating: 0, count: 4 * Int(MAXPATHLEN))
        guard proc_pidpath(pid, &path, UInt32(path.count)) > 0 else { try fail("process-unavailable", "Cannot read PID executable") }
        let executable = URL(fileURLWithPath: String(cString: path)).resolvingSymlinksInPath().path
        guard executable == expectedExecutable else { try fail("identity-mismatch", "PID executable does not match selected helper") }
        return Identity(pid: pid, executable: executable, start: "\(process.pbi_start_tvsec):\(process.pbi_start_tvusec)")
    }
    func validate() throws {
        let current = try Self.read(pid: pid, expectedExecutable: executable)
        guard current.start == start else { try fail("process-replaced", "Selected helper process start identity changed") }
    }
}
func identity(_ options: Options) throws -> Identity {
    guard let pid = Int32(try options.required("pid")), pid > 0 else { try fail("usage", "PID must be positive") }
    let supplied = try options.required("executable")
    guard supplied.hasPrefix("/") else { try fail("usage", "Executable path must be absolute") }
    let canonical = URL(fileURLWithPath: supplied).resolvingSymlinksInPath()
    guard canonical.path.hasSuffix("/Memstack Computer Use.app/Contents/MacOS/cua-helper") else {
        try fail("target-not-helper", "Only the official Computer Use helper bundle is accepted")
    }
    let plist = canonical.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("Info.plist")
    let data = try Data(contentsOf: plist)
    let info = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
    guard info?["CFBundleIdentifier"] as? String == "ai.agistack.desktop.cua-helper" else {
        try fail("target-not-helper", "Selected bundle identifier is not the Computer Use helper")
    }
    let selected = try Identity.read(pid: pid, expectedExecutable: canonical.path)
    if options.command != "identity" {
        guard selected.start == (try options.required("start")) else { try fail("process-replaced", "Observed --start does not match current PID") }
    }
    return selected
}
func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
}
func text(_ element: AXUIElement, _ name: String) -> String {
    if let value = attribute(element, name) as? String { return value }
    if let value = attribute(element, name) as? NSNumber { return value.stringValue }
    return ""
}
func owns(_ element: AXUIElement, _ identity: Identity) -> Bool {
    var pid: pid_t = 0
    return AXUIElementGetPid(element, &pid) == .success && pid == identity.pid
}
func children(_ element: AXUIElement) -> [AXUIElement] {
    attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
}
func label(_ element: AXUIElement) -> String {
    for name in [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute, kAXHelpAttribute] {
        let value = text(element, name)
        if !value.isEmpty { return value }
    }
    return ""
}
func frame(_ element: AXUIElement) -> [String: Double]? {
    guard let position = attribute(element, kAXPositionAttribute), let size = attribute(element, kAXSizeAttribute),
          CFGetTypeID(position) == AXValueGetTypeID(), CFGetTypeID(size) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero; var dimensions = CGSize.zero
    guard AXValueGetValue(position as! AXValue, .cgPoint, &point), AXValueGetValue(size as! AXValue, .cgSize, &dimensions) else { return nil }
    return ["x": point.x, "y": point.y, "width": dimensions.width, "height": dimensions.height]
}
func roots(_ identity: Identity) throws -> [String: AXUIElement] {
    try identity.validate()
    guard AXIsProcessTrusted() else { try fail("accessibility-denied", "Current host lacks Accessibility; no permission prompt or fallback is attempted") }
    let application = AXUIElementCreateApplication(identity.pid)
    AXUIElementSetMessagingTimeout(application, 2)
    var result = ["application": application]
    if let extras = attribute(application, "AXExtrasMenuBar"), CFGetTypeID(extras) == AXUIElementGetTypeID() {
        result["extras"] = (extras as! AXUIElement)
    }
    for (index, window) in (attribute(application, kAXWindowsAttribute) as? [AXUIElement] ?? []).enumerated() {
        result["window:\(index)"] = window
    }
    return result
}
func ownedWindows(_ identity: Identity) throws -> [[String: Any]] {
    try identity.validate()
    let all = CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as? [[String: Any]] ?? []
    return all.filter { ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == identity.pid }.map { value in
        ["window_id": value[kCGWindowNumber as String] ?? NSNull(), "layer": value[kCGWindowLayer as String] ?? NSNull(),
         "title": value[kCGWindowName as String] ?? "", "bounds": value[kCGWindowBounds as String] ?? NSNull(),
         "on_screen": value[kCGWindowIsOnscreen as String] ?? false, "alpha": value[kCGWindowAlpha as String] ?? NSNull()]
    }
}
func windowBounds(_ window: [String: Any]) -> CGRect? {
    guard let value = window["bounds"] as? [String: Any],
          let bounds = CGRect(dictionaryRepresentation: value as CFDictionary),
          bounds.minX.isFinite, bounds.minY.isFinite, bounds.width.isFinite, bounds.height.isFinite,
          bounds.width > 0, bounds.height > 0 else { return nil }
    return bounds
}
func visibleWindow(_ windows: [[String: Any]], id: UInt32) -> [String: Any]? {
    windows.first {
        ($0["window_id"] as? NSNumber)?.uint32Value == id && $0["on_screen"] as? Bool == true && windowBounds($0) != nil
    }
}
func activeDisplays() throws -> [CGDirectDisplayID: CGRect] {
    var count: UInt32 = 0
    guard CGGetActiveDisplayList(0, nil, &count) == .success, count > 0, count <= 32 else {
        try fail("display-unavailable", "Cannot enumerate bounded active displays")
    }
    var values = [CGDirectDisplayID](repeating: 0, count: Int(count))
    guard CGGetActiveDisplayList(count, &values, &count) == .success else { try fail("display-unavailable", "Active display enumeration changed") }
    return Dictionary(uniqueKeysWithValues: values.prefix(Int(count)).map { ($0, CGDisplayBounds($0)) })
}
func positiveIntersection(_ left: CGRect, _ right: CGRect) -> Bool {
    let overlap = left.intersection(right)
    return !overlap.isNull && overlap.width > 0 && overlap.height > 0
}
func inspect(_ identity: Identity, _ maximum: Int) throws -> [String: Any] {
    var nodes: [[String: Any]] = []; var truncated = false
    let selectedRoots = try roots(identity)
    for key in selectedRoots.keys.sorted() {
        guard let root = selectedRoots[key] else { continue }
        var stack: [(AXUIElement, [Int])] = [(root, [])]
        while let (node, path) = stack.popLast() {
            guard nodes.count < maximum else { truncated = true; break }
            guard owns(node, identity) else { continue }
            let descendants = children(node)
            var actionValue: CFArray?
            AXUIElementCopyActionNames(node, &actionValue)
            var record: [String: Any] = ["root": key, "path": path, "role": text(node, kAXRoleAttribute),
                "label": label(node), "title": text(node, kAXTitleAttribute), "description": text(node, kAXDescriptionAttribute),
                "value": text(node, kAXValueAttribute), "enabled": attribute(node, kAXEnabledAttribute) as? Bool ?? true,
                "actions": actionValue as? [String] ?? [], "children_count": descendants.count]
            if let bounds = frame(node) { record["frame"] = bounds }
            nodes.append(record)
            if path.count >= 20 { truncated = truncated || !descendants.isEmpty; continue }
            for (index, child) in descendants.enumerated().reversed() { stack.append((child, path + [index])) }
        }
    }
    try identity.validate()
    return ["identity": identity.json, "nodes": nodes, "truncated": truncated, "windows": try ownedWindows(identity)]
}
func selectedElement(_ identity: Identity, _ options: Options) throws -> (AXUIElement, String, [Int]) {
    let rootName = try options.required("root")
    guard var selected = try roots(identity)[rootName] else { try fail("root-missing", "Observed AX root no longer exists") }
    let rawPath = try options.required("path")
    let path = rawPath == "." ? [] : rawPath.split(separator: ".", omittingEmptySubsequences: false).compactMap { Int($0) }
    guard rawPath == "." || (!path.isEmpty && path.count == rawPath.split(separator: ".", omittingEmptySubsequences: false).count),
          path.count <= 20, path.allSatisfy({ $0 >= 0 }) else { try fail("usage", "--path is dot-separated indices, or . for root") }
    for index in path {
        guard owns(selected, identity) else { try fail("element-owner-mismatch", "AX path left the selected process") }
        let values = children(selected)
        guard values.indices.contains(index) else { try fail("element-missing", "Observed AX path no longer exists") }
        selected = values[index]
    }
    try identity.validate()
    guard owns(selected, identity), text(selected, kAXRoleAttribute) == (try options.required("expect-role")),
          label(selected) == (try options.required("expect-label")) else { try fail("element-mismatch", "Observed AX owner, role or label changed") }
    guard attribute(selected, kAXEnabledAttribute) as? Bool != false else { try fail("element-disabled", "Observed control is disabled") }
    return (selected, rootName, path)
}
func elementGeometry(_ selected: AXUIElement) throws -> ([String: Double], CGRect) {
    guard let geometry = frame(selected), let x = geometry["x"], let y = geometry["y"],
          let width = geometry["width"], let height = geometry["height"],
          [x, y, width, height].allSatisfy({ $0.isFinite }), width > 0, height > 0 else {
        try fail("element-not-visible", "Observed control has no positive finite AX frame")
    }
    return (geometry, CGRect(x: x, y: y, width: width, height: height))
}
func press(_ identity: Identity, _ options: Options) throws -> [String: Any] {
    let (selected, rootName, path) = try selectedElement(identity, options)
    var actions: CFArray?
    AXUIElementCopyActionNames(selected, &actions)
    guard (actions as? [String] ?? []).contains(kAXPressAction) else { try fail("action-unavailable", "Observed element does not support AXPress") }
    let (geometry, elementBounds) = try elementGeometry(selected)
    let supportingWindows = try ownedWindows(identity).filter { window in
        guard window["on_screen"] as? Bool == true, let bounds = windowBounds(window) else { return false }
        return positiveIntersection(elementBounds, bounds)
    }
    let isStatusItem = rootName == "extras" && text(selected, kAXRoleAttribute) == "AXMenuBarItem" && label(selected) == "Memstack Computer Use"
    let supportingDisplays = isStatusItem ? try activeDisplays().filter { positiveIntersection(elementBounds, $0.value) } : [:]
    guard !supportingWindows.isEmpty || !supportingDisplays.isEmpty else {
        try fail("element-not-visible", "Observed control does not overlap an on-screen window owned by the exact helper")
    }
    try identity.validate()
    let before: [String: Any] = ["root": rootName, "path": path, "role": text(selected, kAXRoleAttribute), "label": label(selected)]
    let result = AXUIElementPerformAction(selected, kAXPressAction as CFString)
    if result == .cannotComplete {
        try fail("action-result-unknown", "AXPress returned -25204; the menu may have opened or the action may have executed. Observe the current UI and state; do not replay the action")
    }
    guard result == .success else { try fail("action-failed", "AXPress returned \(result.rawValue); action is not retried") }
    // A successful Stop may intentionally terminate the helper; do not retry.
    return ["identity": identity.json, "pressed": before, "frame": geometry,
            "supporting_window_ids": supportingWindows.compactMap { $0["window_id"] },
            "supporting_display_ids": Array(supportingDisplays.keys), "outcome": "AXPress returned success"]
}
@available(macOS 14.2, *)
func captureStatus(_ identity: Identity, _ options: Options) async throws -> [String: Any] {
    let (selected, rootName, path) = try selectedElement(identity, options)
    guard rootName == "extras", text(selected, kAXRoleAttribute) == "AXMenuBarItem", label(selected) == "Memstack Computer Use" else {
        try fail("status-item-mismatch", "Status capture requires the observed Computer Use AXExtrasMenuBar item")
    }
    let (geometry, bounds) = try elementGeometry(selected)
    guard bounds.width <= 256, bounds.height <= 128 else { try fail("capture-bounds", "Status item exceeds bounded icon geometry") }
    let displays = try activeDisplays().filter { $0.value.contains(bounds) }
    guard displays.count == 1, let displayRecord = displays.first else { try fail("display-mismatch", "Status item does not fit exactly one active display") }
    let output = try options.required("output")
    guard output.hasPrefix("/"), output.hasSuffix(".png"), !FileManager.default.fileExists(atPath: output) else {
        try fail("output-invalid", "--output must be a new absolute PNG path")
    }
    guard CGPreflightScreenCaptureAccess() else { try fail("screen-recording-denied", "Current host lacks Screen Recording; no permission prompt is attempted") }
    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
    try identity.validate()
    guard let display = content.displays.first(where: { $0.displayID == displayRecord.key }), display.frame == displayRecord.value else {
        try fail("display-changed", "Selected active display changed before capture")
    }
    let filter = SCContentFilter(display: display, excludingWindows: [])
    filter.includeMenuBar = true
    let config = SCStreamConfiguration()
    // ScreenCaptureKit crops before producing the image; no full-display image is retained.
    let crop = bounds.offsetBy(dx: -displayRecord.value.minX, dy: -displayRecord.value.minY)
    config.sourceRect = crop
    let scale = max(1, Double(filter.pointPixelScale))
    config.width = max(1, Int((bounds.width * scale).rounded(.up)))
    config.height = max(1, Int((bounds.height * scale).rounded(.up)))
    config.showsCursor = false
    let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
    try identity.validate()
    let (after, _, _) = try selectedElement(identity, options)
    guard try elementGeometry(after).1 == bounds, try activeDisplays()[displayRecord.key] == displayRecord.value else {
        try fail("status-item-changed", "Status item or display frame changed during capture; image discarded")
    }
    guard image.width == config.width, image.height == config.height,
          let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else { try fail("capture-failed", "Unexpected cropped image dimensions or PNG encoding failure") }
    try png.write(to: URL(fileURLWithPath: output), options: .withoutOverwriting)
    return ["identity": identity.json, "root": rootName, "path": path, "frame": geometry, "display_id": displayRecord.key,
            "png_path": output, "width": image.width, "height": image.height,
            "sha256": SHA256.hash(data: png).map { String(format: "%02x", $0) }.joined()]
}
@available(macOS 14.0, *)
func capture(_ identity: Identity, _ options: Options) async throws -> [String: Any] {
    guard let id = UInt32(try options.required("window-id")), id > 0 else { try fail("usage", "--window-id must be positive") }
    let output = try options.required("output")
    guard output.hasPrefix("/"), output.hasSuffix(".png"), !FileManager.default.fileExists(atPath: output) else {
        try fail("output-invalid", "--output must be a new absolute PNG path")
    }
    try identity.validate()
    guard let window = visibleWindow(try ownedWindows(identity), id: id), let expectedBounds = windowBounds(window) else {
        try fail("window-not-visible", "Selected window is absent, off-screen or not owned by the exact helper")
    }
    guard CGPreflightScreenCaptureAccess() else { try fail("screen-recording-denied", "Current host lacks Screen Recording; no permission prompt or broad fallback is attempted") }
    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
    try identity.validate()
    guard let selected = content.windows.first(where: { $0.windowID == id && $0.owningApplication?.processID == identity.pid }) else {
        try fail("capture-window-missing", "Selected helper-owned window is not available to ScreenCaptureKit")
    }
    let bounds = selected.frame
    guard selected.isOnScreen, bounds == expectedBounds else {
        try fail("window-changed", "Selected window visibility or bounds changed before capture")
    }
    guard bounds.width > 0, bounds.height > 0, bounds.width <= 4096, bounds.height <= 4096 else {
        try fail("capture-bounds", "Selected menu or indicator exceeds bounded QA geometry")
    }
    let filter = SCContentFilter(desktopIndependentWindow: selected)
    let configuration = SCStreamConfiguration()
    let scale = min(2.0, 4096.0 / max(bounds.width, bounds.height))
    configuration.width = max(1, Int(bounds.width * scale)); configuration.height = max(1, Int(bounds.height * scale))
    configuration.showsCursor = false
    let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
    try identity.validate()
    guard let after = visibleWindow(try ownedWindows(identity), id: id), windowBounds(after) == expectedBounds else {
        try fail("window-changed", "Window disappeared, became off-screen or changed bounds during capture; image discarded")
    }
    guard let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else { try fail("capture-failed", "Cannot encode PNG") }
    try png.write(to: URL(fileURLWithPath: output), options: .withoutOverwriting)
    return ["identity": identity.json, "window": window, "png_path": output, "width": image.width, "height": image.height,
            "sha256": SHA256.hash(data: png).map { String(format: "%02x", $0) }.joined()]
}
func emit(_ value: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
        FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
    }
}
@main struct NativeMenuDriver {
    static func main() async {
        do {
            let options = try Options(Array(CommandLine.arguments.dropFirst()))
            let selected = try identity(options)
            let result: [String: Any]
            switch options.command {
            case "identity": result = selected.json
            case "inspect":
                let maximum = Int(options.values["max-nodes"] ?? "250") ?? 0
                guard (1...1000).contains(maximum) else { try fail("usage", "--max-nodes must be 1...1000") }
                result = try inspect(selected, maximum)
            case "press": result = try press(selected, options)
            case "capture-status":
                guard #available(macOS 14.2, *) else { try fail("unsupported-host", "Status capture needs macOS 14.2 or later") }
                result = try await captureStatus(selected, options)
            default:
                guard #available(macOS 14.0, *) else { try fail("unsupported-host", "Capture needs macOS 14 or later") }
                result = try await capture(selected, options)
            }
            emit(["ok": true, "command": options.command, "result": result])
        } catch {
            let failure = error as? DriverFailure
            emit(["ok": false, "code": failure?.code ?? "driver-error", "message": failure?.message ?? error.localizedDescription])
            exit(1)
        }
    }
}
