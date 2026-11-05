import AppKit
import CoreFoundation
import CoreGraphics
import Foundation

/// AppKit and Quartz frames deliberately remain in their native global spaces.
struct LockedUseDisplayCoverage: Equatable {
    var id: UInt32
    var appKitFrame: CGRect
    var quartzFrame: CGRect
    var scale: CGFloat
}

struct LockedUseWindowServerCoverage {
    var number: Int32
    var ownerPID: Int32
    var frame: CGRect
    var onScreen: Bool
    var alpha: Double
    var layer: Int
}

struct LockedUseWindowCoverage {
    var displayID: UInt32
    var number: Int32
    var appKitFrame: CGRect
    var visible: Bool
    var opaque: Bool
    var alpha: Double
    var level: Int
    var server: LockedUseWindowServerCoverage?
}

struct LockedUseCoverageReport {
    let topologyMatches: Bool
    let complete: Bool
    let coveredDisplays: Int
    let failure: String?
}

/// Structural observations only: identity, geometry, opacity, ordering and visibility.
enum LockedUseCoverage {
    private static func valid(_ frame: CGRect) -> Bool {
        [frame.origin.x, frame.origin.y, frame.width, frame.height].allSatisfy(\.isFinite)
            && frame.width > 0 && frame.height > 0
    }
    static func validTopology(_ displays: [LockedUseDisplayCoverage]) -> Bool {
        !displays.isEmpty && Set(displays.map(\.id)).count == displays.count
            && displays.allSatisfy {
                $0.id != 0 && valid($0.appKitFrame) && valid($0.quartzFrame)
                    && $0.scale.isFinite && $0.scale > 0
            }
    }
    static func check(expected: [LockedUseDisplayCoverage], current: [LockedUseDisplayCoverage]?,
                      windows: [LockedUseWindowCoverage], ownerPID: Int32,
                      requiredLevel: Int) -> LockedUseCoverageReport {
        guard let current = current, validTopology(expected), validTopology(current),
              expected.sorted(by: { $0.id < $1.id }) == current.sorted(by: { $0.id < $1.id }) else {
            return LockedUseCoverageReport(topologyMatches: false, complete: false,
                coveredDisplays: 0, failure: "display_topology_changed")
        }
        guard ownerPID > 0, windows.count == expected.count,
              Set(windows.map(\.displayID)).count == windows.count,
              Set(windows.map(\.number)).count == windows.count else {
            return LockedUseCoverageReport(topologyMatches: true, complete: false,
                coveredDisplays: 0, failure: "cover_window_identity_mismatch")
        }
        let byDisplay = Dictionary(uniqueKeysWithValues: expected.map { ($0.id, $0) })
        let covered = windows.filter { window in
            guard let display = byDisplay[window.displayID], window.number > 0,
                  valid(window.appKitFrame), window.appKitFrame == display.appKitFrame,
                  window.visible, window.opaque, window.alpha == 1, window.level == requiredLevel,
                  let server = window.server, server.number == window.number, server.ownerPID == ownerPID,
                  valid(server.frame), server.frame == display.quartzFrame,
                  server.onScreen, server.alpha == 1, server.layer == requiredLevel else { return false }
            return true
        }.count
        return LockedUseCoverageReport(topologyMatches: true, complete: covered == expected.count,
            coveredDisplays: covered, failure: covered == expected.count ? nil : "cover_window_not_published")
    }
}

