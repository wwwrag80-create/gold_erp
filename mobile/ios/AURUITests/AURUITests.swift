import XCTest

/// تجربة ÀUR على محاكي الآيفون: يفتح، ثم الترحيب ← الرئيسية ولوحاتها ← البحث عن طقم
/// ← الحسابات والممتلكات، مع صورةٍ لكل خطوة (تُرفق بنتيجة التجربة).
final class AURUITests: XCTestCase {
    var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments += ["-AURUITesting"]   // بلا نافذة موافقة الإعلانات أثناء التجربة الآلية
        app.launch()
    }

    func snap(_ name: String) {
        let a = XCTAttachment(screenshot: app.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }

    func button(_ text: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label CONTAINS[cd] %@", text)).firstMatch
    }

    func anyText(_ text: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[cd] %@", text)).firstMatch
    }

    /// أول تشغيل: رسالة موافقة الإعلانات من Google (UMP) ثم سؤال iOS عن التتبّع — حيث يُعدّها
    /// حساب AdMob، وتصل من الشبكة في أي لحظةٍ من أول التشغيل. «متابعة» (حين تصير قابلةً للّمس،
    /// ويُتأكَّد أنها أُغلقت) ثم «اطلب من التطبيق عدم التتبّع»؛ والتطبيق يعمل في الحالين.
    /// ينتظر اختفاء عنصرٍ — بلا فشلٍ إن اختفى بين سؤالين
    func gone(_ e: XCUIElement, within t: TimeInterval) -> Bool {
        let x = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: e)
        return XCTWaiter().wait(for: [x], timeout: t) == .completed
    }

    func clearConsent(wait: TimeInterval) {
        let cont = app.buttons.matching(NSPredicate(format: "label IN %@", ["Continue", "متابعة"])).firstMatch
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let deny = springboard.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@ OR label CONTAINS %@",
                                                            "Not to Track", "عدم التتبع")).firstMatch
        if deny.exists { snap("00_tracking"); deny.tap() }
        guard cont.waitForExistence(timeout: wait) else { return }
        snap("00_consent")
        // النافذة تظهر بحركة: لمسةٌ في مكان الزرّ على الشاشة بعد أن تستقرّ، ثم انتظار اختفائها
        // (لا سؤال «قابلٌ للّمس؟» عن زرٍّ قد يختفي في اللحظة نفسها)
        for _ in 0..<4 {
            Thread.sleep(forTimeInterval: 2)
            let frame = cont.exists ? cont.frame : .zero
            if frame == .zero { break }
            app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: frame.midX, dy: frame.midY)).tap()
            if gone(cont, within: 8) { break }
        }
        if deny.waitForExistence(timeout: 15) {
            snap("00_tracking")
            deny.tap()
        }
        Thread.sleep(forTimeInterval: 1)
    }

    func testLaunchHomeSearchAndTabs() throws {
        // أول تشغيل: شاشة الترحيب باسم التطبيق وزرّي مجلد الحفظ
        XCTAssertTrue(anyText("ÀUR").waitForExistence(timeout: 30), "الترحيب باسم ÀUR")
        clearConsent(wait: 3)
        XCTAssertTrue(button("اختر مجلد الحفظ").exists, "زرّ مجلد الحفظ التلقائي")
        snap("01_welcome")
        button("تخط").tap()

        // الرئيسية: لوحات العمليات وكشف الحساب والبحث (لمسةٌ ثانية إن ضاعت الأولى — وتُسجَّل صورتها)
        if !button("بيع للعميل").waitForExistence(timeout: 8) {
            snap("01b_skip_again")
            clearConsent(wait: 3)
            button("تخط").tap()
        }
        XCTAssertTrue(button("بيع للعميل").waitForExistence(timeout: 15), "لوحة «بيع للعميل»")
        XCTAssertTrue(button("تحصيل من العميل").exists)
        XCTAssertTrue(button("كشف حساب").exists)
        XCTAssertTrue(button("بحث عن طقم").exists)
        snap("02_home")

        // «المزيد»: القائمة، ومنها خيارات خصوصية الإعلانات حيث يلزمها القانون
        button("المزيد").tap()
        XCTAssertTrue(anyText("سجل العمليات").waitForExistence(timeout: 10), "المزيد")
        snap("03_more")

        // البحث عن طقم (من القائمة — لوحته في الرئيسية تحت الشريط السفلي على هذا الجوال):
        // الخانة جاهزة، ورقمٌ بلا أطقمٍ بعدُ ⇒ «لا طقم»
        app.staticTexts.matching(NSPredicate(format: "label == %@", "بحث عن طقم")).firstMatch.tap()
        let tf = app.textFields.firstMatch, sf = app.searchFields.firstMatch
        var found: XCUIElement?
        for _ in 0..<24 where found == nil {
            if tf.exists { found = tf } else if sf.exists { found = sf } else { Thread.sleep(forTimeInterval: 0.5) }
        }
        guard let input = found else { snap("04_search_missing"); return XCTFail("خانة البحث") }
        input.tap()
        input.typeText("12")
        XCTAssertTrue(anyText("لا طقم").waitForExistence(timeout: 5), "لا نتائج قبل أي بضاعة")
        snap("04_search")

        // تُغلق لوحة المفاتيح (زرّ «تم» فوقها) فيظهر الشريط السفلي. اللمس بموضعه على الشاشة:
        // `tap()` يطلب «إظهار العنصر» أولاً، ويفشل أحياناً وشريط لوحة المفاتيح ما زال يتحرّك
        let done = app.toolbars.buttons.matching(NSPredicate(format: "label IN %@", ["Done", "تم"])).firstMatch
        if done.waitForExistence(timeout: 3) {
            Thread.sleep(forTimeInterval: 0.6)
            done.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        }
        Thread.sleep(forTimeInterval: 0.8)
        if app.keyboards.firstMatch.exists {
            // لم تُغلق بعد: لمسةٌ في أعلى الشاشة (عنوانها، خارج الخانة) تُغلقها
            app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.12)).tap()
        }

        // الأزرار السفلية: الحسابات ثم الممتلكات
        let accounts = button("الحسابات")
        XCTAssertTrue(accounts.waitForExistence(timeout: 10))
        accounts.tap()
        snap("05_accounts")
        button("الممتلكات").tap()
        // 1.11: الممتلكات تبدأ بلوحة «المديونية والذهب الذي معي» (والأطقم في الرئيسية)
        XCTAssertTrue(anyText("المديونية والذهب الذي معي").waitForExistence(timeout: 10), "الممتلكات")
        snap("06_holdings")
    }
}
