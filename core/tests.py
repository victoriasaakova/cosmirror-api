from datetime import date, time
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import unquote_plus

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import (
    NatalChart,
    OnboardingSession,
    OnboardingStep,
    OnboardingStepAnswer,
    Order,
    WaitlistLead,
)
from core.services.prodamus import (
    build_checkout_payload,
    create_payment_link,
    dump_for_signature,
    sign,
    signed_checkout_url,
    verify,
    verify_webhook,
)


class ProdamusHmacTests(TestCase):
    def test_sign_is_stable_and_escapes_slashes(self):
        data = {"urlSuccess": "https://cosmirror.ru/pay/success/", "do": "link"}
        dumped = dump_for_signature(data)
        self.assertIn("\\/", dumped)
        self.assertNotIn("https://", dumped)
        secret = "test-secret"
        first = sign(data, secret)
        second = sign({"do": "link", "urlSuccess": "https://cosmirror.ru/pay/success/"}, secret)
        self.assertEqual(first, second)
        self.assertTrue(verify(data, secret, first))
        self.assertFalse(verify(data, secret, "0" * 64))

    def test_webhook_prefers_submit_and_rejects_demo_in_live(self):
        body = {
            "order_num": "abc",
            "payment_status": "success",
            "submit": {"order_num": "abc", "payment_status": "success"},
        }
        secret = "live-secret"
        live_sign = sign(body["submit"], secret)
        demo_sign = sign(body["submit"], secret + "demo")
        self.assertTrue(verify_webhook(body, secret, live_sign, allow_demo=False))
        self.assertFalse(verify_webhook(body, secret, demo_sign, allow_demo=False))
        self.assertTrue(verify_webhook(body, secret, demo_sign, allow_demo=True))


@override_settings(
    PRODAMUS_FORM_URL="https://cosmirror.payform.ru/",
    PRODAMUS_SECRET_KEY="test-secret",
    PRODAMUS_DEMO_MODE=True,
    FRONTEND_URL="http://localhost:3000",
)
class CheckoutUrlTests(TestCase):
    def test_signed_pay_url_contains_order_and_return(self):
        payload = build_checkout_payload(
            order_id="abc-123",
            product_name="Персональный разбор Cosmirror",
            product_price="777.00",
            product_sku="personal_report",
            customer_email="buyer@example.com",
            url_success="http://localhost:3000/pay/success/?order=abc-123",
            url_return="http://localhost:3000/onboarding/insight/",
            paid_content="Персональный астрологический отчёт Cosmirror. После оплаты отправим отчёт на email.",
        )
        self.assertEqual(payload["do"], "pay")
        self.assertEqual(payload["products"][0]["type"], "service")
        self.assertIn("астрологический отчёт", payload["paid_content"])
        url = signed_checkout_url(payload)
        self.assertTrue(url.startswith("https://cosmirror.payform.ru/?"))
        self.assertIn("do=pay", url)
        self.assertIn("order_id=abc-123", url)
        self.assertIn("777.00", url)
        self.assertIn("urlSuccess", url)
        self.assertIn("pay%2Fsuccess", url)
        self.assertIn("signature=", url)

    def test_discount_value_is_passed_for_promo(self):
        payload = build_checkout_payload(
            order_id="abc-123",
            product_name="Персональный разбор Cosmirror",
            product_price="777.00",
            product_sku="personal_report",
            discount_value="776",
        )
        self.assertEqual(payload["discount_value"], "776")


