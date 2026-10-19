import AppKit

struct PresentationTarget: Equatable {
    let appID: String
    let digest: String
    let processID: pid_t
    let windowID: String?
    init?(_ value: [String: Any]) {
        guard let appID = value["app_id"] as? String,
              let digest = value["identity_digest"] as? String,
              let processID = Self.processID(value["process_id"]) else { return nil }
        self.appID = appID; self.digest = digest; self.processID = processID
        windowID = value["window_id"] as? String
    }
    static func processID(_ value: Any?) -> pid_t? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              let pid = pid_t(exactly: number.doubleValue), pid >= 0 else { return nil }
        return pid
    }
    func isSameApplication(as other: Self) -> Bool {
        appID == other.appID && digest == other.digest && processID == other.processID
    }
}

/// Contains only real, owned sessions; AppKit rendering is separate.
final class NativePresentation {
    static let shared = NativePresentation()
    private let lock = NSLock()
    private var values: [String: [String: Any]] = [:]
    private struct Preview {
        let target: PresentationTarget
        let image: NSImage
        let date: Date
    }
    struct MenuSnapshot {
        let value: [String: Any]
        let preview: (NSImage, Date)?
    }
    private var previews: [String: Preview] = [:]
    private var activeSessions = Set<String>()
    func preview(_ session: NativeSession, screenshot: [String: Any], target: [String: Any]) {
        guard let identity = PresentationTarget(target), identity.windowID != nil,
              let url = screenshot["url"] as? String, let file = URL(string: url), file.isFileURL,
              file.deletingLastPathComponent().path == session.artifactDirectory.path,
              let data = try? Data(contentsOf: file), data.count <= 8 * 1024 * 1024,
              let image = NSImage(data: data) else { return }
        lock.lock(); defer { lock.unlock() }
        guard values[session.id] != nil else { return }
        previews[session.id] = Preview(target: identity, image: image, date: Date())
    }
    func preview(_ id: String) -> (NSImage, Date)? {
        lock.lock(); defer { lock.unlock() }
        return matchingPreview(id, value: values[id] ?? [:])
    }
    private func matchingPreview(_ id: String, value: [String: Any]) -> (NSImage, Date)? {
        guard let target = value["target"] as? [String: Any],
              let identity = PresentationTarget(target), let preview = previews[id],
              preview.target == identity else { return nil }
        return (preview.image, preview.date)
    }
    func begin(_ session: NativeSession) {
        lock.lock(); defer { lock.unlock() }
        var context = session.owner; context["session_id"] = session.id
        values[session.id] = ["context": context, "phase": "idle", "updated_at": Date().timeIntervalSince1970]
    }
    func update(_ session: NativeSession, phase: String, target: [String: Any]? = nil,
                error: String? = nil, resumed: Bool = false, userInitiated: Bool = false,
                userAction: String? = nil, canResume: Bool? = nil, resumeBlockedReason: String? = nil) {
        lock.lock()
        guard var value = values[session.id] else { lock.unlock(); return }
        // Stop is terminal even when a queued resume or host presentation
        // receipt arrives later. A second stop may still carry its user receipt.
        if value["phase"] as? String == "stopped", phase != "stopped" { lock.unlock(); return }
        // An in-flight operation cannot overwrite a newer user stop/pause.
        if ["stopped", "paused"].contains(value["phase"] as? String ?? ""),
           !["stopped", "paused"].contains(phase), !resumed { lock.unlock(); return }
        value["phase"] = phase; value["updated_at"] = Date().timeIntervalSince1970
        if var target = target {
            if let previous = value["target"] as? [String: Any],
               let oldIdentity = PresentationTarget(previous), let newIdentity = PresentationTarget(target),
               oldIdentity.isSameApplication(as: newIdentity) {
                for field in ["window_id", "window_title"] where target[field] == nil { target[field] = previous[field] }
            }
            if previews[session.id]?.target != PresentationTarget(target) { previews.removeValue(forKey: session.id) }
            value["target"] = target
        }
        value["error_code"] = error
        value["user_initiated"] = userInitiated
        value["user_action"] = userAction
        value["can_resume"] = phase == "paused" && canResume == true
        value["resume_blocked_reason"] = resumeBlockedReason
        values[session.id] = value; activeSessions.insert(session.id); lock.unlock()
        IpcServer.notifyStatus(value)
        SessionStatusItem.shared.refresh()
    }
    func end(_ id: String) {
        lock.lock(); values.removeValue(forKey: id); previews.removeValue(forKey: id); activeSessions.remove(id); lock.unlock()
        SessionStatusItem.shared.refresh()
    }
    func recordings(_ session: NativeSession, values recordings: [[String: Any]]) {
        lock.lock()
        guard var value = values[session.id] else { lock.unlock(); return }
        value["recordings"] = recordings
        value["updated_at"] = Date().timeIntervalSince1970
        value["user_initiated"] = false; value["user_action"] = nil
        values[session.id] = value; activeSessions.insert(session.id); lock.unlock()
        IpcServer.notifyStatus(value); SessionStatusItem.shared.refresh()
    }
    func snapshot(activeOnly: Bool = false) -> [[String: Any]] {
        lock.lock(); defer { lock.unlock() }
        return values.filter { !activeOnly || activeSessions.contains($0.key) }.map { $0.value }.sorted {
            ($0["updated_at"] as? Double ?? 0) > ($1["updated_at"] as? Double ?? 0)
        }
    }
    func menuSnapshot() -> [MenuSnapshot] {
        lock.lock(); defer { lock.unlock() }
        return values.filter { activeSessions.contains($0.key) }.map {
            MenuSnapshot(value: $0.value, preview: matchingPreview($0.key, value: $0.value))
        }.sorted {
            ($0.value["updated_at"] as? Double ?? 0) > ($1.value["updated_at"] as? Double ?? 0)
        }
    }
}

