// AxTree.swift — app resolution, accessibility tree serialization with stable
// element indexes, diff-by-default output, per-app element registry, and
// window screenshots. Mirrors the "skyshot" observation unit: one round trip
// returning AX text plus a screenshot (docs/cua/ analysis sections 2-4).

import AppKit
import ApplicationServices
import CoreGraphics

struct ElementRecord {
    let axElement: AXUIElement
    let role: String
    let frame: CGRect
    let isEditable: Bool
    let actions: [String]
}

struct ResolvedApp {
    let id: String            // bundle identifier when known, else process name
    let displayName: String
    let pid: pid_t
    let bundleId: String?
}

/// Per-app element registry. Indexes are only valid against the latest
/// get_app_state; stale references raise `stale_element` so the caller refreshes.
enum AppResolver {
    static func runningApps() -> [ResolvedApp] {
        NSWorkspace.shared.runningApplications
            .filter { $0.activationPolicy == .regular }
            .compactMap { app -> ResolvedApp? in
                guard let pid = app.processIdentifier as pid_t?, pid > 0,
                      let name = app.localizedName else { return nil }
                let bundleId = app.bundleIdentifier
                return ResolvedApp(
                    id: AppIdentity.canonicalID(bundleID: bundleId, url: app.bundleURL ?? app.executableURL),
                    displayName: name,
                    pid: pid,
                    bundleId: bundleId
                )
            }
    }

    /// Accepts a bundle identifier, display name, or "pid:<n>".
    static func resolve(_ identifier: String) throws -> ResolvedApp? {
        if identifier.hasPrefix("pid:"), let pid = pid_t(identifier.dropFirst(4)) {
            return runningApps().first { $0.pid == pid }
        }
        let running = runningApps()
        let exact = running.filter { $0.bundleId == identifier || $0.id == identifier
            || (identifier.hasPrefix("/") && NSRunningApplication(processIdentifier: $0.pid)?.bundleURL?
                .resolvingSymlinksInPath().path == URL(fileURLWithPath: identifier).resolvingSymlinksInPath().path) }
        let candidates = exact.isEmpty ? running.filter {
            $0.displayName.caseInsensitiveCompare(identifier) == .orderedSame
        } : exact
        guard candidates.count <= 1 else {
            throw ActionError.failure(kind: "app_ambiguous", message: "choose an exact application PID",
                extra: ["candidates": candidates.compactMap { try? AppIdentity.payload($0) }])
        }
        return candidates.first
    }

}

enum AxEngine {

    // MARK: permission preflight

    static func accessibilityTrusted() -> Bool {
        AXIsProcessTrusted()
    }

    // MARK: tree serialization

    /// Node budget bounds a single serialization pass; agents page via
    /// targeted queries in later revisions. Mirrors the reference line budget.
    static let nodeBudget = 1500

    static func checkedWindowElements(error: AXError, value: CFTypeRef?) throws -> [AXUIElement] {
        guard error == .success else {
            let kind: String
            switch error {
            case .apiDisabled: kind = "permission_required"
            case .invalidUIElement: kind = "stale_target"
            default: kind = "accessibility_unavailable"
            }
            throw ActionError.failure(kind: kind, message: "cannot enumerate application windows",
                extra: ["ax_error": error.rawValue, "attribute": "AXWindows"])
        }
        guard let elements = value as? [AXUIElement] else {
            throw ActionError.failure(kind: "accessibility_unavailable", message: "invalid accessibility window list")
        }
        return elements
    }
    static func windows(app: ResolvedApp, session: NativeSession,
                        reader: ((AXUIElement) throws -> [AXUIElement])? = nil,
                        identityReader: WindowIdentityReader = .live) throws -> [NativeWindow] {
        let axApp = AXUIElementCreateApplication(app.pid)
        let elements: [AXUIElement]
        if let reader = reader { elements = try reader(axApp) }
        else {
            var raw: CFTypeRef?
            let error = AXUIElementCopyAttributeValue(axApp, kAXWindowsAttribute as CFString, &raw)
            elements = try checkedWindowElements(error: error, value: raw)
        }
        guard let process = identityReader.process(app.pid) else {
            throw ActionError.failure(kind: "stale_target", message: "the window process no longer exists")
        }
        let result = identityReader.reconcile(elements, previous: session.windows[app.id] ?? [], process: process)
        guard identityReader.process(app.pid) == process else {
            throw ActionError.failure(kind: "stale_target", message: "the window process changed during observation")
        }
        session.windows[app.id] = result
        return result
    }

