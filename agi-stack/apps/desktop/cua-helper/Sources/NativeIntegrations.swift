import AppKit
import Contacts
import CryptoKit
import EventKit
import Security

enum AppIdentity {
    static func payload(_ app: ResolvedApp, bundleURL: URL? = nil) throws -> [String: Any] {
        let running = NSRunningApplication(processIdentifier: app.pid)
        let url = bundleURL ?? running?.bundleURL ?? running?.executableURL
        let canonicalID = canonicalID(bundleID: app.bundleId, url: url)
        var code: SecStaticCode?
        var information: CFDictionary?
        if let url = url, SecStaticCodeCreateWithPath(url as CFURL, [], &code) == errSecSuccess,
           let code = code {
            _ = SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &information)
        }
        let info = information as? [String: Any] ?? [:]
        let signatureValid = code.map { SecStaticCodeCheckValidity($0, [], nil) == errSecSuccess } ?? false
        let signedHash = signatureValid ? (info[kSecCodeInfoUnique as String] as? Data)?.base64EncodedString() : nil
        let executable = running?.executableURL ?? bundleURL.flatMap { Bundle(url: $0)?.executableURL }
            ?? (url?.pathExtension == "app" ? nil : url)
        let hash = signedHash ?? executable.map(contentDigest) ?? "unreadable-executable"
        guard hash != "unreadable-executable", url != nil else {
            throw ActionError.failure(kind: "target_identity_unavailable", message: "cannot verify application executable identity")
        }
        let team = info[kSecCodeInfoTeamIdentifier as String] as? String ?? ""
        let material = [canonicalID, url?.resolvingSymlinksInPath().path ?? "", team, hash].joined(separator: "\n")
        let digest = SHA256.hash(data: Data(material.utf8)).map { String(format: "%02x", $0) }.joined()
        return ["app": canonicalID, "app_id": canonicalID, "display_name": app.displayName,
                "process_id": app.pid, "app_path": url?.path ?? NSNull(),
                "identity_digest": digest]
    }
    static func contentDigest(_ url: URL) -> String {
        guard let file = try? FileHandle(forReadingFrom: url) else { return "unreadable-executable" }
        defer { try? file.close() }
        var hasher = SHA256()
        do {
            while let data = try file.read(upToCount: 65_536), !data.isEmpty { hasher.update(data: data) }
        } catch { return "unreadable-executable" }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
    static func canonicalID(bundleID: String?, url: URL?) -> String {
        if let bundleID = bundleID { return bundleID }
        let path = url?.resolvingSymlinksInPath().path ?? ""
        let digest = SHA256.hash(data: Data(path.utf8)).map { String(format: "%02x", $0) }.joined()
        return "executable:" + digest
    }
}

enum NativeIntegrations {
    static let events = EKEventStore()
    static let contacts = CNContactStore()

    static func status() -> [String: Any] {
        func state(_ available: Bool) -> [String: Any] {
            ["state": available ? "available" : "permission_required"]
        }
        let calendar = EKEventStore.authorizationStatus(for: .event)
        let calendarAllowed: Bool
        if #available(macOS 14.0, *) { calendarAllowed = calendar == .fullAccess }
        else { calendarAllowed = calendar == .authorized }
        let contactsAllowed = CNContactStore.authorizationStatus(for: .contacts) == .authorized
        let screenshotState: [String: Any]
        if #available(macOS 14.0, *) { screenshotState = state(CGPreflightScreenCaptureAccess()) }
        else { screenshotState = ["state": "unsupported"] }
        var result: [String: Any] = [
            "app_state": state(AxEngine.accessibilityTrusted()),
            "input": state(AxEngine.accessibilityTrusted() && CGPreflightListenEventAccess()),
            "input_tracking": state(CGPreflightListenEventAccess()),
            "screenshots": screenshotState,
            "calendar": state(calendarAllowed),
            "contacts": state(contactsAllowed),
            "messages": NativeMessages.capability(),
            "locked_use": LockedUseCoordinator.shared.probe()
        ]
        for (key, value) in AudioCapture.shared.capabilities() { result[key] = value }
        return ["platform": "macos", "protocol_version": ipcProtocolVersion, "capabilities": result]
    }

