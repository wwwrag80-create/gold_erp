import Foundation
import WebKit

/// يخدم صفحات التطبيق من داخله على العنوان aur://app/ — أصلٌ ثابت تُحفظ فيه بياناته
/// (IndexedDB) كما على أندرويد (appassets). لا يخرج طلبٌ منه إلى الإنترنت.
final class AssetHandler: NSObject, WKURLSchemeHandler {
    static let scheme = "aur"
    static let base = URL(string: "aur://app/")!
    let root: URL = Bundle.main.url(forResource: "web", withExtension: nil)!

    static let types: [String: String] = [
        "html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
        "css": "text/css; charset=utf-8", "json": "application/json", "png": "image/png",
        "jpg": "image/jpeg", "svg": "image/svg+xml", "ttf": "font/ttf", "txt": "text/plain; charset=utf-8",
    ]

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else { return }
        var path = url.path
        if path.isEmpty || path == "/" { path = "/index.html" }
        let file = root.appendingPathComponent(String(path.dropFirst())).standardizedFileURL
        guard file.path.hasPrefix(root.standardizedFileURL.path), let data = try? Data(contentsOf: file) else {
            task.didReceive(HTTPURLResponse(url: url, statusCode: 404, httpVersion: "HTTP/1.1", headerFields: [:])!)
            task.didFinish()
            return
        }
        let mime = AssetHandler.types[file.pathExtension.lowercased()] ?? "application/octet-stream"
        task.didReceive(HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
                                        headerFields: ["Content-Type": mime, "Content-Length": "\(data.count)",
                                                       "Cache-Control": "no-cache"])!)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}
}