    static func selectWindow(app: ResolvedApp, session: NativeSession, id: String?) throws -> NativeWindow {
        let available = try windows(app: app, session: session)
        if let id = id {
            guard let selected = available.first(where: { $0.id == id }) else {
                throw ActionError.failure(kind: "window_not_found", message: "the selected window no longer exists")
            }
            return selected
        }
        let axApp = AXUIElementCreateApplication(app.pid)
        if let focused = copyElement(axApp, kAXFocusedWindowAttribute as String),
           let selected = available.first(where: { CFEqual($0.element, focused) }) { return selected }
        guard available.count == 1, let selected = available.first else {
            throw ActionError.failure(kind: "window_required", message: "select a window_id from list_windows")
        }
        return selected
    }

    static func appState(app: ResolvedApp, session: NativeSession, windowID: String?, disableDiff: Bool) throws -> [String: Any] {
        try NativeScreenState.requireUnlocked()
        let window = try selectWindow(app: app, session: session, id: windowID)
        var records: [Int: ElementRecord] = [:]
        var lines: [String] = ["# app: \(app.displayName) (\(app.id)) pid=\(app.pid)"]
        var counter = 0
        serialize(element: window.element, depth: 0, lines: &lines, records: &records, counter: &counter)
        if counter >= nodeBudget { lines.append("! tree truncated at node budget") }
        let text = lines.joined(separator: "\n")
        let key = "\(app.pid):\(window.id)"
        // Finish fallible observation before publishing a new input generation.
        // Otherwise an error can leave the client permanently bound to the old one.
        let image = try WindowCapture.capture(app: app, window: window, session: session)
        let target = try AppIcon.target(app, window: window)
        let identity = try AppIcon.identity(app, session: session)
        try session.observeInputTarget(app, window: window)
        let previous = session.previousText[key]
        session.previousText[key] = text
        let snapshot = Snapshot(id: UUID().uuidString, app: app, window: window, records: records,
            inputGeneration: session.inputGeneration)
        session.snapshots[app.id] = snapshot
        var result: [String: Any] = ["app": app.id, "app_id": app.id, "process_id": app.pid,
                "window_id": window.id, "snapshot_id": snapshot.id,
                "input_mode": session.inputMode.rawValue, "input_generation": session.inputGeneration,
                "bounds": window.payload["bounds"]!,
                "window_bounds": window.payload["bounds"]!,
                "text": !disableDiff && previous == text ? "! unchanged" : text,
                "screenshot": image ?? NSNull(), "target": target]
        if let icon = identity["app_icon"] { result["app_icon"] = icon }
        if image == nil {
            result["screenshot_unavailable_reason"] = CGPreflightScreenCaptureAccess()
                ? "window_capture_unavailable" : "screen_recording_required"
        }
        return result
    }

    private static func serialize(element: AXUIElement, depth: Int, lines: inout [String], records: inout [Int: ElementRecord], counter: inout Int) {
        guard counter < nodeBudget, depth < 24 else { return }
        let role = copyString(element, kAXRoleAttribute as String) ?? "unknown"
        let title = copyString(element, kAXTitleAttribute as String)
            ?? copyString(element, kAXDescriptionAttribute as String)
        let value = copyString(element, kAXValueAttribute as String)
        let frame = elementFrame(element)
        let actions = copyActionNames(element)
        var settable = DarwinBoolean(false)
        let editable = AXUIElementIsAttributeSettable(element, kAXValueAttribute as CFString, &settable) == .success
            && settable.boolValue

        let index = counter
        counter += 1
        let indent = String(repeating: "  ", count: min(depth, 12))
        var line = "[\(index)] \(role)"
        if let title = title, !title.isEmpty { line += " \"\(title.prefix(120))\"" }
        if let value = value, !value.isEmpty, value != title {
            line += " value=\"\(value.prefix(160))\""
        }
        line += " frame=(\(Int(frame.origin.x)),\(Int(frame.origin.y)) \(Int(frame.width))x\(Int(frame.height)))"
        let secondary = actions.filter { $0 != kAXPressAction as String }
        if !secondary.isEmpty { line += " actions={\(secondary.joined(separator: ", "))}" }
        if editable { line += " editable" }
        lines.append(indent + line)

        records[index] = ElementRecord(
            axElement: element,
            role: role,
            frame: frame,
            isEditable: editable,
            actions: actions
        )

        if let children = copyArray(element, kAXChildrenAttribute as String) {
            for child in children {
                serialize(element: child, depth: depth + 1, lines: &lines, records: &records, counter: &counter)
            }
        }
    }

