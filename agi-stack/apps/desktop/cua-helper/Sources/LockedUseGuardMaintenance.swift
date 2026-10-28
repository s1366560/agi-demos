import Foundation

/// Shared by timer ticks and every readiness/verification checkpoint. Checking
/// authority is never throttled while admitted; only healthy refreshes are
/// coalesced. A readiness deadline gates each new step, including the arm after
/// renew. An already-started step keeps its existing I/O timeouts and lock behavior.
struct LockedUseGuardMaintenance<Claim> {
    let check: () throws -> Claim
    let renew: (Claim) throws -> Void
    let arm: (Claim) throws -> Void
    let refreshed: () -> Void
    let revoke: (Error) -> Void
    var now: () -> Double = { ProcessInfo.processInfo.systemUptime }

    func run(lastRefresh: Double, force: Bool = false, deadline: Double? = nil) throws {
        func checkDeadline() throws {
            if let deadline = deadline, !(now() < deadline) {
                throw LockedUseFailure(stage: .unlockField, reason: .unlockReadinessTimeout,
                    checks: ["readiness_deadline_reached": true],
                    underlying: ActionError.failure(kind: "locked_use_unavailable",
                        message: "loginwindow readiness admission timed out"))
            }
        }
        do {
            try checkDeadline()
            let claim = try check()
            try checkDeadline()
            guard force || now() - lastRefresh >= 0.25 else { return }
            try checkDeadline()
            try renew(claim)
            try checkDeadline()
            _ = try check()
            try checkDeadline()
            try arm(claim)
            try checkDeadline()
            _ = try check()
            try checkDeadline()
            refreshed()
        } catch {
            revoke(error)
            throw error
        }
    }
}