/// The first revocation survives recovery and later requests. Only closed
/// protocol categories, bounded input metadata and allowlisted CFBooleans leave the process.
struct LockedUseGuardianRevocation {
    enum Source: String, CaseIterable {
        case publicationCheck = "publication_check", pendingTick = "pending_tick"
        case activeTick = "active_tick", renewCoverage = "renew_coverage", authorizeCoverage = "authorize_coverage"
        case windowPresentation = "window_presentation"
        case eventTapTimeout = "event_tap_timeout", eventTapDisabled = "event_tap_disabled"
        case eventTapInput = "event_tap_input", globalMonitorInput = "global_monitor_input"
        case localMonitorInput = "local_monitor_input", screensWake = "screens_wake"
        case screenParameters = "screen_parameters", endGuard = "end_guard"
        case readFailure = "read_failure", writeFailure = "write_failure", unknown
    }
    enum EventType: String, CaseIterable {
        case keyDown = "key_down", keyUp = "key_up", flagsChanged = "flags_changed"
        case mouseDown = "mouse_down", mouseUp = "mouse_up", mouseMoved = "mouse_moved"
        case mouseDragged = "mouse_dragged", scroll, unknown
        init(_ type: CGEventType) {
            switch type {
            case .keyDown: self = .keyDown
            case .keyUp: self = .keyUp
            case .flagsChanged: self = .flagsChanged
            case .leftMouseDown, .rightMouseDown, .otherMouseDown: self = .mouseDown
            case .leftMouseUp, .rightMouseUp, .otherMouseUp: self = .mouseUp
            case .mouseMoved: self = .mouseMoved
            case .leftMouseDragged, .rightMouseDragged, .otherMouseDragged: self = .mouseDragged
            case .scrollWheel: self = .scroll
            default: self = .unknown
            }
        }
        init(_ type: NSEvent.EventType) {
            switch type {
            case .keyDown: self = .keyDown
            case .keyUp: self = .keyUp
            case .flagsChanged: self = .flagsChanged
            case .leftMouseDown, .rightMouseDown, .otherMouseDown: self = .mouseDown
            case .leftMouseUp, .rightMouseUp, .otherMouseUp: self = .mouseUp
            case .mouseMoved: self = .mouseMoved
            case .leftMouseDragged, .rightMouseDragged, .otherMouseDragged: self = .mouseDragged
            case .scrollWheel: self = .scroll
            default: self = .unknown
            }
        }
    }
    /// Raw event timestamps are normalized to seconds without assuming they
    /// share a clock with callback or coverage uptime observations.
    /// Missing observations stay absent; an observed zero is retained.
    /// Event-reported PID/times are not verified process identity. These values
    /// diagnose delivery and never decide whether an input is permitted.
    struct InputEvent {
        static let maximumTimestampSeconds = Double(UInt64.max) / 1_000_000_000
        let sourcePID: Int32?
        let nsEventType: EventType?
        let cgEventType: EventType?
        let receivedUptimeSeconds: Double?
        let nsTimestampSeconds: Double?
        let cgTimestampSeconds: Double?
        let coverageBeginUptimeSeconds: Double?
        let coverageReadyUptimeSeconds: Double?

        init(sourcePID: Int64, nsEventType: EventType?, cgEventType: EventType,
             receivedUptimeSeconds: Double, nsTimestampSeconds: Double?, cgTimestampSeconds: Double,
             coverageBeginUptimeSeconds: Double?, coverageReadyUptimeSeconds: Double?) {
            self.sourcePID = Int32(exactly: sourcePID).flatMap { $0 >= 0 ? $0 : nil }
            self.nsEventType = nsEventType; self.cgEventType = cgEventType
            self.receivedUptimeSeconds = Self.timestamp(receivedUptimeSeconds)
            self.nsTimestampSeconds = Self.timestamp(nsTimestampSeconds)
            self.cgTimestampSeconds = Self.timestamp(cgTimestampSeconds)
            self.coverageBeginUptimeSeconds = Self.timestamp(coverageBeginUptimeSeconds)
            self.coverageReadyUptimeSeconds = Self.timestamp(coverageReadyUptimeSeconds)
        }
        private init(_ raw: [String: Any]) {
            sourcePID = Self.number(raw["source_pid"]).flatMap { Int32(exactly: $0.doubleValue) }
                .flatMap { $0 >= 0 ? $0 : nil }
            nsEventType = (raw["ns_event_type"] as? String).map { EventType(rawValue: $0) ?? .unknown }
            cgEventType = (raw["cg_event_type"] as? String).map { EventType(rawValue: $0) ?? .unknown }
            receivedUptimeSeconds = Self.timestamp(Self.number(raw["received_uptime_seconds"])?.doubleValue)
            nsTimestampSeconds = Self.timestamp(Self.number(raw["ns_timestamp_seconds"])?.doubleValue)
            cgTimestampSeconds = Self.timestamp(Self.number(raw["cg_timestamp_seconds"])?.doubleValue)
            coverageBeginUptimeSeconds = Self.timestamp(Self.number(raw["coverage_begin_uptime_seconds"])?.doubleValue)
            coverageReadyUptimeSeconds = Self.timestamp(Self.number(raw["coverage_ready_uptime_seconds"])?.doubleValue)
        }
        private static func number(_ value: Any?) -> NSNumber? {
            guard let value = value as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID() else { return nil }
            return value
        }
        private static func timestamp(_ value: Double?) -> Double? {
            guard let value = value, value.isFinite, value >= 0, value <= maximumTimestampSeconds else { return nil }
            return value
        }
        static func decode(_ value: Any?) -> Self? {
            guard let raw = value as? [String: Any] else { return nil }
            let result = Self(raw)
            return result.status.isEmpty ? nil : result
        }
        var status: [String: Any] {
            var value: [String: Any] = [:]
            if let sourcePID = sourcePID { value["source_pid"] = sourcePID }
            if let nsEventType = nsEventType { value["ns_event_type"] = nsEventType.rawValue }
            if let cgEventType = cgEventType { value["cg_event_type"] = cgEventType.rawValue }
            if let receivedUptimeSeconds = receivedUptimeSeconds { value["received_uptime_seconds"] = receivedUptimeSeconds }
            if let nsTimestampSeconds = nsTimestampSeconds { value["ns_timestamp_seconds"] = nsTimestampSeconds }
            if let cgTimestampSeconds = cgTimestampSeconds { value["cg_timestamp_seconds"] = cgTimestampSeconds }
            if let coverageBeginUptimeSeconds = coverageBeginUptimeSeconds { value["coverage_begin_uptime_seconds"] = coverageBeginUptimeSeconds }
            if let coverageReadyUptimeSeconds = coverageReadyUptimeSeconds { value["coverage_ready_uptime_seconds"] = coverageReadyUptimeSeconds }
            return value
        }
    }

