import AppKit
import ApplicationServices
import Foundation

/// Availability distinguishes a missing AXChildren attribute from a successful empty array.
struct LockedUseChildCount {
    let count: Int
    let available: Bool
}

/// This interface deliberately has no value, title, description, or input reader.
struct LockedUseFieldAccess<Element> {
    let processes: () throws -> [LockedUseProcessIdentity]
    let alive: (LockedUseProcessIdentity) -> Bool
    let root: (LockedUseProcessIdentity) -> Element
    let identical: (Element, Element) -> Bool
    let identifier: (Element, Float) throws -> String?
    let childCount: (Element, Float) throws -> LockedUseChildCount
    let children: (Element, Int, Float) throws -> [Element]
    let valueSettable: (Element, Float) throws -> Bool
}

struct LockedUseFieldReadFailure: Error {
    let reason: LockedUseFailure.Reason
    let retryable: Bool
    static func ax(_ error: AXError) -> Self {
        switch error {
        case .cannotComplete: return Self(reason: .unlockAXCannotComplete, retryable: true)
        case .invalidUIElement: return Self(reason: .unlockAXInvalidElement, retryable: true)
        case .apiDisabled: return Self(reason: .unlockAXDisabled, retryable: false)
        default: return Self(reason: .unlockAXFailed, retryable: false)
        }
    }
}

struct LockedUseLocatedField<Element> {
    let element: Element
    let process: LockedUseProcessIdentity
}

/// The three-second deadline admits new readiness/AX/polling steps across all
/// attempts. Checkpoints receive that deadline to stop later supervision steps.
/// Already-started supervision I/O retains its own timeouts and lock behavior;
/// this is not a strict end-to-end wall-clock bound. The node budget is global,
/// and a complete tree is required before a candidate can be considered unique.
struct LockedUseFieldLocator<Element> {
    let access: LockedUseFieldAccess<Element>
    let checkpoint: (Double) throws -> Void
    var now: () -> Double = { ProcessInfo.processInfo.systemUptime }
    var wait: (Double) throws -> Void = { Thread.sleep(forTimeInterval: $0) }
    var readinessSeconds = 3.0
    var nodeBudget = 1000
    var depthLimit = 12

    func locate() throws -> LockedUseLocatedField<Element> {
        let until = now() + readinessSeconds
        var remaining = nodeBudget
        var completedScans = 0
        var reason = LockedUseFailure.Reason.unlockReadinessTimeout
        var stage = LockedUseFailure.Stage.unlockLoginwindow
        var checks: [String: Bool] = [:]
        func failure(_ reason: LockedUseFailure.Reason) -> LockedUseFailure {
            LockedUseFailure(stage: stage, reason: reason, checks: checks,
                underlying: ActionError.failure(kind: "locked_use_unavailable",
                    message: "the supported loginwindow field is not ready"))
        }
        func remainingTime() throws -> Double {
            let left = until - now()
            guard left > 0 else {
                checks["readiness_deadline_reached"] = true
                throw failure(reason)
            }
            return left
        }
        func check(_ process: LockedUseProcessIdentity? = nil) throws -> Float {
            // Do not start even a supervision checkpoint after admission closes.
            _ = try remainingTime()
            try checkpoint(until)
            _ = try remainingTime()
            if let process = process, !access.alive(process) {
                throw failure(.unlockProcessChanged)
            }
            return Float(min(0.1, try remainingTime()))
        }
        func read<T>(_ process: LockedUseProcessIdentity, _ operation: (Float) throws -> T) throws -> T {
            let timeout = try check(process)
            let result: Result<T, Error>
            do { result = .success(try operation(timeout)) }
            catch { result = .failure(error) }
            // Check authority after failed AX calls too, unless the deadline has
            // closed; either path stops all further AX and unlock effects.
            _ = try check(process)
            return try result.get()
        }
        while true {
            _ = try check()
            checks = [:]
            stage = .unlockLoginwindow
            let processes = try access.processes()
            _ = try check()
            checks["loginwindow_found"] = !processes.isEmpty
            checks["loginwindow_unique"] = processes.count == 1
            do {
                guard !processes.isEmpty else {
                    throw LockedUseFieldReadFailure(reason: .unlockLoginwindowAbsent, retryable: true)
                }
                guard processes.count == 1 else { throw failure(.unlockLoginwindowAmbiguous) }
                let process = processes[0]
                _ = try check(process)
                stage = .unlockField
                var pending = [(access.root(process), 0)]
                var visited: [Element] = []
                var candidate: Element?
                var rootChildrenAvailable: Bool?
                var rootHasChildren = false
                var hasGrandchildren = false
                var descendantChildrenUnavailable = false
                checks["scan_complete"] = false
                checks["field_identifier_found"] = false
                checks["field_unique"] = false
                while let (element, depth) = pending.popLast() {
                    _ = try check(process)
                    if visited.contains(where: { access.identical($0, element) }) { continue }
                    guard remaining > 0, depth < depthLimit else { throw failure(.unlockScanBudgetExceeded) }
                    remaining -= 1
                    visited.append(element)
                    let identifier = try read(process) { try access.identifier(element, $0) }
                    if identifier == "UserPasswordTextField" {
                        checks["field_identifier_found"] = true
                        guard candidate == nil else { throw failure(.unlockFieldAmbiguous) }
                        candidate = element
                    }
                    let childInfo = try read(process) { try access.childCount(element, $0) }
                    let count = childInfo.count
                    if depth == 0 {
                        rootChildrenAvailable = childInfo.available
                        rootHasChildren = count > 0
                    } else {
                        if !childInfo.available { descendantChildrenUnavailable = true }
                        if count > 0 { hasGrandchildren = true }
                    }
                    guard count >= 0, count <= remaining, count == 0 || depth + 1 < depthLimit else {
                        throw failure(.unlockScanBudgetExceeded)
                    }
                    if count > 0 {
                        let children = try read(process) { try access.children(element, count, $0) }
                        guard children.count == count else {
                            throw LockedUseFieldReadFailure(reason: .unlockAXInvalidElement, retryable: true)
                        }
                        pending.append(contentsOf: children.reversed().map { ($0, depth + 1) })
                    }
                }
                checks["scan_complete"] = true
                completedScans += 1
                checks["scan_multiple_complete"] = completedScans > 1
                checks["scan_root_children_available"] = rootChildrenAvailable
                checks["scan_root_has_children"] = rootHasChildren
                checks["scan_has_grandchildren"] = hasGrandchildren
                checks["scan_has_at_least_ten_nodes"] = visited.count >= 10
                checks["scan_descendant_children_unavailable"] = descendantChildrenUnavailable
                guard let candidate = candidate else {
                    throw LockedUseFieldReadFailure(reason: .unlockFieldAbsent, retryable: true)
                }
                checks["field_unique"] = true
                let settable = try read(process) { try access.valueSettable(candidate, $0) }
                checks["field_value_settable"] = settable
                guard settable else {
                    throw LockedUseFieldReadFailure(reason: .unlockFieldNotSettable, retryable: true)
                }
                return LockedUseLocatedField(element: candidate, process: process)
            } catch let readFailure as LockedUseFieldReadFailure {
                reason = readFailure.reason
                guard readFailure.retryable else { throw failure(reason) }
            }
            _ = try check()
            let delay = min(0.05, until - now())
            if delay > 0 { try wait(delay) }
        }
    }
}

