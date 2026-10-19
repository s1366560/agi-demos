import CoreGraphics

/// Reuses the native session dictionary read by the isolated Locked Use guardian.
/// No unlock, installation, or input is performed here.
enum NativeScreenState {
    static func isLocked(_ state: [String: Any]?) -> Bool {
        state?["CGSSessionScreenIsLocked"] as? Bool == true
    }
    static func requireUnlocked(_ state: [String: Any]? = CGSessionCopyCurrentDictionary() as? [String: Any]) throws {
        if isLocked(state) {
            throw ActionError.failure(kind: "screen_locked", message: "unlock the computer before ordinary computer use")
        }
    }
}
