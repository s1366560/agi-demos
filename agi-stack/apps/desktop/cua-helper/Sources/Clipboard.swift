import AppKit

enum NativeClipboard {
    struct Saved {
        let owned: Bool
        let path: String?
        let board: NSPasteboard
        var baseline: ClipboardItems
        var parent: String?
        var count: Int?
    }
    static var handles: [String: [String: Saved]] = [:]
    private static var active: [String: String] = [:]
    static var board = NSPasteboard.general
    private static func capacity() throws {
        guard handles.values.reduce(0, { $0 + $1.count }) < 8 else {
            throw ActionError.failure(kind: "clipboard_handle_limit", message: "release a clipboard handle before creating another")
        }
    }
    static func read(session: NativeSession) throws -> [String: Any] {
        try capacity()
        let values = try ClipboardFiles.snapshot(board)
        let handle = UUID().uuidString
        handles[session.id, default: [:]][handle] = Saved(owned: false, path: nil, board: board,
            baseline: [], parent: nil, count: nil)
        return ["handle": handle, "items": values.map { values -> [String: Any] in
            ["types": values.map { $0.type },
             "text": values.first { $0.type == NSPasteboard.PasteboardType.string.rawValue }
                .flatMap { String(data: $0.data, encoding: .utf8) } ?? NSNull()]
        }]
    }
    static func write(text: String, format: String, session: NativeSession) throws -> [String: Any] {
        try capacity()
        guard ["text", "md", "html"].contains(format), text.utf8.count <= 1_000_000 else {
            throw ActionError.failure(kind: "invalid_params", message: "invalid clipboard format or size")
        }
        let before = board.changeCount
        let baseline = try ClipboardFiles.snapshot(board)
        guard board.changeCount == before else { throw ClipboardFiles.failure("clipboard_changed") }
        var replacement = [ClipboardValue(type: NSPasteboard.PasteboardType.string.rawValue, data: Data(text.utf8))]
        if format == "html" { replacement.append(ClipboardValue(type: NSPasteboard.PasteboardType.html.rawValue, data: Data(text.utf8))) }
        let (path, digest) = try ClipboardFiles.prepare(ClipboardDocument(baseline: baseline, replacement: [replacement]), directory: session.artifactDirectory)
        let handle = UUID().uuidString
        let parent = active[board.name.rawValue].flatMap { owns($0, sessionID: session.id) ? $0 : nil }
        // Register the mirror before asking the writer. clearContents advances
        // exactly one generation; an ACK later replaces this with its receipt.
        // An owner marker is also required, so an uncommitted clear is never
        // mistaken for a person's empty clipboard.
        handles[session.id, default: [:]][handle] = Saved(owned: true, path: path, board: board,
            baseline: baseline, parent: parent, count: before + 1)
        active[board.name.rawValue] = handle
        do {
            let receipt = try SyntheticInput.shared.clipboard(ClipboardCommand(operation: "write", boardName: board.name.rawValue,
                sessionID: session.id, handle: handle, path: path, digest: digest, expectedCount: before))
            guard receipt.handle == handle, let count = receipt.ownedCount else {
                throw ClipboardFiles.failure("clipboard_unavailable")
            }
            handles[session.id]?[handle]?.count = count
            return ["handle": handle]
        } catch {
            let restoredCount = SyntheticInput.shared.watchdogStopped ? fallback(handle, sessionID: session.id) : nil
            discard(handle, sessionID: session.id, restoredCount: restoredCount)
            try? FileManager.default.removeItem(atPath: path)
            throw error
        }
    }
    static func release(handle: String, sessionID: String) throws -> [String: Any] {
        guard let saved = handles[sessionID]?[handle] else {
            throw ActionError.failure(kind: "invalid_params", message: "clipboard handle is not owned by this session")
        }
        var restoredCount: Int?
        if saved.owned {
            do {
                let receipt = try SyntheticInput.shared.clipboard(ClipboardCommand(operation: "release", boardName: saved.board.name.rawValue,
                    sessionID: sessionID, handle: handle))
                if receipt.restored { restoredCount = receipt.ownedCount }
            } catch {
                guard SyntheticInput.shared.watchdogStopped else { throw error }
                restoredCount = fallback(handle, sessionID: sessionID)
            }
        }
        discard(handle, sessionID: sessionID, restoredCount: restoredCount)
        if let path = saved.path { try? FileManager.default.removeItem(atPath: path) }
        return ["ok": true]
    }
    private static func owns(_ handle: String, sessionID: String) -> Bool {
        guard let value = handles[sessionID]?[handle], value.owned,
              value.count == value.board.changeCount,
              value.board.string(forType: ClipboardFiles.marker) == handle else { return false }
        return true
    }
    private static func fallback(_ handle: String, sessionID: String) -> Int? {
        guard let value = handles[sessionID]?[handle],
              active[value.board.name.rawValue] == handle, owns(handle, sessionID: sessionID) else { return nil }
        return ClipboardFiles.write(value.baseline, board: value.board, owner: value.parent)
    }
    private static func discard(_ handle: String, sessionID: String, restoredCount: Int?) {
        guard let value = handles[sessionID]?[handle] else { return }
        if active[value.board.name.rawValue] == handle {
            let parentStillOwned = value.parent.map { owns($0, sessionID: sessionID) } ?? false
            active[value.board.name.rawValue] = restoredCount != nil || parentStillOwned ? value.parent : nil
            if let parent = value.parent, let count = restoredCount { handles[sessionID]?[parent]?.count = count }
        }
        handles[sessionID]?[handle] = nil
        for child in Array(handles[sessionID]?.keys ?? Dictionary<String, Saved>().keys)
            where handles[sessionID]?[child]?.parent == handle {
            handles[sessionID]?[child]?.baseline = value.baseline
            handles[sessionID]?[child]?.parent = value.parent
        }
    }
    static func end(_ sessionID: String) {
        for handle in Array(handles[sessionID]?.keys ?? Dictionary<String, Saved>().keys) {
            _ = try? release(handle: handle, sessionID: sessionID)
        }
        handles.removeValue(forKey: sessionID)
    }
}
