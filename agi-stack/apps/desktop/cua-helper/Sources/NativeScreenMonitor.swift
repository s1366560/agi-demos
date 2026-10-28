import AppKit
import CoreGraphics

/// Idle held input must be released when the console ceases to be available.
/// Notifications cover sleep before suspension; polling also covers missed lock
/// notifications and fast-user-switch transitions. Resuming requires a new session.
final class NativeScreenMonitor {
    static let shared = NativeScreenMonitor()
    private var observers: [(NotificationCenter, NSObjectProtocol)] = []
    private var distributedObservers: [NSObjectProtocol] = []
    private var timer: DispatchSourceTimer?
    private let queue = DispatchQueue(label: "memstack.cua.console-state")

    static func unavailableReason(_ state: [String: Any]?) -> String? {
        guard let state = state else { return "console_session_unavailable" }
        if NativeScreenState.isLocked(state) { return "screen_locked" }
        if state[kCGSessionOnConsoleKey as String] as? Bool == false ||
            state[kCGSessionLoginDoneKey as String] as? Bool == false {
            return "console_session_inactive"
        }
        return nil
    }
    private static func handle(_ reason: String) {
        if reason == "screen_locked", LockedUseCoordinator.shared.handleLockEvent() { return }
        LockedUseCoordinator.shared.revokeImmediately(reason: reason)
        IpcServer.stopForSystemEvent(reason: reason)
    }
    func start() {
        guard timer == nil else { return }
        let workspace = NSWorkspace.shared.notificationCenter
        for (name, reason) in [(NSWorkspace.willSleepNotification, "system_sleep"),
            (NSWorkspace.screensDidSleepNotification, "display_sleep"),
            (NSWorkspace.sessionDidResignActiveNotification, "console_session_inactive")] {
            let observer = workspace.addObserver(forName: name, object: nil, queue: nil) { _ in
                Self.handle(reason)
            }
            observers.append((workspace, observer))
        }
        let distributed = DistributedNotificationCenter.default()
        distributedObservers.append(distributed.addObserver(
            forName: NSNotification.Name("com.apple.screenIsLocked"), object: nil, queue: nil) { _ in
                Self.handle("screen_locked")
            })
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: .milliseconds(250))
        timer.setEventHandler {
            if let reason = Self.unavailableReason(CGSessionCopyCurrentDictionary() as? [String: Any]) {
                Self.handle(reason)
            }
        }
        self.timer = timer; timer.resume()
    }
}
