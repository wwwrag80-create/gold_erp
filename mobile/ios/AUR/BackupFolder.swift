import Foundation

/// مجلد الحفظ التلقائي — كما على أندرويد: مجلدٌ يختاره صاحب الجهاز (في «الملفات» أو
/// iCloud Drive) فيبقى ولو حُذف التطبيق. بعد كل تغيير يُكتب `gold-data.json` (الأحدث)
/// ونسخةُ اليوم `gold-data-YYYY-MM-DD.json` (تبقى آخر 14)، وصور الأطقم في `gold-photos`.
/// الإذن بالمجلد يُحفظ «علامةً» (bookmark) في إعدادات التطبيق وحده.
final class BackupFolder {
    static let latest = "gold-data.json"
    static let daily = "gold-data-"
    static let oldLatest = "jadeite-data.json"
    static let photos = "gold-photos"
    static let keepDays = 14
    let defaults = UserDefaults.standard
    let lock = NSLock()

    enum Failure: LocalizedError {
        case noFolder, unreadable
        var errorDescription: String? {
            switch self {
            case .noFolder: return "لم يُختر مجلد الحفظ التلقائي، أو سُحب إذنه"
            case .unreadable: return "تعذّر فتح المجلد — اختره من جديد"
            }
        }
    }

    static func validId(_ id: String) -> Bool {
        id.range(of: "^[A-Za-z0-9_-]{1,64}$", options: .regularExpression) != nil
    }

    func name() -> String { defaults.string(forKey: "backupName") ?? "" }
    func hasFolder() -> Bool { defaults.data(forKey: "backupBookmark") != nil }

    /// المجلد المختار: يُحفظ إذنه (bookmark) واسمه
    func set(_ url: URL) throws {
        guard url.startAccessingSecurityScopedResource() else { throw Failure.unreadable }
        defer { url.stopAccessingSecurityScopedResource() }
        let mark = try url.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil)
        defaults.set(mark, forKey: "backupBookmark")
        defaults.set(url.lastPathComponent, forKey: "backupName")
    }

    /// يفتح المجلد (بإذنه المحفوظ) طوال `body` ثم يغلقه
    func with<T>(_ body: (URL) throws -> T) throws -> T {
        lock.lock()
        defer { lock.unlock() }
        guard let mark = defaults.data(forKey: "backupBookmark") else { throw Failure.noFolder }
        var stale = false
        let url = try URL(resolvingBookmarkData: mark, options: [], relativeTo: nil, bookmarkDataIsStale: &stale)
        guard url.startAccessingSecurityScopedResource() else { throw Failure.noFolder }
        defer { url.stopAccessingSecurityScopedResource() }
        if stale, let fresh = try? url.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil) {
            defaults.set(fresh, forKey: "backupBookmark")
        }
        return try body(url)
    }

    func coordinatedWrite(_ data: Data, to file: URL) throws {
        var err: NSError?
        var inner: Error?
        NSFileCoordinator().coordinate(writingItemAt: file, options: .forReplacing, error: &err) { u in
            do { try data.write(to: u, options: .atomic) } catch { inner = error }
        }
        if let e = err ?? inner { throw e }
    }

    func dayStamp() -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }

    /// النسخة: الأحدث ونسخة اليوم، ويُحذف ما زاد على 14 يوماً (بالاسم، الأقدم أولاً)
    func write(_ json: String) throws -> Double {
        try with { dir in
            let data = Data(json.utf8)
            try coordinatedWrite(data, to: dir.appendingPathComponent(Self.latest))
            try coordinatedWrite(data, to: dir.appendingPathComponent(Self.daily + dayStamp() + ".json"))
            let names = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
            let days = names.filter { $0.hasPrefix(Self.daily) && $0.hasSuffix(".json") }.sorted(by: >)
            for old in days.dropFirst(Self.keepDays) {
                try? FileManager.default.removeItem(at: dir.appendingPathComponent(old))
            }
            return Date().timeIntervalSince1970 * 1000
        }
    }

    func savePhoto(_ id: String, _ jpeg: Data) throws {
        try with { dir in
            let p = dir.appendingPathComponent(Self.photos, isDirectory: true)
            try FileManager.default.createDirectory(at: p, withIntermediateDirectories: true)
            let f = p.appendingPathComponent(id + ".jpg")
            if FileManager.default.fileExists(atPath: f.path) { return }
            try coordinatedWrite(jpeg, to: f)
        }
    }

    func photoIds() -> Set<String> {
        (try? with { dir -> Set<String> in
            let p = dir.appendingPathComponent(Self.photos, isDirectory: true)
            let names = (try? FileManager.default.contentsOfDirectory(atPath: p.path)) ?? []
            return Set(names.filter { $0.hasSuffix(".jpg") }.map { String($0.dropLast(4)) }.filter(Self.validId))
        }) ?? []
    }

    func readPhoto(_ id: String) -> Data? {
        try? with { dir in try Data(contentsOf: dir.appendingPathComponent(Self.photos).appendingPathComponent(id + ".jpg")) }
    }

    /// أحدث نسخةٍ في المجلد: gold-data.json، أو أحدث نسخةٍ يوميةٍ أو قديمة بالاسم
    func readLatest() throws -> (file: String, text: String)? {
        try with { dir in
            let names = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
            var pick: String?
            if names.contains(Self.latest) { pick = Self.latest }
            else if names.contains(Self.oldLatest) { pick = Self.oldLatest }
            else {
                pick = names.filter { n in n.hasSuffix(".json") &&
                    ["gold-data", "gold-backup", "jadeite-data", "jadeite-backup"].contains { n.hasPrefix($0) } }
                    .sorted(by: >).first
            }
            guard let file = pick else { return nil }
            let text = try String(contentsOf: dir.appendingPathComponent(file), encoding: .utf8)
            return (file, text)
        }
    }
}
