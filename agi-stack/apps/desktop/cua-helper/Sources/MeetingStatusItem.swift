import AppKit

/// A user meeting remains stoppable while agent computer-use sessions are idle.
final class MeetingStatusItem: NSObject {
    static let shared = MeetingStatusItem()
    private var item: NSStatusItem?
    private var values: [String: [String: Any]] = [:]
    func update(_ receipt: [String: Any]) {
        DispatchQueue.main.async { [self] in
            guard let id = receipt["audio_session_id"] as? String else { return }
            if ["recording", "paused"].contains(receipt["state"] as? String ?? "") { values[id] = receipt }
            else { values.removeValue(forKey: id) }
            render()
        }
    }
    private func render() {
        guard !values.isEmpty else {
            if let item = item { NSStatusBar.system.removeStatusItem(item); self.item = nil }
            return
        }
        let zh = Locale.preferredLanguages.first?.hasPrefix("zh") == true
        if item == nil { item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength) }
        item?.button?.image = NSImage(systemSymbolName: "waveform", accessibilityDescription: zh ? "会议录音" : "Meeting recording")
        let menu = NSMenu()
        for (id, value) in values.sorted(by: { $0.key < $1.key }) {
            let milliseconds = value["captured_ms"] as? Int ?? 0
            let time = String(format: "%02d:%02d:%02d", milliseconds / 3_600_000,
                milliseconds / 60_000 % 60, milliseconds / 1000 % 60)
            let paused = value["state"] as? String == "paused"
            let label = (paused ? (zh ? "会议已暂停" : "Meeting paused") : (zh ? "正在录制会议" : "Recording meeting")) + " · " + time
            let heading = NSMenuItem(title: label, action: nil, keyEquivalent: ""); heading.isEnabled = false
            menu.addItem(heading)
            let stop = NSMenuItem(title: zh ? "停止并保存会议" : "Stop and save meeting", action: #selector(stopMeeting(_:)), keyEquivalent: "")
            stop.target = self; stop.representedObject = id; menu.addItem(stop)
            menu.addItem(.separator())
        }
        item?.menu = menu
    }
    @objc private func stopMeeting(_ sender: NSMenuItem) {
        if let id = sender.representedObject as? String { MeetingAudioSessions.shared.stopFromMenu(id: id) }
    }
}