    enum CoverageFailure: String, CaseIterable {
        case topologyChanged = "display_topology_changed"
        case identityMismatch = "cover_window_identity_mismatch"
        case notPublished = "cover_window_not_published"
        case unknown
    }
    struct Record {
        let source: Source
        let eventType: EventType?
        let coverageFailure: CoverageFailure?
        let checks: [String: Bool]
        let inputEvent: InputEvent?
        init(source: Source, eventType: EventType? = nil, coverageFailure: CoverageFailure? = nil,
             checks: Any? = nil, inputEvent: InputEvent? = nil) {
            self.source = source; self.eventType = eventType; self.coverageFailure = coverageFailure
            self.inputEvent = inputEvent
            let raw = checks as? [String: Any] ?? [:]
            var safe: [String: Bool] = [:]
            for key in ["was_active", "was_pending", "was_relocking", "was_suppressed",
                        "old_claim_valid", "dependencies_healthy", "connected", "not_suppressed", "not_relocking",
                        "topology_matches", "covered_all_displays", "has_covered_display",
                        "event_tap_created", "event_tap_valid", "event_tap_enabled", "source_alive", "watchdog_alive",
                        "sender_is_zero", "sender_is_guardian", "sender_is_source", "sender_is_watchdog", "recovery_tag_matches",
                        "event_source_hid", "event_source_combined", "event_source_private"] {
                if let value = raw[key] as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() {
                    safe[key] = value.boolValue
                }
            }
            self.checks = safe
        }
        static func capturing(source: Source, eventType: EventType? = nil,
                              report: LockedUseCoverageReport? = nil, checks: [String: Bool],
                              inputEvent: InputEvent? = nil) -> Self {
            var checks = checks
            if let report = report {
                checks["topology_matches"] = report.topologyMatches
                checks["covered_all_displays"] = report.complete
                checks["has_covered_display"] = report.coveredDisplays > 0
            }
            return Self(source: source, eventType: eventType,
                coverageFailure: report?.failure.map { CoverageFailure(rawValue: $0) ?? .unknown },
                checks: checks, inputEvent: inputEvent)
        }
        static func decode(_ value: Any?) -> Self? {
            guard let raw = value as? [String: Any], let source = raw["source"] as? String else { return nil }
            return Self(source: Source(rawValue: source) ?? .unknown,
                eventType: (raw["event_type"] as? String).map { EventType(rawValue: $0) ?? .unknown },
                coverageFailure: (raw["coverage_failure"] as? String).map { CoverageFailure(rawValue: $0) ?? .unknown },
                checks: raw["checks"], inputEvent: InputEvent.decode(raw["input_event"]))
        }
        var status: [String: Any] {
            var value: [String: Any] = ["source": source.rawValue]
            if let eventType = eventType { value["event_type"] = eventType.rawValue }
            if let coverageFailure = coverageFailure { value["coverage_failure"] = coverageFailure.rawValue }
            if !checks.isEmpty { value["checks"] = checks }
            if let inputEvent = inputEvent, !inputEvent.status.isEmpty { value["input_event"] = inputEvent.status }
            return value
        }
    }
    private(set) var first: Record?
    mutating func record(_ value: Record) {
        if first == nil { first = value }
    }
}

