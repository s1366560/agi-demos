import AppKit

final class NativeInputPresentation {
    static let shared = NativeInputPresentation()
    private let lock = NSLock()
    private var sequences: [String: UInt64] = [:]
    private var cursors: [String: [String: Any]] = [:]
    func update(_ session: NativeSession, route: InputRoute?, phase: String, point: CGPoint? = nil,
                keys: [UInt16] = [], buttons: [UInt32] = [], reason: String? = nil,
                evidence: String = "dispatched") {
        lock.lock()
        let phase = session.inputStopPhase ?? phase
        let generation = session.inputGeneration
        let key = session.id + ":" + generation
        sequences[key, default: 0] &+= 1
        var context = session.owner
        context["session_id"] = session.id; context["input_mode"] = session.inputMode.rawValue
        var value: [String: Any] = ["context": context, "input_generation": generation,
            "sequence": sequences[key]!, "updated_at": Date().timeIntervalSince1970,
            "phase": phase, "evidence": evidence, "target_pid": route?.pid ?? 0,
            "held_keys": keys.sorted(), "held_buttons": buttons.sorted()]
        if let route = route { value["target_window_id"] = route.windowID }
        if let route = route, let point = point {
            cursors[session.id] = ["x": min(route.bounds.width.nextDown, max(0, point.x - route.bounds.x)),
                "y": min(route.bounds.height.nextDown, max(0, point.y - route.bounds.y)),
                "width": route.bounds.width, "height": route.bounds.height, "window_id": route.windowID]
        }
        if ["paused", "stopped", "error"].contains(phase) { cursors[session.id] = nil }
        if let cursor = cursors[session.id], cursor["window_id"] as? String == route?.windowID { value["virtual_cursor"] = cursor }
        if let reason = reason { value["reason"] = reason }
        lock.unlock()
        IpcServer.notifyInput(value)
        if let route = route, route.mode == .background, let point = point,
           !["paused", "stopped", "error"].contains(phase) {
            SoftwareCursor.shared.move(point, route: route, session: session)
        } else if ["paused", "stopped", "error"].contains(phase) {
            SoftwareCursor.shared.hide(sessionID: session.id, generation: generation)
        }
    }
    func forget(_ sessionID: String) {
        lock.lock(); cursors[sessionID] = nil
        sequences = sequences.filter { !$0.key.hasPrefix(sessionID + ":") }; lock.unlock()
        SoftwareCursor.shared.hide(sessionID: sessionID)
    }
}

/// An inert overlay is a presentation of dispatched coordinates. It never
/// warps, hides, or changes the physical cursor or receives mouse events.
final class SoftwareCursor {
    static let shared = SoftwareCursor()
    private var panel: NSPanel?
    private var owner: String?
    private var position: (CGPoint, InputRoute)?
    private weak var session: NativeSession?
    private var visibilityTimer: Timer?
    func move(_ point: CGPoint, route: InputRoute, session: NativeSession) {
        DispatchQueue.main.async { [self, weak session] in
            guard let session = session, session.inputGeneration == route.generation,
                  session.inputStopPhase == nil else { return }
            if panel == nil {
                let value = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 24, height: 28),
                    styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
                value.isOpaque = false; value.backgroundColor = .clear; value.hasShadow = false
                value.ignoresMouseEvents = true; value.hidesOnDeactivate = false
                value.setAccessibilityHidden(true)
                value.level = .normal; value.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
                value.contentView = CursorView(frame: value.contentRect(forFrameRect: value.frame))
                panel = value
            }
            owner = session.id; self.session = session
            position = (point, route)
            refreshVisibility()
            if visibilityTimer == nil {
                let timer = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in self?.refreshVisibility() }
                RunLoop.main.add(timer, forMode: .common); visibilityTimer = timer
            }
        }
    }
    func hide(sessionID: String, generation: String? = nil) {
        DispatchQueue.main.async { [self] in
            guard owner == sessionID, generation == nil || position?.1.generation == generation else { return }
            panel?.orderOut(nil); owner = nil; position = nil; session = nil
            visibilityTimer?.invalidate(); visibilityTimer = nil
        }
    }
    private func refreshVisibility() {
        guard let (observedPoint, route) = position, let session = session,
              session.inputGeneration == route.generation, session.inputStopPhase == nil,
              let frame = try? route.currentFrame() else { panel?.orderOut(nil); return }
        let local = CGPoint(x: observedPoint.x - route.bounds.x, y: observedPoint.y - route.bounds.y)
        guard local.x >= 0, local.x < frame.width, local.y >= 0, local.y < frame.height else {
            panel?.orderOut(nil); return
        }
        let point = CGPoint(x: frame.minX + local.x, y: frame.minY + local.y)
        guard InputWindowVisibility.visible(route, at: point) else { panel?.orderOut(nil); return }
        let top = NSScreen.screens.first?.frame.maxY ?? 0
        panel?.setFrameOrigin(NSPoint(x: point.x - 3, y: top - point.y - 25))
        panel?.order(.above, relativeTo: Int(route.window))
    }
    private final class CursorView: NSView {
        override func draw(_ dirtyRect: NSRect) {
            let path = NSBezierPath()
            path.move(to: NSPoint(x: 3, y: 25)); path.line(to: NSPoint(x: 3, y: 5))
            path.line(to: NSPoint(x: 9, y: 10)); path.line(to: NSPoint(x: 13, y: 2))
            path.line(to: NSPoint(x: 17, y: 4)); path.line(to: NSPoint(x: 13, y: 12))
            path.line(to: NSPoint(x: 21, y: 12)); path.close()
            NSColor.systemPurple.setFill(); path.fill(); NSColor.white.setStroke(); path.lineWidth = 1.5; path.stroke()
        }
    }
}