@override_settings(
    PRODAMUS_FORM_URL="https://cosmirror.payform.ru/",
    PRODAMUS_SECRET_KEY="test-secret",
    PRODAMUS_DEMO_MODE=True,
    FRONTEND_URL="http://localhost:3000",
)
class CheckoutLinkTests(TestCase):
    def test_create_payment_link_uses_do_pay_form(self):
        url = create_payment_link(
            order_id="abc-123",
            product_name="Персональный разбор Cosmirror",
            product_price="777.00",
            product_sku="personal_report",
            customer_email="buyer@example.com",
            paid_content="Персональный астрологический отчёт Cosmirror",
        )
        self.assertIn("do=pay", url)
        self.assertNotIn("do=link", url)
        self.assertNotIn("localhost", url)
        self.assertIn("abc-123", url)
        self.assertIn("paid_content", url)
        self.assertIn("buyer%40example.com", url)
        self.assertIn("астрологический отчёт", unquote_plus(url))
        self.assertIn("signature=", url)

    def test_short_paylink_is_stale_do_pay_is_not(self):
        from core.services.orders import _payment_url_is_stale

        self.assertFalse(
            _payment_url_is_stale(
                "https://cosmirror.payform.ru/?do=pay&order_id=1&signature=abc"
            )
        )
        self.assertTrue(_payment_url_is_stale("https://payform.ru/x/?urlSuccess=http://localhost:3000/"))
        self.assertTrue(_payment_url_is_stale("https://payform.ru/u8zDE/"))
        self.assertTrue(
            _payment_url_is_stale(
                "https://cosmirror.payform.ru/?invoice_id=abc&paylink=1"
            )
        )


@override_settings(FRONTEND_URL="http://localhost:3000")
class LocalRedirectTests(TestCase):
    def test_http_localhost_is_not_sent_to_prodamus(self):
        from core.services.orders import _return_url, _success_url
        from core.models import Order

        order = Order(public_id="00000000-0000-0000-0000-000000000001")
        self.assertEqual(_success_url(order), "")
        self.assertEqual(_return_url(), "")


