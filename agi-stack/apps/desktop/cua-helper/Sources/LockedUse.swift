import AppKit
import ApplicationServices
import Foundation

/// Host-authorized, short-lived continuity. The ordinary execution queue never
/// owns revocation; EOF and watchdog failures can close the guardian pipe at once.
final class LockedUseCoordinator {
    static let shared = LockedUseCoordinator()
    static var configurationURL: URL {
        URL(fileURLWithPath: "/Library/Application Support/MemStack/ComputerUse/locked-use.plist")
    }
    private let lock = NSLock()
    private let channelLock = NSLock()
    private let work = DispatchQueue(label: "memstack.cua.locked-use")
    private var binding: LockedUseBinding?
    private var displayBinding = LockedUseDisplayBinding()
    private weak var session: NativeSession?
    private var deadline = 0.0
    private var approvalDeadline = 0.0
    private var attempted = false
    private var phase = "idle"
    private var reason: String?
    private var failure: LockedUseFailure?
    private var state = "available"
    private var retired: [LockedUseBinding] = []
    private var guardian: Process?
    private var guardianIdentity: LockedUseProcessIdentity?
    private var watchdogIdentity: LockedUseProcessIdentity?
    private var input: FileHandle?
    private var output: FileHandle?
    private var broker: LockedUseBroker?
    private var timer: DispatchSourceTimer?
    private var guardStarted = false
    private var recovering = false
    private var lastRefresh = 0.0
    private var unlockPending = false

