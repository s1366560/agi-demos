import CoreFoundation
import Foundation

/// Only protocol enums, explicitly named booleans and process exit status may
/// leave the native coordinator. Never serialize an underlying error or frame.
struct LockedUseFailure: Error {
    enum Stage: String {
        case prepare, leaseCheck = "lease_check", watchdogPrepare = "watchdog_prepare"
        case guardianLaunch = "guardian_launch", guardianIdentity = "guardian_identity"
        case guardianInitialize = "guardian_initialize", guardianProof = "guardian_proof"
        case guardianBegin = "guardian_begin", watchdogArm = "watchdog_arm"
        case authorizationBroker = "authorization_broker", guardianRenew = "guardian_renew"
        case guardianAuthorize = "guardian_authorize", guardianProcess = "guardian_process"
        case unlock, unlockLoginwindow = "unlock_loginwindow", unlockField = "unlock_field"
        case unlockSetValue = "unlock_set_value", unlockSubmit = "unlock_submit", unlockVerify = "unlock_verify"
    }
    enum Reason: String {
        case pipeClosed = "pipe_closed", pipeTimeout = "pipe_timeout", invalidFrame = "invalid_frame"
        case guardianAuthenticationFailed = "guardian_authentication_failed"
        case guardRejected = "guard_rejected", invalidRequest = "invalid_request"
        case guardianRejected = "guardian_rejected", guardianExited = "guardian_exited"
        case guardNotReady = "guard_not_ready", coverageFailed = "coverage_failed"
        case lockedUseExpired = "locked_use_expired", lockedUseUnavailable = "locked_use_unavailable"
        case userStoppedSession = "user_stopped_session", nativeOperationFailed = "native_operation_failed"
        case unlockLoginwindowAbsent = "unlock_loginwindow_absent", unlockLoginwindowAmbiguous = "unlock_loginwindow_ambiguous"
        case unlockProcessChanged = "unlock_process_changed", unlockFieldAbsent = "unlock_field_absent"
        case unlockFieldAmbiguous = "unlock_field_ambiguous", unlockFieldNotSettable = "unlock_field_not_settable"
        case unlockScanBudgetExceeded = "unlock_scan_budget_exceeded", unlockReadinessTimeout = "unlock_readiness_timeout"
        case unlockAXCannotComplete = "unlock_ax_cannot_complete", unlockAXInvalidElement = "unlock_ax_invalid_element"
        case unlockAXDisabled = "unlock_ax_disabled", unlockAXFailed = "unlock_ax_failed"
    }
    let stage: Stage
    let reason: Reason
    let checks: [String: Bool]
    let guardianRevocation: LockedUseGuardianRevocation.Record?
    let exitStatus: Int32?
    let exitReason: Process.TerminationReason?
    // Retained only to preserve the original exception returned to an action.
    // `status` intentionally never serializes it.
    let underlying: Error?

    init(stage: Stage, reason: Reason, checks: Any? = nil, guardianRevocation: Any? = nil, underlying: Error? = nil,
         exitStatus: Int32? = nil, exitReason: Process.TerminationReason? = nil) {
        self.stage = stage; self.reason = reason; self.underlying = underlying
        self.guardianRevocation = LockedUseGuardianRevocation.Record.decode(guardianRevocation)
        self.exitStatus = exitStatus; self.exitReason = exitReason
        let raw = checks as? [String: Any] ?? [:]
        var safe: [String: Bool] = [:]
        for key in ["fresh_initialization", "secret_shape_valid", "nonce_shape_valid", "parent_identity_valid",
                    "self_executable_available", "self_signing_valid", "parent_signing_valid",
                    "watchdog_identity_valid", "watchdog_signing_valid", "event_tag_valid",
                    "initialized", "suppressed", "relocking", "claim_valid",
                    "guardian_identity_matches", "binding_matches", "screen_locked",
                    "event_tap_created", "event_tap_valid", "event_tap_enabled",
                    "has_covered_display", "covered_all_displays", "topology_matches", "source_alive", "watchdog_alive",
                    "loginwindow_found", "loginwindow_unique", "scan_complete", "field_identifier_found",
                    "field_unique", "field_value_settable", "readiness_deadline_reached",
                    "scan_multiple_complete", "scan_root_children_available", "scan_root_has_children",
                    "scan_has_grandchildren", "scan_has_at_least_ten_nodes", "scan_descendant_children_unavailable"] {
            if let value = raw[key] as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() {
                safe[key] = value.boolValue
            }
        }
        self.checks = safe
    }
    var status: [String: Any] {
        var value: [String: Any] = ["stage": stage.rawValue, "reason": reason.rawValue]
        if !checks.isEmpty { value["checks"] = checks }
        if let guardianRevocation = guardianRevocation { value["guardian_revocation"] = guardianRevocation.status }
        if let exitStatus = exitStatus { value["exit_status"] = exitStatus }
        if let exitReason = exitReason {
            value["exit_reason"] = exitReason == .exit ? "exit" : "signal"
        }
        return value
    }
    static func capture(_ error: Error, stage: Stage) -> Self {
        if let failure = error as? Self { return failure }
        let reason: Reason
        switch error {
        case LockedUseWireError.closed: reason = .pipeClosed
        case LockedUseWireError.timeout: reason = .pipeTimeout
        case LockedUseWireError.invalidFrame: reason = .invalidFrame
        default: reason = .nativeOperationFailed
        }
        return Self(stage: stage, reason: reason, underlying: error)
    }
    static func result(_ response: [String: Any], stage: Stage) throws -> [String: Any] {
        guard let result = response["result"] as? [String: Any] else {
            throw Self(stage: stage, reason: .invalidFrame, underlying: LockedUseWireError.invalidFrame)
        }
        if let error = result["error"] {
            let reason: Reason
            switch error as? String {
            case "guardian_authentication_failed": reason = .guardianAuthenticationFailed
            case "guard_rejected": reason = .guardRejected
            case "invalid_request": reason = .invalidRequest
            default: reason = .guardianRejected
            }
            throw Self(stage: stage, reason: reason, checks: result["checks"],
                       guardianRevocation: result["guardian_revocation"], underlying: LockedUseWireError.invalidFrame)
        }
        return result
    }
    static func requestStage(_ method: String) -> Stage {
        switch method {
        case "initialize": return .guardianInitialize
        case "begin_guard": return .guardianBegin
        case "renew_guard": return .guardianRenew
        case "authorize_unlock": return .guardianAuthorize
        default: return .prepare
        }
    }
}
