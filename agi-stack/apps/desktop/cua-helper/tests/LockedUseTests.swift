import AppKit
import Darwin
import Foundation

enum LockedUseTests {
    static func run() throws {
        try LockedUseUnlockTests.run()
        try unlockVerification()
        try inputProtection()
        try diagnostics()
        try guardianRevocationWireRegression()
        try guardianInputEventWireRegression()
        try guardianInputEventDiagnostics()
        try guardianRevocationDiagnostics()
        try probeSnapshot()
        displayBinding()
        configurationPermissions()
        installationErrors()
        let binding = LockedUseBinding(sessionID: "session", runID: "run", generation: "generation")
        let guardian = LockedUseProcessIdentity(pid: 42, startSeconds: 100, startMicroseconds: 200)
        let claim = LockedUseSupervisionClaim(binding: binding, guardian: guardian, expiresAtUptime: 110)
        var supervision = LockedUseSupervision()
        precondition(supervision.accept(claim, now: 100))
        // Repeating the ordinary input heartbeat cannot extend host authority.
        precondition(supervision.accept(claim, now: 109))
        supervision.check(now: 110, guardianAlive: true)
        precondition(supervision.mustRelock && supervision.reason == "lease_expired")
        precondition(!supervision.accept(claim, now: 100))
        supervision.confirmLocked()
        precondition(supervision.claim == nil && !supervision.mustRelock)
        precondition(supervision.accept(claim, now: 100))
        let different = LockedUseSupervisionClaim(binding: LockedUseBinding(
            sessionID: "session", runID: "other-run", generation: "generation"),
            guardian: guardian, expiresAtUptime: 110)
        precondition(!supervision.accept(different, now: 100))
        let reused = LockedUseSupervisionClaim(binding: binding, guardian: LockedUseProcessIdentity(
            pid: 42, startSeconds: 101, startMicroseconds: 200), expiresAtUptime: 110)
        precondition(!supervision.accept(reused, now: 100))
        supervision.check(now: 101, guardianAlive: false)
        precondition(supervision.mustRelock && supervision.reason == "guardian_exited")
        supervision.confirmLocked()
        precondition(supervision.accept(claim, now: 100))
        precondition(supervision.accept(nil, now: 101))
        precondition(supervision.mustRelock && supervision.reason == "lease_released")
        for expiry in [100, 111, Double.infinity, Double.nan] {
            let invalid = LockedUseSupervisionClaim(binding: binding, guardian: guardian, expiresAtUptime: expiry)
            precondition(!invalid.valid(now: 100))
        }
        let me = LockedUseProcessIdentity.current(getpid())!
        precondition(me.alive)
        precondition(!LockedUseProcessIdentity(pid: me.pid, startSeconds: me.startSeconds + 1,
            startMicroseconds: me.startMicroseconds).alive)
        var nativeLocked = false, requests = 0
        let recovery = LockedUseRelock(locked: { nativeLocked }, request: { requests += 1 })
        precondition(!recovery.step(now: 1) && requests == 1)
        precondition(!recovery.step(now: 1.1) && requests == 1)
        precondition(!recovery.step(now: 1.5) && requests == 2)
        nativeLocked = true
        precondition(recovery.step(now: 2) && requests == 2)
        let owner = Dictionary(uniqueKeysWithValues: Sessions.ownerFields.map { ($0, "lock-test-" + $0) })
        let session = try NativeSession(id: "lock-binding-test", owner: owner)
        defer { try? FileManager.default.removeItem(at: session.artifactDirectory) }
        let params: [String: Any] = ["run_id": owner["run_id"]!, "generation": "gen", "ttl_ms": 10000]
        let admitted = try LockedUseCoordinator.hostBinding(params, session: session)
        precondition(admitted.0.runID == owner["run_id"] && admitted.1 == 10)
        for invalid: Any in [true, 999, 10001, 1000.5, "1000", Double.infinity] {
            var rejected = params; rejected["ttl_ms"] = invalid
            do { _ = try LockedUseCoordinator.hostBinding(rejected, session: session)
                preconditionFailure("invalid host lease accepted") } catch {}
        }
        for field in ["run_id", "generation"] {
            var rejected = params; rejected[field] = ""
            do { _ = try LockedUseCoordinator.hostBinding(rejected, session: session)
                preconditionFailure("invalid host binding accepted") } catch {}
        }
        let cancelledInstallation = session.cancellation
        session.cancel()
        try session.reset()
        try session.cancellation.check()
        for install in [true, false] {
            do {
                _ = try LockedUseManagement.install(install, cancellation: cancelledInstallation,
                    generation: session.inputGeneration)
                preconditionFailure("cancelled management request reached administrator authorization")
            } catch ActionError.failure(let kind, _, _) {
                precondition(kind == "user_stopped_session")
            }
        }
        try wire()
        print("LOCKED_USE_SUPERVISION_OK")
    }
    static func guardianRevocationWireRegression() throws {
        struct Failure: Error { let message: String }
        let revocation: [String: Any] = ["source": "event_tap_input", "event_type": "mouse_moved",
            "checks": ["was_active": true, "was_pending": false, "sender_is_source": false]]
        do {
            _ = try LockedUseFailure.result(["result": ["error": "guard_rejected",
                "guardian_revocation": revocation]], stage: .guardianRenew)
            throw Failure(message: "guard rejection was accepted")
        } catch let failure as LockedUseFailure {
            guard let observed = failure.status["guardian_revocation"] as? [String: Any],
                  NSDictionary(dictionary: observed).isEqual(to: revocation) else {
                throw Failure(message: "the original guardian revocation was discarded by the request failure")
            }
        }
        print("LOCKED_USE_FIRST_REVOCATION_WIRE_OK")
    }

