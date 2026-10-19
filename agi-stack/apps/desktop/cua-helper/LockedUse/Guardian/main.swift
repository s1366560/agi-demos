import AppKit
import CoreGraphics
import CryptoKit
import Foundation

/// The guardian runs independently of the control worker. Any pipe loss,
/// expired lease, or physical input revokes its lease and requests native lock.
final class Guardian: NSObject {
    private var windows: [NSWindow] = []
    private var monitor: Any?
    private var localMonitor: Any?
    private var eventTap: CFMachPort?
    private var timer: Timer?
    private var initialized = false
    private var active = false
    private var suppressed = false
    private var sourcePID: Int64 = 0
    private var expiry = Date.distantPast
    private let outputLock = NSLock()

    func start() {
        let types: [CGEventType] = [.keyDown, .keyUp, .flagsChanged, .leftMouseDown, .leftMouseUp,
            .rightMouseDown, .rightMouseUp, .otherMouseDown, .otherMouseUp, .mouseMoved,
            .leftMouseDragged, .rightMouseDragged, .otherMouseDragged, .scrollWheel]
        let mask = types.reduce(CGEventMask(0)) { $0 | (CGEventMask(1) << $1.rawValue) }
        eventTap = CGEvent.tapCreate(tap: .cghidEventTap, place: .headInsertEventTap,
            options: .defaultTap, eventsOfInterest: mask, callback: { _, type, event, pointer in
                guard let pointer = pointer else { return Unmanaged.passUnretained(event) }
                let owner = Unmanaged<Guardian>.fromOpaque(pointer).takeUnretainedValue()
                return owner.filter(type: type, event: event)
            }, userInfo: Unmanaged.passUnretained(self).toOpaque())
        if let tap = eventTap, let source = CFMachPortCreateRunLoopSource(nil, tap, 0) {
            CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
            CGEvent.tapEnable(tap: tap, enable: true)
        }
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.screensDidWakeNotification,
            object: nil, queue: .main) { [weak self] _ in self?.refresh() }
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification,
            object: nil, queue: .main) { [weak self] _ in self?.refresh() }
        monitor = NSEvent.addGlobalMonitorForEvents(matching: [.keyDown, .leftMouseDown, .rightMouseDown,
                                                              .otherMouseDown, .mouseMoved, .scrollWheel]) {
            [weak self] event in
            guard let self = self, self.active,
                  event.cgEvent?.getIntegerValueField(.eventSourceUnixProcessID) != self.sourcePID else { return }
            self.suppressed = true; self.relock()
        }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .leftMouseDown, .rightMouseDown,
                                                                   .otherMouseDown, .mouseMoved, .scrollWheel]) {
            [weak self] event in
            guard let self = self, self.active,
                  event.cgEvent?.getIntegerValueField(.eventSourceUnixProcessID) != self.sourcePID else { return event }
            self.suppressed = true; self.relock()
            return nil
        }
        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            guard let self = self, self.active, Date() >= self.expiry else { return }
            self.relock()
        }
        Thread { [weak self] in self?.readLoop() }.start()
    }

    private func filter(type: CGEventType, event: CGEvent) -> Unmanaged<CGEvent>? {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            suppressed = true; relock()
            if let tap = eventTap { CGEvent.tapEnable(tap: tap, enable: true) }
            return nil
        }
        let sender = event.getIntegerValueField(.eventSourceUnixProcessID)
        if sender == Int64(getpid()) { return Unmanaged.passUnretained(event) }
        if active && sender == sourcePID { return Unmanaged.passUnretained(event) }
        if active || !windows.isEmpty {
            suppressed = true
            if active { relock() }
            return nil
        }
        return Unmanaged.passUnretained(event)
    }
    private func refresh() {
        guard active else { return }
        let previous = windows; windows.removeAll()
        for screen in NSScreen.screens {
            let window = NSWindow(contentRect: screen.frame, styleMask: [.borderless],
                backing: .buffered, defer: false, screen: screen)
            window.level = NSWindow.Level(rawValue: Int(CGShieldingWindowLevel()) + 1)
            window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
            window.backgroundColor = .black
            window.isOpaque = true; window.ignoresMouseEvents = true
            let message = NSTextField(labelWithString: NSLocalizedString(
                "Computer Use is active. Press any key or click to return to the lock screen.", comment: "locked use"))
            message.textColor = .white
            message.frame = NSRect(x: 40, y: 40, width: min(screen.frame.width - 80, 800), height: 60)
            window.contentView?.addSubview(message)
            window.orderFrontRegardless(); windows.append(window)
        }
        previous.forEach { $0.orderOut(nil) }
    }

    private func relock() {
        guard active else { return }
        active = false
        // Public system Lock Screen shortcut; never enters or persists credentials.
        let down = CGEvent(keyboardEventSource: nil, virtualKey: 0x0c, keyDown: true)
        let up = CGEvent(keyboardEventSource: nil, virtualKey: 0x0c, keyDown: false)
        down?.flags = [.maskControl, .maskCommand]; up?.flags = [.maskControl, .maskCommand]
        down?.post(tap: .cghidEventTap); up?.post(tap: .cghidEventTap)
        // Retain coverage until the actual system reports locked.
        Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] timer in
            let state = CGSessionCopyCurrentDictionary() as? [String: Any]
            if state?["CGSSessionScreenIsLocked"] as? Bool == true {
                self?.windows.forEach { $0.orderOut(nil) }; self?.windows.removeAll()
                timer.invalidate()
            }
        }
    }

    private func readLoop() {
        while let header = exact(4) {
            let length = header.withUnsafeBytes { UInt32(littleEndian: $0.loadUnaligned(as: UInt32.self)) }
            guard length > 0, length <= 4096, let data = exact(Int(length)),
                  let request = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { break }
            DispatchQueue.main.sync { handle(request) }
        }
        DispatchQueue.main.async { [self] in
            relock()
            if windows.isEmpty { exit(0) }
            // Stay alive behind the overlay until lock completion; parent may have crashed.
        }
    }
    private func handle(_ request: [String: Any]) {
        let id = request["id"] ?? NSNull()
        let params = request["params"] as? [String: Any] ?? [:]
        var response: [String: Any]
        switch request["method"] as? String {
        case "initialize":
            guard !initialized, let secret = params["secret"] as? String, secret.utf8.count >= 32,
                  let nonce = params["nonce"] as? String, nonce.utf8.count >= 16 else { return }
            initialized = true
            let proof = HMAC<SHA256>.authenticationCode(for: Data(nonce.utf8),
                using: SymmetricKey(data: Data(secret.utf8))).map { String(format: "%02x", $0) }.joined()
            response = ["nonce": nonce, "proof": proof]
        case "begin_guard":
            guard initialized, !suppressed, let ttl = params["ttl_seconds"] as? Double,
                  ttl.isFinite, ttl > 0, ttl <= 30, let pid = params["source_pid"] as? Int64 else {
                send(id: id, response: ["error": "guard_rejected"]); return
            }
            sourcePID = pid; expiry = Date().addingTimeInterval(ttl); active = true; refresh()
            response = ["covered_displays": windows.count, "physical_monitor": monitor != nil,
                        "ready": !windows.isEmpty && eventTap.map(CFMachPortIsValid) == true]
        case "renew_guard":
            guard initialized, active, !suppressed else {
                send(id: id, response: ["error": "guard_rejected"]); return
            }
            expiry = Date().addingTimeInterval(10); response = ["ok": true]
        case "end_guard":
            guard initialized else { return }; relock(); response = ["ok": true]
        default: response = ["error": "invalid_request"]
        }
        send(id: id, response: response)
    }
    private func send(id: Any, response: [String: Any]) {
        let payload = try! JSONSerialization.data(withJSONObject: ["jsonrpc": "2.0", "id": id, "result": response])
        var size = UInt32(payload.count).littleEndian
        var frame = Data(bytes: &size, count: 4); frame.append(payload)
        outputLock.lock(); defer { outputLock.unlock() }
        try? FileHandle.standardOutput.write(contentsOf: frame)
    }
    private func exact(_ count: Int) -> Data? {
        var result = Data()
        while result.count < count {
            guard let part = try? FileHandle.standardInput.read(upToCount: count - result.count), !part.isEmpty else { return nil }
            result.append(part)
        }
        return result
    }
}
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
let guardian = Guardian()
guardian.start()
application.run()