extension LockedUseFieldAccess where Element == AXUIElement {
    static var loginwindow: Self {
        Self(processes: {
            NSWorkspace.shared.runningApplications
                .filter { $0.bundleIdentifier == "com.apple.loginwindow" }
                .compactMap { LockedUseProcessIdentity.current($0.processIdentifier) }
        }, alive: { $0.alive }, root: { AXUIElementCreateApplication($0.pid) },
        identical: { CFEqual($0, $1) }, identifier: { element, timeout in
            try messagingTimeout(element, timeout)
            var value: CFTypeRef?
            let error = AXUIElementCopyAttributeValue(element, kAXIdentifierAttribute as CFString, &value)
            if error == .attributeUnsupported || error == .noValue { return nil }
            guard error == .success else { throw LockedUseFieldReadFailure.ax(error) }
            guard value == nil || value is String else { throw LockedUseFieldReadFailure.ax(.failure) }
            return value as? String
        }, childCount: { element, timeout in
            try messagingTimeout(element, timeout)
            var count = CFIndex(0)
            let error = AXUIElementGetAttributeValueCount(element, kAXChildrenAttribute as CFString, &count)
            if error == .attributeUnsupported || error == .noValue {
                return LockedUseChildCount(count: 0, available: false)
            }
            guard error == .success else { throw LockedUseFieldReadFailure.ax(error) }
            return LockedUseChildCount(count: count, available: true)
        }, children: { element, count, timeout in
            try messagingTimeout(element, timeout)
            var value: CFArray?
            let error = AXUIElementCopyAttributeValues(element, kAXChildrenAttribute as CFString, 0, count, &value)
            guard error == .success else { throw LockedUseFieldReadFailure.ax(error) }
            guard let children = value as? [AXUIElement] else { throw LockedUseFieldReadFailure.ax(.failure) }
            return children
        }, valueSettable: { element, timeout in
            try messagingTimeout(element, timeout)
            var settable = DarwinBoolean(false)
            let error = AXUIElementIsAttributeSettable(element, kAXValueAttribute as CFString, &settable)
            if error == .attributeUnsupported || error == .noValue { return false }
            guard error == .success else { throw LockedUseFieldReadFailure.ax(error) }
            return settable.boolValue
        })
    }
    private static func messagingTimeout(_ element: AXUIElement, _ timeout: Float) throws {
        let error = AXUIElementSetMessagingTimeout(element, timeout)
        guard error == .success else { throw LockedUseFieldReadFailure.ax(error) }
    }
}
