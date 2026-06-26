// On-device(模拟器)冒烟:用 UniFFI 生成的 Swift 绑定驱动同一可移植核心,
// 走「摄取 → 关键词检索 → 语义检索」三步,证 SQLite 持久化 + 嵌入 + 检索全在 iOS 进程内跑通。
// 由 scripts/build-ios.sh 编译并经 `xcrun simctl spawn booted` 在已启动模拟器上执行。
import Foundation

let tmp = NSTemporaryDirectory() + "agistack_smoke_\(UUID().uuidString).db"
let core = MobileCore(dbPath: tmp)
print("INGEST: " + core.ingest(projectId: "p1", authorId: "u1", content: "The capital of France is Paris."))
print("SEARCH: " + core.search(projectId: "p1", query: "Paris", limit: 5))
print("SEMANTIC: " + core.semanticSearch(projectId: "p1", query: "France capital city", limit: 5))
print("SMOKE_OK")