/// Keeps the same AppKit items while a menu is tracking, so new authority and
/// phase updates also reach the menu that is currently on screen.
final class SessionMenuRows {
    let heading = NSMenuItem()
    let preview = NSMenuItem()
    let window = NSMenuItem()
    let pause = NSMenuItem()
    let stop = NSMenuItem()
    let recording = NSMenuItem()
    let stopRecording = NSMenuItem()
    let separator = NSMenuItem.separator()
    let icon = NSImageView(frame: NSRect(x: 10, y: 8, width: 20, height: 20))
    let title = NSTextField(labelWithString: "")
    private let picture = NSImageView(frame: NSRect(x: 5, y: 27, width: 300, height: 186))
    private let caption = NSTextField(labelWithString: "")
    private var cachedIcon: (PresentationTarget, NSImage)?
    var items: [NSMenuItem] { [heading, preview, window, recording, stopRecording, pause, stop, separator] }
    func applicationIcon(_ target: [String: Any]?, load: () -> NSImage?) -> NSImage? {
        guard let target = target, let identity = PresentationTarget(target) else {
            cachedIcon = nil; return nil
        }
        // Retain the image of the verified application, never fetch an icon
        // from a reused PID on each phase change. Session removal releases it.
        if let (previous, image) = cachedIcon, previous.isSameApplication(as: identity) { return image }
        cachedIcon = nil
        guard let image = load() else { return nil }
        cachedIcon = (identity, image); return image
    }
    init() {
        let header = NSView(frame: NSRect(x: 0, y: 0, width: 310, height: 36))
        icon.imageScaling = .scaleProportionallyUpOrDown
        title.frame = NSRect(x: 38, y: 9, width: 262, height: 18)
        title.font = .systemFont(ofSize: 13, weight: .medium)
        title.textColor = .labelColor; title.lineBreakMode = .byTruncatingTail
        header.addSubview(icon); header.addSubview(title); heading.view = header
        let view = NSView(frame: NSRect(x: 0, y: 0, width: 310, height: 218))
        picture.imageScaling = .scaleProportionallyUpOrDown
        caption.frame = NSRect(x: 8, y: 4, width: 296, height: 18)
        caption.font = .systemFont(ofSize: 11); caption.textColor = .secondaryLabelColor
        view.addSubview(picture); view.addSubview(caption); preview.view = view
        heading.isEnabled = false; preview.isEnabled = false; window.isEnabled = false
    }
    func update(_ snapshot: NativePresentation.MenuSnapshot, id: String, zh: Bool,
                icon image: NSImage?, target: AnyObject, action: Selector) {
        let value = snapshot.value
        let phase = value["phase"] as? String ?? "idle"
        let app = value["target"] as? [String: Any]
        let name = String((app?["display_name"] as? String ?? (zh ? "电脑操作" : "Computer Use")).prefix(80))
        heading.title = "\(name) · \(SessionStatusItem.phaseTitle(phase, zh: zh))"
        title.stringValue = heading.title
        title.setAccessibilityLabel(heading.title)
        icon.image = image; icon.setAccessibilityLabel(name)
        icon.setAccessibilityValue(zh ? "应用图标" : "Application icon")
        icon.isHidden = image == nil
        title.frame.origin.x = image == nil ? 10 : 38
        title.frame.size.width = image == nil ? 290 : 262
        picture.image = snapshot.preview?.0
        picture.setAccessibilityLabel(zh ? "最近授权窗口预览" : "Last authorized window preview")
        preview.isHidden = snapshot.preview == nil
        if let (_, date) = snapshot.preview {
            caption.stringValue = (zh ? "最近授权预览 · " : "Last authorized preview · ")
                + DateFormatter.localizedString(from: date, dateStyle: .none, timeStyle: .medium)
        }
        window.title = String((app?["window_title"] as? String ?? "").prefix(100))
        window.isHidden = window.title.isEmpty
        pause.isHidden = phase == "stopped"; stop.isHidden = phase == "stopped"
        let canResume = value["can_resume"] as? Bool == true
        pause.isEnabled = phase != "stopped" && (phase != "paused" || canResume)
        if phase == "paused" && !canResume {
            pause.title = zh ? "请先恢复已授权任务" : "Resume the authorized task first"
        } else {
            pause.title = phase == "paused" ? (zh ? "恢复电脑操作" : "Resume Computer Use")
                : (zh ? "暂停电脑操作" : "Pause Computer Use")
        }
        pause.target = target; pause.action = action
        pause.representedObject = ["id": id, "method": phase == "paused" ? "resume_session" : "pause_session"]
        stop.title = zh ? "停止电脑操作" : "Stop Computer Use"
        stop.isEnabled = phase != "stopped"; stop.target = target; stop.action = action
        stop.representedObject = ["id": id, "method": "stop_session"]
        let receipts = value["recordings"] as? [[String: Any]] ?? []
        let active = receipts.last(where: { $0["status"] as? String == "recording" })
        let latest = active ?? receipts.last
        recording.isHidden = latest == nil; recording.isEnabled = false
        let sourceNames = ["microphone": zh ? "麦克风" : "Microphone", "system": zh ? "系统音频" : "System audio", "mixed": zh ? "混合音频" : "Mixed audio"]
        let labels = ["recording": zh ? "正在录音" : "Recording", "stopping": zh ? "正在停止录音" : "Stopping recording",
            "pending_export": zh ? "录音待保存" : "Recording awaiting export", "saved": zh ? "录音已保存" : "Recording saved",
            "failed": zh ? "录音失败" : "Recording failed"]
        recording.title = "\(labels[latest?["status"] as? String ?? ""] ?? "") · \(sourceNames[latest?["source"] as? String ?? ""] ?? "")"
        stopRecording.title = zh ? "停止录音" : "Stop Recording"
        stopRecording.isHidden = active == nil; stopRecording.isEnabled = active != nil
        stopRecording.target = target; stopRecording.action = action
        stopRecording.representedObject = ["id": id, "method": "audio_stop", "recording_id": active?["recording_id"] as? String ?? ""]
    }
}

