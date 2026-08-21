from datetime import date, time
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, unquote_plus, urlencode, urlparse

from django.contrib.auth.models import User
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
    flatten_php,
    sign,
    signed_checkout_url,
    verify,
    verify_webhook,
)
from core.services.yandex_oauth import issue_auth_token


def _make_user(*, email="buyer@example.com", yandex_id="1000034426"):
    user = User.objects.create_user(
        username=f"yandex_{yandex_id}_{email.split('@')[0]}"[:150],
        email=email,
    )
    user.set_unusable_password()
    user.save()
    user.profile.yandex_id = yandex_id
    user.profile.save(update_fields=["yandex_id"])
    token = issue_auth_token(user)
    return user, token.key


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
        self.assertNotIn("callbackType", payload)
        self.assertNotIn("payments_limit", payload)
        self.assertNotIn("currency", payload)
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
        self.assertFalse(
            _payment_url_is_stale(
                "https://cosmirror.payform.ru/?do=pay&urlSuccess=http://localhost:3000/report/x/"
            )
        )
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
        self.assertEqual(_return_url(order), "")

    def test_report_email_link_stays_on_localhost(self):
        from core.services.report import report_page_url
        from core.models import Order

        order = Order(public_id="00000000-0000-0000-0000-000000000001")
        self.assertEqual(
            report_page_url(order),
            "http://localhost:3000/account/",
        )


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
        self.user, self.auth_key = _make_user()
        self.lead = WaitlistLead.objects.create(
            email="buyer@example.com",
            telegram="buyername",
            name="Вика",
            phone="+79990000000",
            user=self.user,
        )
        self.session = OnboardingSession.objects.create(
            waitlist_lead=self.lead,
            user=self.user,
        )

    def _create(self, key="idem-key-0001", token=None, promo="", auth_key=None, **kwargs):
        body = {"session_token": str(token or self.session.token)}
        if promo:
            body["promo_code"] = promo
        headers = {
            "HTTP_IDEMPOTENCY_KEY": key,
            "HTTP_AUTHORIZATION": f"Bearer {auth_key or self.auth_key}",
        }
        headers.update(kwargs)
        return self.client.post(
            "/api/orders/",
            body,
            format="json",
            **headers,
        )

    def test_requires_auth(self):
        response = self.client.post(
            "/api/orders/",
            {"session_token": str(self.session.token)},
            format="json",
            HTTP_IDEMPOTENCY_KEY="no-auth-key-01",
        )
        self.assertEqual(response.status_code, 401)

    def test_requires_idempotency_key(self):
        response = self.client.post(
            "/api/orders/",
            {"session_token": str(self.session.token)},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.auth_key}",
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
        other_user, other_key = _make_user(email="other@example.com", yandex_id="2002")
        other = OnboardingSession.objects.create(
            waitlist_lead=WaitlistLead.objects.create(
                email="other@example.com",
                telegram="othername",
                user=other_user,
            ),
            user=other_user,
        )
        first = self._create(key="shared-key-1")
        self.assertEqual(first.status_code, 201)
        conflict = self._create(key="shared-key-1", token=other.token, auth_key=other_key)
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
        self.assertEqual(response.content, b"success")
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
        self.assertEqual(again.content, b"success")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        mocked_deliver.assert_called_once()

    @patch("core.services.fulfillment.deliver_paid_order")
    def test_form_urlencoded_and_noslash_mark_paid(self, mocked_deliver):
        payload = self._payload()
        signature = sign(payload["submit"], "test-secret")
        body = urlencode(flatten_php(payload), doseq=True)
        response = self.client.post(
            "/api/payments/prodamus/webhook",
            body,
            content_type="application/x-www-form-urlencoded",
            HTTP_SIGN=signature,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.content, b"success")
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

    def test_get_order_requires_owner(self):
        response = self.client.get(f"/api/orders/{self.order.public_id}/")
        self.assertEqual(response.status_code, 401)

        owner, key = _make_user(email="buyer@example.com", yandex_id="3003")
        self.order.user = owner
        self.order.session.user = owner
        self.order.session.save(update_fields=["user"])
        self.order.save(update_fields=["user"])
        response = self.client.get(
            f"/api/orders/{self.order.public_id}/",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.order.public_id))
        self.assertIsNone(response.json()["report"])
        self.assertNotIn("customer_email", response.json())