    // MARK: typed AX attribute helpers

    static func hasAttribute(_ element: AXUIElement, _ attribute: String) -> Bool {
        var names: CFArray?
        guard AXUIElementCopyAttributeNames(element, &names) == .success, let list = names as? [String] else {
            return false
        }
        return list.contains(attribute)
    }

    static func copyString(_ element: AXUIElement, _ attribute: String) -> String? {
        var raw: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &raw) == .success else { return nil }
        return raw as? String
    }

    static func copyElement(_ element: AXUIElement, _ attribute: String) -> AXUIElement? {
        var raw: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &raw) == .success else { return nil }
        guard let raw = raw, CFGetTypeID(raw) == AXUIElementGetTypeID() else { return nil }
        return unsafeBitCast(raw, to: AXUIElement.self)
    }

    static func copyArray(_ element: AXUIElement, _ attribute: String) -> [AXUIElement]? {
        var raw: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &raw) == .success else { return nil }
        return raw as? [AXUIElement]
    }

    static func copyActionNames(_ element: AXUIElement) -> [String] {
        var names: CFArray?
        guard AXUIElementCopyActionNames(element, &names) == .success else { return [] }
        return names as? [String] ?? []
    }

    static func elementFrame(_ element: AXUIElement) -> CGRect {
        var position = CGPoint.zero
        var size = CGSize.zero
        var raw: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &raw) == .success {
            if let raw = raw, CFGetTypeID(raw) == AXValueGetTypeID() {
                AXValueGetValue(unsafeBitCast(raw, to: AXValue.self), .cgPoint, &position)
            }
        }
        if AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &raw) == .success {
            if let raw = raw, CFGetTypeID(raw) == AXValueGetTypeID() {
                AXValueGetValue(unsafeBitCast(raw, to: AXValue.self), .cgSize, &size)
            }
        }
        return CGRect(origin: position, size: size)
    }
}

/// Native application identity decoration; never AX content or model image data.
enum AppIcon {
    static func target(_ app: ResolvedApp, window: NativeWindow? = nil) throws -> [String: Any] {
        let identity = try AppIdentity.payload(app)
        var value: [String: Any] = ["app_id": app.id, "display_name": app.displayName,
            "process_id": app.pid, "identity_digest": identity["identity_digest"]!]
        if let window = window { value["window_id"] = window.id; value["window_title"] = window.title }
        return value
    }
    static func identity(_ app: ResolvedApp, session: NativeSession, bundleURL: URL? = nil) throws -> [String: Any] {
        var value = try AppIdentity.payload(app, bundleURL: bundleURL)
        if let digest = value["identity_digest"] as? String,
           let icon = try artifact(app, digest: digest, session: session, bundleURL: bundleURL) { value["app_icon"] = icon }
        return value
    }
    static func artifact(_ app: ResolvedApp, digest: String, session: NativeSession,
                         bundleURL: URL? = nil) throws -> [String: Any]? {
        if let cached = session.appIcons[digest] { return cached }
        let render = { () -> Data? in
            let icon = NSRunningApplication(processIdentifier: app.pid)?.icon
                ?? bundleURL.map { NSWorkspace.shared.icon(forFile: $0.path) }
            guard let icon = icon, let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil,
                pixelsWide: 64, pixelsHigh: 64, bitsPerSample: 8, samplesPerPixel: 4,
                hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
                let context = NSGraphicsContext(bitmapImageRep: bitmap) else { return nil }
            NSGraphicsContext.saveGraphicsState(); defer { NSGraphicsContext.restoreGraphicsState() }
            NSGraphicsContext.current = context
            icon.draw(in: NSRect(x: 0, y: 0, width: 64, height: 64), from: .zero,
                      operation: .copy, fraction: 1)
            context.flushGraphics()
            return bitmap.representation(using: .png, properties: [:])
        }
        let data = Thread.isMainThread ? render() : DispatchQueue.main.sync(execute: render)
        guard let data = data, data.count <= 1024 * 1024 else { return nil }
        let file = session.artifactDirectory.appendingPathComponent("app-icon-\(UUID().uuidString).png")
        try data.write(to: file, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        let artifact: [String: Any] = ["url": file.absoluteString, "width": 64, "height": 64,
                                     "mime_type": "image/png", "kind": "app_icon"]
        session.appIcons[digest] = artifact
        return artifact
    }
}