final class SessionStatusItem: NSObject, NSMenuDelegate {
    static let shared = SessionStatusItem()
    private var item: NSStatusItem?
    private let menu = NSMenu()
    private var rows: [String: SessionMenuRows] = [:]
    override init() {
        super.init(); menu.autoenablesItems = false; menu.delegate = self
    }
    func refresh() { DispatchQueue.main.async { [weak self] in self?.render() } }
    func menuWillOpen(_ menu: NSMenu) { render() }
    private func render() {
        let visible = NativePresentation.shared.menuSnapshot()
        guard !visible.isEmpty else {
            if let item = item { NSStatusBar.system.removeStatusItem(item) }
            item = nil; menu.removeAllItems(); rows.removeAll(); return
        }
        let status = item ?? NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item = status
        if status.menu !== menu { status.menu = menu }
        let phase = visible.first?.value["phase"] as? String ?? "idle"
        status.button?.image = Self.templateIcon(phase: phase)
        status.button?.image?.isTemplate = true
        status.button?.setAccessibilityLabel("Memstack Computer Use")
        let zh = Locale.preferredLanguages.first?.hasPrefix("zh") ?? false
        status.button?.setAccessibilityValue(Self.phaseTitle(phase, zh: zh))
        status.button?.toolTip = (zh ? "电脑操作 · " : "Computer Use · ") + Self.phaseTitle(phase, zh: zh)
        let ids = Set(visible.compactMap { ($0.value["context"] as? [String: String])?["session_id"] })
        for id in rows.keys.filter({ !ids.contains($0) }) {
            if let previous = rows.removeValue(forKey: id) { previous.items.forEach { menu.removeItem($0) } }
        }
        for snapshot in visible {
            let value = snapshot.value
            guard let context = value["context"] as? [String: String], let id = context["session_id"] else { continue }
            let target = value["target"] as? [String: Any]
            let content: SessionMenuRows
            if let previous = rows[id] { content = previous }
            else {
                content = SessionMenuRows(); rows[id] = content
                content.items.forEach { menu.addItem($0) }
            }
            let icon = content.applicationIcon(target) { Self.applicationIcon(target) }
            content.update(snapshot, id: id, zh: zh, icon: icon,
                target: self, action: #selector(controlClicked(_:)))
        }
    }
    static func applicationIcon(_ target: [String: Any]?,
        resolve: (pid_t) -> ([String: Any], NSImage?)? = resolvedIcon) -> NSImage? {
        guard let target = target, let expected = PresentationTarget(target), expected.processID > 0,
              let (identity, image) = resolve(expected.processID), let current = PresentationTarget(identity),
              expected.isSameApplication(as: current) else { return nil }
        return image
    }
    private static func resolvedIcon(_ pid: pid_t) -> ([String: Any], NSImage?)? {
        guard let running = NSRunningApplication(processIdentifier: pid) else { return nil }
        let app = ResolvedApp(id: AppIdentity.canonicalID(bundleID: running.bundleIdentifier,
            url: running.bundleURL ?? running.executableURL), displayName: running.localizedName ?? "",
            pid: pid, bundleId: running.bundleIdentifier)
        guard let identity = try? AppIdentity.payload(app) else { return nil }
        return (identity, running.icon ?? running.bundleURL.map { NSWorkspace.shared.icon(forFile: $0.path) })
    }
    @objc private func controlClicked(_ sender: NSMenuItem) {
        guard sender.isEnabled, !sender.isHidden,
              let control = sender.representedObject as? [String: String],
              let id = control["id"], let method = control["method"] else { return }
        IpcServer.controlSession(id: id, method: method, recordingID: control["recording_id"])
    }
    static func phaseTitle(_ phase: String, zh: Bool) -> String {
        // Static presentation of protocol states; no intent classification.
        let titles = ["idle": ("就绪", "Ready"), "observing": ("查看中", "Observing"),
            "acting": ("操作中", "Acting"), "awaiting_permission": ("等待授权", "Awaiting permission"),
            "paused": ("已暂停", "Paused"), "stopped": ("已停止", "Stopped"),
            "focus_required": ("需要聚焦目标窗口", "Focus required"), "error": ("操作失败", "Error")]
        let title = titles[phase] ?? titles["idle"]!
        return zh ? title.0 : title.1
    }
    /// Original screen-and-pointer glyph, with a pause or stop ownership state.
    private static func templateIcon(phase: String) -> NSImage {
        let image = NSImage(size: NSSize(width: 20, height: 18), flipped: false) { _ in
            NSColor.black.setStroke()
            let screen = NSBezierPath(roundedRect: NSRect(x: 1, y: 4, width: 13, height: 10), xRadius: 2, yRadius: 2)
            screen.lineWidth = 1.4; screen.stroke()
            NSColor.black.setFill()
            let cursor = NSBezierPath()
            cursor.move(to: NSPoint(x: 12, y: 1)); cursor.line(to: NSPoint(x: 12, y: 10))
            cursor.line(to: NSPoint(x: 18.5, y: 5.5)); cursor.line(to: NSPoint(x: 15.4, y: 5))
            cursor.line(to: NSPoint(x: 17, y: 2)); cursor.line(to: NSPoint(x: 15.5, y: 1.2))
            cursor.line(to: NSPoint(x: 14, y: 4)); cursor.close(); cursor.fill()
            if phase == "paused" {
                NSBezierPath(rect: NSRect(x: 3.5, y: 6, width: 2, height: 6)).fill()
                NSBezierPath(rect: NSRect(x: 7.5, y: 6, width: 2, height: 6)).fill()
            } else if phase == "stopped" {
                NSBezierPath(rect: NSRect(x: 4, y: 6, width: 5.5, height: 5.5)).fill()
            }
            return true
        }
        image.isTemplate = true
        return image
    }
}
