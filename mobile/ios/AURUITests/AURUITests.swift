import XCTest

/// تجربة ÀUR على محاكي الآيفون: يفتح، ثم الترحيب ← الرئيسية ولوحاتها ← البحث عن طقم
/// ← الحسابات والممتلكات، مع صورةٍ لكل خطوة (تُرفق بنتيجة التجربة).
final class AURUITests: XCTestCase {
    var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
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

    /// أول تشغيل: رسالة موافقة الإعلانات من Google (UMP) ثم سؤال iOS عن التتبّع — حيث
    /// يُعدّها حساب AdMob. «متابعة» ثم «اطلب من التطبيق عدم التتبّع»؛ والتطبيق يعمل في الحالين.
    func passConsent() {
        let cont = app.buttons.matching(NSPredicate(format: "label IN %@", ["Continue", "متابعة"])).firstMatch
        guard cont.waitForExistence(timeout: 25) else { return }
        snap("00_consent")
        cont.tap()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let deny = springboard.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@ OR label CONTAINS %@",
                                                            "Not to Track", "عدم التتبع")).firstMatch
        if deny.waitForExistence(timeout: 10) {
            snap("00_tracking")
            deny.tap()
        }
    }

    func testLaunchHomeSearchAndTabs() throws {
        // أول تشغيل: شاشة الترحيب باسم التطبيق وزرّي مجلد الحفظ
        XCTAssertTrue(anyText("ÀUR").waitForExistence(timeout: 30), "الترحيب باسم ÀUR")
        passConsent()
        XCTAssertTrue(button("اختر مجلد الحفظ").exists, "زرّ مجلد الحفظ التلقائي")
        snap("01_welcome")
        button("تخط").tap()

        // الرئيسية: لوحات العمليات وكشف الحساب والبحث
        XCTAssertTrue(button("بيع للعميل").waitForExistence(timeout: 15), "لوحة «بيع للعميل»")
        XCTAssertTrue(button("تحصيل من العميل").exists)
        XCTAssertTrue(button("كشف حساب").exists)
        XCTAssertTrue(button("بحث عن طقم").exists)
        snap("02_home")

        // البحث عن طقم: الخانة جاهزة، ورقمٌ بلا أطقمٍ بعدُ ⇒ «لا طقم»
        button("بحث عن طقم").tap()
        let field = app.textFields.firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 10), "خانة البحث")
        field.tap()
        field.typeText("12")
        XCTAssertTrue(anyText("لا طقم").waitForExistence(timeout: 5), "لا نتائج قبل أي بضاعة")
        snap("03_search")

        // تُغلق لوحة المفاتيح (زرّ «تم» فوقها) فيظهر الشريط السفلي
        let done = app.toolbars.buttons.matching(NSPredicate(format: "label IN %@", ["Done", "تم"])).firstMatch
        if done.exists { done.tap() }

        // الأزرار السفلية: الحسابات ثم الممتلكات
        let accounts = button("الحسابات")
        XCTAssertTrue(accounts.waitForExistence(timeout: 10))
        accounts.tap()
        snap("04_accounts")
        button("الممتلكات").tap()
        XCTAssertTrue(anyText("الأطقم التي معي").waitForExistence(timeout: 10), "الممتلكات")
        snap("05_holdings")
    }
}