    static func guardianInputEventWireRegression() throws {
        struct Failure: Error { let message: String }
        let input: [String: Any] = ["source_pid": 1234, "ns_event_type": "mouse_down",
            "cg_event_type": "mouse_down", "received_uptime_seconds": 100.75,
            "ns_timestamp_seconds": 99.25, "cg_timestamp_seconds": 99.25,
            "coverage_begin_uptime_seconds": 100.0, "coverage_ready_uptime_seconds": 100.5]
        let revocation: [String: Any] = ["source": "global_monitor_input", "event_type": "mouse_down",
            "checks": ["was_active": true, "sender_is_source": false], "input_event": input]
        let wire = try JSONSerialization.jsonObject(with: JSONSerialization.data(withJSONObject:
            ["result": ["error": "guard_rejected", "guardian_revocation": revocation]])) as! [String: Any]
        do {
            _ = try LockedUseFailure.result(wire, stage: .guardianRenew)
            throw Failure(message: "guard rejection was accepted")
        } catch let failure as LockedUseFailure {
            guard let observed = failure.status["guardian_revocation"] as? [String: Any],
                  NSDictionary(dictionary: observed).isEqual(to: revocation) else {
                throw Failure(message: "first input sender and event timing were lost across guardian failure JSON")
            }
        }
        let notReady = try LockedUseFailure.result(["result": ["ready": false,
            "guardian_revocation": revocation]], stage: .guardianBegin)
        let unavailable = LockedUseFailure(stage: .guardianBegin, reason: .coverageFailed,
            guardianRevocation: notReady["guardian_revocation"])
        let wrapped = LockedUseFailure.capture(unavailable, stage: .prepare)
        guard let preserved = wrapped.status["guardian_revocation"] as? [String: Any],
              NSDictionary(dictionary: preserved).isEqual(to: revocation) else {
            throw Failure(message: "ready=false or failure wrapping dropped first input metadata")
        }
        print("LOCKED_USE_FIRST_INPUT_WIRE_OK")
    }

