import Foundation

/// A revoked binding attributes status only. It never grants execution authority.
struct LockedUseDisplayBinding {
    private(set) var revoked: LockedUseBinding?

    mutating func began() { revoked = nil }
    mutating func ended(_ binding: LockedUseBinding) { revoked = binding }

    func append(to value: inout [String: Any], active: LockedUseBinding?) {
        if let active = active {
            value["session_id"] = active.sessionID
            value["run_id"] = active.runID
            value["generation"] = active.generation
        } else if let revoked = revoked {
            value["revoked_binding"] = ["session_id": revoked.sessionID,
                "run_id": revoked.runID, "generation": revoked.generation]
        }
    }

    func canDisplayRelockCompletion(_ expected: LockedUseBinding, active: LockedUseBinding?) -> Bool {
        active == nil && revoked == expected
    }
}