    func probe() -> [String: Any] {
        LockedUseProbe(installed: { FileManager.default.fileExists(atPath: Self.configurationURL.path) },
            supportedOS: { ProcessInfo.processInfo.isOperatingSystemAtLeast(
                OperatingSystemVersion(majorVersion: 14, minorVersion: 4, patchVersion: 0)) },
            accessibility: { AXIsProcessTrusted() }, inputMonitoring: { CGPreflightListenEventAccess() },
            configuration: {
                do {
                    _ = try LockedUseManagement.configuration()
                    return .init(state: "available")
                } catch ActionError.failure(let kind, let message, _) {
                    return .init(state: kind, reason: message)
                } catch {
                    return .init(state: "failed", reason: "configuration_unavailable")
                }
            }, runtimeStatus: { self.status() }).read()
    }
    private func requirements() throws {
        guard ProcessInfo.processInfo.isOperatingSystemAtLeast(OperatingSystemVersion(majorVersion: 14, minorVersion: 4, patchVersion: 0)) else {
            throw ActionError.failure(kind: "unsupported", message: "macos_14_4_required")
        }
        guard AXIsProcessTrusted(), CGPreflightListenEventAccess() else {
            throw ActionError.failure(kind: "permission_required", message: "accessibility_and_input_monitoring_required")
        }
        _ = try LockedUseManagement.configuration()
    }
    private func status() -> [String: Any] {
        lock.lock(); defer { lock.unlock() }
        var result: [String: Any] = ["state": state, "enabled": binding != nil,
            "phase": phase, "requires_manual_unlock": state == "suppressed" || state == "failed"]
        displayBinding.append(to: &result, active: binding)
        if let reason = reason { result["reason"] = reason }
        if let failure = failure { result["failure"] = failure.status }
        return result
    }
    static func hostBinding(_ params: [String: Any], session: NativeSession) throws -> (LockedUseBinding, Double) {
        guard let run = params["run_id"] as? String, run == session.owner["run_id"],
              let generation = params["generation"] as? String,
              let ttl = params["ttl_ms"] as? NSNumber, CFGetTypeID(ttl) != CFBooleanGetTypeID(),
              ttl.doubleValue.isFinite, ttl.doubleValue.rounded() == ttl.doubleValue,
              (1000...10000).contains(ttl.intValue) else {
            throw ActionError.failure(kind: "invalid_params", message: "run_id, generation and an integer ttl_ms from 1000 through 10000 are required")
        }
        let binding = LockedUseBinding(sessionID: session.id, runID: run, generation: generation)
        guard binding.valid else { throw ActionError.failure(kind: "invalid_params", message: "invalid lock-continuity binding") }
        return (binding, Double(ttl.intValue) / 1000)
    }
    func enable(_ session: NativeSession, params: [String: Any]) throws -> [String: Any] {
        let (next, ttl) = try Self.hostBinding(params, session: session)
        try session.cancellation.check()
        return try work.sync {
            try requirements()
            lock.lock()
            guard !recovering, binding == nil || binding == next, !retired.contains(next) else {
                lock.unlock(); throw ActionError.failure(kind: "locked_use_unavailable", message: "a fresh, exclusive continuity generation is required")
            }
            displayBinding.began()
            binding = next; self.session = session; deadline = ProcessInfo.processInfo.systemUptime + ttl
            state = "active"; reason = nil; failure = nil
            if guardian == nil { phase = "armed" }
            lock.unlock()
            startTimer()
            if LockedUseRelock.systemLocked() {
                // Reply before the potentially slow OS authorization flow so
                // the host can begin renewing the short lease immediately.
                work.async { [self] in
                    do { try prepare(next) }
                    catch { revokeImmediately(reason: "unlock_failed", expected: next,
                        failure: diagnostic(error, stage: .prepare)) }
                }
            }
            return status()
        }
    }
    /// This method is called directly by the authenticated IPC reader, so a
    /// long-running application request cannot prevent host lease renewal.
    func renew(_ session: NativeSession, params: [String: Any]) throws -> [String: Any] {
        let (next, ttl) = try Self.hostBinding(params, session: session)
        try session.cancellation.check()
        lock.lock()
        guard binding == next, deadline > ProcessInfo.processInfo.systemUptime, !recovering else {
            lock.unlock(); throw ActionError.failure(kind: "locked_use_expired", message: "the continuity generation is no longer active")
        }
        deadline = ProcessInfo.processInfo.systemUptime + ttl
        lock.unlock()
        return status()
    }
    func disable(_ session: NativeSession, params: [String: Any]) throws -> [String: Any] {
        lock.lock()
        let current = binding
        let valid = current == nil || (current?.sessionID == session.id
            && (params["generation"] == nil || params["generation"] as? String == current?.generation))
        lock.unlock()
        guard valid else { throw ActionError.failure(kind: "locked_use_expired", message: "the continuity generation changed") }
        revokeImmediately(sessionID: session.id, reason: "disabled")
        return status()
    }
    func end(sessionID: String? = nil) { revokeImmediately(sessionID: sessionID, reason: "session_ended") }
    func revokeImmediately(sessionID: String? = nil, reason: String, expected: LockedUseBinding? = nil,
                           failure: LockedUseFailure? = nil) {
        lock.lock()
        guard let current = binding, sessionID == nil || current.sessionID == sessionID,
              expected == nil || current == expected else { lock.unlock(); return }
        let mustLock = guardStarted
        let ownedSession = session, pipe = input, reader = output, authorization = broker
        displayBinding.ended(current)
        binding = nil; deadline = 0; approvalDeadline = 0; attempted = true
        input = nil; output = nil; broker = nil; guardian = nil; guardianIdentity = nil; watchdogIdentity = nil
        guardStarted = false; recovering = mustLock
        retired.append(current); if retired.count > 128 { retired.removeFirst() }
        self.reason = reason; self.failure = failure
        state = ["disabled", "session_ended"].contains(reason) ? "available" : "suppressed"
        phase = mustLock ? "relocking" : "idle"
        lock.unlock()
        // Cancellation and authorization invalidation precede any queue work.
        if mustLock { ownedSession?.cancel(); AudioCapture.shared.endSoon(current.sessionID, reason: "revoked") }
        authorization?.stop()
        try? pipe?.close(); try? reader?.close()
        work.async {
            if mustLock {
                SyntheticInput.shared.releaseSession(current.sessionID, phase: "paused", reason: reason)
                HeldInput.shared.release(current.sessionID)
            }
            SyntheticInput.shared.clearLockedUse(current)
        }
        if mustLock {
            DispatchQueue.global(qos: .userInitiated).async { [self] in
                let recovery = LockedUseRelock()
                while !recovery.step() { Thread.sleep(forTimeInterval: 0.1) }
                lock.lock(); recovering = false
                if displayBinding.canDisplayRelockCompletion(current, active: binding) { phase = "idle" }
                lock.unlock()
            }
        }
    }
    /// A permitted lock transition is handled on a dedicated queue. Sleep,
    /// logout and fast-user switching never take this path.
    func handleLockEvent() -> Bool {
        lock.lock()
        let current = binding
        let admitted = current != nil && !recovering && deadline > ProcessInfo.processInfo.systemUptime
            && session?.inputStopPhase == nil
        let scheduled = unlockPending
        if admitted { unlockPending = true }
        lock.unlock()
        guard admitted, let current = current else { return false }
        if scheduled { return true }
        work.async { [self] in
            defer { lock.lock(); unlockPending = false; lock.unlock() }
            do { try prepare(current) }
            catch { revokeImmediately(reason: "unlock_failed", expected: current,
                failure: diagnostic(error, stage: .prepare)) }
        }
        return true
    }
    func ensureUnlocked(_ session: NativeSession) throws {
        guard LockedUseRelock.systemLocked() else { return }
        lock.lock(); let current = binding; lock.unlock()
        guard let current = current, current.sessionID == session.id else { try NativeScreenState.requireUnlocked(); return }
        do { try work.sync { try prepare(current) } }
        catch {
            revokeImmediately(reason: "unlock_failed", expected: current, failure: diagnostic(error, stage: .prepare))
            throw (error as? LockedUseFailure)?.underlying ?? error
        }
        try NativeScreenState.requireUnlocked()
    }
    private func startTimer() {
        guard timer == nil else { return }
        let timer = DispatchSource.makeTimerSource(queue: work)
        timer.schedule(deadline: .now() + 0.1, repeating: 0.1)
        timer.setEventHandler { [weak self] in self?.tick() }
        timer.resume(); self.timer = timer
    }
    private func tick() {
        lock.lock(); let current = binding, until = deadline, child = guardianIdentity
        let stopped = session?.inputStopPhase != nil; lock.unlock()
        guard let current = current else { return }
        let now = ProcessInfo.processInfo.systemUptime
        guard now < until, !stopped, AXIsProcessTrusted(), CGPreflightListenEventAccess() else {
            revokeImmediately(reason: "lease_expired", expected: current); return
        }
        guard child != nil else { return }
        do { try maintainGuard(current) } catch { /* maintainGuard revokes synchronously. */ }
    }
    /// Readiness and verification run on `work`, so they must renew supervision
    /// themselves instead of starving the timer on the same serial queue.
    private func maintainGuard(_ expected: LockedUseBinding, force: Bool = false,
                               readinessDeadline: Double? = nil) throws {
        var stage = LockedUseFailure.Stage.leaseCheck
        let maintenance = LockedUseGuardMaintenance(check: {
            stage = .leaseCheck
            let (session, until) = try self.current(expected)
            guard session.inputStopPhase == nil else {
                throw ActionError.failure(kind: "user_stopped_session", message: "computer use was stopped")
            }
            guard AXIsProcessTrusted(), CGPreflightListenEventAccess() else {
                throw ActionError.failure(kind: "permission_required", message: "accessibility_and_input_monitoring_required")
            }
            self.lock.lock(); let child = self.guardianIdentity, watcher = self.watchdogIdentity; self.lock.unlock()
            stage = .guardianRenew
            guard let child = child, child.alive, watcher?.alive == true else {
                throw LockedUseFailure(stage: stage, reason: .guardNotReady,
                    checks: ["source_alive": child?.alive == true, "watchdog_alive": watcher?.alive == true])
            }
            return LockedUseSupervisionClaim(binding: expected, guardian: child, expiresAtUptime: until)
        }, renew: { claim in
            stage = .guardianRenew
            let response = try self.request("renew_guard", ["claim": try self.object(claim)])
            guard response["ready"] as? Bool == true else {
                throw LockedUseFailure(stage: stage, reason: .guardNotReady,
                    checks: response["checks"], guardianRevocation: response["guardian_revocation"],
                    underlying: LockedUseWireError.closed)
            }
        }, arm: { claim in
            stage = .watchdogArm
            try SyntheticInput.shared.armLockedUse(claim)
        }, refreshed: {
            self.lastRefresh = ProcessInfo.processInfo.systemUptime
        }, revoke: { error in
            self.revokeImmediately(reason: "guardian_unavailable", expected: expected,
                failure: self.diagnostic(error, stage: stage))
        })
        do { try maintenance.run(lastRefresh: lastRefresh, force: force, deadline: readinessDeadline) }
        catch { throw diagnostic(error, stage: stage) }
    }
    private func current(_ expected: LockedUseBinding) throws -> (NativeSession, Double) {
        lock.lock(); defer { lock.unlock() }
        guard binding == expected, let session = session, deadline > ProcessInfo.processInfo.systemUptime,
              !recovering else { throw ActionError.failure(kind: "locked_use_expired", message: "the host continuity lease expired") }
        try session.cancellation.check()
        return (session, deadline)
    }
    private func prepare(_ expected: LockedUseBinding) throws {
        var stage = LockedUseFailure.Stage.leaseCheck
        do {
            let (session, _) = try current(expected)
            guard LockedUseRelock.systemLocked() else { return }
            lock.lock(); let existing = guardianIdentity; lock.unlock()
            if existing == nil {
                SyntheticInput.shared.releaseSession(session.id, phase: "paused", reason: "screen_locked")
                HeldInput.shared.release(session.id)
                stage = .watchdogPrepare
                let watcher = try SyntheticInput.shared.prepareLockedUse(session.id)
                let child = Process(), incoming = Pipe(), outgoing = Pipe()
                child.executableURL = LockedUseManagement.componentRoot.appendingPathComponent("memstack-cua-guardian")
                child.standardInput = incoming; child.standardOutput = outgoing; child.standardError = FileHandle.standardError
                child.terminationHandler = { [weak self] child in
                    self?.revokeImmediately(reason: "guardian_exited", expected: expected,
                        failure: LockedUseFailure(stage: .guardianProcess, reason: .guardianExited,
                            exitStatus: child.terminationStatus, exitReason: child.terminationReason))
                }
                stage = .guardianLaunch
                try child.run()
                stage = .guardianIdentity
                guard let identity = LockedUseProcessIdentity.current(child.processIdentifier) else { throw LockedUseWireError.closed }
                lock.lock()
                guard binding == expected else {
                    lock.unlock(); try? incoming.fileHandleForWriting.close(); try? outgoing.fileHandleForReading.close()
                    throw LockedUseWireError.closed
                }
                guardian = child; guardianIdentity = identity; watchdogIdentity = watcher.identity
                input = incoming.fileHandleForWriting; output = outgoing.fileHandleForReading; lock.unlock()
                let secret = UUID().uuidString + UUID().uuidString, nonce = UUID().uuidString
                stage = .guardianInitialize
                let initialized = try request("initialize", ["secret": secret, "nonce": nonce,
                    "watchdog": try object(watcher.identity), "event_tag": watcher.tag], timeout: 3)
                stage = .guardianProof
                guard initialized["nonce"] as? String == nonce,
                      initialized["proof"] as? String == IpcServer.proof(secret: secret, nonce: nonce) else { throw LockedUseWireError.invalidFrame }
                // Launch and authentication may consume the earlier host lease.
                // Take the current authorized expiry once; pending coverage cannot extend it.
                stage = .leaseCheck
                let (_, until) = try current(expected)
                let claim = LockedUseSupervisionClaim(binding: expected, guardian: identity, expiresAtUptime: until)
                lock.lock()
                guard binding == expected else { lock.unlock(); throw LockedUseWireError.closed }
                guardStarted = true; phase = "covering"; lock.unlock()
                stage = .guardianBegin
                let ready = try request("begin_guard", ["claim": try object(claim)],
                    timeout: LockedUseCoverageState.beginReplyTimeout, expiresAtUptime: claim.expiresAtUptime)
                guard ready["ready"] as? Bool == true, (ready["covered_displays"] as? Int ?? 0) > 0 else {
                    throw LockedUseFailure(stage: .guardianBegin, reason: .coverageFailed, checks: ready["checks"],
                        guardianRevocation: ready["guardian_revocation"],
                        underlying: ActionError.failure(kind: "coverage_failed", message: "guardian did not cover every display"))
                }
                stage = .watchdogArm
                try SyntheticInput.shared.armLockedUse(claim)
                stage = .authorizationBroker
                let authorization = try LockedUseBroker(socketURL: LockedUseManagement.socketURL) { [weak self] in
                    self?.approve(expected) == true
                }
                lock.lock()
                guard binding == expected else { lock.unlock(); authorization.stop(); throw LockedUseWireError.closed }
                broker = authorization; lock.unlock()
            }
            stage = .leaseCheck
            _ = try current(expected)
            // Renew against the current guardian state before any AX readiness
            // work; process liveness alone cannot authorize a suppressed guard.
            stage = .guardianRenew
            try maintainGuard(expected, force: true)
            stage = .unlock
            try unlock(expected)
            session.requestObservationRefresh()
            lock.lock(); if binding == expected { phase = "guarded" }; lock.unlock()
        } catch { throw diagnostic(error, stage: stage) }
    }
    private func diagnostic(_ error: Error, stage: LockedUseFailure.Stage) -> LockedUseFailure {
        if let failure = error as? LockedUseFailure { return failure }
        if case ActionError.failure(let kind, _, _) = error {
            return LockedUseFailure(stage: stage,
                reason: LockedUseFailure.Reason(rawValue: kind) ?? .nativeOperationFailed, underlying: error)
        }
        return LockedUseFailure.capture(error, stage: stage)
    }
    private func approve(_ expected: LockedUseBinding) -> Bool {
        lock.lock()
        let now = ProcessInfo.processInfo.systemUptime
        guard binding == expected, phase == "unlocking", !attempted, now < approvalDeadline, now < deadline,
              guardianIdentity?.alive == true, watchdogIdentity?.alive == true else { lock.unlock(); return false }
        attempted = true; lock.unlock()
        guard let reply = try? request("authorize_unlock", ["binding": object(expected)]),
              reply["authorized"] as? Bool == true else { return false }
        lock.lock(); defer { lock.unlock() }
        let checked = ProcessInfo.processInfo.systemUptime
        return binding == expected && phase == "unlocking" && checked < approvalDeadline && checked < deadline
    }
    private func unlock(_ expected: LockedUseBinding) throws {
        let locator = LockedUseFieldLocator(access: LockedUseFieldAccess<AXUIElement>.loginwindow,
            checkpoint: { until in try self.maintainGuard(expected, readinessDeadline: until) })
        let execution = LockedUseUnlockExecution(locate: locator.locate,
            checkpoint: { process in
                try self.maintainGuard(expected)
                guard process.alive else {
                    throw LockedUseFailure(stage: .unlockField, reason: .unlockProcessChanged,
                        underlying: ActionError.failure(kind: "locked_use_unavailable", message: "loginwindow changed"))
                }
            }, openAuthorization: {
                _ = try self.current(expected)
                self.lock.lock(); defer { self.lock.unlock() }
                let now = ProcessInfo.processInfo.systemUptime
                guard self.binding == expected, self.deadline > now, !self.recovering else {
                    throw ActionError.failure(kind: "locked_use_expired", message: "the host continuity lease expired")
                }
                self.phase = "unlocking"; self.attempted = false
                self.approvalDeadline = min(self.deadline, now + 5)
            }, closeAuthorization: {
                self.lock.lock(); self.approvalDeadline = 0; self.lock.unlock()
            }, setSentinel: { field in
                guard AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString,
                    UUID().uuidString as CFString) == .success else {
                    throw ActionError.failure(kind: "locked_use_unavailable", message: "loginwindow rejected the authorization sentinel")
                }
            }, focus: { field in
                guard AXUIElementSetAttributeValue(field, kAXFocusedAttribute as CFString, kCFBooleanTrue) == .success else {
                    throw ActionError.failure(kind: "locked_use_unavailable", message: "loginwindow rejected focus")
                }
            }, submit: { try SyntheticInput.shared.submitLockedUseUnlock(expected) }, verify: {
                let until = ProcessInfo.processInfo.systemUptime + 5
                while ProcessInfo.processInfo.systemUptime < until {
                    try self.maintainGuard(expected)
                    if LockedUseUnlockVerification.isUnlocked(CGSessionCopyCurrentDictionary() as? [String: Any],
                        expectedUserID: getuid()) { return }
                    Thread.sleep(forTimeInterval: 0.05)
                }
                throw ActionError.failure(kind: "locked_use_unavailable", message: "native unlock verification timed out")
            })
        do { try execution.run() }
        catch { throw diagnostic(error, stage: .unlock) }
    }
    private func object<T: Encodable>(_ value: T) throws -> Any {
        try JSONSerialization.jsonObject(with: JSONEncoder().encode(value))
    }
    private func request(_ method: String, _ params: [String: Any], timeout: Double = 0.5,
                         expiresAtUptime: Double? = nil) throws -> [String: Any] {
        channelLock.lock(); defer { channelLock.unlock() }
        lock.lock(); let writer = input, reader = output; lock.unlock()
        guard let writer = writer, let reader = reader else { throw LockedUseWireError.closed }
        try LockedUseWire.write(["jsonrpc": "2.0", "id": 1, "method": method, "params": params], fd: writer.fileDescriptor)
        // Compute after writing: a delayed pipe write must not extend the claim's read bound.
        let now = ProcessInfo.processInfo.systemUptime
        let readTimeout = expiresAtUptime.map { min(timeout, $0 - now) } ?? timeout
        guard readTimeout.isFinite, readTimeout > 0 else { throw LockedUseWireError.timeout }
        let response = try LockedUseWire.read(reader.fileDescriptor, timeout: readTimeout)
        return try LockedUseFailure.result(response, stage: LockedUseFailure.requestStage(method))
    }
}