@override_settings(
    PRODAMUS_FORM_URL="https://demo.payform.ru/",
    PRODAMUS_SECRET_KEY="test-secret",
    PRODAMUS_SYS="cosmirror",
    PRODAMUS_DEMO_MODE=False,
    FRONTEND_URL="http://localhost:3000",
    PUBLIC_API_URL="http://127.0.0.1:8000",
    COSMIRROR_PRODUCT_SKU="personal_report",
    COSMIRROR_PRODUCT_NAME="Персональный разбор Cosmirror",
    COSMIRROR_PRODUCT_PRICE="777",
    PRODAMUS_PROMO_DISCOUNTS="test100:776",
)
class OrderApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.lead = WaitlistLead.objects.create(
            email="buyer@example.com",
            telegram="buyername",
            name="Вика",
            phone="+79990000000",
        )
        self.session = OnboardingSession.objects.create(waitlist_lead=self.lead)

    def _create(self, key="idem-key-0001", token=None, promo="", **kwargs):
        body = {"session_token": str(token or self.session.token)}
        if promo:
            body["promo_code"] = promo
        return self.client.post(
            "/api/orders/",
            body,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
            **kwargs,
        )

    def test_requires_idempotency_key(self):
        response = self.client.post(
            "/api/orders/",
            {"session_token": str(self.session.token)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("core.services.orders.create_payment_link", return_value="https://cosmirror.payform.ru/?do=pay&signature=x")
    def test_creates_order_and_prodamus_link(self, mocked):
        response = self._create()
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["status"], "awaiting_payment")
        self.assertEqual(data["payment_url"], "https://cosmirror.payform.ru/?do=pay&signature=x")
        self.assertEqual(data["amount"], "777.00")
        order = Order.objects.get(public_id=data["id"])
        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["order_id"], str(order.public_id))
        self.assertEqual(kwargs["customer_email"], "buyer@example.com")
        self.assertEqual(kwargs["customer_phone"], "")
        self.assertIn("астрологический отчёт", kwargs["paid_content"])
        self.assertIn("астрологический отчёт", kwargs["customer_extra"].lower())
        self.assertNotIn("telegram:", kwargs["customer_extra"])
        self.assertNotIn("session:", kwargs["customer_extra"])

    @patch("core.services.orders.create_payment_link", return_value="https://cosmirror.payform.ru/?do=pay&signature=promo")
    def test_known_promo_passes_discount_value(self, mocked):
        response = self._create(key="promo-key-aaaa", promo="test100")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(mocked.call_args.kwargs["discount_value"], Decimal("776.00"))

    def test_unknown_promo_is_rejected(self):
        response = self._create(key="promo-key-bbbb", promo="no-such")
        self.assertEqual(response.status_code, 400)
        self.assertIn("промокод", response.json()["detail"].lower())

    @patch("core.services.orders.create_payment_link", return_value="https://cosmirror.payform.ru/?do=pay&signature=x")
    def test_same_idempotency_key_returns_same_order(self, mocked):
        first = self._create(key="same-key-aaaa")
        second = self._create(key="same-key-aaaa")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(mocked.call_count, 1)

    @patch(
        "core.services.orders.create_payment_link",
        side_effect=[
            "https://cosmirror.payform.ru/?do=pay&signature=old",
            "https://cosmirror.payform.ru/?do=pay&signature=fresh",
        ],
    )
    def test_awaiting_link_is_reissued_after_retry_window(self, mocked):
        from datetime import timedelta

        from django.utils import timezone

        first = self._create(key="retry-key-aaaa")
        self.assertEqual(first.status_code, 201)
        order = Order.objects.get(public_id=first.json()["id"])
        Order.objects.filter(pk=order.pk).update(
            updated_at=timezone.now() - timedelta(minutes=2)
        )
        again = self._create(key="retry-key-aaaa")
        self.assertEqual(again.status_code, 201, again.content)
        self.assertNotEqual(first.json()["id"], again.json()["id"])
        self.assertEqual(again.json()["payment_url"], "https://cosmirror.payform.ru/?do=pay&signature=fresh")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELED)
        self.assertEqual(mocked.call_count, 2)

    @patch("core.services.orders.create_payment_link", return_value="https://cosmirror.payform.ru/?do=pay&order_id=new&signature=x")
    def test_stale_short_link_is_rebuilt(self, mocked):
        first = self._create(key="rebuild-key-1")
        self.assertEqual(first.status_code, 201)
        order = Order.objects.get(public_id=first.json()["id"])
        order.payment_url = "https://payform.ru/u8zDE/"
        order.save(update_fields=["payment_url"])
        mocked.reset_mock()
        again = self._create(key="rebuild-key-1")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(
            again.json()["payment_url"],
            "https://cosmirror.payform.ru/?do=pay&order_id=new&signature=x",
        )
        mocked.assert_called_once()

    @patch("core.services.orders.create_payment_link", return_value="https://cosmirror.payform.ru/?do=pay&signature=x")
    def test_same_key_different_session_conflicts(self, _mocked):
        other = OnboardingSession.objects.create(
            waitlist_lead=WaitlistLead.objects.create(email="other@example.com")
        )
        first = self._create(key="shared-key-1")
        self.assertEqual(first.status_code, 201)
        conflict = self._create(key="shared-key-1", token=other.token)
        self.assertEqual(conflict.status_code, 409)

    @patch("core.services.orders.create_payment_link", return_value="https://cosmirror.payform.ru/?do=pay&signature=paid")
    def test_paid_order_is_reused_without_new_prodamus_call(self, mocked):
        created = self._create(key="pay-once-key")
        order = Order.objects.get(public_id=created.json()["id"])
        order.status = Order.Status.PAID
        order.save(update_fields=["status"])
        mocked.reset_mock()
        again = self._create(key="another-key-zz")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["id"], created.json()["id"])
        mocked.assert_not_called()


