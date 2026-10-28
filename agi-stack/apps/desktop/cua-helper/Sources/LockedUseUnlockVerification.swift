import CoreFoundation
import CoreGraphics
import Foundation

/// Used only after the current locked-use attempt observed a locked console.
/// A missing lock marker is accepted only within a positively identified,
/// active, logged-in GUI session; an unavailable or malformed state never is.
enum LockedUseUnlockVerification {
    static func isUnlocked(_ state: [String: Any]?, expectedUserID: UInt32) -> Bool {
        guard let state = state,
              boolean(state[kCGSessionOnConsoleKey as String]) == true,
              boolean(state[kCGSessionLoginDoneKey as String]) == true,
              userID(state[kCGSessionUserIDKey as String]) == expectedUserID else { return false }
        guard let lock = state["CGSSessionScreenIsLocked"] else { return true }
        return boolean(lock) == false
    }
    private static func boolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }
    private static func userID(_ value: Any?) -> UInt32? {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFNumberGetTypeID(),
              !CFNumberIsFloatType(number as CFNumber) else { return nil }
        var integer: Int64 = 0
        guard CFNumberGetValue(number as CFNumber, .sInt64Type, &integer) else { return nil }
        return UInt32(exactly: integer)
    }
}