    static func guardianInputEventDiagnostics() throws {
        struct Failure: Error { let message: String }
        var assertions = 0
        func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
            assertions += 1
            if !condition() { throw Failure(message: message) }
        }
        typealias Trace = LockedUseGuardianRevocation
        typealias Input = Trace.InputEvent
        let keys = ["received_uptime_seconds", "ns_timestamp_seconds", "cg_timestamp_seconds",
            "coverage_begin_uptime_seconds", "coverage_ready_uptime_seconds"]
        let raw: [String: Any] = ["source_pid": Int32.max, "ns_event_type": "mouse_down",
            "cg_event_type": "mouse_up", "received_uptime_seconds": 101.25,
            "ns_timestamp_seconds": 99.5, "cg_timestamp_seconds": 99.75,
            "coverage_begin_uptime_seconds": 100.0, "coverage_ready_uptime_seconds": 100.5]
        let input = Input.decode(raw)!
        try expect(NSDictionary(dictionary: input.status).isEqual(to: raw), "paired raw observations were altered")
        try expect(input.nsEventType == .mouseDown && input.cgEventType == .mouseUp,
            "different native and CG event types must remain distinguishable")
        let json = try JSONSerialization.data(withJSONObject: input.status)
        let roundTrip = Input.decode(try JSONSerialization.jsonObject(with: json))!
        try expect(NSDictionary(dictionary: roundTrip.status).isEqual(to: raw), "JSON changed sender or event timing")
        for value: Any in [true, false, "0", "123", NSNull(), [], ["value": 1], -1, 1.5,
                            Int64(Int32.max) + 1, Double.nan, Double.infinity] {
            try expect(Input.decode(["source_pid": value]) == nil, "invalid PID was coerced or truncated")
        }
        for value in [Int32(0), 123, Int32.max] {
            try expect(Input.decode(["source_pid": value])?.sourcePID == value, "an observed integer PID was lost")
        }
        for key in keys {
            for value: Any in [true, false, "1.5", NSNull(), [], -0.1, Double.nan,
                              Double.infinity, -Double.infinity, Input.maximumTimestampSeconds.nextUp] {
                try expect(Input.decode([key: value]) == nil, "invalid time escaped finite protocol bounds")
            }
            for value in [0.0, 0.25, Input.maximumTimestampSeconds] {
                try expect(Input.decode([key: value])?.status[key] as? Double == value,
                    "zero or a valid timestamp was lost")
            }
        }
        let future = Input.decode(["received_uptime_seconds": 10.0, "cg_timestamp_seconds": 11.0])!
        try expect(future.cgTimestampSeconds == 11, "future event time was silently normalized")
        let hid = Input(sourcePID: 0, nsEventType: nil, cgEventType: .mouseDown,
            receivedUptimeSeconds: 0, nsTimestampSeconds: nil, cgTimestampSeconds: 0,
            coverageBeginUptimeSeconds: nil, coverageReadyUptimeSeconds: nil)
        try expect(hid.sourcePID == 0 && hid.cgTimestampSeconds == 0 && hid.receivedUptimeSeconds == 0,
            "an observed zero must remain zero")
        try expect(hid.nsEventType == nil && hid.nsTimestampSeconds == nil
            && hid.coverageBeginUptimeSeconds == nil && hid.coverageReadyUptimeSeconds == nil,
            "unobserved NS event or coverage times were fabricated")
        let invalidCapture = Input(sourcePID: -1, nsEventType: nil, cgEventType: .unknown,
            receivedUptimeSeconds: .nan, nsTimestampSeconds: -.infinity, cgTimestampSeconds: -1,
            coverageBeginUptimeSeconds: .infinity, coverageReadyUptimeSeconds: Input.maximumTimestampSeconds.nextUp)
        try expect(invalidCapture.status.count == 1, "native capture did not apply the same numeric bounds")
        for (type, expected) in [(NSEvent.EventType.leftMouseDown, Trace.EventType.mouseDown),
                                 (.rightMouseUp, .mouseUp), (.keyDown, .keyDown), (.keyUp, .keyUp),
                                 (.flagsChanged, .flagsChanged), (.mouseMoved, .mouseMoved),
                                 (.otherMouseDragged, .mouseDragged), (.scrollWheel, .scroll), (.appKitDefined, .unknown)] {
            try expect(Trace.EventType(type) == expected, "native event type was not a closed category")
        }
        let unknown = Input.decode(["source_pid": 123, "ns_event_type": "PRIVATE_EVENT",
            "cg_event_type": "PRIVATE_EVENT", "path": "PRIVATE_PATH", "keycode": 7, "coordinates": [1, 2]])!
        try expect(unknown.nsEventType == .unknown && unknown.cgEventType == .unknown,
            "unknown input types impersonated known categories")
        let text = String(data: try JSONSerialization.data(withJSONObject: unknown.status), encoding: .utf8)!
        try expect(!text.contains("PRIVATE_") && !text.contains("path") && !text.contains("keycode")
            && !text.contains("coordinates"), "unapproved event data escaped serialization")
        let legacy = Trace.Record(source: .globalMonitorInput, eventType: .mouseDown)
        try expect(legacy.status["input_event"] == nil, "legacy record acquired an empty input event")
        for malformed: Any in [NSNull(), "PRIVATE_VALUE", [], [:], ["source_pid": true]] {
            let decoded = Trace.Record.decode(["source": "global_monitor_input", "input_event": malformed])!
            try expect(decoded.status["input_event"] == nil, "invalid input event was published")
        }
        var coverage = LockedUseCoverageState()
        try expect(coverage.beginUptimeSeconds == nil && coverage.readyUptimeSeconds == nil,
            "unstarted coverage has fabricated causal times")
        try expect(coverage.begin(now: 10, expiresAt: 10) == nil && coverage.beginUptimeSeconds == nil,
            "rejected begin published an observed start")
        let token = coverage.begin(now: 10, expiresAt: 15)!
        try expect(coverage.beginUptimeSeconds == 10 && coverage.readyUptimeSeconds == nil,
            "begin recorded readiness before publication")
        let pending = LockedUseCoverageReport(topologyMatches: true, complete: false, coveredDisplays: 0, failure: nil)
        let ready = LockedUseCoverageReport(topologyMatches: true, complete: true, coveredDisplays: 2, failure: nil)
        _ = coverage.advance(token: UUID(), now: 10.1, report: ready, leaseValid: true, dependenciesHealthy: true)
        _ = coverage.advance(token: token, now: 10.2, report: pending, leaseValid: true, dependenciesHealthy: true)
        try expect(coverage.readyUptimeSeconds == nil && coverage.pending, "stale or incomplete publication became ready")
        _ = coverage.advance(token: token, now: 10.5, report: ready, leaseValid: true, dependenciesHealthy: true)
        try expect(coverage.active && coverage.readyUptimeSeconds == 10.5, "readiness did not retain its transition clock")
        let observed = Input(sourcePID: 123, nsEventType: .mouseDown, cgEventType: .mouseDown,
            receivedUptimeSeconds: 10.75, nsTimestampSeconds: 9.5, cgTimestampSeconds: 9.5,
            coverageBeginUptimeSeconds: coverage.beginUptimeSeconds, coverageReadyUptimeSeconds: coverage.readyUptimeSeconds)
        var trace = Trace()
        trace.record(.capturing(source: .globalMonitorInput, checks: coverage.diagnosticState, inputEvent: observed))
        let first = trace.first!.status
        coverage.revoke(); coverage.confirmLocked()
        trace.record(.capturing(source: .eventTapInput, checks: coverage.diagnosticState, inputEvent: hid))
        try expect(coverage.suppressed && !coverage.active && !coverage.pending && !coverage.relocking,
            "diagnostics changed revoke or lock confirmation")
        try expect(coverage.beginUptimeSeconds == 10 && coverage.readyUptimeSeconds == 10.5,
            "recovery destroyed the original coverage times")
        try expect(NSDictionary(dictionary: trace.first!.status).isEqual(to: first),
            "later event or recovery overwrote the first input cause")
        try expect(coverage.begin(now: 11, expiresAt: 15) == nil && coverage.beginUptimeSeconds == 10,
            "suppressed generation was reopened or its start time replaced")
        print("LOCKED_USE_FIRST_INPUT_DIAGNOSTICS_OK assertions=\(assertions)")
    }

    static func guardianRevocationDiagnostics() throws {
        struct Failure: Error { let message: String }
        var assertions = 0
        func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
            assertions += 1
            if !condition() { throw Failure(message: message) }
        }
        typealias Trace = LockedUseGuardianRevocation
        typealias Record = LockedUseGuardianRevocation.Record
        func same(_ lhs: [String: Any], _ rhs: [String: Any]) -> Bool {
            NSDictionary(dictionary: lhs).isEqual(to: rhs)
        }
        let partial = LockedUseCoverageReport(topologyMatches: true, complete: false,
            coveredDisplays: 0, failure: "cover_window_not_published")
        let good = LockedUseCoverageReport(topologyMatches: true, complete: true, coveredDisplays: 2, failure: nil)
        for source in Trace.Source.allCases {
            var trace = Trace()
            let first = Record(source: source, checks: ["old_claim_valid": false, "sender_is_zero": false])
            trace.record(first)
            trace.record(Record(source: .readFailure, checks: ["old_claim_valid": true]))
            try expect(trace.first?.source == source, "later EOF replaced the first revocation source")
            try expect(same(Record.decode(first.status)!.status, first.status), "a closed source did not round-trip")
        }
        try expect(Set(Trace.Source.allCases.map(\.rawValue)).count == Trace.Source.allCases.count,
            "revocation branches must have distinct protocol sources")
        for event in Trace.EventType.allCases {
            let record = Record(source: .eventTapInput, eventType: event)
            try expect(Record.decode(record.status)?.eventType == event, "event category did not round-trip")
        }
        for failure in Trace.CoverageFailure.allCases {
            let record = Record(source: .activeTick, coverageFailure: failure)
            try expect(Record.decode(record.status)?.coverageFailure == failure, "coverage failure did not round-trip")
        }
        for (event, category) in [(CGEventType.keyDown, Trace.EventType.keyDown), (.keyUp, .keyUp),
                                  (.flagsChanged, .flagsChanged), (.leftMouseDown, .mouseDown),
                                  (.rightMouseDown, .mouseDown), (.otherMouseDown, .mouseDown),
                                  (.leftMouseUp, .mouseUp), (.rightMouseUp, .mouseUp), (.otherMouseUp, .mouseUp),
                                  (.mouseMoved, .mouseMoved), (.leftMouseDragged, .mouseDragged),
                                  (.rightMouseDragged, .mouseDragged), (.otherMouseDragged, .mouseDragged),
                                  (.scrollWheel, .scroll), (.null, .unknown)] {
            try expect(Trace.EventType(event) == category, "input metadata escaped its closed category")
        }
        var pending = LockedUseCoverageState()
        let token = pending.begin(now: 10, expiresAt: 11)!
        var observed = pending.diagnosticState
        observed["old_claim_valid"] = false; observed["dependencies_healthy"] = true
        _ = pending.advance(token: token, now: 11, report: partial, leaseValid: false, dependenciesHealthy: true)
        var pendingTrace = Trace()
        pendingTrace.record(.capturing(source: .publicationCheck, report: partial, checks: observed))
        let pendingFirst = pendingTrace.first!.status
        pending.confirmLocked()
        pendingTrace.record(Record(source: .readFailure, checks: pending.diagnosticState))
        try expect(same(pendingTrace.first!.status, pendingFirst), "lock confirmation or EOF replaced the trigger sample")
        try expect(pendingTrace.first!.checks["was_pending"] == true && pendingTrace.first!.checks["was_active"] == false,
            "internal advance revocation hid the prior pending phase")
        try expect(pendingTrace.first!.checks["old_claim_valid"] == false,
            "a later valid renewal must not replace the original claim observation")
        try expect(pendingTrace.first!.checks["covered_all_displays"] == false
            && pendingTrace.first!.checks["has_covered_display"] == false
            && pendingTrace.first!.checks["topology_matches"] == true,
            "coverage diagnostics did not preserve the failed report")
        var active = LockedUseCoverageState()
        let activeToken = active.begin(now: 10, expiresAt: 15)!
        _ = active.advance(token: activeToken, now: 10.1, report: good, leaseValid: true, dependenciesHealthy: true)
        let activeBefore = active.diagnosticState
        _ = active.validateActive(report: partial, leaseValid: true, dependenciesHealthy: true)
        let activeRecord = Record.capturing(source: .activeTick, report: partial, checks: activeBefore)
        active.confirmLocked()
        try expect(activeRecord.checks["was_active"] == true && activeRecord.checks["was_pending"] == false,
            "internal validateActive revocation hid the prior active phase")

        let safe = Record(source: .eventTapInput, eventType: .mouseMoved,
            checks: ["was_active": true, "was_pending": false, "sender_is_source": false,
                     "sender_is_zero": true, "event_source_hid": false, "old_claim_valid": false])
        let serialized = try JSONSerialization.data(withJSONObject: safe.status)
        let roundTrip = Record.decode(try JSONSerialization.jsonObject(with: serialized))!
        try expect(same(roundTrip.status, safe.status), "JSON round-trip dropped real false booleans")
        for invalid: Any in [NSNumber(value: 0), NSNumber(value: 1), 0, 1, "false", "true", NSNull(), [], ["x": true]] {
            let rejected = Record(source: .pendingTick, checks: ["old_claim_valid": invalid])
            try expect(rejected.checks.isEmpty, "non-CFBoolean was accepted as a diagnostic fact")
        }
        let unreachable = Record(source: .pendingTick, checks: ["connected": false])
        try expect(unreachable.checks["source_alive"] == nil && unreachable.checks["event_tap_valid"] == nil,
            "unreached checks must remain absent, not invented false values")
        let unknown = Record.decode(["source": "PRIVATE_SOURCE", "event_type": "PRIVATE_EVENT",
            "coverage_failure": "PRIVATE_FAILURE", "keycode": 42, "sender_pid": 123,
            "coordinates": [1, 2], "secret": "PRIVATE_SECRET",
            "checks": ["was_active": false, "unknown_secret": true, "sender_pid": 123]])!
        try expect(unknown.source == .unknown && unknown.eventType == .unknown && unknown.coverageFailure == .unknown,
            "unknown categories must not impersonate a known first cause")
        try expect(unknown.checks == ["was_active": false], "unknown check fields escaped filtering")
        let safeText = String(data: try JSONSerialization.data(withJSONObject: unknown.status), encoding: .utf8)!
        try expect(!safeText.contains("PRIVATE_") && !safeText.contains("sender_pid") && !safeText.contains("keycode")
            && !safeText.contains("coordinates") && !safeText.contains("secret"), "raw input or arbitrary strings escaped serialization")
        for malformed: Any in [NSNull(), "PRIVATE_VALUE", [], [:], ["source": 1]] {
            try expect(Record.decode(malformed) == nil, "malformed trace must remain absent")
        }
        try expect(Record.decode(nil) == nil, "missing trace must remain absent")

        let readyFalse = try LockedUseFailure.result(["result": ["ready": false,
            "checks": ["topology_matches": false], "guardian_revocation": safe.status]], stage: .guardianBegin)
        let failure = LockedUseFailure(stage: .guardianBegin, reason: .coverageFailed, checks: readyFalse["checks"],
            guardianRevocation: readyFalse["guardian_revocation"])
        try expect(same(failure.guardianRevocation!.status, safe.status), "ready=false failure discarded the first revocation")
        try expect(failure.checks["topology_matches"] == false, "topology false was lost at the existing checks boundary")
        let captured = LockedUseFailure.capture(failure, stage: .prepare)
        try expect(same(captured.status, failure.status), "wrapping an existing failure replaced its original diagnostic")
        let legacy = LockedUseFailure(stage: .guardianRenew, reason: .guardNotReady)
        try expect(legacy.status["guardian_revocation"] == nil, "legacy failures acquired a fabricated diagnostic")
        print("LOCKED_USE_FIRST_REVOCATION_DIAGNOSTICS_OK assertions=\(assertions)")
    }

    static func probeSnapshot() throws {
        struct Failure: Error { let message: String }
        var assertions = 0
        func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
            assertions += 1
            if !condition() { throw Failure(message: message) }
        }
        let active: [String: Any] = ["state": "active", "enabled": true, "phase": "armed",
            "session_id": "session", "run_id": "run", "generation": "generation",
            "requires_manual_unlock": false]
        let idle: [String: Any] = ["state": "available", "enabled": false, "phase": "idle",
            "requires_manual_unlock": false]
        let revoked: [String: Any] = ["state": "suppressed", "enabled": false, "phase": "relocking",
            "reason": "guardian_unavailable", "requires_manual_unlock": true,
            "failure": ["stage": "guardian_renew", "reason": "guard_not_ready"],
            "revoked_binding": ["session_id": "session", "run_id": "run", "generation": "generation"]]
        func same(_ lhs: Any?, _ rhs: Any?) -> Bool {
            guard let lhs = lhs, let rhs = rhs else { return lhs == nil && rhs == nil }
            return NSDictionary(dictionary: ["value": lhs]).isEqual(to: ["value": rhs])
        }
        var reads: [String] = [], axReads = 0, inputReads = 0
        let changing = LockedUseProbe(installed: { reads.append("installed"); return true },
            supportedOS: { reads.append("os"); return true },
            accessibility: { reads.append("ax"); axReads += 1; return axReads == 1 },
            inputMonitoring: { reads.append("input"); inputReads += 1; return inputReads == 1 },
            configuration: { reads.append("configuration"); return .init(state: "available") },
            runtimeStatus: { reads.append("runtime"); return active })
        let first = changing.read()
        try expect(axReads == 1 && inputReads == 1, "each permission must be sampled exactly once per probe")
        try expect(reads == ["installed", "os", "ax", "input", "configuration", "runtime"],
            "availability must finish before the final runtime snapshot")
        try expect(first["accessibility"] as? Bool == true && first["input_monitoring"] as? Bool == true,
            "reported permission flags must be the sampled values")
        for (key, value) in active { try expect(same(first[key], value), "probe lost active runtime field \(key)") }
        try expect((first["availability"] as? [String: Any])?["state"] as? String == "available",
            "availability disagreed with its own sampled permission flags")
        try expect(LockedUseProbe.permissionRecord(first)["state"] as? String == "granted",
            "available capability should report permission granted")
        let second = changing.read()
        try expect(axReads == 2 && inputReads == 2, "later probes must sample again instead of caching grants")
        try expect(second["accessibility"] as? Bool == false && second["input_monitoring"] as? Bool == false,
            "later denied observations were not exposed")
        for (key, value) in active { try expect(same(second[key], value), "availability rewrote live runtime field \(key)") }
        try expect((second["availability"] as? [String: Any])?["state"] as? String == "permission_required",
            "active binding must not hide denied availability")
        try expect(LockedUseProbe.permissionRecord(second)["state"] as? String == "denied",
            "active runtime state must not make denied permissions look granted")

        for (supported, ax, input, setupState) in [(false, true, true, "unsupported"),
                                                  (true, false, true, "permission_required"),
                                                  (true, true, false, "permission_required")] {
            var configurationReads = 0, flagReads = 0
            let probe = LockedUseProbe(installed: { flagReads += 1; return true },
                supportedOS: { flagReads += 1; return supported },
                accessibility: { flagReads += 1; return ax },
                inputMonitoring: { flagReads += 1; return input },
                configuration: { configurationReads += 1; return .init(state: "available") },
                runtimeStatus: { idle })
            let value = probe.read()
            try expect(flagReads == 4 && configurationReads == 0, "unavailable setup must sample flags once and skip configuration")
            try expect(value["state"] as? String == setupState && value["enabled"] as? Bool == false,
                "idle capability setup failure must remain visible")
            try expect(value["phase"] as? String == "idle", "idle phase must survive setup failure")
            try expect(LockedUseProbe.permissionRecord(value)["state"] as? String == (supported ? "denied" : "unavailable"),
                "permission projection must use availability")
        }
        var runtime = active
        let duringConfiguration = LockedUseProbe(installed: { true }, supportedOS: { true },
            accessibility: { true }, inputMonitoring: { true },
            configuration: {
                runtime = revoked
                return .init(state: "permission_required", reason: "system_component_configuration_invalid")
            }, runtimeStatus: { runtime })
        let changed = duringConfiguration.read()
        for (key, value) in revoked { try expect(same(changed[key], value), "probe hid concurrent revocation field \(key)") }
        try expect(LockedUseProbe.permissionRecord(changed)["detail"] as? String == "system_component_configuration_invalid",
            "permission detail must describe availability separately from runtime failure")
        for terminalState in ["available", "suppressed", "failed"] {
            var terminal = revoked; terminal["state"] = terminalState
            terminal["requires_manual_unlock"] = terminalState != "available"
            let value = LockedUseProbe(installed: { true }, supportedOS: { true }, accessibility: { false },
                inputMonitoring: { true }, configuration: { .init(state: "available") },
                runtimeStatus: { terminal }).read()
            for (key, field) in terminal { try expect(same(value[key], field), "setup failure erased terminal field \(key)") }
        }
        let invalid = LockedUseProbe(installed: { true }, supportedOS: { true }, accessibility: { true },
            inputMonitoring: { true }, configuration: { .init(state: "failed", reason: "configuration_unavailable") },
            runtimeStatus: { idle }).read()
        try expect(invalid["state"] as? String == "failed", "configuration failure must block idle availability")
        try expect(LockedUseProbe.permissionRecord(["state": "active"])["state"] as? String == "denied",
            "missing availability cannot manufacture a permission grant")
        print("LOCKED_USE_PROBE_SNAPSHOT_OK assertions=\(assertions)")
    }

    static func displayBinding() {
        let old = LockedUseBinding(sessionID: "session", runID: "run", generation: "old")
        let next = LockedUseBinding(sessionID: "session", runID: "run", generation: "next")
        var display = LockedUseDisplayBinding()
        var value: [String: Any] = ["enabled": false]
        display.append(to: &value, active: nil)
        precondition(value["revoked_binding"] == nil)
        display.ended(old)
        display.append(to: &value, active: nil)
        let revoked = value["revoked_binding"] as? [String: String]
        precondition(revoked == ["session_id": "session", "run_id": "run", "generation": "old"])
        precondition(value["session_id"] == nil && value["run_id"] == nil && value["generation"] == nil)
        precondition(value["enabled"] as? Bool == false)
        precondition(display.canDisplayRelockCompletion(old, active: nil))
        precondition(!display.canDisplayRelockCompletion(next, active: nil))
        precondition(!display.canDisplayRelockCompletion(old, active: next))
        display.began()
        precondition(!display.canDisplayRelockCompletion(old, active: nil))
        value = ["enabled": true]
        display.append(to: &value, active: next)
        precondition(value["generation"] as? String == "next" && value["revoked_binding"] == nil)
        display.ended(next)
        precondition(!display.canDisplayRelockCompletion(old, active: nil))
        precondition(display.canDisplayRelockCompletion(next, active: nil))
        print("LOCKED_USE_DISPLAY_BINDING_OK")
    }

    static func unlockVerification() throws {
        struct TestFailure: Error { let message: String }
        var cases = 0
        func expect(_ state: [String: Any]?, _ expected: Bool, _ label: String, userID: UInt32 = 501) throws {
            cases += 1
            if LockedUseUnlockVerification.isUnlocked(state, expectedUserID: userID) != expected {
                throw TestFailure(message: label)
            }
        }
        let onConsole = kCGSessionOnConsoleKey as String
        let loginDone = kCGSessionLoginDoneKey as String
        let user = kCGSessionUserIDKey as String
        let lock = "CGSSessionScreenIsLocked"
        let active: [String: Any] = [onConsole: true, loginDone: true, user: 501]
        try expect(active, true, "valid active session with absent lock marker was rejected")
        var explicitUnlocked = active; explicitUnlocked[lock] = false
        try expect(explicitUnlocked, true, "explicit false lock marker was rejected")
        try expect(nil, false, "unavailable GUI session was accepted")
        try expect([:], false, "empty session was accepted")
        for field in [onConsole, loginDone, user] {
            var missing = active; missing.removeValue(forKey: field)
            try expect(missing, false, "missing required session field was accepted")
        }
        for field in [onConsole, loginDone] {
            for invalid: Any in [false, 0, 1, "true", "false", NSNull()] {
                var state = active; state[field] = invalid
                try expect(state, false, "inactive or non-Boolean session field was accepted")
            }
        }
        for invalid: Any in [true, 0, 1, "false", "true", NSNull()] {
            var state = active; state[lock] = invalid
            try expect(state, false, "locked or non-Boolean lock marker was accepted")
        }
        for invalid: Any in [true, false, 502, -1, UInt64.max, UInt64(UInt32.max) + 1,
                             501.0, 501.5, Double.nan, Double.infinity, "501", NSNull()] {
            var state = active; state[user] = invalid
            try expect(state, false, "invalid or different user identity was accepted")
        }
        for value in [UInt32(0), UInt32.max] {
            var state = active; state[user] = NSNumber(value: value)
            try expect(state, true, "matching UInt32 identity was rejected", userID: value)
        }
        var switched = explicitUnlocked; switched[onConsole] = false
        try expect(switched, false, "explicit unlocked marker overrode inactive console")
        var loggedOut = explicitUnlocked; loggedOut[loginDone] = false
        try expect(loggedOut, false, "explicit unlocked marker overrode incomplete login")
        var otherUser = explicitUnlocked; otherUser[user] = 502
        try expect(otherUser, false, "explicit unlocked marker overrode different user")
        print("LOCKED_USE_UNLOCK_VERIFICATION_OK cases=\(cases)")
    }
    static func inputProtection() throws {
        struct TestFailure: Error { let message: String }
        func require(_ condition: Bool, _ message: String) throws {
            if !condition { throw TestFailure(message: message) }
        }
        for present in [false, true] {
            for valid in [false, true] {
                for enabled in [false, true] {
                    var active = true, suppressed = false, relocking = false
                    var validReads = 0, enabledReads = 0
                    let tap: Int? = present ? 1 : nil
                    let ready = LockedUseInputProtection.checkTap(tap,
                        isValid: { _ in validReads += 1; return valid },
                        isEnabled: { _ in enabledReads += 1; return enabled },
                        active: &active, suppressed: &suppressed, relocking: &relocking)
                    let healthy = present && valid && enabled
                    try require(ready == healthy, "tap admission ignored presence, validity, or enabled state")
                    try require(active == healthy && suppressed == !healthy && relocking == !healthy,
                        "an unhealthy active tap did not revoke the generation")
                    try require(validReads == (present ? 1 : 0), "invalid presence read")
                    try require(enabledReads == (present && valid ? 1 : 0), "enabled was read on an invalid port")
                }
            }
        }
        // ready, authorize, and active tick all execute this same production
        // check. No disabled callback is invoked by the following transition.
        var active = true, suppressed = false, relocking = false
        let denied = LockedUseInputProtection.checkTap(1, isValid: { _ in true }, isEnabled: { _ in false },
            active: &active, suppressed: &suppressed, relocking: &relocking)
        try require(!denied && !active && suppressed && relocking, "disabled tap remained authorized")
        let restored = LockedUseInputProtection.checkTap(1, isValid: { _ in true }, isEnabled: { _ in true },
            active: &active, suppressed: &suppressed, relocking: &relocking)
        try require(!restored && !active && suppressed && relocking, "restored tap revived its old generation")
        // Successful OS relock clears only relocking in the Guardian.
        relocking = false
        let afterRelock = LockedUseInputProtection.checkTap(1, isValid: { _ in true }, isEnabled: { _ in true },
            active: &active, suppressed: &suppressed, relocking: &relocking)
        try require(!afterRelock && !active && suppressed && !relocking, "completed relock cleared suppression")
        // The existing disabled callback independently establishes this same
        // terminal state before it asks the OS to re-enable the tap.
        active = false; suppressed = true; relocking = true
        let afterCallback = LockedUseInputProtection.checkTap(1, isValid: { _ in true }, isEnabled: { _ in true },
            active: &active, suppressed: &suppressed, relocking: &relocking)
        try require(!afterCallback && suppressed && relocking, "callback suppression was cleared")
        // No active generation is consumed while the initial tap is absent.
        active = false; suppressed = false; relocking = false
        let idle = LockedUseInputProtection.checkTap(nil as Int?, isValid: { _ in true }, isEnabled: { _ in true },
            active: &active, suppressed: &suppressed, relocking: &relocking)
        try require(!idle && !active && !suppressed && !relocking, "idle sampling consumed a generation")
        active = true
        let fresh = LockedUseInputProtection.checkTap(1, isValid: { _ in true }, isEnabled: { _ in true },
            active: &active, suppressed: &suppressed, relocking: &relocking)
        try require(fresh && active && !suppressed && !relocking, "a fresh healthy generation was rejected")
        print("LOCKED_USE_INPUT_PROTECTION_OK")
    }
    static func diagnostics() throws {
        for (error, reason): (LockedUseWireError, LockedUseFailure.Reason) in [
            (.closed, .pipeClosed), (.timeout, .pipeTimeout), (.invalidFrame, .invalidFrame)] {
            let failure = LockedUseFailure.capture(error, stage: .guardianInitialize)
            precondition(failure.stage == .guardianInitialize && failure.reason == reason)
            precondition(failure.underlying is LockedUseWireError)
        }
        for (code, reason): (String, LockedUseFailure.Reason) in [
            ("guardian_authentication_failed", .guardianAuthenticationFailed),
            ("guard_rejected", .guardRejected), ("invalid_request", .invalidRequest),
            ("private-secret-nonce-proof", .guardianRejected)] {
            do {
                _ = try LockedUseFailure.result(["result": ["error": code, "checks": [
                    "event_tap_created": false, "event_tap_valid": false,
                    "covered_all_displays": true, "nonce": "private-secret-nonce-proof",
                    "source_alive": 1, "watchdog_alive": "private-secret-nonce-proof"]]], stage: .guardianBegin)
                preconditionFailure("a guardian error was accepted")
            } catch let failure as LockedUseFailure {
                precondition(failure.stage == .guardianBegin && failure.reason == reason)
                precondition(failure.checks == ["event_tap_created": false,
                    "event_tap_valid": false, "covered_all_displays": true])
                let text = String(data: try JSONSerialization.data(withJSONObject: failure.status), encoding: .utf8)!
                precondition(!text.contains("private-secret") && !text.contains("nonce") && !text.contains("proof"))
                let preserved = LockedUseFailure.capture(failure, stage: .prepare)
                precondition(preserved.stage == .guardianBegin && preserved.reason == reason)
            }
        }
        for response: [String: Any] in [[:], ["result": "private-secret"], ["result": NSNull()]] {
            do { _ = try LockedUseFailure.result(response, stage: .guardianInitialize)
                preconditionFailure("a malformed guardian result was accepted") }
            catch let failure as LockedUseFailure { precondition(failure.reason == .invalidFrame) }
        }
        let reply = try LockedUseFailure.result(["result": ["ready": true]], stage: .guardianBegin)
        precondition(reply["ready"] as? Bool == true)
        let unknown = LockedUseFailure.capture(NSError(domain: "private-secret-nonce-proof", code: 123,
            userInfo: [NSLocalizedDescriptionKey: "private-secret-nonce-proof"]), stage: .watchdogPrepare)
        let text = String(data: try JSONSerialization.data(withJSONObject: unknown.status), encoding: .utf8)!
        precondition(unknown.reason == .nativeOperationFailed && !text.contains("private-secret"))
        precondition(Set(unknown.status.keys) == ["stage", "reason"])
        for (exitReason, name): (Process.TerminationReason, String) in [(.exit, "exit"), (.uncaughtSignal, "signal")] {
            let failure = LockedUseFailure(stage: .guardianProcess, reason: .guardianExited,
                exitStatus: 9, exitReason: exitReason)
            precondition(failure.status["exit_status"] as? Int32 == 9)
            precondition(failure.status["exit_reason"] as? String == name)
        }
        for (method, stage): (String, LockedUseFailure.Stage) in [
            ("initialize", .guardianInitialize), ("begin_guard", .guardianBegin),
            ("renew_guard", .guardianRenew), ("authorize_unlock", .guardianAuthorize),
            ("private-secret", .prepare)] {
            precondition(LockedUseFailure.requestStage(method) == stage)
        }
        let initializationChecks: [String: Bool] = ["fresh_initialization": true, "secret_shape_valid": true,
            "nonce_shape_valid": true, "parent_identity_valid": true, "self_executable_available": true,
            "self_signing_valid": true, "parent_signing_valid": false]
        let initializationFailure = LockedUseFailure(stage: .guardianInitialize,
            reason: .guardianAuthenticationFailed, checks: initializationChecks)
        precondition(initializationFailure.checks == initializationChecks)
        precondition(initializationFailure.checks["watchdog_signing_valid"] == nil)
        for stage: LockedUseFailure.Stage in [.unlockLoginwindow, .unlockField, .unlockSetValue,
                                              .unlockSubmit, .unlockVerify] {
            let failure = LockedUseFailure(stage: stage, reason: .lockedUseUnavailable)
            let preserved = LockedUseFailure.capture(failure, stage: .unlock)
            precondition(preserved.stage == stage && preserved.status["stage"] as? String == stage.rawValue)
        }
        let notReady = LockedUseFailure(stage: .guardianBegin, reason: .coverageFailed,
            checks: ["event_tap_created": false, "event_tap_valid": false, "event_tap_enabled": false,
                "covered_all_displays": true, "has_covered_display": true])
        precondition(notReady.checks["event_tap_created"] == false
            && notReady.checks["covered_all_displays"] == true)
        let rejected = LockedUseFailure(stage: .guardianBegin, reason: .guardRejected,
            checks: ["claim_valid": false, "guardian_identity_matches": true,
                "binding_matches": true, "screen_locked": true, "secret": true])
        precondition(rejected.checks.count == 4 && rejected.checks["claim_valid"] == false)
        print("LOCKED_USE_DIAGNOSTICS_OK")
    }
    private static func configurationPermissions() {
        for mode: mode_t in [0o600, 0o644, 0o640] {
            var attributes = stat(); attributes.st_uid = 0; attributes.st_mode = S_IFREG | mode
            precondition(LockedUseManagement.configurationIsProtected(attributes))
            attributes.st_uid = 501
            precondition(!LockedUseManagement.configurationIsProtected(attributes))
        }
        for mode: mode_t in [0o620, 0o602, 0o664, 0o666] {
            var attributes = stat(); attributes.st_uid = 0; attributes.st_mode = S_IFREG | mode
            precondition(!LockedUseManagement.configurationIsProtected(attributes))
        }
        var directory = stat(); directory.st_uid = 0; directory.st_mode = S_IFDIR | 0o755
        precondition(!LockedUseManagement.configurationIsProtected(directory))
    }
    private static func installationErrors() {
        for code in [-128, -1743, 1] {
            let detail = "locked-use installer failed: installation directory is not protected"
            let error = LockedUseManagement.installationFailure([
                NSAppleScript.errorNumber: code, NSAppleScript.errorMessage: detail])
            if case ActionError.failure(let kind, let message, _) = error {
                precondition(kind == (code == -128 ? "administrator_authorization_cancelled" : "locked_use_setup_failed"))
                if code != -128 { precondition(message.contains(detail) && message.contains(String(code))) }
            }
        }
    }
    private static func wire() throws {
        let pipe = Pipe()
        defer { try? pipe.fileHandleForReading.close(); try? pipe.fileHandleForWriting.close() }
        try LockedUseWire.write(["method": "lease", "generation": "g"], fd: pipe.fileHandleForWriting.fileDescriptor)
        let value = try LockedUseWire.read(pipe.fileHandleForReading.fileDescriptor, timeout: 0.1)
        precondition(value["generation"] as? String == "g")
        do { _ = try LockedUseWire.read(pipe.fileHandleForReading.fileDescriptor, timeout: 0.02)
            preconditionFailure("unresponsive guardian did not time out") }
        catch LockedUseWireError.timeout {}
        var oversized = UInt32(4097).littleEndian
        try pipe.fileHandleForWriting.write(contentsOf: Data(bytes: &oversized, count: 4))
        do { _ = try LockedUseWire.read(pipe.fileHandleForReading.fileDescriptor, timeout: 0.1)
            preconditionFailure("oversized guardian message accepted") }
        catch LockedUseWireError.invalidFrame {}
    }
}
