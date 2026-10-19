import AppKit
import CryptoKit
import Darwin

struct ClipboardValue: Codable { let type: String; let data: Data }
typealias ClipboardItems = [[ClipboardValue]]
struct ClipboardDocument: Codable {
    let baseline: ClipboardItems
    let replacement: ClipboardItems
}
struct ClipboardCommand: Codable {
    let operation: String
    let boardName: String
    let sessionID: String
    let handle: String
    var path: String? = nil
    var digest: String? = nil
    var expectedCount: Int? = nil
}
struct ClipboardReceipt: Codable {
    let handle: String
    let restored: Bool
    let ownedCount: Int?
}

enum ClipboardFiles {
    static let maximum = 16 * 1024 * 1024
    static let marker = NSPasteboard.PasteboardType("ai.memstack.cua.clipboard-owner")
    static func snapshot(_ board: NSPasteboard) throws -> ClipboardItems {
        var total = 0
        let items = board.pasteboardItems ?? []
        guard items.count <= 128 else { throw failure("clipboard_too_large") }
        return try items.map { item in
            guard item.types.count <= 128 else { throw failure("clipboard_too_large") }
            return try item.types.filter { $0 != marker }.map { type in
                guard let data = item.data(forType: type) else { throw failure("clipboard_unavailable") }
                total += data.count
                guard total <= 8_388_608 else { throw failure("clipboard_too_large") }
                return ClipboardValue(type: type.rawValue, data: data)
            }
        }
    }
    static func failure(_ code: String) -> ActionError {
        .failure(kind: code, message: "clipboard recovery could not safely complete")
    }
    static func write(_ items: ClipboardItems, board: NSPasteboard, owner: String?) -> Int {
        let count = board.clearContents()
        var objects = items.map { values -> NSPasteboardItem in
            let item = NSPasteboardItem()
            values.forEach { item.setData($0.data, forType: NSPasteboard.PasteboardType($0.type)) }
            return item
        }
        if let owner = owner {
            if objects.isEmpty { objects = [NSPasteboardItem()] }
            objects[0].setString(owner, forType: marker)
        }
        if !objects.isEmpty { _ = board.writeObjects(objects) }
        // Preserve clearContents' generation; a concurrent local copy wins.
        return count
    }
    static func prepare(_ document: ClipboardDocument, directory: URL) throws -> (String, String) {
        let data = try JSONEncoder().encode(document)
        guard data.count <= maximum else { throw failure("clipboard_too_large") }
        let url = directory.appendingPathComponent("clipboard-\(UUID().uuidString).json")
        let descriptor = open(url.path, O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW | O_CLOEXEC, mode_t(0o600))
        guard descriptor >= 0 else { throw failure("clipboard_unavailable") }
        defer { close(descriptor) }
        do {
            try data.withUnsafeBytes { bytes in
                var offset = 0
                while offset < bytes.count {
                    let count = Darwin.write(descriptor, bytes.baseAddress!.advanced(by: offset), bytes.count - offset)
                    if count < 0 && errno == EINTR { continue }
                    guard count > 0 else { throw failure("clipboard_unavailable") }
                    offset += count
                }
            }
            guard fsync(descriptor) == 0 else { throw failure("clipboard_unavailable") }
        } catch { try? FileManager.default.removeItem(at: url); throw error }
        return (url.path, SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined())
    }
    static func read(_ command: ClipboardCommand, directories: [String]) throws -> ClipboardDocument {
        guard let path = command.path, let digest = command.digest else { throw failure("clipboard_unavailable") }
        let url = URL(fileURLWithPath: path).standardizedFileURL
        let prefix = "clipboard-"
        guard directories.contains(url.deletingLastPathComponent().path),
              url.lastPathComponent.hasPrefix(prefix), url.pathExtension == "json",
              UUID(uuidString: String(url.deletingPathExtension().lastPathComponent.dropFirst(prefix.count))) != nil else {
            throw failure("clipboard_unavailable")
        }
        let descriptor = open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure("clipboard_unavailable") }
        defer { close(descriptor) }
        var attributes = stat()
        guard fstat(descriptor, &attributes) == 0, attributes.st_uid == getuid(),
              attributes.st_mode & S_IFMT == S_IFREG, attributes.st_mode & 0o777 == 0o600,
              attributes.st_nlink == 1, attributes.st_size > 0, attributes.st_size <= maximum else {
            throw failure("clipboard_unavailable")
        }
        var data = Data(count: Int(attributes.st_size))
        try data.withUnsafeMutableBytes { bytes in
            var offset = 0
            while offset < bytes.count {
                let count = Darwin.read(descriptor, bytes.baseAddress!.advanced(by: offset), bytes.count - offset)
                if count < 0 && errno == EINTR { continue }
                guard count > 0 else { throw failure("clipboard_unavailable") }
                offset += count
            }
        }
        guard SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == digest else {
            throw failure("clipboard_unavailable")
        }
        let document = try JSONDecoder().decode(ClipboardDocument.self, from: data)
        guard document.baseline.count <= 128, document.replacement.count <= 128,
              document.baseline.allSatisfy({ $0.count <= 128 }), document.replacement.allSatisfy({ $0.count <= 128 }),
              document.baseline.flatMap({ $0 }).reduce(0, { $0 + $1.data.count }) <= 8_388_608,
              document.replacement.flatMap({ $0 }).reduce(0, { $0 + $1.data.count }) <= 2_000_000 else {
            throw failure("clipboard_too_large")
        }
        return document
    }
}

