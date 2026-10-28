/// A failed observation revokes the active generation. Re-enabling the tap
/// cannot reset suppression; only a fresh guardian starts with fresh state.
/// The callbacks read the actual native tap in production and permit pure tests.
enum LockedUseInputProtection {
    static func checkTap<T>(_ tap: T?, isValid: (T) -> Bool, isEnabled: (T) -> Bool,
                            active: inout Bool, suppressed: inout Bool, relocking: inout Bool) -> Bool {
        // Never ask whether an absent or invalid port is enabled.
        let healthy = tap.map { isValid($0) && isEnabled($0) } ?? false
        if !healthy && active {
            active = false; suppressed = true; relocking = true
        }
        return healthy && !suppressed && !relocking
    }
}
