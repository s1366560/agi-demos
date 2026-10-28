import Foundation

/// Read-only readiness completes before opening one short authorization window.
/// There is deliberately no retry around writes, focus, submit, or verification.
struct LockedUseUnlockExecution<Element> {
    let locate: () throws -> LockedUseLocatedField<Element>
    let checkpoint: (LockedUseProcessIdentity) throws -> Void
    let openAuthorization: () throws -> Void
    let closeAuthorization: () -> Void
    let setSentinel: (Element) throws -> Void
    let focus: (Element) throws -> Void
    let submit: () throws -> Void
    let verify: () throws -> Void

    func run() throws {
        let field = try locate()
        var stage = LockedUseFailure.Stage.unlockField
        do {
            try checkpoint(field.process)
            try openAuthorization()
            defer { closeAuthorization() }
            stage = .unlockSetValue
            try checkpoint(field.process)
            try setSentinel(field.element)
            try checkpoint(field.process)
            try focus(field.element)
            try checkpoint(field.process)
            stage = .unlockSubmit
            try submit()
            try checkpoint(field.process)
            stage = .unlockVerify
            try verify()
        } catch {
            if let failure = error as? LockedUseFailure { throw failure }
            if case ActionError.failure(let kind, _, _) = error {
                throw LockedUseFailure(stage: stage,
                    reason: LockedUseFailure.Reason(rawValue: kind) ?? .nativeOperationFailed, underlying: error)
            }
            throw LockedUseFailure.capture(error, stage: stage)
        }
    }
}
