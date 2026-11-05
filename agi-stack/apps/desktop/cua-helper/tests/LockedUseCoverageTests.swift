import CoreGraphics
import Foundation

@main
enum LockedUseCoverageTests {
    private static var assertions = 0
    private static let owner: Int32 = 42
    private static let level = 2147483629
    private static let displays = [
        LockedUseDisplayCoverage(id: 1, appKitFrame: CGRect(x: 0, y: 0, width: 1728, height: 1117),
            quartzFrame: CGRect(x: 0, y: 0, width: 1728, height: 1117), scale: 2),
        LockedUseDisplayCoverage(id: 3, appKitFrame: CGRect(x: -119, y: 1117, width: 1920, height: 1280),
            quartzFrame: CGRect(x: -119, y: -1280, width: 1920, height: 1280), scale: 1),
    ]
    private static var windows: [LockedUseWindowCoverage] {
        displays.enumerated().map { index, display in
            LockedUseWindowCoverage(displayID: display.id, number: Int32(index + 10),
                appKitFrame: display.appKitFrame, visible: true, opaque: true, alpha: 1, level: level,
                server: LockedUseWindowServerCoverage(number: Int32(index + 10), ownerPID: owner,
                    frame: display.quartzFrame, onScreen: true, alpha: 1, layer: level))
        }
    }
    private static func expect(_ value: @autoclosure () -> Bool, _ message: String) {
        assertions += 1
        guard value() else { fatalError(message) }
    }
    private static func report(_ observed: [LockedUseWindowCoverage],
                               current: [LockedUseDisplayCoverage]? = displays) -> LockedUseCoverageReport {
        LockedUseCoverage.check(expected: displays, current: current, windows: observed,
            ownerPID: owner, requiredLevel: level)
    }
    private static func intermediateComplete(_ state: inout LockedUseCoverageState, _ token: UUID,
                                             start: Double, report good: LockedUseCoverageReport) {
        for offset in [0.25, 0.5, 0.75] {
            expect(state.advance(token: token, now: start + offset, report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
                "intermediate complete observations cannot grant authority before one second")
        }
    }
    private static func geometryTests() {
        expect(report(windows).complete, "two displays have full actual coverage")
        expect(report(windows, current: displays.reversed()).complete, "screen order is not identity")
        var observed = windows
        observed[1].appKitFrame.origin = CGPoint(x: -238, y: 2234)
        observed[1].server?.frame.origin = CGPoint(x: -238, y: -2397)
        expect(!report(observed).complete, "Native36 double-origin external cover must fail despite count=2")
        for index in windows.indices {
            for mutation in 0..<19 {
                var changed = windows
                switch mutation {
                case 0: changed[index].visible = false
                case 1: changed[index].opaque = false
                case 2: changed[index].alpha = 0.99
                case 3: changed[index].level -= 1
                case 4: changed[index].appKitFrame.size.width -= 1
                case 5: changed[index].appKitFrame.origin.x += 1
                case 6: changed[index].number = 0
                case 7: changed[index].server = nil
                case 8: changed[index].server?.number += 1
                case 9: changed[index].server?.ownerPID += 1
                case 10: changed[index].server?.frame.size = .zero
                case 11: changed[index].server?.frame.origin.y -= 1
                case 12: changed[index].server?.onScreen = false
                case 13: changed[index].server?.alpha = 0.99
                case 14: changed[index].server?.layer -= 1
                case 15: changed[index].alpha = .nan
                case 16: changed[index].server?.alpha = .nan
                case 17: changed[index].appKitFrame.origin.x = .infinity
                default: changed[index].server?.frame.origin.x = .nan
                }
                expect(!report(changed).complete, "reject window \(index) invalid property \(mutation)")
            }
        }
        expect(!report([]).complete, "empty windows fail")
        expect(!report([windows[0]]).complete, "missing cover fails")
        expect(!report(windows + [windows[0]]).complete, "extra cover fails")
        var duplicate = windows
        duplicate[1].displayID = duplicate[0].displayID
        expect(!report(duplicate).complete, "duplicate display binding fails")
        duplicate = windows
        let duplicateNumber = duplicate[0].number
        duplicate[1].number = duplicateNumber; duplicate[1].server?.number = duplicateNumber
        expect(!report(duplicate).complete, "duplicate actual window fails")
        expect(!report(windows, current: nil).complete, "missing topology fails")
        expect(!report(windows, current: []).complete, "zero screens fail")
        expect(!report(windows, current: [displays[0], displays[0]]).complete, "duplicate screen ID fails")
        expect(!report(windows, current: [displays[0]]).complete, "screen removed fails")
        for mutation in 0..<7 {
            var changed = displays
            switch mutation {
            case 0: changed[1].id = 4
            case 1: changed[1].appKitFrame.origin.x += 1
            case 2: changed[1].quartzFrame.origin.x += 1
            case 3: changed[1].scale = 2
            case 4: changed[1].scale = 0
            case 5: changed[1].scale = .nan
            default: changed[1].quartzFrame.size = .zero
            }
            expect(!report(windows, current: changed).complete, "same-count topology mutation \(mutation) fails")
        }
    }
    private static func transitionPublicationTests() {
        var transformed = windows
        transformed[0].server?.frame = CGRect(x: 86, y: 55, width: 1556, height: 1007)
        transformed[1].server?.frame = CGRect(x: -23, y: -1216, width: 1728, height: 1152)
        let partial = report(transformed)
        let good = report(windows)
        expect(partial.topologyMatches && !partial.complete && partial.coveredDisplays == 0,
            "Native38 centered WindowServer transform must not count as full coverage")
        var state = LockedUseCoverageState()
        let token = state.begin(now: 10, expiresAt: 15)!
        expect(state.advance(token: token, now: 10.35, report: partial,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "cold window creation and lock transition may outlast 250ms without granting authority")
        expect(state.pending && !state.active, "transformed windows cannot authorize unlock")
        expect(state.advance(token: token, now: 10.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "a complete observation begins, but cannot bypass, the stability interval")
        intermediateComplete(&state, token, start: 10.75, report: good)
        expect(state.advance(token: token, now: 11.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready,
            "stable exact coverage is a ready candidate before claim expiry")
        expect(state.pending && !state.active, "candidate cannot authorize until committed")
        expect(state.commitReady(token: token, now: 11.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready,
            "fresh checks commit stable coverage")

        var missing = windows; missing[0].server = nil
        var zero = windows; zero[1].server?.frame = .zero
        for invalid in [missing, zero, transformed] {
            var waiting = LockedUseCoverageState()
            let attempt = waiting.begin(now: 10, expiresAt: 15)!
            expect(waiting.advance(token: attempt, now: 11, report: report(invalid),
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
                "missing, zero-size, and transformed windows remain pending")
            expect(!waiting.active, "publication waiting never substitutes for actual coverage")
            expect(waiting.advance(token: attempt,
                now: 10 + LockedUseCoverageState.publicationTimeout, report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .revoked,
                "even a complete report at the strict publication deadline must revoke")
            expect(waiting.advance(token: attempt, now: 13, report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale,
                "late complete callbacks cannot restore an expired generation")
        }
        var shortClaim = LockedUseCoverageState()
        let shortToken = shortClaim.begin(now: 10, expiresAt: 10.8)!
        expect(shortClaim.advance(token: shortToken, now: 10.7, report: partial,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "a shorter original claim can wait only while still valid")
        expect(shortClaim.advance(token: shortToken, now: 10.8, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .revoked,
            "original claim expiry wins over the larger publication budget")
    }
    private static func pendingTests() {
        let good = report(windows)
        var idle = LockedUseCoverageState()
        idle.revoke(); idle.confirmLocked()
        expect(idle.suppressed && !idle.active && !idle.pending && !idle.relocking,
            "pre-claim failure suppresses startup without initiating a lock")
        expect(idle.begin(now: 10, expiresAt: 11) == nil, "pre-claim suppression is permanent")
        var unpublished = windows; unpublished[1].server = nil
        let partial = report(unpublished)
        var state = LockedUseCoverageState()
        let token = state.begin(now: 10, expiresAt: 12)!
        expect(!state.active && state.pending, "begin cannot grant authority")
        expect(!state.validateActive(report: good, leaseValid: true, dependenciesHealthy: true),
            "renew/authorize reject pending")
        expect(state.advance(token: token, now: 10.1, report: partial,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending, "publication may settle asynchronously")
        expect(!state.active, "partial report never becomes active")
        expect(state.advance(token: token, now: 10.25, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending, "first full report starts stability")
        intermediateComplete(&state, token, start: 10.25, report: good)
        expect(state.advance(token: token, now: 11.25, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready, "stable report is ready to commit")
        expect(state.commitReady(token: token, now: 11.25, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready, "fresh ready check grants authority")
        expect(state.active && !state.pending, "ready settles pending generation")
        expect(state.advance(token: token, now: 11.25, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale, "completed callback cannot reply twice")
        for expiry in [10.2, 11.0] {
            var expired = LockedUseCoverageState()
            let attempt = expired.begin(now: 10, expiresAt: expiry)!
            expect(expired.advance(token: attempt, now: min(expiry, 10 + LockedUseCoverageState.publicationTimeout), report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .revoked, "deadline is strict including claim expiry")
            expect(expired.relocking && expired.suppressed, "deadline failure latches suppression")
            expect(expired.advance(token: attempt, now: 10.3, report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale, "timeout cannot later publish ready")
            expired.confirmLocked()
            expect(expired.advance(token: attempt, now: 10.4, report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale, "completed timeout relock cannot publish ready")
        }
        for reason in ["end_guard", "EOF", "parent_exit", "watchdog_exit", "tap_failure", "topology_change",
                       "wake", "physical_input", "send_failure"] {
            var cancelled = LockedUseCoverageState()
            let attempt = cancelled.begin(now: 10, expiresAt: 11)!
            cancelled.revoke()
            expect(cancelled.advance(token: attempt, now: 10.1, report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale, "\(reason) invalidates queued callback")
            expect(cancelled.relocking && cancelled.suppressed && !cancelled.active,
                "\(reason) late callback cannot clear relock")
            cancelled.confirmLocked()
            expect(cancelled.advance(token: attempt, now: 10.1, report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale, "\(reason) stays stale after lock confirmation")
            expect(cancelled.begin(now: 11, expiresAt: 12) == nil, "\(reason) cannot restart suppressed generation")
        }
        var disconnected = LockedUseCoverageState()
        let closedAttempt = disconnected.begin(now: 10, expiresAt: 11)!
        disconnected.revoke(); disconnected.confirmLocked(); disconnected.revoke()
        expect(disconnected.relocking && disconnected.suppressed,
            "EOF after lock confirmation still enters the cleanup path")
        expect(disconnected.advance(token: closedAttempt, now: 10.1, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale,
            "EOF cleanup cannot restore an already closed generation")
        disconnected.confirmLocked()
        expect(!disconnected.relocking && disconnected.suppressed, "EOF cleanup can complete without restoring authority")
        for failure in 0..<3 {
            var pending = LockedUseCoverageState()
            let attempt = pending.begin(now: 10, expiresAt: 11)!
            let changed = report(windows, current: [displays[0]])
            expect(pending.advance(token: attempt, now: 10.01, report: failure == 0 ? changed : good,
                leaseValid: failure != 1, dependenciesHealthy: failure != 2, systemLocked: true) == .revoked,
                "topology/lease/dependency failures revoke pending immediately")
            expect(pending.relocking && pending.suppressed, "pending failure latches relock")
        }
        expect(LockedUseCoverageState.publicationTimeout < 5, "publication remains bounded below the normal host lease")
        var invalid = LockedUseCoverageState()
        expect(invalid.begin(now: .nan, expiresAt: 11) == nil, "invalid clock cannot start a generation")
        expect(invalid.begin(now: 10, expiresAt: .infinity) == nil, "unbounded lease cannot start a generation")
        expect(invalid.begin(now: 10, expiresAt: 10) == nil, "expired lease cannot start a generation")
        let attempt = invalid.begin(now: 10, expiresAt: 11)!
        expect(invalid.begin(now: 10, expiresAt: 11) == nil, "second begin cannot replace pending token")
        expect(invalid.advance(token: UUID(), now: 10.01, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale, "foreign token cannot publish ready")
        expect(invalid.pending && !invalid.suppressed, "foreign callback cannot disturb the pending owner")
        expect(invalid.advance(token: attempt, now: .nan, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .revoked, "invalid observation clock revokes pending")
    }
    private static func activeTests() {
        let good = report(windows)
        for path in ["renew", "authorize", "tick"] {
            for failure in 0..<4 {
                var state = LockedUseCoverageState()
                let token = state.begin(now: 10, expiresAt: 12)!
                expect(state.advance(token: token, now: 10.25, report: good,
                    leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending, "active fixture starts stability")
                intermediateComplete(&state, token, start: 10.25, report: good)
                expect(state.advance(token: token, now: 11.25, report: good,
                    leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready, "active fixture is ready to commit")
                expect(state.commitReady(token: token, now: 11.25, report: good,
                    leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready, "active fixture becomes ready")
                expect(state.validateActive(report: good, leaseValid: true, dependenciesHealthy: true),
                    "\(path) accepts fresh full observation")
                let failedReport = failure == 0 ? report([])
                    : failure == 3 ? report(windows, current: [displays[0]]) : good
                expect(!state.validateActive(report: failedReport,
                    leaseValid: failure != 1, dependenciesHealthy: failure != 2),
                    "\(path) rejects fresh failed observation")
                expect(state.relocking && state.suppressed && !state.active,
                    "\(path) revokes authority and relocks")
                expect(!state.validateActive(report: good, leaseValid: true, dependenciesHealthy: true),
                    "\(path) healthy later sample cannot restore authority")
            }
        }
    }
    private static func stabilityTests() {
        let good = report(windows)
        let partial = report([windows[0]])
        var state = LockedUseCoverageState()
        let token = state.begin(now: 10, expiresAt: 15)!
        expect(state.advance(token: token, now: 10.125, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "first full sample must not authorize an unstable cover")
        expect(state.advance(token: token, now: 10.5, report: partial,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "a coverage gap stays pending but resets the complete interval")
        expect(state.advance(token: token, now: 10.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "coverage recovery starts a new interval")
        intermediateComplete(&state, token, start: 10.75, report: good)
        expect(state.advance(token: token, now: 11.749, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "less than one second after recovery cannot grant authority")
        expect(state.advance(token: token, now: 11.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready,
            "one full second of consecutive complete observations can settle")
        expect(state.pending && !state.active, "a ready candidate remains unable to authorize")
        expect(state.commitReady(token: token, now: 11.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready,
            "fresh commit becomes active")
        expect(!state.validateActive(report: partial, leaseValid: true, dependenciesHealthy: true),
            "active coverage loss still revokes without a stability grace period")
        expect(state.suppressed && state.relocking, "active loss remains fail-closed")
        var unlocked = LockedUseCoverageState()
        let unlockedToken = unlocked.begin(now: 10, expiresAt: 15)!
        expect(unlocked.advance(token: unlockedToken, now: 10.25, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "locked first observation begins stability")
        expect(unlocked.advance(token: unlockedToken, now: 10.5, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: false) == .revoked,
            "loss or unavailability of OS lock revokes pending immediately")
        expect(unlocked.advance(token: unlockedToken, now: 11.5, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale,
            "reacquired lock cannot revive the revoked generation")
        var backwards = LockedUseCoverageState()
        let backwardsToken = backwards.begin(now: 10, expiresAt: 15)!
        expect(backwards.advance(token: backwardsToken, now: 10.5, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "valid observation establishes start")
        expect(backwards.advance(token: backwardsToken, now: 10.4, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .revoked,
            "nonmonotonic time fails closed")
        var tickGap = LockedUseCoverageState()
        let tickToken = tickGap.begin(now: 10, expiresAt: 15)!
        expect(tickGap.advance(token: tickToken, now: 10.125, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending, "tick fixture starts")
        // A separate timer observed an incomplete report even though poll later sees full coverage.
        tickGap.resetPendingCoverage()
        expect(tickGap.advance(token: tickToken, now: 10.25, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "pending tick coverage loss resets observation start")
        intermediateComplete(&tickGap, tickToken, start: 10.25, report: good)
        expect(tickGap.advance(token: tickToken, now: 11.125, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "tick gap prevents old complete timestamp from granting")
        expect(tickGap.advance(token: tickToken, now: 11.25, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready,
            "only a full fresh interval after tick gap can prepare ready")
        var noCandidate = LockedUseCoverageState()
        let noCandidateToken = noCandidate.begin(now: 10, expiresAt: 15)!
        expect(noCandidate.commitReady(token: noCandidateToken, now: 10.125, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "commit cannot initialize or bypass the candidate")
        expect(noCandidate.pending && !noCandidate.active, "commit without candidate cannot grant")
        var sparse = LockedUseCoverageState()
        let sparseToken = sparse.begin(now: 10, expiresAt: 15)!
        expect(sparse.advance(token: sparseToken, now: 10.125, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending, "begin observing")
        expect(sparse.advance(token: sparseToken, now: 10.5, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "unobserved interval beyond max gap resets the candidate")
        intermediateComplete(&sparse, sparseToken, start: 10.5, report: good)
        expect(sparse.advance(token: sparseToken, now: 11.5, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready,
            "one second of bounded observations after the gap yields a candidate")
        expect(sparse.commitReady(token: sparseToken, now: 11.5, report: partial,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "fresh incomplete commit report resets stability and never activates")
        expect(!sparse.active && sparse.pending, "failed fresh report keeps pending")
        var crossing = LockedUseCoverageState()
        let crossingToken = crossing.begin(now: 10, expiresAt: 15)!
        expect(crossing.advance(token: crossingToken, now: 10.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending, "candidate starts")
        intermediateComplete(&crossing, crossingToken, start: 10.75, report: good)
        expect(crossing.advance(token: crossingToken, now: 11.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready, "candidate is still pending")
        expect(crossing.commitReady(token: crossingToken, now: 12, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .revoked,
            "deadline crossing between candidate and fresh commit revokes")
        expect(crossing.relocking && crossing.suppressed && !crossing.active, "deadline failure is fail-closed")
        var unlockAtCommit = LockedUseCoverageState()
        let unlockAtCommitToken = unlockAtCommit.begin(now: 10, expiresAt: 15)!
        _ = unlockAtCommit.advance(token: unlockAtCommitToken, now: 10.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true)
        intermediateComplete(&unlockAtCommit, unlockAtCommitToken, start: 10.75, report: good)
        expect(unlockAtCommit.advance(token: unlockAtCommitToken, now: 11.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready, "candidate requires second check")
        expect(unlockAtCommit.commitReady(token: unlockAtCommitToken, now: 11.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: false) == .revoked,
            "OS lock failure during final check cannot publish")
        expect(unlockAtCommit.commitReady(token: unlockAtCommitToken, now: 11.76, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale,
            "late final check cannot revive revoked generation")
        var strictDeadline = LockedUseCoverageState()
        let strictToken = strictDeadline.begin(now: 10, expiresAt: 15)!
        expect(strictDeadline.advance(token: strictToken, now: 11, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "complete observations cannot extend the original publication deadline")
        expect(strictDeadline.advance(token: strictToken, now: 12, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .revoked,
            "strict deadline wins even when stability duration is exactly met")
        var shortClaim = LockedUseCoverageState()
        let shortToken = shortClaim.begin(now: 10, expiresAt: 10.75)!
        expect(shortClaim.advance(token: shortToken, now: 10.125, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "short claim cannot grant without full duration")
        expect(shortClaim.advance(token: shortToken, now: 10.75, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .revoked,
            "short claim expires without granting authority")
    }
    private static func finalObservationTests() {
        let good = report(windows)
        let partial = report([windows[0]])
        func candidate() -> (LockedUseCoverageState, UUID) {
            var state = LockedUseCoverageState()
            let token = state.begin(now: 10, expiresAt: 15)!
            for now in [10.25, 10.5, 10.75, 11.0] {
                expect(state.advance(token: token, now: now, report: good,
                    leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
                    "each initial observation remains pending")
            }
            expect(state.advance(token: token, now: 11.25, report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .ready,
                "only a full interval prepares the final check")
            expect(state.pending && !state.active, "all final observations begin while pending")
            return (state, token)
        }
        for failure in 0..<4 {
            var (state, token) = candidate()
            let changed = report(windows, current: [displays[0]])
            expect(state.commitReady(token: token, now: 11.25, report: failure == 0 ? changed : good,
                leaseValid: failure != 1, dependenciesHealthy: failure != 2, systemLocked: failure != 3) == .revoked,
                "final topology, lease, dependency, or lock failure immediately revokes")
            expect(!state.active && state.relocking && state.suppressed, "failed final check cannot grant")
            expect(state.commitReady(token: token, now: 11.26, report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale,
                "a late successful final check cannot revive revoked authority")
        }
        for source in ["input", "wake", "parent_exit", "tap_failure"] {
            var (state, token) = candidate()
            state.revoke()
            expect(state.commitReady(token: token, now: 11.25, report: good,
                leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .stale,
                "\(source) between candidate and commit rejects the queued final callback")
            expect(!state.active && state.relocking, "\(source) remains fail-closed")
        }
        var (tick, tickToken) = candidate()
        tick.resetPendingCoverage()
        expect(tick.commitReady(token: tickToken, now: 11.25, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "independent tick gap invalidates a prepared candidate")
        expect(tick.pending && !tick.active, "tick gap cannot publish")
        var (gap, gapToken) = candidate()
        expect(gap.commitReady(token: gapToken, now: 11.501, report: good,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "a scheduler gap during the final observation restarts settling")
        expect(gap.pending && !gap.active, "late final observation never activates")
        var (lost, lostToken) = candidate()
        expect(lost.commitReady(token: lostToken, now: 11.25, report: partial,
            leaseValid: true, dependenciesHealthy: true, systemLocked: true) == .pending,
            "final poll detecting incomplete coverage invalidates the candidate")
        expect(lost.pending && !lost.active, "partial final report never activates")
    }
    static func main() {
        finalObservationTests(); stabilityTests(); geometryTests(); transitionPublicationTests(); pendingTests(); activeTests()
        print("LockedUseCoverage: \(assertions) assertions passed")
    }
}
