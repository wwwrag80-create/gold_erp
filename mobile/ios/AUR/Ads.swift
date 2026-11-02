import UIKit
import GoogleMobileAds
import UserMessagingPlatform

/// إعلان AdMob على الآيفون — كأندرويد تماماً: شريطٌ واحد صغير أسفل الشاشة (تكيّفي ثابت)،
/// في شاشات التصفّح وحدها (الصفحة تقول ما يناسب كل شاشة)، مطويٌّ حتى يصل إعلان،
/// ولا إعلانات بملء الشاشة ولا بمكافأة ولا بصوت. الموافقة (UMP) أولاً حيث يلزمها
/// القانون — ومنها رسالة «السماح بالتتبّع» إن فعّلها المالك في حساب AdMob.
/// بمعرّفات Google التجريبية: نسخة التطوير (Debug) وحدها تعرض إعلاناً.
final class Ads: NSObject, GADBannerViewDelegate {
    weak var host: WebViewController?
    var banner: GADBannerView?
    var wanted = false
    var loaded = false
    var started = false
    var error = ""
    var retries = 0

    init(host: WebViewController) { self.host = host }

    var appId: String { (Bundle.main.object(forInfoDictionaryKey: "GADApplicationIdentifier") as? String) ?? "" }
    var unitId: String { (Bundle.main.object(forInfoDictionaryKey: "AURBannerUnitID") as? String) ?? "" }
    var testIds: Bool { appId.hasPrefix("ca-app-pub-3940256099942544") }
    var enabled: Bool {
        #if DEBUG
        return !unitId.isEmpty
        #else
        return !testIds && !unitId.isEmpty
        #endif
    }

    /// تجربة الواجهة الآلية (نسخة التطوير وحدها): بلا نافذة موافقة — توقيتها من الشبكة يجعل
    /// التجربة متقلّبة؛ والإعلان التجريبي يُحمَّل كالعادة. المستخدمون لا يمرّرون هذا أبداً.
    var uiTesting: Bool {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("-AURUITesting")
        #else
        return false
        #endif
    }

    func start() {
        push()
        guard enabled, !started else { return }
        if uiTesting { return initSDK() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { self.initSDK() }
        let info = UMPConsentInformation.sharedInstance
        info.requestConsentInfoUpdate(with: UMPRequestParameters()) { [weak self] err in
            guard let self else { return }
            if let err {
                self.error = "consent: \(err.localizedDescription)"
                self.initSDK()
                return
            }
            guard let host = self.host else { return self.initSDK() }
            UMPConsentForm.loadAndPresentIfRequired(from: host) { err in
                if let err { self.error = "consent form: \(err.localizedDescription)" }
                self.initSDK()
            }
        }
        if info.canRequestAds { initSDK() }
    }

    func initSDK() {
        guard !started else { return }
        started = true
        push()
        GADMobileAds.sharedInstance().start { _ in DispatchQueue.main.async { self.load() } }
    }

    func load() {
        guard let host else { return }
        if banner == nil {
            let width = host.view.frame.inset(by: host.view.safeAreaInsets).width
            let b = GADBannerView(adSize: GADCurrentOrientationAnchoredAdaptiveBannerAdSizeWithWidth(max(320, width)))
            b.adUnitID = unitId
            b.rootViewController = host
            b.delegate = self
            b.translatesAutoresizingMaskIntoConstraints = false
            host.adBar.addSubview(b)
            NSLayoutConstraint.activate([
                b.centerXAnchor.constraint(equalTo: host.adBar.centerXAnchor),
                b.topAnchor.constraint(equalTo: host.adBar.topAnchor),
            ])
            banner = b
        }
        banner?.load(GADRequest())
    }

    func bannerViewDidReceiveAd(_ bannerView: GADBannerView) {
        loaded = true
        apply()
    }

    func bannerView(_ bannerView: GADBannerView, didFailToReceiveAdWithError err: Error) {
        // لا إعلان (لا إنترنت أو لا مخزون): الشريط مطويّ، ومحاولةٌ لاحقة هادئة
        loaded = false
        error = "\((err as NSError).code) \(err.localizedDescription)"
        apply()
        if retries < 3 {
            let wait = 60.0 * pow(2.0, Double(retries))
            retries += 1
            DispatchQueue.main.asyncAfter(deadline: .now() + wait) { self.banner?.load(GADRequest()) }
        }
    }

    /// الصفحة: هل تناسب الشاشة الحالية إعلاناً؟ (التصفّح نعم، الإدخال لا)
    func setWanted(_ w: Bool) {
        wanted = w
        apply()
    }

    func apply() {
        DispatchQueue.main.async {
            guard let host = self.host else { return }
            let show = self.enabled && self.wanted && self.loaded
            host.adHeight.constant = show ? (self.banner?.adSize.size.height ?? 0) : 0
            self.banner?.isHidden = !show
            host.view.layoutIfNeeded()
            self.push()
        }
    }

    /// حيث يلزم القانون (أوروبا وبريطانيا): زرٌّ في «المزيد» لتغيير موافقة الإعلانات
    var privacyRequired: Bool {
        enabled && UMPConsentInformation.sharedInstance.privacyOptionsRequirementStatus == .required
    }

    func showPrivacy() {
        guard let host else { return }
        UMPConsentForm.presentPrivacyOptionsForm(from: host) { err in
            if let err { self.error = "privacy: \(err.localizedDescription)" }
            self.push()
        }
    }

    func push() {
        let h = Double(host?.adHeight?.constant ?? 0)
        let state: [String: Any] = ["enabled": enabled, "testIds": testIds, "privacy": privacyRequired, "started": started,
                                    "wanted": wanted, "loaded": loaded, "visible": h > 0, "height": h, "error": error]
        host?.setState("ads", state)
    }
}
