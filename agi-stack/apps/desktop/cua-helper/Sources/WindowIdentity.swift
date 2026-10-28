import ApplicationServices
import CoreGraphics
import Darwin

struct NativeProcessIdentity: Equatable, Hashable {
    let pid: pid_t
    let startSeconds: UInt64
    let startMicroseconds: UInt64

    static func read(_ pid: pid_t) -> NativeProcessIdentity? {
        var info = proc_bsdinfo()
        let size = Int32(MemoryLayout<proc_bsdinfo>.size)
        guard pid > 0, proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, size) == size,
              info.pbi_uid == getuid(), info.pbi_status != SZOMB else { return nil }
        return NativeProcessIdentity(pid: pid, startSeconds: info.pbi_start_tvsec,
            startMicroseconds: info.pbi_start_tvusec)
    }
}

struct NativeWindowIdentity: Equatable, Hashable {
    let process: NativeProcessIdentity
    let windowID: CGWindowID
}

struct NativeWindowServerRecord {
    let windowID: CGWindowID
    let ownerPID: pid_t
    let frame: CGRect
}

/// Independent native reads also let regression tests model AX re-enumeration
/// without moving a real window or changing the user's active Space.
struct WindowIdentityReader {
    var process: (pid_t) -> NativeProcessIdentity?
    var element: (AXUIElement) -> (pid: pid_t, windowID: CGWindowID)?
    var window: (CGWindowID) -> NativeWindowServerRecord?
    var title: (AXUIElement) -> String

    static let live = WindowIdentityReader(process: NativeProcessIdentity.read, element: { element in
        var pid: pid_t = 0
        var role: CFTypeRef?
        // A retained AX object must still answer a native attribute query. A
        // cached PID or WindowServer ID alone does not prove that it is live.
        guard AXUIElementGetPid(element, &pid) == .success,
              AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &role) == .success,
              role as? String == kAXWindowRole as String,
              let windowID = BackgroundInputSPI.windowID(element) else { return nil }
        return (pid, windowID)
    }, window: { windowID in
        guard let entries = CGWindowListCopyWindowInfo(.optionIncludingWindow, windowID) as? [[String: Any]],
              let entry = entries.first(where: {
                  ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == windowID
              }), let ownerPID = (entry[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value,
              let raw = entry[kCGWindowBounds as String] as? [String: Any],
              let frame = CGRect(dictionaryRepresentation: raw as CFDictionary) else { return nil }
        return NativeWindowServerRecord(windowID: windowID, ownerPID: ownerPID, frame: frame)
    }, title: { AxEngine.copyString($0, kAXTitleAttribute as String) ?? "" })

    func identify(_ element: AXUIElement, process expected: NativeProcessIdentity) -> NativeWindow? {
        guard process(expected.pid) == expected,
              let ax = self.element(element), ax.pid == expected.pid, ax.windowID != 0,
              let native = window(ax.windowID), native.windowID == ax.windowID,
              native.ownerPID == expected.pid,
              native.frame.origin.x.isFinite, native.frame.origin.y.isFinite,
              native.frame.width.isFinite, native.frame.height.isFinite,
              native.frame.width > 0, native.frame.height > 0 else { return nil }
        let identity = NativeWindowIdentity(process: expected, windowID: ax.windowID)
        return NativeWindow(id: "\(expected.pid):\(UUID().uuidString)", element: element,
            frame: native.frame, title: title(element), captureID: ax.windowID, identity: identity)
    }

    func reconcile(_ elements: [AXUIElement], previous: [NativeWindow],
                   process: NativeProcessIdentity) -> [NativeWindow] {
        var result: [NativeWindow] = []
        var seen = Set<NativeWindowIdentity>()
        func append(_ candidate: NativeWindow, id: String) {
            guard let identity = candidate.identity, seen.insert(identity).inserted else { return }
            result.append(NativeWindow(id: id, element: candidate.element, frame: candidate.frame,
                title: candidate.title, captureID: candidate.captureID, identity: identity))
        }
        for element in elements {
            guard let candidate = identify(element, process: process) else { continue }
            let old = previous.first { $0.identity == candidate.identity }
            append(candidate, id: old?.id ?? candidate.id)
        }
        // AXWindows may omit windows on another Space. Recheck each missing
        // handle against the exact native identity, never its title or geometry.
        for old in previous {
            guard let identity = old.identity, identity.process == process,
                  !seen.contains(identity), old.captureID == identity.windowID,
                  let candidate = identify(old.element, process: process),
                  candidate.identity == identity else { continue }
            append(candidate, id: old.id)
        }
        return result
    }
}