/// A single-use generation. Cancellation permanently invalidates its queued callbacks.
/// A deadline is a publication budget, never evidence that coverage exists.
struct LockedUseCoverageState {
    enum Advance: Equatable { case pending, ready, revoked, stale }
    private enum Phase { case idle, pending, guarded, relocking, locked }
    private var phase = Phase.idle
    private var attempt: (token: UUID, deadline: Double)?
    private var completeSince: Double?
    private var lastPendingObservation: Double?
    private var readyCandidate: UUID?
    private(set) var suppressed = false
    private(set) var beginUptimeSeconds: Double?
    private(set) var readyUptimeSeconds: Double?
    // Cold AppKit publication can overlap the system lock transition. Waiting
    // grants no authority and remains capped by the original supervision claim.
    // Consecutive observations add a pre-unlock settling interval, not proof of future coverage.
    static let requiredCompleteObservation = 1.0
    // Polling targets 10ms. Large scheduler gaps must reset, never count as continuous samples.
    static let maximumObservationGap = 0.25
    static let publicationTimeout = 2.0
    static let beginReplyTimeout = publicationTimeout + 0.5
    var active: Bool { phase == .guarded }
    var pending: Bool { phase == .pending }
    var relocking: Bool { phase == .relocking }
    var diagnosticState: [String: Bool] {
        ["was_active": active, "was_pending": pending, "was_relocking": relocking, "was_suppressed": suppressed]
    }

    mutating func begin(now: Double, expiresAt: Double) -> UUID? {
        guard phase == .idle, !suppressed, now.isFinite, expiresAt.isFinite, expiresAt > now else { return nil }
        let token = UUID()
        let deadline = min(now + Self.publicationTimeout, expiresAt)
        attempt = (token, deadline); phase = .pending
        beginUptimeSeconds = now; completeSince = nil; lastPendingObservation = now; readyCandidate = nil
        return token
    }
    mutating func advance(token: UUID, now: Double, report: LockedUseCoverageReport,
                          leaseValid: Bool, dependenciesHealthy: Bool, systemLocked: Bool) -> Advance {
        guard phase == .pending, let attempt = attempt, attempt.token == token else { return .stale }
        guard now.isFinite, let previous = lastPendingObservation, now >= previous,
              now < attempt.deadline, leaseValid, dependenciesHealthy, systemLocked,
              report.topologyMatches else {
            revoke(); return .revoked
        }
        lastPendingObservation = now
        guard report.complete else { resetPendingCoverage(); return .pending }
        guard let start = completeSince, now - previous <= Self.maximumObservationGap else {
            completeSince = now; readyCandidate = nil; return .pending
        }
        guard now - start >= Self.requiredCompleteObservation else { return .pending }
        // A ready candidate remains pending until a fresh check commits the same token.
        readyCandidate = token
        return .ready
    }
    mutating func commitReady(token: UUID, now: Double, report: LockedUseCoverageReport,
                              leaseValid: Bool, dependenciesHealthy: Bool, systemLocked: Bool) -> Advance {
        guard phase == .pending, let attempt = attempt, attempt.token == token else { return .stale }
        guard readyCandidate == token else { return .pending }
        let checked = advance(token: token, now: now, report: report, leaseValid: leaseValid,
            dependenciesHealthy: dependenciesHealthy, systemLocked: systemLocked)
        guard checked == .ready else { return checked }
        self.attempt = nil; completeSince = nil; lastPendingObservation = nil; readyCandidate = nil; phase = .guarded
        readyUptimeSeconds = now
        return .ready
    }
    // Any independent pending observation of a coverage gap invalidates stability.
    mutating func resetPendingCoverage() {
        guard pending else { return }
        completeSince = nil; readyCandidate = nil
    }
    mutating func validateActive(report: LockedUseCoverageReport, leaseValid: Bool,
                                 dependenciesHealthy: Bool) -> Bool {
        guard active else { return false }
        guard report.topologyMatches, report.complete, leaseValid, dependenciesHealthy else { revoke(); return false }
        return true
    }
    mutating func revoke() {
        suppressed = true; attempt = nil; completeSince = nil; lastPendingObservation = nil
        readyCandidate = nil
        if phase != .idle { phase = .relocking }
    }
    mutating func confirmLocked() {
        guard relocking else { return }
        phase = .locked
    }
}