    static func handle(_ method: String, params: [String: Any], session: NativeSession) throws -> [String: Any] {
        switch method {
        case "calendar_list":
            try requireCalendar()
            let (start, end) = try range(params)
            let predicate = events.predicateForEvents(withStart: start, end: end, calendars: nil)
            return ["events": events.events(matching: predicate).prefix(500).map {
                ["id": $0.eventIdentifier ?? "", "calendar_id": $0.calendar.calendarIdentifier,
                 "title": $0.title ?? "", "start": ISO8601DateFormatter().string(from: $0.startDate),
                 "end": ISO8601DateFormatter().string(from: $0.endDate)]
            }, "calendars": events.calendars(for: .event).map {
                ["id": $0.calendarIdentifier, "title": $0.title, "writable": $0.allowsContentModifications]
            }]
        case "calendar_create":
            try requireCalendar()
            let (start, end) = try range(params)
            guard let title = params["title"] as? String, !title.isEmpty,
                  let calendarID = params["calendar_id"] as? String,
                  let calendar = events.calendar(withIdentifier: calendarID),
                  calendar.allowsContentModifications else {
                throw ActionError.failure(kind: "invalid_params", message: "title and a writable calendar_id are required")
            }
            let event = EKEvent(eventStore: events)
            event.title = title; event.startDate = start; event.endDate = end; event.calendar = calendar
            try session.cancellation.check()
            try events.save(event, span: .thisEvent, commit: true)
            return ["id": event.eventIdentifier ?? "", "ok": true]
        case "calendar_update", "calendar_delete":
            try requireCalendar()
            return try NativeRecords.calendar(method, params: params, store: events, session: session)
        case "contacts_list":
            try requireContacts()
            let limit = params["limit"] as? Int ?? 100
            guard (1...500).contains(limit) else {
                throw ActionError.failure(kind: "invalid_params", message: "limit must be between one and 500")
            }
            let keys = [CNContactIdentifierKey, CNContactGivenNameKey, CNContactFamilyNameKey, CNContactEmailAddressesKey]
            let request = CNContactFetchRequest(keysToFetch: keys as [CNKeyDescriptor])
            var result: [[String: Any]] = []
            try contacts.enumerateContacts(with: request) { contact, stop in
                result.append(["id": contact.identifier, "given_name": contact.givenName,
                               "family_name": contact.familyName,
                               "emails": contact.emailAddresses.map { $0.value as String }])
                if result.count >= limit { stop.pointee = true }
            }
            return ["contacts": result]
        case "contacts_create":
            try requireContacts()
            guard let name = params["given_name"] as? String, !name.isEmpty else {
                throw ActionError.failure(kind: "invalid_params", message: "given_name is required")
            }
            let contact = CNMutableContact()
            contact.givenName = name
            contact.familyName = params["family_name"] as? String ?? ""
            if let email = params["email"] as? String {
                contact.emailAddresses = [CNLabeledValue(label: CNLabelOther, value: email as NSString)]
            }
            let request = CNSaveRequest(); request.add(contact, toContainerWithIdentifier: nil)
            try session.cancellation.check(); try contacts.execute(request)
            return ["id": contact.identifier, "ok": true]
        case "contacts_update", "contacts_delete":
            try requireContacts()
            return try NativeRecords.contact(method, params: params, store: contacts, session: session)
        case "messages_list", "messages_services", "messages_resolve_recipient", "messages_send":
            return try NativeMessages.execute(method, params: params, session: session)
        default:
            throw ActionError.failure(kind: "method_not_found", message: "unknown integration method")
        }
    }

    static func requestAccess(_ capability: String, session: NativeSession) throws -> [String: Any] {
        switch capability {
        case "input_monitoring", "input_tracking":
            return ["granted": CGRequestListenEventAccess()]
        case "accessibility", "input", "app_state":
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
            return ["granted": AXIsProcessTrustedWithOptions(options)]
        case "screenshots", "screen_capture", "audio_system", "system_audio":
            return ["granted": CGRequestScreenCaptureAccess()]
        case "audio_microphone", "microphone":
            return try AudioCapture.shared.requestMicrophone(session)
        case "messages":
            return ["granted": NativeMessages.permission(prompt: true) == noErr]
        case "calendar":
            let granted: Bool = try WindowCapture.wait(session: session) { done in
                if #available(macOS 14.0, *) { events.requestFullAccessToEvents { done($0, $1) } }
                else { events.requestAccess(to: .event) { done($0, $1) } }
            }
            return ["granted": granted]
        case "contacts":
            let granted: Bool = try WindowCapture.wait(session: session) { done in
                contacts.requestAccess(for: .contacts) { done($0, $1) }
            }
            return ["granted": granted]
        default:
            throw ActionError.failure(kind: "unsupported", message: "this capability has no native permission flow")
        }
    }

    private static func requireCalendar() throws {
        let status = EKEventStore.authorizationStatus(for: .event)
        if #available(macOS 14.0, *) {
            if status == .fullAccess { return }
        } else if status == .authorized { return }
        throw ActionError.failure(kind: "permission_required", message: "Calendar permission is required")
    }
    private static func requireContacts() throws {
        guard CNContactStore.authorizationStatus(for: .contacts) == .authorized else {
            throw ActionError.failure(kind: "permission_required", message: "Contacts permission is required")
        }
    }
    private static func range(_ params: [String: Any]) throws -> (Date, Date) {
        guard let start = params["start"] as? String, let end = params["end"] as? String,
              let first = ISO8601DateFormatter().date(from: start),
              let last = ISO8601DateFormatter().date(from: end),
              first < last, last.timeIntervalSince(first) <= 366 * 24 * 3600 else {
            throw ActionError.failure(kind: "invalid_params", message: "start/end must be an ISO-8601 range of at most one year")
        }
        return (first, last)
    }
}
