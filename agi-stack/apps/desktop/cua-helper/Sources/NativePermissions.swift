import AppKit
import ApplicationServices
import AVFoundation
import Carbon
import Contacts
import EventKit

/// Permission state is distinct from a feature capability. These probes never
/// request consent; the host exposes permission_request only on explicit UI use.
enum NativePermissions {
    static func status() -> [String: Any] {
        func record(_ state: String, detail: String? = nil) -> [String: Any] {
            var result: [String: Any] = ["state": state]
            if let detail = detail { result["detail"] = detail }
            return result
        }
        let ax = record(AXIsProcessTrusted() ? "granted" : "denied",
            detail: "The Accessibility API reports granted versus not granted; it cannot distinguish an unrequested grant.")
        let screen = record(CGPreflightScreenCaptureAccess() ? "granted" : "denied",
            detail: "The screen-capture preflight reports granted versus not granted; it cannot distinguish an unrequested grant.")
        let inputMonitoring = record(CGPreflightListenEventAccess() ? "granted" : "denied",
            detail: "Input Monitoring is required to distinguish owned injection from local input; this preflight never requests permission.")
        let microphone: String
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: microphone = "granted"
        case .notDetermined: microphone = "not_determined"
        default: microphone = "denied"
        }
        let calendar: String
        let eventStatus = EKEventStore.authorizationStatus(for: .event)
        if eventStatus == .notDetermined { calendar = "not_determined" }
        else if #available(macOS 14.0, *), eventStatus == .fullAccess { calendar = "granted" }
        else if eventStatus == .authorized { calendar = "granted" }
        else { calendar = "denied" }
        let contacts: String
        switch CNContactStore.authorizationStatus(for: .contacts) {
        case .authorized: contacts = "granted"
        case .notDetermined: contacts = "not_determined"
        default: contacts = "denied"
        }
        let messages: String
        if NSWorkspace.shared.urlForApplication(withBundleIdentifier: NativeMessages.bundleID) == nil {
            messages = "unavailable"
        } else {
            switch NativeMessages.permission() {
            case noErr: messages = "granted"
            case OSStatus(errAEEventWouldRequireUserConsent): messages = "not_determined"
            case OSStatus(procNotFound): messages = "unavailable"
            default: messages = "denied"
            }
        }
        return ["accessibility": ax, "input_monitoring": inputMonitoring, "screen_capture": screen, "microphone": record(microphone),
                "system_audio": screen, "calendar": record(calendar), "contacts": record(contacts),
                "messages": record(messages), "locked_use": record("unverified")]
    }
}