@override_settings(
    PRODAMUS_FORM_URL="https://demo.payform.ru/",
    PRODAMUS_SECRET_KEY="test-secret",
    PRODAMUS_DEMO_MODE=False,
)
class ProdamusWebhookTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        lead = WaitlistLead.objects.create(email="buyer@example.com")
        session = OnboardingSession.objects.create(waitlist_lead=lead)
        self.order = Order.objects.create(
            idempotency_key="wh-key-0001",
            idempotency_request_hash="a" * 64,
            session=session,
            waitlist_lead=lead,
            customer_email="buyer@example.com",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.AWAITING_PAYMENT,
            payment_url="https://payform.ru/u8zDE/",
        )

    def _payload(self, status="success"):
        submit = {
            "date": "2026-08-14T12:00:00+03:00",
            "order_id": "300155",
            "order_num": str(self.order.public_id),
            "sum": "777.00",
            "currency": "rub",
            "payment_status": status,
            "payment_status_description": "Успешная оплата",
            "payment_init": "manual",
        }
        return {**submit, "submit": submit}

    @patch("core.services.fulfillment.deliver_paid_order")
    def test_success_marks_paid(self, mocked_deliver):
        payload = self._payload()
        signature = sign(payload["submit"], "test-secret")
        response = self.client.post(
            "/api/payments/prodamus/webhook/",
            payload,
            format="json",
            HTTP_SIGN=signature,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.order.prodamus_order_id, "300155")
        self.assertIsNotNone(self.order.paid_at)
        mocked_deliver.assert_called_once()

        again = self.client.post(
            "/api/payments/prodamus/webhook/",
            payload,
            format="json",
            HTTP_SIGN=signature,
        )
        self.assertEqual(again.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        mocked_deliver.assert_called_once()

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        RESEND_API_KEY="",
    )
    def test_paid_order_sends_demo_report_once(self):
        from django.core import mail
        from core.services.fulfillment import deliver_paid_order

        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        self.assertTrue(deliver_paid_order(self.order))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Персональный астрологический отчёт", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["buyer@example.com"])
        self.assertTrue(mail.outbox[0].attachments)
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.fulfilled_at)
        self.assertFalse(deliver_paid_order(self.order))
        self.assertEqual(len(mail.outbox), 1)

    def test_bad_signature_rejected(self):
        response = self.client.post(
            "/api/payments/prodamus/webhook/",
            self._payload(),
            format="json",
            HTTP_SIGN="ab" * 32,
        )
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)

    def test_get_order(self):
        response = self.client.get(f"/api/orders/{self.order.public_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.order.public_id))
        self.assertIsNone(response.json()["report"])


@override_settings(
    FRONTEND_URL="https://cosmirror.ru",
    PUBLIC_API_URL="https://api.cosmirror.ru",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RESEND_API_KEY="",
)
class PaidReportTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        lead = WaitlistLead.objects.create(email="wrong@example.com", name="Вика")
        session = OnboardingSession.objects.create(
            waitlist_lead=lead,
            birth_date=date(1993, 8, 21),
            birth_time=time(9, 45),
            birth_place="Москва",
            timezone="Europe/Moscow",
        )
        natal = {
            "engine": "swiss_ephemeris",
            "has_birth_time": True,
            "timezone": "Europe/Moscow",
            "location": {"place": "Москва", "lat": 55.75, "lng": 37.61},
            "planets": {
                "sun": {
                    "sign": "leo",
                    "sign_ru": "Лев",
                    "degree": 28.1,
                    "sign_index": 4,
                    "house": 10,
                },
                "moon": {
                    "sign": "capricorn",
                    "sign_ru": "Козерог",
                    "degree": 12.0,
                    "sign_index": 9,
                    "house": 3,
                },
            },
            "ascendant": {"sign": "scorpio", "sign_ru": "Скорпион", "degree": 5.0, "sign_index": 7},
            "houses": [
                {"house": i + 1, "sign": "scorpio", "sign_ru": "Скорпион"}
                for i in range(12)
            ],
        }
        NatalChart.objects.create(
            session=session,
            birth_date=date(1993, 8, 21),
            birth_time=time(9, 45),
            birth_place="Москва",
            status=NatalChart.Status.READY,
            chart_data=natal,
        )
        self.order = Order.objects.create(
            idempotency_key="report-key-0001",
            idempotency_request_hash="b" * 64,
            session=session,
            waitlist_lead=lead,
            customer_email="wrong@example.com",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.AWAITING_PAYMENT,
        )

    def test_success_and_fail_redirects(self):
        from core.services.orders import _return_url, _success_url

        self.assertIn("/report/?order=", _success_url(self.order))
        self.assertIn("/pay/failed/?order=", _return_url(self.order))

    def test_paid_report_pdf_and_email_fix(self):
        from django.core import mail

        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        detail = self.client.get(f"/api/orders/{self.order.public_id}/")
        self.assertEqual(detail.status_code, 200)
        report = detail.json()["report"]
        self.assertIn("Солнце", report["sections"][1]["title"])
        self.assertTrue(any(block["title"].startswith("1-й дом") for block in report["sections"][2]["blocks"]))

        pdf = self.client.get(f"/api/orders/{self.order.public_id}/report.pdf/")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))

        response = self.client.post(
            f"/api/orders/{self.order.public_id}/email/",
            {"email": "right@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.customer_email, "right@example.com")
        self.assertIsNotNone(self.order.fulfilled_at)
        self.assertEqual(mail.outbox[-1].to, ["right@example.com"])
        self.assertTrue(mail.outbox[-1].attachments)

    def test_pdf_forbidden_until_paid(self):
        response = self.client.get(f"/api/orders/{self.order.public_id}/report.pdf/")
        self.assertEqual(response.status_code, 403)


class OnboardingEmailSourceTests(TestCase):
    def test_contacts_step_email_wins_over_old_lead(self):
        from core.services.orders import _contacts

        lead = WaitlistLead.objects.create(email="old@icloud.com", telegram="victoriss")
        session = OnboardingSession.objects.create(waitlist_lead=lead)
        step = OnboardingStep.objects.create(
            slug="contacts",
            title="Контакты",
            step_type=OnboardingStep.StepType.WAITLIST,
            order=1,
        )
        OnboardingStepAnswer.objects.create(
            session=session,
            step=step,
            completed=True,
            payload={"email": "saakovka@gmail.com", "telegram": "victoriss"},
        )
        email, _phone, telegram = _contacts(session)
        self.assertEqual(email, "saakovka@gmail.com")
        self.assertEqual(telegram, "victoriss")

    @override_settings(
        PRODAMUS_FORM_URL="https://demo.payform.ru/",
        PRODAMUS_SECRET_KEY="test-secret",
        FRONTEND_URL="http://localhost:3000",
        COSMIRROR_PRODUCT_PRICE="777",
    )
    @patch(
        "core.services.orders.create_payment_link",
        return_value="https://cosmirror.payform.ru/?do=pay&signature=fresh",
    )
    def test_resume_rebuilds_link_when_onboarding_email_changed(self, mocked):
        from core.services.orders import _request_hash

        lead = WaitlistLead.objects.create(email="old@icloud.com", telegram="victoriss")
        session = OnboardingSession.objects.create(waitlist_lead=lead)
        step = OnboardingStep.objects.create(
            slug="contacts",
            title="Контакты",
            step_type=OnboardingStep.StepType.WAITLIST,
            order=1,
        )
        OnboardingStepAnswer.objects.create(
            session=session,
            step=step,
            completed=True,
            payload={"email": "saakovka@gmail.com", "telegram": "victoriss"},
        )
        order = Order.objects.create(
            idempotency_key="email-sync-key-01",
            idempotency_request_hash=_request_hash(str(session.token), "personal_report", ""),
            session=session,
            waitlist_lead=lead,
            customer_email="old@icloud.com",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.AWAITING_PAYMENT,
            payment_url="https://cosmirror.payform.ru/?do=pay&signature=old",
        )
        client = APIClient()
        response = client.post(
            "/api/orders/",
            {"session_token": str(session.token)},
            format="json",
            HTTP_IDEMPOTENCY_KEY="email-sync-key-01",
        )
        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual(order.customer_email, "saakovka@gmail.com")
        self.assertEqual(mocked.call_args.kwargs["customer_email"], "saakovka@gmail.com")
        self.assertEqual(
            order.payment_url,
            "https://cosmirror.payform.ru/?do=pay&signature=fresh",
        )