/// All managed writes happen in the surviving watchdog. It owns the rollback
/// before touching the board and records the actual generation before ACK.
final class ClipboardRecovery {
    struct Saved {
        let sessionID: String
        let board: NSPasteboard
        var baseline: ClipboardItems
        var parent: String?
        var count: Int?
    }
    private var saved: [String: Saved] = [:]
    private var active: [String: String] = [:]
    var hasOwnedWrites: Bool { !active.isEmpty }
    func perform(_ command: ClipboardCommand, directories: [String]) throws -> ClipboardReceipt {
        let board = NSPasteboard(name: NSPasteboard.Name(command.boardName))
        if command.operation == "release" { return try release(command.handle, sessionID: command.sessionID) }
        guard command.operation == "write", saved.count < 8, saved[command.handle] == nil,
              UUID(uuidString: command.handle) != nil else { throw ClipboardFiles.failure("clipboard_unavailable") }
        let document = try ClipboardFiles.read(command, directories: directories)
        guard board.changeCount == command.expectedCount else { throw ClipboardFiles.failure("clipboard_changed") }
        let current = active[command.boardName]
        let parent = current.flatMap { handle in owns(handle) ? handle : nil }
        saved[command.handle] = Saved(sessionID: command.sessionID, board: board,
            baseline: document.baseline, parent: parent, count: nil)
        active[command.boardName] = command.handle
        let count = ClipboardFiles.write(document.replacement, board: board, owner: command.handle)
        saved[command.handle]?.count = count
        // A concurrent local copy wins; never claim that new generation.
        guard owns(command.handle) else {
            active[command.boardName] = nil
            saved[command.handle] = nil
            throw ClipboardFiles.failure("clipboard_changed")
        }
        return ClipboardReceipt(handle: command.handle, restored: false, ownedCount: count)
    }
    private func owns(_ handle: String) -> Bool {
        guard let value = saved[handle], value.count == value.board.changeCount,
              value.board.string(forType: ClipboardFiles.marker) == handle else { return false }
        return true
    }
    func release(_ handle: String, sessionID: String) throws -> ClipboardReceipt {
        guard let value = saved[handle], value.sessionID == sessionID else {
            throw ClipboardFiles.failure("clipboard_unavailable")
        }
        let owned = active[value.board.name.rawValue] == handle && owns(handle)
        var count: Int?
        if owned {
            count = ClipboardFiles.write(value.baseline, board: value.board, owner: value.parent)
            active[value.board.name.rawValue] = value.parent
            if let parent = value.parent { saved[parent]?.count = count }
        } else if active[value.board.name.rawValue] == handle { active[value.board.name.rawValue] = nil }
        saved[handle] = nil
        for child in Array(saved.keys) where saved[child]?.parent == handle {
            saved[child]?.baseline = value.baseline
            saved[child]?.parent = value.parent
        }
        return ClipboardReceipt(handle: handle, restored: owned, ownedCount: count)
    }
    func recover() {
        for (_, handle) in active {
            guard let value = saved[handle], owns(handle) else { continue }
            var baseline = value.baseline
            var parent = value.parent
            var visited = Set<String>()
            while let next = parent, visited.insert(next).inserted, let value = saved[next] {
                baseline = value.baseline; parent = value.parent
            }
            _ = ClipboardFiles.write(baseline, board: value.board, owner: nil)
        }
        active.removeAll(); saved.removeAll()
    }
}
