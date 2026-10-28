import ApplicationServices
import Foundation

enum LockedUseUnlockTests {
    private static let identity = LockedUseProcessIdentity(pid: 42, startSeconds: 100, startMicroseconds: 200)
    private final class Fixture {
        var time = 0.0
        var latency = 0.0
        var processes = [identity]
        var alive = true
        var identifiers = [1: "UserPasswordTextField"]
        var descendants = [0: [1]]
        var settable = true
        var checks = 0
        var checkpointDeadlines: [Double] = []
        var reads: [String] = []
        var timeouts: [Float] = []
        var waits = 0
        var errors: [String: [AXError]] = [:]
        var onRead: (() -> Void)?
        var onWait: (() -> Void)?
        var onCheck: (() throws -> Void)?
        var onDeadlineCheck: ((Double) throws -> Void)?
        func read(_ name: String, _ element: Int, _ timeout: Float) throws {
            reads.append("\(name):\(element)"); timeouts.append(timeout)
            time += latency
            onRead?()
            if var pending = errors[name], !pending.isEmpty {
                let error = pending.removeFirst(); errors[name] = pending
                throw LockedUseFieldReadFailure.ax(error)
            }
        }
        func locator(seconds: Double = 0.2, nodes: Int = 1000, depth: Int = 12) -> LockedUseFieldLocator<Int> {
            let access = LockedUseFieldAccess<Int>(processes: { self.processes }, alive: { _ in self.alive },
                root: { _ in 0 }, identical: ==, identifier: { element, timeout in
                    try self.read("identifier", element, timeout); return self.identifiers[element]
                }, childCount: { element, timeout in
                    try self.read("count", element, timeout); return self.descendants[element]?.count ?? 0
                }, children: { element, _, timeout in
                    try self.read("children", element, timeout); return self.descendants[element] ?? []
                }, valueSettable: { element, timeout in
                    try self.read("settable", element, timeout); return self.settable
                })
            return LockedUseFieldLocator(access: access, checkpoint: { until in
                self.checkpointDeadlines.append(until)
                self.checks += 1; try self.onDeadlineCheck?(until); try self.onCheck?()
            }, now: { self.time }, wait: { seconds in
                precondition(seconds > 0 && seconds <= 0.05)
                self.time += seconds; self.waits += 1; self.onWait?()
            }, readinessSeconds: seconds, nodeBudget: nodes, depthLimit: depth)
        }
    }
    private static func rejected(_ reason: LockedUseFailure.Reason, _ operation: () throws -> Void) throws -> LockedUseFailure {
        do { try operation(); preconditionFailure("an unsafe unlock operation was accepted") }
        catch let failure as LockedUseFailure {
            precondition(failure.reason == reason, "unexpected reason \(failure.reason)")
            return failure
        }
    }
    static func run() throws {
        try deadlineCheckpoints()
        try maintenance()
        try readiness()
        try bounds()
        try cancellation()
        try execution()
        try diagnostics()
        print("LOCKED_USE_UNLOCK_LOCATOR_OK")
    }
    private static func readiness() throws {
        let delayed = Fixture(); delayed.descendants = [:]
        delayed.onWait = { if delayed.waits == 2 { delayed.descendants = [0: [1]] } }
        let field = try delayed.locator().locate()
        precondition(field.element == 1 && field.process == identity && delayed.waits == 2)
        precondition(delayed.reads.filter { $0.hasPrefix("settable:") }.count == 1)
        precondition(delayed.timeouts.allSatisfy { $0 > 0 && $0 <= 0.1 })

        let messaging = Fixture(); messaging.errors = ["identifier": [.cannotComplete, .invalidUIElement]]
        let messagingField = try messaging.locator().locate()
        precondition(messagingField.element == 1)
        precondition(messaging.waits == 2)
        let disabled = Fixture(); disabled.errors = ["identifier": [.apiDisabled]]
        _ = try rejected(.unlockAXDisabled) { _ = try disabled.locator().locate() }
        precondition(disabled.waits == 0 && disabled.reads.count == 1)

        let absent = Fixture(); absent.identifiers = [:]
        let missing = try rejected(.unlockFieldAbsent) { _ = try absent.locator().locate() }
        precondition(missing.checks["scan_complete"] == true
            && missing.checks["field_identifier_found"] == false
            && missing.checks["readiness_deadline_reached"] == true)
        precondition(absent.time <= 0.2 && !absent.reads.contains("settable:1"))

        let unavailable = Fixture(); unavailable.processes = []
        let noProcess = try rejected(.unlockLoginwindowAbsent) { _ = try unavailable.locator().locate() }
        precondition(noProcess.stage == .unlockLoginwindow && unavailable.reads.isEmpty)
        let ambiguous = Fixture(); ambiguous.processes.append(identity)
        _ = try rejected(.unlockLoginwindowAmbiguous) { _ = try ambiguous.locator().locate() }
        precondition(ambiguous.reads.isEmpty && ambiguous.waits == 0)

        let restarted = Fixture(); restarted.onRead = { restarted.alive = false }
        _ = try rejected(.unlockProcessChanged) { _ = try restarted.locator().locate() }
        precondition(restarted.reads.count == 1 && restarted.waits == 0)

        let twoFields = Fixture(); twoFields.descendants = [0: [1, 2]]
        twoFields.identifiers[2] = "UserPasswordTextField"
        _ = try rejected(.unlockFieldAmbiguous) { _ = try twoFields.locator().locate() }
        precondition(!twoFields.reads.contains { $0.hasPrefix("settable:") })
        let sharedReference = Fixture(); sharedReference.descendants = [0: [1, 1]]
        let sharedField = try sharedReference.locator().locate()
        precondition(sharedField.element == 1)

        let readonly = Fixture(); readonly.settable = false
        readonly.onWait = { readonly.settable = true }
        let writableField = try readonly.locator().locate()
        precondition(writableField.element == 1)
        precondition(readonly.waits == 1)
        let neverWritable = Fixture(); neverWritable.settable = false
        let notWritable = try rejected(.unlockFieldNotSettable) { _ = try neverWritable.locator().locate() }
        precondition(notWritable.checks["field_value_settable"] == false)

        let wrongIdentifier = Fixture(); wrongIdentifier.identifiers[1] = "UserPasswordTextField-extra"
        _ = try rejected(.unlockFieldAbsent) { _ = try wrongIdentifier.locator().locate() }
        precondition(!wrongIdentifier.reads.contains("settable:1"))
    }
    private static func bounds() throws {
        let repeated = Fixture(); repeated.descendants = [:]; repeated.identifiers = [:]
        _ = try rejected(.unlockScanBudgetExceeded) { _ = try repeated.locator(seconds: 1, nodes: 3).locate() }
        precondition(repeated.reads.filter { $0 == "identifier:0" }.count == 3)
        precondition(repeated.time < 1)
        let broad = Fixture(); broad.descendants = [0: Array(1...1001)]
        _ = try rejected(.unlockScanBudgetExceeded) { _ = try broad.locator().locate() }
        precondition(!broad.reads.contains("children:0"))
        let deep = Fixture(); deep.identifiers = [0: "UserPasswordTextField"]
        deep.descendants = Dictionary(uniqueKeysWithValues: (0...12).map { ($0, [$0 + 1]) })
        _ = try rejected(.unlockScanBudgetExceeded) { _ = try deep.locator().locate() }
        precondition(!deep.reads.contains("identifier:12") && !deep.reads.contains("settable:0"))
        let slow = Fixture(); slow.latency = 0.11
        let expired = try rejected(.unlockReadinessTimeout) { _ = try slow.locator(seconds: 0.1).locate() }
        precondition(slow.reads.count == 1 && expired.checks["readiness_deadline_reached"] == true)
        precondition(slow.timeouts == [0.1])
        let narrowBudget = Fixture()
        _ = try rejected(.unlockScanBudgetExceeded) { _ = try narrowBudget.locator(nodes: 1).locate() }
        precondition(!narrowBudget.reads.contains("children:0"))
    }
    private static func cancellation() throws {
        for failAfterRead in 0...6 {
            let fixture = Fixture()
            fixture.onCheck = {
                if fixture.reads.count >= failAfterRead {
                    throw ActionError.failure(kind: "user_stopped_session", message: "cancelled")
                }
            }
            do { _ = try fixture.locator().locate(); preconditionFailure("cancellation was ignored") }
            catch ActionError.failure(let kind, _, _) { precondition(kind == "user_stopped_session") }
            precondition(fixture.reads.count == failAfterRead && fixture.waits == 0)
        }
        let failedRead = Fixture(); failedRead.errors = ["identifier": [.cannotComplete]]
        failedRead.onCheck = {
            if !failedRead.reads.isEmpty {
                throw ActionError.failure(kind: "locked_use_expired", message: "expired")
            }
        }
        do { _ = try failedRead.locator().locate(); preconditionFailure("AX failure hid lease expiry") }
        catch ActionError.failure(let kind, _, _) { precondition(kind == "locked_use_expired") }
        precondition(failedRead.reads.count == 1 && failedRead.waits == 0)
        let guardFailure = Fixture()
        guardFailure.onCheck = {
            if guardFailure.time >= 0.1 {
                throw LockedUseFailure(stage: .guardianRenew, reason: .guardNotReady)
            }
        }
        guardFailure.descendants = [:]
        let failure = try rejected(.guardNotReady) { _ = try guardFailure.locator().locate() }
        precondition(failure.stage == .guardianRenew && guardFailure.time == 0.1)
    }
    private static func execution() throws {
        let field = LockedUseLocatedField(element: 1, process: identity)
        func run(fail: String? = nil, failCheck: Int? = nil) throws -> [String] {
            var events: [String] = [], checks = 0
            func event(_ name: String) throws {
                events.append(name)
                if fail == name { throw ActionError.failure(kind: "locked_use_unavailable", message: "injected") }
            }
            let execution = LockedUseUnlockExecution(locate: { try event("locate"); return field },
                checkpoint: { _ in
                    checks += 1; events.append("check")
                    if checks == failCheck { throw LockedUseFailure(stage: .guardianRenew, reason: .guardNotReady) }
                }, openAuthorization: { try event("open") }, closeAuthorization: { events.append("close") },
                setSentinel: { _ in try event("set") }, focus: { _ in try event("focus") },
                submit: { try event("submit") }, verify: { try event("verify") })
            do {
                try execution.run()
                precondition(fail == nil && failCheck == nil)
            } catch {
                precondition(fail != nil || failCheck != nil)
                if let failCheck = failCheck {
                    precondition((error as? LockedUseFailure)?.reason == .guardNotReady)
                    precondition(checks == failCheck)
                }
            }
            for name in ["locate", "open", "set", "focus", "submit", "verify", "close"] {
                precondition(events.filter { $0 == name }.count <= 1, "unlock effects were retried")
            }
            return events
        }
        let completed = try run()
        precondition(completed == ["locate", "check", "open", "check", "set", "check", "focus", "check",
            "submit", "check", "verify", "close"])
        for failure in ["locate", "open", "set", "focus", "submit", "verify"] {
            let events = try run(fail: failure)
            if ["locate", "open"].contains(failure) { precondition(!events.contains("set") && !events.contains("submit")) }
            else { precondition(events.last == "close") }
            if ["set", "focus"].contains(failure) { precondition(!events.contains("submit")) }
            if failure == "submit" { precondition(!events.contains("verify")) }
        }
        for check in 1...5 {
            let events = try run(failCheck: check)
            if check == 1 { precondition(!events.contains("open")) }
            else { precondition(events.last == "close") }
            if check <= 2 { precondition(!events.contains("set")) }
            if check <= 4 { precondition(!events.contains("submit")) }
            precondition(!events.contains("verify"))
        }
        let delayed = Fixture(); delayed.descendants = [:]
        var writes = 0, submissions = 0, authorizations = 0
        let execution = LockedUseUnlockExecution(locate: delayed.locator().locate,
            checkpoint: { _ in }, openAuthorization: { authorizations += 1 }, closeAuthorization: {},
            setSentinel: { _ in writes += 1 }, focus: { _ in }, submit: { submissions += 1 }, verify: {})
        _ = try rejected(.unlockFieldAbsent) { try execution.run() }
        precondition(writes == 0 && submissions == 0 && authorizations == 0)
    }
    private static func maintenance() throws {
        func run(now: Double = 0.25, force: Bool = false, fail: String? = nil) throws -> [String] {
            var events: [String] = [], checks = 0
            func event(_ name: String) throws {
                events.append(name)
                if fail == name { throw LockedUseFailure(stage: .guardianRenew, reason: .guardNotReady) }
            }
            let maintenance = LockedUseGuardMaintenance(check: {
                checks += 1; try event("check\(checks)"); return 42
            }, renew: { claim in precondition(claim == 42); try event("renew") },
                arm: { claim in precondition(claim == 42); try event("arm") },
                refreshed: { events.append("refreshed") }, revoke: { _ in events.append("revoke") }, now: { now })
            do { try maintenance.run(lastRefresh: 0, force: force); precondition(fail == nil) }
            catch let failure as LockedUseFailure { precondition(fail != nil && failure.reason == .guardNotReady) }
            if fail != nil { precondition(events.last == "revoke" && !events.contains("refreshed")) }
            return events
        }
        let notDue = try run(now: 0.249)
        precondition(notDue == ["check1"])
        let due = try run()
        precondition(due == ["check1", "renew", "check2", "arm", "check3", "refreshed"])
        let forced = try run(now: 0, force: true)
        precondition(forced == due)
        for failure in ["check1", "renew", "check2", "arm", "check3"] {
            let events = try run(fail: failure)
            if ["check1", "renew", "check2"].contains(failure) { precondition(!events.contains("arm")) }
            if failure == "check1" { precondition(!events.contains("renew")) }
        }
        let revokedWhileNotDue = try run(now: 0.1, fail: "check1")
        precondition(revokedWhileNotDue == ["check1", "revoke"])

        let waiting = Fixture(); waiting.descendants = [:]
        var lastRefresh = -1.0, renewals = 0, arms = 0, revocations = 0
        let heartbeat = LockedUseGuardMaintenance(check: { 42 }, renew: { _ in renewals += 1 },
            arm: { _ in arms += 1 }, refreshed: { lastRefresh = waiting.time },
            revoke: { _ in revocations += 1 }, now: { waiting.time })
        waiting.onCheck = { try heartbeat.run(lastRefresh: lastRefresh) }
        waiting.onWait = { if waiting.waits == 8 { waiting.descendants = [0: [1]] } }
        let field = try waiting.locator(seconds: 1).locate()
        precondition(field.element == 1 && renewals >= 2 && arms == renewals && revocations == 0)

        let expired = Fixture(); expired.descendants = [:]
        lastRefresh = -1; renewals = 0; arms = 0; revocations = 0
        let expiringHeartbeat = LockedUseGuardMaintenance(check: {
            guard expired.time < 0.3 else {
                throw ActionError.failure(kind: "locked_use_expired", message: "expired")
            }
            return 42
        }, renew: { _ in renewals += 1 }, arm: { _ in arms += 1 },
            refreshed: { lastRefresh = expired.time }, revoke: { _ in revocations += 1 }, now: { expired.time })
        expired.onCheck = { try expiringHeartbeat.run(lastRefresh: lastRefresh) }
        do { _ = try expired.locator(seconds: 1).locate(); preconditionFailure("refresh extended host authority") }
        catch ActionError.failure(let kind, _, _) { precondition(kind == "locked_use_expired") }
        precondition(expired.time == 0.3 && renewals >= 2 && arms == renewals && revocations == 1)
    }
    private static func deadlineCheckpoints() throws {
        let expired = Fixture()
        _ = try rejected(.unlockReadinessTimeout) { _ = try expired.locator(seconds: 0).locate() }
        precondition(expired.checks == 0 && expired.reads.isEmpty)

        let slowCheckpoint = Fixture()
        slowCheckpoint.onCheck = { slowCheckpoint.time += 0.2 }
        let timeout = try rejected(.unlockReadinessTimeout) { _ = try slowCheckpoint.locator().locate() }
        precondition(slowCheckpoint.checks == 1 && slowCheckpoint.reads.isEmpty)
        precondition(timeout.checks["readiness_deadline_reached"] == true)

        let slowPostRead = Fixture()
        slowPostRead.onCheck = { if !slowPostRead.reads.isEmpty { slowPostRead.time = 0.2 } }
        _ = try rejected(.unlockReadinessTimeout) { _ = try slowPostRead.locator().locate() }
        precondition(slowPostRead.reads.count == 1)
        precondition(slowPostRead.checkpointDeadlines.allSatisfy { $0 == 0.2 })

        let expiredDuringRead = Fixture(); expiredDuringRead.latency = 0.2
        var checksAtRead = 0
        expiredDuringRead.onRead = { checksAtRead = expiredDuringRead.checks }
        _ = try rejected(.unlockReadinessTimeout) { _ = try expiredDuringRead.locator().locate() }
        precondition(expiredDuringRead.reads.count == 1 && expiredDuringRead.checks == checksAtRead)

        for overrun in ["expired", "check1", "renew", "check2", "arm", "check3"] {
            var time = overrun == "expired" ? 0.2 : 0.0
            var events: [String] = [], checks = 0
            func event(_ name: String) {
                events.append(name)
                if overrun == name { time = 0.2 }
            }
            let maintenance = LockedUseGuardMaintenance(check: {
                checks += 1; event("check\(checks)"); return 42
            }, renew: { _ in event("renew") }, arm: { _ in event("arm") },
                refreshed: { event("refreshed") }, revoke: { _ in event("revoke") }, now: { time })
            _ = try rejected(.unlockReadinessTimeout) {
                try maintenance.run(lastRefresh: -1, deadline: 0.2)
            }
            precondition(events.last == "revoke" && !events.contains("refreshed"))
            if overrun == "expired" { precondition(events == ["revoke"]) }
            if ["expired", "check1"].contains(overrun) { precondition(!events.contains("renew")) }
            if ["expired", "check1", "renew", "check2"].contains(overrun) { precondition(!events.contains("arm")) }
        }

        let waiting = Fixture()
        var arms = 0, authorizations = 0, writes = 0, submissions = 0, revocations = 0
        let heartbeat = LockedUseGuardMaintenance(check: { 42 }, renew: { _ in waiting.time += 0.25 },
            arm: { _ in arms += 1 }, refreshed: {}, revoke: { _ in revocations += 1 }, now: { waiting.time })
        waiting.onDeadlineCheck = { until in try heartbeat.run(lastRefresh: -1, deadline: until) }
        let execution = LockedUseUnlockExecution(locate: waiting.locator().locate,
            checkpoint: { _ in }, openAuthorization: { authorizations += 1 }, closeAuthorization: {},
            setSentinel: { _ in writes += 1 }, focus: { _ in }, submit: { submissions += 1 }, verify: {})
        _ = try rejected(.unlockReadinessTimeout) { try execution.run() }
        precondition(waiting.checks == 1 && waiting.reads.isEmpty && arms == 0 && revocations == 1)
        precondition(authorizations == 0 && writes == 0 && submissions == 0)
    }
    private static func diagnostics() throws {
        let failure = LockedUseFailure(stage: .unlockField, reason: .unlockAXCannotComplete, checks: [
            "loginwindow_unique": true, "scan_complete": false, "field_identifier_found": false,
            "field_value_settable": "private-password", "readiness_deadline_reached": 1,
            "AXValue": "private-password", "AXTitle": "private-account", "AXIdentifier": "private-identifier"],
            underlying: NSError(domain: "private-password", code: 1))
        precondition(failure.checks.count == 3)
        let text = String(data: try JSONSerialization.data(withJSONObject: failure.status), encoding: .utf8)!
        precondition(!text.contains("private-") && !text.contains("AXValue") && !text.contains("AXTitle")
            && !text.contains("AXIdentifier"))
        precondition(LockedUseFailure.capture(failure, stage: .prepare).reason == .unlockAXCannotComplete)
    }
}
