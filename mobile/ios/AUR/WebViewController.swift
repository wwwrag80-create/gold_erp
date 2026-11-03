import UIKit
import WebKit
import UniformTypeIdentifiers

/// صفحات ÀUR (mobile/web) في WKWebView، وجسرٌ بالأسماء نفسها التي يعرفها التطبيق على
/// أندرويد (`AndroidBridge`): فلا يتغيّر في الصفحات سطرٌ واحد. الصفحة تنادي، وهذا
/// الغلاف ينفّذ ثم يردّ بأحداث `window.__native(اسم، بيانات)`.
final class WebViewController: UIViewController, WKNavigationDelegate, WKUIDelegate,
                               WKScriptMessageHandler, UIDocumentPickerDelegate {
    var web: WKWebView!
    let adBar = UIView()
    var adHeight: NSLayoutConstraint!
    lazy var ads = Ads(host: self)
    let backup = BackupFolder()
    let work = DispatchQueue(label: "aur.backup")
    var picking = ""                      // backupFolder · restore · save
    var hidden: [WKWebView] = []          // صفحاتٌ مخفية للصورة والطباعة
    var hiddenDone: [ObjectIdentifier: () -> Void] = [:]

    var version: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "0"
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(named: "Surface")
        let cfg = pageConfig()
        let ucc = cfg.userContentController
        ucc.addUserScript(WKUserScript(source: shim(), injectionTime: .atDocumentStart, forMainFrameOnly: true))
        #if DEBUG
        ucc.addUserScript(WKUserScript(source: Self.debugScript, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        #endif
        ucc.add(WeakHandler(self), name: "aur")
        web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true      // السحب من الحافة = رجوع صفحة
        web.isOpaque = false
        web.backgroundColor = UIColor(named: "Background")
        if #available(iOS 16.4, *) {
            #if DEBUG
            web.isInspectable = true
            #endif
        }
        web.translatesAutoresizingMaskIntoConstraints = false
        adBar.translatesAutoresizingMaskIntoConstraints = false
        adBar.backgroundColor = UIColor(named: "Surface")
        adBar.clipsToBounds = true
        view.addSubview(web)
        view.addSubview(adBar)
        let g = view.safeAreaLayoutGuide
        adHeight = adBar.heightAnchor.constraint(equalToConstant: 0)
        NSLayoutConstraint.activate([
            web.topAnchor.constraint(equalTo: g.topAnchor),
            web.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            web.bottomAnchor.constraint(equalTo: adBar.topAnchor),
            adBar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            adBar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            adBar.bottomAnchor.constraint(equalTo: g.bottomAnchor),
            adHeight,
        ])
        web.load(URLRequest(url: AssetHandler.base.appendingPathComponent("index.html")))
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        ads.start()
    }

    func pageConfig() -> WKWebViewConfiguration {
        let cfg = WKWebViewConfiguration()
        cfg.setURLSchemeHandler(AssetHandler(), forURLScheme: AssetHandler.scheme)
        cfg.allowsInlineMediaPlayback = true
        return cfg
    }

    // ══ الجسر: الأسماء نفسها التي في أندرويد ══
    func shim() -> String {
        let folder = jsonString(backup.name())
        return """
        (function () {
          if (window.AndroidBridge) return;
          var post = function (fn, args) { window.webkit.messageHandlers.aur.postMessage({ fn: fn, args: args || [] }); };
          window.__iosState = { version: \(jsonString(version)), backupFolder: \(folder), ads: {} };
          window.AndroidBridge = {
            appVersion: function () { return window.__iosState.version; },
            setLang: function () {},
            setAds: function (on) { post("setAds", [!!on]); },
            adsState: function () { return JSON.stringify(window.__iosState.ads || {}); },
            adsPrivacy: function () { post("adsPrivacy"); },
            shareText: function (t) { post("shareText", [t]); },
            shareHtmlImage: function (h, n) { post("shareHtmlImage", [h, n]); },
            printHtml: function (h, n) { post("printHtml", [h, n]); },
            saveFile: function (n, b, m) { post("saveFile", [n, b, m]); },
            shareFile: function (n, b, m) { post("shareFile", [n, b, m]); },
            backupFolder: function () { return window.__iosState.backupFolder || ""; },
            pickBackupFolder: function () { post("pickBackupFolder"); },
            restoreFromFolder: function () { post("restoreFromFolder"); },
            savePhoto: function (id, b) { post("savePhoto", [id, b]); },
            syncPhotos: function (j) { post("syncPhotos", [j]); },
            restorePhotos: function () { post("restorePhotos"); },
            autoBackup: function (j) { post("autoBackup", [j]); },
            // التحديث من App Store وحده — فلا زرّ ولا قناة في التطبيق
            updateState: function () { return JSON.stringify({ unsupported: true, store: "appstore", version: window.__iosState.version }); },
            checkUpdate: function () {}, installUpdate: function () {}, requestNotifications: function () {}
          };
        })();
        """
    }

    #if DEBUG
    /// نسخة التطوير وحدها: أخطاء الصفحة ونقراتها وانتقالاتها إلى سجلّ الجهاز (AUR-JS) — لتجربة المحاكي
    static let debugScript = """
    (function () {
      var log = function () {
        try { window.webkit.messageHandlers.aur.postMessage({ fn: "log", args: [Array.prototype.map.call(arguments, String).join(" ")] }); } catch (e) {}
      };
      window.addEventListener("error", function (e) { log("error", e.message, (e.filename || "") + ":" + e.lineno); });
      window.addEventListener("unhandledrejection", function (e) { log("rejection", e.reason && (e.reason.stack || e.reason)); });
      window.addEventListener("hashchange", function () { log("hash", location.hash); });
      document.addEventListener("click", function (e) { log("click", e.target && (e.target.textContent || "").trim().slice(0, 40)); }, true);
      document.addEventListener("DOMContentLoaded", function () {
        var ls = "?"; try { localStorage.setItem("__t", "1"); ls = localStorage.getItem("__t"); } catch (e) { ls = "x " + e; }
        log("loaded", location.href, "localStorage=" + ls, "indexedDB=" + (typeof indexedDB), "hash=" + location.hash);
      });
      var ce = console.error;
      console.error = function () { log.apply(null, ["console.error"].concat([].slice.call(arguments))); ce.apply(console, arguments); };
    })();
    """
    #endif

    func jsonString(_ s: String) -> String {
        let d = try? JSONSerialization.data(withJSONObject: [s])
        let a = d.flatMap { String(data: $0, encoding: .utf8) } ?? "[\"\"]"
        return String(a.dropFirst().dropLast())
    }

    /// حدثٌ إلى الصفحة: window.__native(اسم، بيانات)
    func emit(_ event: String, _ data: [String: Any] = [:]) {
        let body = (try? JSONSerialization.data(withJSONObject: data)).flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
        DispatchQueue.main.async {
            self.web.evaluateJavaScript("window.__native&&window.__native(\(self.jsonString(event)),\(body))")
        }
    }

    /// حالةٌ تقرؤها الصفحة مباشرةً (اسم المجلد، الإعلان)
    func setState(_ key: String, _ value: Any) {
        let v = (try? JSONSerialization.data(withJSONObject: [value])).flatMap { String(data: $0, encoding: .utf8) } ?? "[null]"
        DispatchQueue.main.async {
            self.web?.evaluateJavaScript("window.__iosState&&(window.__iosState[\(self.jsonString(key))]=\(v)[0])")
        }
    }

    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let m = message.body as? [String: Any], let fn = m["fn"] as? String else { return }
        let a = (m["args"] as? [Any]) ?? []
        let s = { (i: Int) -> String in i < a.count ? ((a[i] as? String) ?? "") : "" }
        switch fn {
        case "setAds": ads.setWanted((a.first as? Bool) ?? false)
        case "adsPrivacy": ads.showPrivacy()
        case "shareText": share([s(0)])
        case "shareHtmlImage": capture(html: s(0), name: s(1))
        case "printHtml": printPage(html: s(0), name: s(1))
        case "saveFile": saveFile(name: s(0), b64: s(1))
        case "shareFile": shareFile(name: s(0), b64: s(1))
        case "pickBackupFolder": pickFolder("backupFolder")
        case "restoreFromFolder": pickFolder("restore")
        case "savePhoto": savePhoto(id: s(0), b64: s(1))
        case "syncPhotos": syncPhotos(s(0))
        case "restorePhotos": restorePhotos()
        case "autoBackup": autoBackup(s(0))
        case "log": NSLog("AUR-JS %@", s(0))
        default: break
        }
    }

    // ══ الروابط: صفحات التطبيق داخله، وما سواها (اتصال، واتساب) في تطبيقه ══
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { return decisionHandler(.cancel) }
        #if DEBUG
        NSLog("AUR-NAV %@ type=%ld main=%ld", url.absoluteString, action.navigationType.rawValue, action.targetFrame?.isMainFrame == true ? 1 : 0)
        #endif
        if url.scheme == AssetHandler.scheme || url.scheme == "about" || url.scheme == "data" {
            return decisionHandler(.allow)
        }
        UIApplication.shared.open(url)
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        #if DEBUG
        NSLog("AUR-NAV finished %@", webView.url?.absoluteString ?? "-")
        #endif
        if let done = hiddenDone.removeValue(forKey: ObjectIdentifier(webView)) { done() }
    }

    // ══ المشاركة والحفظ ══
    func present(_ vc: UIViewController) {
        if let p = vc.popoverPresentationController {
            p.sourceView = view
            p.sourceRect = CGRect(x: view.bounds.midX, y: view.bounds.maxY - 80, width: 1, height: 1)
        }
        (presentedViewController ?? self).present(vc, animated: true)
    }

    func share(_ items: [Any]) {
        DispatchQueue.main.async { self.present(UIActivityViewController(activityItems: items, applicationActivities: nil)) }
    }

    func tempFile(_ name: String, _ data: Data) throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("share", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let safe = name.replacingOccurrences(of: "/", with: "-")
        let url = dir.appendingPathComponent(safe.isEmpty ? "file" : safe)
        try data.write(to: url, options: .atomic)
        return url
    }

    func shareFile(name: String, b64: String) {
        guard let d = Data(base64Encoded: b64, options: .ignoreUnknownCharacters), let url = try? tempFile(name, d) else { return }
        share([url])
    }

    func saveFile(name: String, b64: String) {
        guard let d = Data(base64Encoded: b64, options: .ignoreUnknownCharacters), let url = try? tempFile(name, d) else { return }
        DispatchQueue.main.async {
            let p = UIDocumentPickerViewController(forExporting: [url], asCopy: true)
            self.picking = "save"
            p.delegate = self
            self.present(p)
        }
    }

    // ══ صفحةٌ مخفية (بعرضٍ معيّن) — للصورة والطباعة، بخطوط التطبيق نفسها ══
    func hiddenPage(_ html: String, width: CGFloat, done: @escaping (WKWebView) -> Void) {
        let v = WKWebView(frame: CGRect(x: -20000, y: 0, width: width, height: 1400), configuration: pageConfig())
        v.navigationDelegate = self
        view.addSubview(v)
        hidden.append(v)
        hiddenDone[ObjectIdentifier(v)] = { done(v) }
        v.loadHTMLString(html, baseURL: AssetHandler.base)
    }

    func dropHidden(_ v: WKWebView) {
        v.removeFromSuperview()
        hidden.removeAll { $0 === v }
    }

    /// المستند صورةً بعرض 1080 (كأندرويد) ثم نافذة المشاركة (واتساب وغيره)
    func capture(html: String, name: String) {
        var pw = 1000
        if let r = html.range(of: "<!--page-width:(\\d{3,4})-->", options: .regularExpression) {
            let digits = html[r].filter { $0.isNumber }
            pw = max(320, min(1000, Int(digits) ?? 1000))
        }
        let page = html.replacingOccurrences(of: "width=device-width,initial-scale=1", with: "width=\(pw)")
        DispatchQueue.main.async {
            self.hiddenPage(page, width: CGFloat(pw)) { v in
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
                    v.evaluateJavaScript("document.documentElement.scrollHeight") { h, _ in
                        var height = CGFloat((h as? NSNumber)?.doubleValue ?? 1400)
                        let maxH = CGFloat(9000) * CGFloat(pw) / 1080
                        if height > maxH { height = maxH }
                        v.frame.size.height = max(200, height)
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                            let c = WKSnapshotConfiguration()
                            c.rect = CGRect(x: 0, y: 0, width: CGFloat(pw), height: v.frame.height)
                            c.snapshotWidth = NSNumber(value: Double(1080) / Double(UIScreen.main.scale))
                            v.takeSnapshot(with: c) { img, _ in
                                self.dropHidden(v)
                                guard let png = img?.pngData(), let url = try? self.tempFile(name + ".png", png) else { return }
                                self.share([url])
                            }
                        }
                    }
                }
            }
        }
    }

    /// الطباعة — ومنها «حفظ PDF» من نافذة الطباعة
    func printPage(html: String, name: String) {
        DispatchQueue.main.async {
            self.hiddenPage(html, width: 794) { v in
                let info = UIPrintInfo(dictionary: nil)
                info.jobName = name
                info.outputType = .general
                let pc = UIPrintInteractionController.shared
                pc.printInfo = info
                pc.printFormatter = v.viewPrintFormatter()
                pc.present(animated: true) { _, _, _ in self.dropHidden(v) }
            }
        }
    }

    // ══ مجلد الحفظ التلقائي (يبقى بعد حذف التطبيق: في «الملفات» أو iCloud Drive) ══
    func pickFolder(_ purpose: String) {
        DispatchQueue.main.async {
            let p = UIDocumentPickerViewController(forOpeningContentTypes: [UTType.folder])
            self.picking = purpose
            p.delegate = self
            self.present(p)
        }
    }

    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        let purpose = picking
        picking = ""
        guard purpose == "backupFolder" || purpose == "restore", let url = urls.first else { return }
        do {
            try backup.set(url)
            setState("backupFolder", backup.name())
        } catch {
            emit(purpose, ["ok": false, "error": error.localizedDescription])
            return
        }
        if purpose == "backupFolder" {
            emit("backupFolder", ["ok": true, "name": backup.name()])
            return
        }
        work.async {
            do {
                if let r = try self.backup.readLatest() {
                    self.emit("restore", ["ok": true, "file": r.file, "text": r.text, "name": self.backup.name()])
                } else {
                    self.emit("restore", ["ok": false, "error": "لا توجد نسخةٌ من بيانات التطبيق في هذا المجلد",
                                          "name": self.backup.name()])
                }
            } catch {
                self.emit("restore", ["ok": false, "error": error.localizedDescription])
            }
        }
    }

    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        let purpose = picking
        picking = ""
        if purpose == "backupFolder" || purpose == "restore" { emit(purpose, ["ok": false]) }
    }

    func autoBackup(_ json: String) {
        work.async {
            do {
                let at = try self.backup.write(json)
                self.emit("backupDone", ["ok": true, "at": at])
            } catch {
                self.emit("backupDone", ["ok": false, "error": error.localizedDescription])
            }
        }
    }

    func savePhoto(id: String, b64: String) {
        guard BackupFolder.validId(id), let d = Data(base64Encoded: b64, options: .ignoreUnknownCharacters) else { return }
        work.async {
            do { try self.backup.savePhoto(id, d) } catch {
                self.emit("backupDone", ["ok": false, "error": error.localizedDescription])
            }
        }
    }

    func syncPhotos(_ idsJson: String) {
        work.async {
            guard self.backup.hasFolder(),
                  let want = (try? JSONSerialization.jsonObject(with: Data(idsJson.utf8))) as? [String] else { return }
            let have = self.backup.photoIds()
            let missing = want.filter { BackupFolder.validId($0) && !have.contains($0) }
            if !missing.isEmpty { self.emit("photosMissing", ["ids": missing]) }
        }
    }

    func restorePhotos() {
        work.async {
            var n = 0
            for id in self.backup.photoIds() {
                guard let d = self.backup.readPhoto(id) else { continue }
                self.emit("photo", ["id": id, "b64": d.base64EncodedString()])
                n += 1
            }
            self.emit("photosDone", ["n": n])
        }
    }
}

/// يمنع حلقة الاحتفاظ بين WKUserContentController والمتحكّم
final class WeakHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ t: WKScriptMessageHandler) { target = t }
    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(ucc, didReceive: message)
    }
}
