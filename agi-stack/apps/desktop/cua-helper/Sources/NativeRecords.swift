import Contacts
import EventKit
import Foundation

/// Fixed native record edits. Identifiers are exact and field names are an API
/// allow-list; every operation still passes through the host's tool consent.
enum NativeRecords {
    static func fields(_ params: [String: Any], allowed: Set<String>) throws -> (String, [String: Any]) {
        guard let id = params["id"] as? String, !id.isEmpty, id.utf8.count <= 4096,
              let fields = params["fields"] as? [String: Any], !fields.isEmpty,
              Set(fields.keys).isSubset(of: allowed) else {
            throw ActionError.failure(kind: "invalid_params", message: "exact id and supported fields are required")
        }
        return (id, fields)
    }
    static func identifier(_ params: [String: Any]) throws -> String {
        guard let id = params["id"] as? String, !id.isEmpty, id.utf8.count <= 4096 else {
            throw ActionError.failure(kind: "invalid_params", message: "exact id is required")
        }
        return id
    }
    static func calendar(_ method: String, params: [String: Any], store: EKEventStore,
                         session: NativeSession) throws -> [String: Any] {
        let id = try identifier(params)
        guard let event = store.event(withIdentifier: id), event.eventIdentifier == id,
              event.calendar.allowsContentModifications else {
            throw ActionError.failure(kind: "record_not_found", message: "a writable event with that exact id is required")
        }
        if method == "calendar_delete" {
            try session.cancellation.check(); try store.remove(event, span: .thisEvent, commit: true)
            return ["id": id, "deleted": true]
        }
        let (_, edits) = try fields(params, allowed: ["title", "start", "end", "location", "notes", "calendar_id"])
        for (field, value) in edits {
            guard let text = value as? String, text.utf8.count <= 100_000 else {
                throw ActionError.failure(kind: "invalid_params", message: "calendar fields must be bounded strings")
            }
            switch field {
            case "title":
                guard !text.isEmpty else { throw ActionError.failure(kind: "invalid_params", message: "title must not be empty") }
                event.title = text
            case "start", "end":
                guard let date = ISO8601DateFormatter().date(from: text) else {
                    throw ActionError.failure(kind: "invalid_params", message: "dates must use ISO-8601")
                }
                if field == "start" { event.startDate = date } else { event.endDate = date }
            case "location": event.location = text
            case "notes": event.notes = text
            case "calendar_id":
                guard let calendar = store.calendar(withIdentifier: text), calendar.allowsContentModifications else {
                    throw ActionError.failure(kind: "invalid_params", message: "calendar_id must be writable")
                }
                event.calendar = calendar
            default: preconditionFailure("validated field missing")
            }
        }
        guard event.startDate < event.endDate, event.endDate.timeIntervalSince(event.startDate) <= 366 * 86400 else {
            throw ActionError.failure(kind: "invalid_params", message: "event must have a positive duration of at most one year")
        }
        try session.cancellation.check(); try store.save(event, span: .thisEvent, commit: true)
        return ["id": event.eventIdentifier ?? id, "ok": true]
    }
    static func contact(_ method: String, params: [String: Any], store: CNContactStore,
                        session: NativeSession) throws -> [String: Any] {
        let id = try identifier(params)
        let keys = [CNContactIdentifierKey, CNContactGivenNameKey, CNContactFamilyNameKey,
                    CNContactEmailAddressesKey, CNContactPhoneNumbersKey]
        let original = try store.unifiedContact(withIdentifier: id, keysToFetch: keys as [CNKeyDescriptor])
        guard original.identifier == id, let contact = original.mutableCopy() as? CNMutableContact else {
            throw ActionError.failure(kind: "record_not_found", message: "contact with that exact id is required")
        }
        let request = CNSaveRequest()
        if method == "contacts_delete" { request.delete(contact) }
        else {
            let (_, edits) = try fields(params, allowed: ["given_name", "family_name", "email", "emails", "phones"])
            for (field, value) in edits {
                switch field {
                case "given_name", "family_name", "email":
                    guard let text = value as? String, text.utf8.count <= 4096 else {
                        throw ActionError.failure(kind: "invalid_params", message: "contact fields must be bounded strings")
                    }
                    if field == "given_name" { contact.givenName = text }
                    else if field == "family_name" { contact.familyName = text }
                    else { contact.emailAddresses = text.isEmpty ? [] : [CNLabeledValue(label: CNLabelOther, value: text as NSString)] }
                case "emails", "phones":
                    guard let texts = value as? [String], texts.count <= 100,
                          texts.allSatisfy({ $0.utf8.count <= 4096 }) else {
                        throw ActionError.failure(kind: "invalid_params", message: "emails and phones must be bounded string arrays")
                    }
                    if field == "emails" {
                        contact.emailAddresses = texts.map { CNLabeledValue(label: CNLabelOther, value: $0 as NSString) }
                    } else {
                        contact.phoneNumbers = texts.map { CNLabeledValue(label: CNLabelOther, value: CNPhoneNumber(stringValue: $0)) }
                    }
                default: preconditionFailure("validated field missing")
                }
            }
            request.update(contact)
        }
        try session.cancellation.check(); try store.execute(request)
        return ["id": id, method == "contacts_delete" ? "deleted" : "ok": true]
    }
}
