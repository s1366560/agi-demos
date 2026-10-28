import CoreGraphics
import Darwin
import Foundation

/// These fields are supplied by the authenticated host, never inferred from text.
struct LockedUseBinding: Codable, Equatable {
    let sessionID: String
    let runID: String
    let generation: String
    var valid: Bool { [sessionID, runID, generation].allSatisfy { !$0.isEmpty && $0.utf8.count <= 256 } }
}

struct LockedUseProcessIdentity: Codable, Equatable {
    let pid: Int32
    let startSeconds: UInt64
    let startMicroseconds: UInt64
    static func current(_ pid: Int32) -> Self? {
        var info = proc_bsdinfo()
        let size = Int32(MemoryLayout<proc_bsdinfo>.size)
        guard pid > 0, proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, size) == size,
              info.pbi_uid == getuid(), info.pbi_status != SZOMB else { return nil }
        return Self(pid: pid, startSeconds: info.pbi_start_tvsec, startMicroseconds: info.pbi_start_tvusec)
    }
    var alive: Bool { Self.current(pid) == self }
}

struct LockedUseSupervisionClaim: Codable, Equatable {
    let binding: LockedUseBinding
    let guardian: LockedUseProcessIdentity
    /// systemUptime has the same origin in the cooperating processes. Repeating
    /// an input heartbeat does not extend this independently expiring authority.
    let expiresAtUptime: Double
    func valid(now: Double) -> Bool {
        binding.valid && guardian.pid > 0 && expiresAtUptime.isFinite
            && expiresAtUptime > now && expiresAtUptime <= now + 10.1
    }
}

/// Pure lease transitions are tested without locking the developer's screen.
struct LockedUseSupervision {
    private(set) var claim: LockedUseSupervisionClaim?
    private(set) var mustRelock = false
    private(set) var reason: String?
    mutating func accept(_ next: LockedUseSupervisionClaim?, now: Double) -> Bool {
        guard let next = next else {
            if claim != nil { revoke("lease_released") }
            return true
        }
        guard !mustRelock, next.valid(now: now),
              claim == nil || (claim?.binding == next.binding && claim?.guardian == next.guardian) else { return false }
        if claim == nil { reason = nil }
        claim = next
        return true
    }
    mutating func check(now: Double, guardianAlive: Bool) {
        guard let claim = claim else { return }
        if !guardianAlive { revoke("guardian_exited") }
        else if now >= claim.expiresAtUptime { revoke("lease_expired") }
    }
    mutating func revoke(_ reason: String) {
        guard claim != nil else { return }
        mustRelock = true
        if self.reason == nil { self.reason = reason }
    }
    mutating func confirmLocked() { claim = nil; mustRelock = false; reason = nil }
}

/// A request is not a completed lock. Keep retrying while an independently
/// observed console state is unlocked or unavailable, retaining any live cover.
final class LockedUseRelock {
    private let locked: () -> Bool
    private let request: () -> Void
    private var nextAttempt = -Double.infinity
    init(locked: @escaping () -> Bool = LockedUseRelock.systemLocked,
         request: @escaping () -> Void = { LockedUseRelock.postLock() }) {
        self.locked = locked; self.request = request
    }
    static func systemLocked() -> Bool {
        (CGSessionCopyCurrentDictionary() as? [String: Any])?["CGSSessionScreenIsLocked"] as? Bool == true
    }
    static func postLock(tag: Int64 = 0) {
        let source = CGEventSource(stateID: .privateState)
        for pressed in [true, false] {
            guard let event = CGEvent(keyboardEventSource: source, virtualKey: 0x0c, keyDown: pressed) else { continue }
            event.flags = [.maskControl, .maskCommand]
            event.setIntegerValueField(.eventSourceUserData, value: tag)
            event.post(tap: .cghidEventTap)
        }
    }
    func step(now: Double = ProcessInfo.processInfo.systemUptime) -> Bool {
        if locked() { return true }
        if now >= nextAttempt { request(); nextAttempt = now + 0.5 }
        return false
    }
}
