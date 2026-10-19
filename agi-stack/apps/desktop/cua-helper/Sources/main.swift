import AppKit
import ApplicationServices
import Foundation

if CommandLine.arguments == [CommandLine.arguments[0], "--input-watchdog"] {
    InputWatchdogWorker.run()
}
if CommandLine.arguments.contains("--request-access") {
    let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
    exit(AXIsProcessTrustedWithOptions(options) ? 0 : 1)
}
guard CommandLine.arguments.contains("--stdio") else {
    FileHandle.standardError.write(Data("usage: cua-helper --stdio | --request-access\n".utf8))
    exit(2)
}
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
let server = IpcServer(dispatcher: dispatch)
server.start()
application.run()
