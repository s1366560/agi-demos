import AppKit
import CoreGraphics
import CryptoKit
import Foundation

/// This process owns coverage independently of the helper's execution queue.
/// The separate input watchdog remains responsible if this process itself exits.
final class Guardian: NSObject {
    private let windows = GuardianCoverageWindows()
    private var coverage = LockedUseCoverageState()
    private var revocation = LockedUseGuardianRevocation()
    private typealias RevocationSource = LockedUseGuardianRevocation.Source
    private var pendingReply: (token: UUID, id: Any)?
    private var monitor: Any?
    private var localMonitor: Any?
    private var eventTap: CFMachPort?
    private var timer: Timer?
    private var initialized = false
    private var active: Bool { coverage.active }
    private var suppressed: Bool { coverage.suppressed }
    private var disconnected = false
    private var relocking: Bool { coverage.relocking }
    private var source: LockedUseProcessIdentity?
    private var watchdog: LockedUseProcessIdentity?
    private var recoveryTag: Int64 = 0
    private var claim: LockedUseSupervisionClaim?
    private let recovery = LockedUseRelock()

    func start() {
        signal(SIGPIPE, SIG_IGN)
        let types: [CGEventType] = [.keyDown, .keyUp, .flagsChanged, .leftMouseDown, .leftMouseUp,
            .rightMouseDown, .rightMouseUp, .otherMouseDown, .otherMouseUp, .mouseMoved,
            .leftMouseDragged, .rightMouseDragged, .otherMouseDragged, .scrollWheel]
        let mask = types.reduce(CGEventMask(0)) { $0 | (CGEventMask(1) << $1.rawValue) }
        eventTap = CGEvent.tapCreate(tap: .cghidEventTap, place: .headInsertEventTap,
            options: .defaultTap, eventsOfInterest: mask, callback: { _, type, event, pointer in
                guard let pointer = pointer else { return Unmanaged.passUnretained(event) }
                return Unmanaged<Guardian>.fromOpaque(pointer).takeUnretainedValue().filter(type: type, event: event)
            }, userInfo: Unmanaged.passUnretained(self).toOpaque())
        if let tap = eventTap, let runSource = CFMachPortCreateRunLoopSource(nil, tap, 0) {
            CFRunLoopAddSource(CFRunLoopGetMain(), runSource, .commonModes)
            CGEvent.tapEnable(tap: tap, enable: true)
        }
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.screensDidWakeNotification,
            object: nil, queue: .main) { [weak self] _ in self?.topologyChanged(.screensWake) }
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification,
            object: nil, queue: .main) { [weak self] _ in self?.topologyChanged(.screenParameters) }
        monitor = NSEvent.addGlobalMonitorForEvents(matching: [.keyDown, .leftMouseDown, .rightMouseDown,
            .otherMouseDown, .mouseMoved, .scrollWheel]) { [weak self] event in self?.physical(event, source: .globalMonitorInput) }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .leftMouseDown, .rightMouseDown,
            .otherMouseDown, .mouseMoved, .scrollWheel]) { [weak self] event in
            self?.physical(event, source: .localMonitorInput); return self?.active == true || self?.coverage.pending == true || self?.relocking == true ? nil : event
        }
        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in self?.tick() }
        Thread { [weak self] in self?.readLoop() }.start()
    }
    private func physical(_ event: NSEvent, source: RevocationSource) {
        guard active || coverage.pending, let cg = event.cgEvent else { return }
        let inputEvent = captureInputEvent(cg, native: event)
        var checks = coverage.diagnosticState
        guard !permitted(cg, checks: &checks) else { return }
        relock(source, checks: checks, event: cg, inputEvent: inputEvent)
    }
    private func captureInputEvent(_ event: CGEvent, native: NSEvent? = nil) -> LockedUseGuardianRevocation.InputEvent {
        LockedUseGuardianRevocation.InputEvent(
            sourcePID: event.getIntegerValueField(.eventSourceUnixProcessID),
            nsEventType: native.map { .init($0.type) }, cgEventType: .init(event.type),
            receivedUptimeSeconds: ProcessInfo.processInfo.systemUptime,
            nsTimestampSeconds: native?.timestamp, cgTimestampSeconds: Double(event.timestamp) / 1_000_000_000,
            coverageBeginUptimeSeconds: coverage.beginUptimeSeconds,
            coverageReadyUptimeSeconds: coverage.readyUptimeSeconds)
    }
    private func permitted(_ event: CGEvent, checks: inout [String: Bool]) -> Bool {
        let sender = event.getIntegerValueField(.eventSourceUnixProcessID)
        checks["sender_is_zero"] = sender == 0
        let isGuardian = sender == Int64(getpid())
        checks["sender_is_guardian"] = isGuardian
        if isGuardian { return true }
        let isSource = sender == Int64(source?.pid ?? 0)
        checks["sender_is_source"] = isSource
        if isSource {
            let alive = source?.alive == true
            checks["source_alive"] = alive
            if alive {
                if active { return true }
                if [.keyDown, .keyUp].contains(event.type), event.getIntegerValueField(.keyboardEventKeycode) == 0x0c,
                   event.flags.contains([.maskControl, .maskCommand]) { return true }
            }
        }
        let isWatchdog = sender == Int64(watchdog?.pid ?? 0)
        checks["sender_is_watchdog"] = isWatchdog
        guard isWatchdog else { return false }
        let alive = watchdog?.alive == true
        checks["watchdog_alive"] = alive
        guard alive else { return false }
        let tagMatches = event.getIntegerValueField(.eventSourceUserData) == recoveryTag
        checks["recovery_tag_matches"] = tagMatches
        guard tagMatches else { return false }
        if [.keyUp, .leftMouseUp, .rightMouseUp, .otherMouseUp].contains(event.type) { return true }
        return event.type == .keyDown && event.getIntegerValueField(.keyboardEventKeycode) == 0x0c
            && event.flags.contains([.maskControl, .maskCommand])
    }
    private func filter(type: CGEventType, event: CGEvent) -> Unmanaged<CGEvent>? {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            relock(type == .tapDisabledByTimeout ? .eventTapTimeout : .eventTapDisabled)
            if let tap = eventTap { CGEvent.tapEnable(tap: tap, enable: true) }
            return nil
        }
        let inputEvent = captureInputEvent(event)
        var checks = coverage.diagnosticState
        if permitted(event, checks: &checks) { return Unmanaged.passUnretained(event) }
        if active || coverage.pending || !windows.isEmpty {
            relock(.eventTapInput, checks: checks, event: event, inputEvent: inputEvent); return nil
        }
        return Unmanaged.passUnretained(event)
    }
    private func topologyChanged(_ source: RevocationSource) {
        guard claim != nil else { return }
        // A new topology needs a new authenticated generation, never an automatic refresh.
        relock(source)
    }
    private func inputProtectionReady(_ checks: inout [String: Bool]) -> Bool {
        var observedActive = active, observedSuppressed = suppressed, observedRelocking = relocking
        var observed: [String: Bool] = ["event_tap_created": eventTap != nil]
        let ready = LockedUseInputProtection.checkTap(eventTap, isValid: {
            let valid = CFMachPortIsValid($0); observed["event_tap_valid"] = valid; return valid
        }, isEnabled: {
            let enabled = CGEvent.tapIsEnabled(tap: $0); observed["event_tap_enabled"] = enabled; return enabled
        }, active: &observedActive, suppressed: &observedSuppressed, relocking: &observedRelocking)
        checks.merge(observed) { _, value in value }
        return ready
    }
    private func dependenciesReady(_ checks: inout [String: Bool]) -> Bool {
        func checked(_ name: String, _ value: Bool) -> Bool { checks[name] = value; return value }
        let ready = checked("connected", !disconnected) && checked("not_suppressed", !suppressed)
            && checked("not_relocking", !relocking) && checked("source_alive", source?.alive == true)
            && checked("watchdog_alive", watchdog?.alive == true) && inputProtectionReady(&checks)
        checks["dependencies_healthy"] = ready
        return ready
    }
    private func validClaim() -> Bool {
        claim?.valid(now: ProcessInfo.processInfo.systemUptime) == true
    }
    private func validateCoverage(_ source: RevocationSource) -> (Bool, LockedUseCoverageReport) {
        var checks = coverage.diagnosticState
        let report = windows.report()
        let leaseValid = validClaim(); checks["old_claim_valid"] = leaseValid
        let dependenciesHealthy = dependenciesReady(&checks)
        let ready = coverage.validateActive(report: report, leaseValid: leaseValid,
            dependenciesHealthy: dependenciesHealthy)
        if !ready { relock(source, report: report, checks: checks) }
        return (ready, report)
    }
    private func beginCoverage(_ id: Any, claim next: LockedUseSupervisionClaim) {
        guard let token = coverage.begin(now: ProcessInfo.processInfo.systemUptime,
            expiresAt: next.expiresAtUptime) else { send(id, ["error": "guard_rejected"]); return }
        claim = next; pendingReply = (token, id)
        guard windows.present() else { relock(.windowPresentation); return }
        pollCoverage(token)
    }
    private func pollCoverage(_ token: UUID) {
        guard coverage.pending, pendingReply?.token == token else { return }
        var checks = coverage.diagnosticState
        let report = windows.report()
        let now = ProcessInfo.processInfo.systemUptime
        let leaseValid = validClaim(); checks["old_claim_valid"] = leaseValid
        let dependenciesHealthy = dependenciesReady(&checks)
        let result = coverage.advance(token: token, now: now,
            report: report, leaseValid: leaseValid, dependenciesHealthy: dependenciesHealthy)
        switch result {
        case .pending:
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.01) { [weak self] in self?.pollCoverage(token) }
        case .ready:
            guard let reply = pendingReply, reply.token == token else { return }
            pendingReply = nil
            send(reply.id, coverageResponse(ready: true, report: report))
        case .revoked: relock(.publicationCheck, report: report, checks: checks)
        case .stale: return
        }
    }
    private func coverageResponse(ready: Bool, report: LockedUseCoverageReport) -> [String: Any] {
        var response: [String: Any] = ["ready": ready, "covered_displays": report.coveredDisplays,
            "phase": ready ? "guarded" : "relocking"]
        if !ready {
            response["checks"] = ["topology_matches": report.topologyMatches, "covered_all_displays": report.complete,
                "event_tap_created": eventTap != nil,
                "event_tap_valid": eventTap.map(CFMachPortIsValid) == true,
                "event_tap_enabled": eventTap.map { CFMachPortIsValid($0) && CGEvent.tapIsEnabled(tap: $0) } == true,
                "source_alive": source?.alive == true, "watchdog_alive": watchdog?.alive == true]
            response["coverage_failure"] = report.failure ?? "guard_dependency_unavailable"
        }
        return response
    }
    private func tick() {
        if coverage.pending {
            var checks = coverage.diagnosticState
            let report = windows.report()
            func checkedClaim() -> Bool {
                let valid = validClaim(); checks["old_claim_valid"] = valid; return valid
            }
            if !report.topologyMatches || !checkedClaim() || !dependenciesReady(&checks) {
                relock(.pendingTick, report: report, checks: checks)
            }
        } else if active { _ = validateCoverage(.activeTick) }
        if relocking, recovery.step() {
            coverage.confirmLocked(); windows.close()
            if disconnected { exit(0) }
        }
    }
    private func relock(_ source: RevocationSource, report: LockedUseCoverageReport? = nil,
                        checks observed: [String: Bool]? = nil, event: CGEvent? = nil,
                        inputEvent: LockedUseGuardianRevocation.InputEvent? = nil) {
        var checks = observed ?? coverage.diagnosticState
        if let event = event {
            let state = event.getIntegerValueField(.eventSourceStateID)
            checks["event_source_hid"] = state == Int64(CGEventSourceStateID.hidSystemState.rawValue)
            checks["event_source_combined"] = state == Int64(CGEventSourceStateID.combinedSessionState.rawValue)
            checks["event_source_private"] = state == Int64(CGEventSourceStateID.privateState.rawValue)
        }
        revocation.record(.capturing(source: source,
            eventType: event.map { LockedUseGuardianRevocation.EventType($0.type) }, report: report,
            checks: checks, inputEvent: inputEvent))
        // Consume the response slot before writing or initiating recovery, including on EOF.
        coverage.revoke()
        let reply = pendingReply; pendingReply = nil
        guard claim != nil else { return }
        _ = recovery.step()
        if let reply = reply, !disconnected {
            send(reply.id, coverageResponse(ready: false, report: windows.report()))
        }
    }
    private func readLoop() {
        do {
            while true {
                let request = try LockedUseWire.read(STDIN_FILENO, timeout: 11)
                DispatchQueue.main.sync { handle(request) }
            }
        } catch {
            DispatchQueue.main.async { [self] in
                disconnected = true; relock(.readFailure)
                if claim == nil { exit(0) }
                tick()
            }
        }
    }
    private func decode<T: Decodable>(_ type: T.Type, _ value: Any?) -> T? {
        guard let value = value, JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }
    private func handle(_ request: [String: Any]) {
        let id = request["id"] ?? NSNull()
        let params = request["params"] as? [String: Any] ?? [:]
        var response: [String: Any]
        switch request["method"] as? String {
        case "initialize":
            var checks: [String: Bool] = [:]
            func checked(_ name: String, _ value: Bool) -> Bool {
                checks[name] = value; return value
            }
            func checkedValue<T>(_ name: String, _ value: T?, valid: (T) -> Bool = { _ in true }) -> T? {
                let accepted = value.map(valid) ?? false
                checks[name] = accepted; return accepted ? value : nil
            }
            // Keep the original short-circuit order. Unreached checks stay absent.
            guard checked("fresh_initialization", !initialized),
                  let secret = checkedValue("secret_shape_valid", params["secret"] as? String,
                    valid: { $0.utf8.count >= 32 }),
                  let nonce = checkedValue("nonce_shape_valid", params["nonce"] as? String,
                    valid: { $0.utf8.count >= 16 }),
                  let parent = checkedValue("parent_identity_valid", LockedUseProcessIdentity.current(getppid())),
                  let executable = checkedValue("self_executable_available", Bundle.main.executableURL),
                  let team = checkedValue("self_signing_valid",
                    LockedUseSigning.team(executable, identifier: "ai.agistack.desktop.cua.guardian")),
                  checked("parent_signing_valid",
                    LockedUseSigning.process(parent, identifier: "ai.agistack.desktop.cua-helper", team: team)),
                  let watcher = checkedValue("watchdog_identity_valid", decode(LockedUseProcessIdentity.self, params["watchdog"])),
                  checked("watchdog_signing_valid",
                    LockedUseSigning.process(watcher, identifier: "ai.agistack.desktop.cua-helper", team: team)),
                  let tag = checkedValue("event_tag_valid", params["event_tag"] as? Int64, valid: { $0 > 0 }) else {
                send(id, ["error": "guardian_authentication_failed", "checks": checks]); return
            }
            initialized = true; source = parent; watchdog = watcher; recoveryTag = tag
            let proof = HMAC<SHA256>.authenticationCode(for: Data(nonce.utf8), using: SymmetricKey(data: Data(secret.utf8)))
                .map { String(format: "%02x", $0) }.joined()
            response = ["nonce": nonce, "proof": proof]
        case "begin_guard", "renew_guard":
            let begin = request["method"] as? String == "begin_guard"
            guard initialized, !suppressed, !relocking, (begin ? claim == nil : active),
                  let next = decode(LockedUseSupervisionClaim.self, params["claim"]),
                  next.valid(now: ProcessInfo.processInfo.systemUptime),
                  next.guardian == LockedUseProcessIdentity.current(getpid()),
                  claim == nil || claim?.binding == next.binding,
                  !begin || LockedUseRelock.systemLocked() else {
                let rejected = decode(LockedUseSupervisionClaim.self, params["claim"])
                send(id, ["error": "guard_rejected", "suppressed": suppressed, "checks": [
                    "initialized": initialized, "suppressed": suppressed, "relocking": relocking,
                    "claim_valid": rejected?.valid(now: ProcessInfo.processInfo.systemUptime) == true,
                    "guardian_identity_matches": rejected != nil && rejected?.guardian == LockedUseProcessIdentity.current(getpid()),
                    "binding_matches": claim == nil || claim?.binding == rejected?.binding,
                    "screen_locked": LockedUseRelock.systemLocked()]]); return
            }
            if begin { beginCoverage(id, claim: next); return }
            let (ready, report) = validateCoverage(.renewCoverage)
            if ready { claim = next }
            response = coverageResponse(ready: ready, report: report)
        case "end_guard":
            guard initialized else { return }; relock(.endGuard); response = ["ok": true]
        case "authorize_unlock":
            let requested = decode(LockedUseBinding.self, params["binding"])
            let ready = active ? validateCoverage(.authorizeCoverage).0 : false
            response = ["authorized": initialized && ready && !suppressed && !relocking
                && requested == claim?.binding && validClaim()]
        default: response = ["error": "invalid_request"]
        }
        send(id, response)
    }
    private func send(_ id: Any, _ response: [String: Any]) {
        var response = response
        if let first = revocation.first { response["guardian_revocation"] = first.status }
        do { try LockedUseWire.write(["jsonrpc": "2.0", "id": id, "result": response], fd: STDOUT_FILENO) }
        catch { disconnected = true; relock(.writeFailure) }
    }

}
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
let guardian = Guardian()
guardian.start()
application.run()