@override_settings(
    FRONTEND_URL="https://cosmirror.ru",
    PUBLIC_API_URL="https://api.cosmirror.ru",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RESEND_API_KEY="",
)
class PaidReportTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user, self.auth_key = _make_user(email="wrong@example.com", yandex_id="4004")
        lead = WaitlistLead.objects.create(
            email="wrong@example.com",
            name="Вика",
            telegram="vikatelegram",
            user=self.user,
        )
        session = OnboardingSession.objects.create(
            waitlist_lead=lead,
            user=self.user,
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
            user=self.user,
            customer_email="wrong@example.com",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.AWAITING_PAYMENT,
        )

    def _auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.auth_key}"}

    def test_success_and_fail_redirects(self):
        from core.services.orders import _return_url, _success_url

        self.assertIn("/account/", _success_url(self.order))
        self.assertIn("from=prodamus", _success_url(self.order))
        self.assertNotIn(str(self.order.public_id), _success_url(self.order))
        self.assertEqual(_return_url(self.order), "https://cosmirror.ru/pay/failed/")

    def test_paid_report_pdf_and_email_fix(self):
        from django.core import mail

        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        detail = self.client.get(f"/api/orders/{self.order.public_id}/", **self._auth())
        self.assertEqual(detail.status_code, 200)
        report = detail.json()["report"]
        self.assertEqual(report["schema_version"], 3)
        self.assertIn("document", report)
        self.assertNotIn("person", report)
        self.assertNotIn("customer_email", detail.json())
        self.assertNotIn("name", report["document"].get("quiz") or {})
        self.assertNotIn("payload", report["document"].get("generation") or {})
        section_ids = [section["id"] for section in report["sections"]]
        self.assertEqual(
            section_ids,
            ["natal", "cycles", "request", "summary"],
        )
        natal_section = next(section for section in report["sections"] if section["id"] == "natal")
        self.assertTrue(any("Солнце" in block["title"] for block in natal_section["blocks"]))
        self.assertTrue(any(block["title"].startswith("1-й дом") for block in natal_section["blocks"]))
        self.assertFalse(any(block["title"] == "Исходные данные" for block in natal_section["blocks"]))
        self.assertTrue(report["document"]["factual"]["natal"].get("wheel", {}).get("planets"))
        self.assertEqual(report["document"]["generation"]["system_prompt_id"], "paid_report")
        self.assertEqual(report["document"]["interpretive"]["status"], "pending_llm")

        pdf = self.client.get(f"/api/orders/{self.order.public_id}/report.pdf/", **self._auth())
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertNotIn(b"1993", pdf.content)

        response = self.client.post(
            f"/api/orders/{self.order.public_id}/email/",
            {"email": "right@example.com"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.customer_email, "right@example.com")
        self.assertIsNotNone(self.order.fulfilled_at)
        self.assertEqual(mail.outbox[-1].to, ["right@example.com"])
        self.assertTrue(mail.outbox[-1].attachments)
        html = mail.outbox[-1].alternatives[0][0]
        self.assertIn("Привет, Вика", html)
        self.assertIn("Открыть отчёт", html)
        self.assertIn("/account/", html)
        self.assertIn("на сайте Cosmirror", html)
        self.assertIn('href="https://cosmirror.ru/account/"', html)
        self.assertNotIn(str(self.order.public_id), html)
        self.assertNotIn("Если это не та почта", html)
        self.assertNotIn("укажи другой адрес", html)

    def test_pdf_forbidden_until_paid(self):
        response = self.client.get(
            f"/api/orders/{self.order.public_id}/report.pdf/",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(DEBUG=True, PRODAMUS_DEMO_MODE=True)
    def test_demo_complete_marks_paid_after_checkout(self):
        from django.core import mail

        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)
        self.assertIsNone(self.order.fulfilled_at)
        response = self.client.post(
            f"/api/orders/{self.order.public_id}/demo-complete/",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertIsNotNone(self.order.fulfilled_at)
        self.assertTrue(mail.outbox)
        self.assertIn("Открыть отчёт", mail.outbox[-1].alternatives[0][0])


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
        user, auth_key = _make_user(email="saakovka@gmail.com", yandex_id="5005")
        session.user = user
        session.save(update_fields=["user"])
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
            user=user,
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
            HTTP_AUTHORIZATION=f"Bearer {auth_key}",
        )
        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual(order.customer_email, "saakovka@gmail.com")
        self.assertEqual(mocked.call_args.kwargs["customer_email"], "saakovka@gmail.com")
        self.assertEqual(
            order.payment_url,
            "https://cosmirror.payform.ru/?do=pay&signature=fresh",
        )


def _funnel_insight(**overrides):
    cards = [
        {"key": "natal", "label": "Натал", "before": "1", "after": "2"},
        {"key": "cycles", "label": "Циклы", "before": "1", "after": "2"},
        {"key": "tension", "label": "Напряжение", "before": "1", "after": "2"},
        {"key": "focus", "label": "Фокус", "before": "1", "after": "2"},
    ]
    data = {
        "funnel_version": 5,
        "source": "polza",
        "opening": {"bridge": "сейчас важно", "insight": "выйти из тесной роли"},
        "body": "Первое предложение. Второе предложение про паттерн и выбор сейчас.",
        "product_pitch": {
            "title": "Стань ближе к своему истинному я через подробный разбор",
            "text": "Разберём основу и космопортрет.\nСоединим запрос с текущими циклами.",
        },
        "outcomes": {"title": "Что ты поймёшь после разбора", "cards": cards},
        "offer": {"title": "Стань ближе к своему истинному я через подробный разбор"},
    }
    data.update(overrides)
    return data


class InsightPersonalizeTests(TestCase):
    def test_llm_first_pass_is_ready_without_editorial(self):
        from core.services.personalize import insight_is_ready, is_personalized

        insight = _funnel_insight()
        self.assertTrue(is_personalized(insight))
        self.assertTrue(insight_is_ready(insight))

    @override_settings(POLZA_API_KEY="test-key", GROQ_API_KEY="")
    def test_templates_are_not_ready_until_attempt_finishes(self):
        from core.services.personalize import insight_is_ready, is_personalized

        insight = _funnel_insight(source="templates")
        self.assertFalse(is_personalized(insight))
        self.assertFalse(insight_is_ready(insight))
        insight["personalize_attempted"] = True
        self.assertTrue(insight_is_ready(insight))

    @override_settings(POLZA_API_KEY="test-key", GROQ_API_KEY="")
    @patch("core.services.personalize.editorial.edit_user_facing_texts")
    @patch("core.services.personalize.llm_client.chat_json")
    def test_personalize_does_not_call_editorial(self, chat_json, edit):
        from core.services.personalize import personalize_insight

        chat_json.return_value = _funnel_insight()
        result = personalize_insight(
            insight={"influences": [], "cycles": [], "disclaimer": ""},
            natal={"planets": {}, "has_birth_time": False},
            quiz={},
        )
        edit.assert_not_called()
        chat_json.assert_called_once()
        self.assertTrue(result.get("editorial_passed"))
        self.assertEqual(result.get("source"), "polza")


class ReportBlueprintTests(TestCase):
    def test_uranus_sun_conjunction_is_primary_and_prompt_exists(self):
        from core.services.report_blueprint import build_report_document, load_paid_report_prompt
        from core.services.report_facts import transits_now

        natal = {
            "engine": "swiss_ephemeris",
            "has_birth_time": True,
            "planets": {
                "sun": {"sign": "leo", "sign_ru": "Лев", "sign_index": 4, "degree": 6.0, "house": 10},
                "moon": {"sign": "capricorn", "sign_ru": "Козерог", "sign_index": 9, "degree": 12.0, "house": 4},
                "venus": {"sign": "virgo", "sign_ru": "Дева", "sign_index": 5, "degree": 2.0, "house": 11},
                "mars": {"sign": "gemini", "sign_ru": "Близнецы", "sign_index": 2, "degree": 8.0, "house": 8},
                "pluto": {"sign": "scorpio", "sign_ru": "Скорпион", "sign_index": 7, "degree": 6.2, "house": 1},
            },
            "ascendant": {"sign": "scorpio", "sign_ru": "Скорпион", "sign_index": 7, "degree": 5.0},
            "houses": [
                {"house": i + 1, "sign": "scorpio", "sign_ru": "Скорпион"}
                for i in range(12)
            ],
        }
        sky = {
            "datetime_utc": "2026-08-17T12:00:00Z",
            "planets": {
                "sun": {"sign": "leo", "sign_ru": "Лев", "sign_index": 4, "degree": 24.0, "speed": 0.97},
                "uranus": {"sign": "leo", "sign_ru": "Лев", "sign_index": 4, "degree": 6.4, "speed": 0.014},
                "neptune": {"sign": "aries", "sign_ru": "Овен", "sign_index": 0, "degree": 4.0, "speed": 0.006},
                "pluto": {"sign": "aquarius", "sign_ru": "Водолей", "sign_index": 10, "degree": 4.8, "speed": 0.004},
                "jupiter": {"sign": "cancer", "sign_ru": "Рак", "sign_index": 3, "degree": 12.0, "speed": 0.12},
            },
        }
        hits = transits_now(natal, sky)
        uranus_sun = next(hit for hit in hits if hit["id"] == "t_uranus_conjunction_sun")
        self.assertLess(uranus_sun["orb"], 0.5)
        self.assertEqual(uranus_sun["polarity"], "pressure")

        document = build_report_document(
            natal=natal,
            sky_now=sky,
            quiz={
                "focus": ["path", "confidence"],
                "life_stage": "many-spheres",
                "intent": "life-stage",
                "chart_knowledge": "sun-only",
                "astrology_trigger": "understand-self",
            },
            person={"name": "Вика"},
        )
        primary = document["accents"]["primary"][0]
        self.assertEqual(primary["transit"], "uranus")
        self.assertEqual(primary["natal"], "sun")
        self.assertEqual(document["accents"]["through_line"]["transit"], "uranus")
        self.assertEqual(document["quiz"]["knowledge_depth"], "explain_all")
        payload = document["generation"]["payload"]
        self.assertEqual(payload["task"], "generate_paid_report")
        self.assertTrue(payload["rules"]["no_predictions"])
        self.assertIn("cycles", payload["output"]["sections"])
        self.assertIn("summary", payload["output"]["sections"])
        self.assertTrue(document["factual"]["natal"]["wheel"]["planets"])
        prompt = load_paid_report_prompt()
        self.assertIn("сквозная линия", prompt.lower())
        self.assertIn("Не пересчитывай небо", prompt)


class SwissPlacidusTests(TestCase):
    def test_placidus_returns_twelve_cusps(self):
        from datetime import date, time

        from core.services.swiss_engine import calculate_natal

        natal = calculate_natal(
            birth_date=date(1995, 5, 26),
            birth_time=time(19, 25),
            latitude=54.516498,
            longitude=18.540274,
            timezone_name="Europe/Warsaw",
            place="Gdynia",
        )
        self.assertEqual(natal["house_system"], "placidus")
        self.assertEqual(len(natal["houses"]), 12)
        self.assertAlmostEqual(natal["houses"][0]["cusp_longitude"], natal["ascendant"]["longitude"], places=2)
        self.assertIn(natal["planets"]["sun"]["house"], range(1, 13))


@override_settings(
    YANDEX_OAUTH_CLIENT_ID="test-client",
    YANDEX_OAUTH_CLIENT_SECRET="test-secret",
    YANDEX_OAUTH_REDIRECT_URI="http://localhost:3000/onboarding/contacts/",
    FRONTEND_URL="http://localhost:3000",
    PUBLIC_API_URL="http://127.0.0.1:8000",
    CORS_ALLOWED_ORIGINS=["http://localhost:3000"],
)
class YandexAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.session = OnboardingSession.objects.create()
        OnboardingStep.objects.create(
            slug="contacts",
            title="Контакты",
            step_type=OnboardingStep.StepType.WAITLIST,
            order=1,
        )

    def test_start_returns_authorize_url(self):
        response = self.client.get(
            "/api/auth/yandex/start/",
            {"session_token": str(self.session.token)},
        )
        self.assertEqual(response.status_code, 200)
        url = response.json()["url"]
        self.assertIn("oauth.yandex.ru/authorize", url)
        self.assertIn("client_id=test-client", url)
        self.assertIn("code_challenge", url)
        query = parse_qs(urlparse(url).query)
        self.assertNotIn("scope", query)
        redirect = query["redirect_uri"][0]
        self.assertEqual(redirect, "http://localhost:3000/onboarding/contacts")
        self.assertEqual(response.json()["redirect_uri"], redirect)

    def test_start_uses_page_redirect_without_trailing_slash(self):
        response = self.client.get(
            "/api/auth/yandex/start/",
            {
                "session_token": str(self.session.token),
                "redirect_uri": "http://localhost:3000/onboarding/contacts/",
            },
        )
        self.assertEqual(response.status_code, 200)
        redirect = parse_qs(urlparse(response.json()["url"]).query)["redirect_uri"][0]
        self.assertEqual(redirect, "http://localhost:3000/onboarding/contacts")

    def test_start_rejects_foreign_redirect(self):
        response = self.client.get(
            "/api/auth/yandex/start/",
            {
                "session_token": str(self.session.token),
                "redirect_uri": "https://evil.example/onboarding/contacts",
            },
        )
        self.assertEqual(response.status_code, 200)
        redirect = parse_qs(urlparse(response.json()["url"]).query)["redirect_uri"][0]
        self.assertEqual(redirect, "http://localhost:3000/onboarding/contacts")

    @patch("core.services.yandex_oauth._get_json")
    @patch("core.services.yandex_oauth._post_form")
    def test_callback_creates_user_and_attaches_session(self, post_form, get_json):
        from core.models import YandexOAuthState

        YandexOAuthState.objects.create(
            nonce="state-1",
            session=self.session,
            code_verifier="verifier",
            redirect_uri="http://localhost:3000/onboarding/contacts",
        )
        post_form.return_value = {"access_token": "ya-token"}
        get_json.return_value = {
            "id": "42",
            "login": "ivan",
            "default_email": "ivan@yandex.ru",
            "first_name": "Иван",
            "last_name": "Иванов",
            "display_name": "Иван",
        }
        response = self.client.post(
            "/api/auth/yandex/callback/",
            {"code": "1234567", "state": "state-1"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            post_form.call_args[0][1]["redirect_uri"],
            "http://localhost:3000/onboarding/contacts",
        )
        data = response.json()
        self.assertTrue(data["token"])
        self.session.refresh_from_db()
        self.assertEqual(self.session.user.email, "ivan@yandex.ru")
        self.assertEqual(self.session.user.profile.yandex_id, "42")
        self.assertEqual(self.session.waitlist_lead.email, "ivan@yandex.ru")
        me = self.client.get("/api/me/", HTTP_AUTHORIZATION=f"Bearer {data['token']}")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "ivan@yandex.ru")
        report = self.client.get(
            "/api/me/report/",
            HTTP_AUTHORIZATION=f"Bearer {data['token']}",
        )
        self.assertEqual(report.status_code, 404)

    @patch("core.services.yandex_oauth._get_json")
    @patch("core.services.yandex_oauth._post_form")
    def test_yandex_get_callback_redirects_to_insight(self, post_form, get_json):
        from core.models import YandexOAuthState

        YandexOAuthState.objects.create(
            nonce="state-2",
            session=self.session,
            code_verifier="verifier",
            redirect_uri="http://localhost:3000/onboarding/contacts",
        )
        post_form.return_value = {"access_token": "ya-token"}
        get_json.return_value = {
            "id": "99",
            "login": "anna",
            "default_email": "anna@yandex.ru",
            "display_name": "Анна",
        }
        response = self.client.get(
            "/api/auth/yandex/callback/",
            {"code": "999", "state": "state-2"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/onboarding/insight/", response["Location"])
        self.assertIn("#auth=", response["Location"])



