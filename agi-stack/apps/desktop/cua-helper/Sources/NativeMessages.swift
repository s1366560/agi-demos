import AppKit
import Carbon

/// Fixed operations from Messages.sdef. User values are Apple Event parameters,
/// never interpolated into executable AppleScript source.
enum NativeMessages {
    static let bundleID = "com.apple.MobileSMS"
    static let scriptSource = """
    on list_accounts()
        tell application id "com.apple.MobileSMS"
            set rows to {}
            repeat with itemAccount in accounts
                set end of rows to {id of itemAccount as text, description of itemAccount as text, service type of itemAccount as text, enabled of itemAccount}
            end repeat
            return rows
        end tell
    end list_accounts
    on resolve_recipient(accountID, recipientHandle)
        tell application id "com.apple.MobileSMS"
            set selectedAccount to account id accountID
            set selectedParticipant to participant recipientHandle of selectedAccount
            return {id of selectedParticipant as text, handle of selectedParticipant as text, name of selectedParticipant as text}
        end tell
    end resolve_recipient
    on send_message(accountID, recipientHandle, textValue)
        tell application id "com.apple.MobileSMS"
            set selectedAccount to account id accountID
            set selectedParticipant to participant recipientHandle of selectedAccount
            send textValue to selectedParticipant
            return true
        end tell
    end send_message
    """
    static func permission(prompt: Bool = false) -> OSStatus {
        let target = NSAppleEventDescriptor(bundleIdentifier: bundleID)
        return AEDeterminePermissionToAutomateTarget(target.aeDesc, typeWildCard, typeWildCard, prompt)
    }
    static func capability() -> [String: Any] {
        guard NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) != nil else {
            return ["state": "unsupported", "reason": "Messages is not installed"]
        }
        return ["state": permission() == noErr ? "available" : "permission_required"]
    }
    static func execute(_ method: String, params: [String: Any], session: NativeSession) throws -> [String: Any] {
        guard permission() == noErr else {
            throw ActionError.failure(kind: "permission_required", message: "Messages Automation permission is required")
        }
        let handler: String
        var arguments: [String] = []
        switch method {
        case "messages_list", "messages_services": handler = "list_accounts"
        case "messages_resolve_recipient", "messages_send":
            guard let account = (params["account_id"] ?? params["service_id"]) as? String, !account.isEmpty,
                  let recipient = params["recipient"] as? String, !recipient.isEmpty else {
                throw ActionError.failure(kind: "invalid_params", message: "account_id and recipient are required")
            }
            arguments = [account, recipient]
            if method == "messages_send" {
                guard let content = params["text"] as? String, !content.isEmpty, content.utf8.count <= 100_000 else {
                    throw ActionError.failure(kind: "invalid_params", message: "message text is required and must fit the budget")
                }
                arguments.append(content); handler = "send_message"
            } else { handler = "resolve_recipient" }
        default:
            throw ActionError.failure(kind: "method_not_found", message: "unknown Messages operation")
        }
        let script = NSAppleScript(source: scriptSource)!
        let event = NSAppleEventDescriptor(eventClass: AEEventClass(kASAppleScriptSuite), eventID: AEEventID(kASSubroutineEvent),
            targetDescriptor: NSAppleEventDescriptor.currentProcess(),
            returnID: AEReturnID(kAutoGenerateReturnID), transactionID: AETransactionID(kAnyTransactionID))
        event.setParam(NSAppleEventDescriptor(string: handler), forKeyword: AEKeyword(keyASSubroutineName))
        let list = NSAppleEventDescriptor.list()
        for (index, value) in arguments.enumerated() {
            list.insert(NSAppleEventDescriptor(string: value), at: index + 1)
        }
        event.setParam(list, forKeyword: keyDirectObject)
        try session.cancellation.check()
        var error: NSDictionary?
        let result = script.executeAppleEvent(event, error: &error)
        if let error = error {
            let code = error[NSAppleScript.errorNumber] as? Int ?? -1
            throw ActionError.failure(kind: code == -1743 ? "permission_required" : "messages_error",
                message: "Messages operation failed", extra: ["native_code": code])
        }
        if handler == "send_message" { return ["sent": result.booleanValue] }
        if handler == "resolve_recipient" {
            return ["id": result.atIndex(1)?.stringValue ?? "",
                    "handle": result.atIndex(2)?.stringValue ?? "",
                    "name": result.atIndex(3)?.stringValue ?? ""]
        }
        let rows = (1...max(1, result.numberOfItems)).compactMap { index -> [String: Any]? in
            guard let row = result.atIndex(index), row.numberOfItems == 4 else { return nil }
            return ["id": row.atIndex(1)?.stringValue ?? "", "description": row.atIndex(2)?.stringValue ?? "",
                    "service_type": row.atIndex(3)?.stringValue ?? "", "enabled": row.atIndex(4)?.booleanValue ?? false]
        }
        return ["services": rows]
    }
}
