import json
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, unquote_plus, urlencode, urlparse

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    AuthToken,
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
    parse_checkout_return,
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
    PRODAMUS_FORM_URL="https://demo.payform.ru/",
    PRODAMUS_SECRET_KEY="test-secret",
    PRODAMUS_DEMO_MODE=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RESEND_API_KEY="",
)
class CheckoutReturnConfirmTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user, self.auth_key = _make_user(email="return@example.com", yandex_id="5105")
        lead = WaitlistLead.objects.create(email="return@example.com")
        session = OnboardingSession.objects.create(waitlist_lead=lead, user=self.user)
        self.order = Order.objects.create(
            idempotency_key="return-key-0001",
            idempotency_request_hash="c" * 64,
            session=session,
            waitlist_lead=lead,
            user=self.user,
            customer_email="return@example.com",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.AWAITING_PAYMENT,
        )

    def _auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.auth_key}"}

    def test_parse_underscore_payform_keys(self):
        parsed = parse_checkout_return(
            {
                "_payform_status": "success",
                "_payform_id": "48103246",
                "_payform_order_id": str(self.order.public_id),
            }
        )
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["payform_id"], "48103246")
        self.assertEqual(parsed["order_ref"], str(self.order.public_id))

    @patch("core.services.fulfillment.deliver_paid_order")
    def test_success_return_marks_paid(self, mocked_deliver):
        response = self.client.post(
            "/api/me/report/confirm-payment/",
            {
                "_payform_status": "success",
                "_payform_id": "48103246",
                "_payform_order_id": str(self.order.public_id),
            },
            format="json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "paid")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.order.prodamus_order_id, "48103246")
        mocked_deliver.assert_called_once()

        again = self.client.post(
            "/api/me/report/confirm-payment/",
            {
                "payform_status": "success",
                "payform_id": "48103246",
                "payform_order_id": str(self.order.public_id),
            },
            format="json",
            **self._auth(),
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["status"], "paid")
        mocked_deliver.assert_called_once()

    def test_from_prodamus_without_success_does_not_mark_paid(self):
        response = self.client.post(
            "/api/me/report/confirm-payment/",
            {"from": "prodamus"},
            format="json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "awaiting_payment")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)

    def test_success_without_payform_id_does_not_mark_paid(self):
        response = self.client.post(
            "/api/me/report/confirm-payment/",
            {
                "_payform_status": "success",
                "_payform_order_id": str(self.order.public_id),
            },
            format="json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)

    def test_wrong_order_is_rejected(self):
        other = "00000000-0000-0000-0000-000000000099"
        response = self.client.post(
            "/api/me/report/confirm-payment/",
            {
                "_payform_status": "success",
                "_payform_id": "48103246",
                "_payform_order_id": other,
            },
            format="json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 404)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)

    def test_requires_auth(self):
        response = self.client.post(
            "/api/me/report/confirm-payment/",
            {
                "_payform_status": "success",
                "_payform_id": "48103246",
                "_payform_order_id": str(self.order.public_id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 401)


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
        self.assertEqual(report["schema_version"], 4)
        self.assertIn("document", report)
        person = report["person"]
        self.assertEqual(person["birth_date"], "1993-08-21")
        self.assertEqual(person["birth_time"], "09:45")
        self.assertEqual(person["birth_place"], "Москва")
        self.assertTrue(person["has_birth_time"])
        self.assertNotIn("name", person)
        self.assertNotIn("customer_email", detail.json())
        self.assertNotIn("name", report["document"].get("quiz") or {})
        self.assertNotIn("payload", report["document"].get("generation") or {})
        section_ids = [section["id"] for section in report["sections"]]
        self.assertEqual(
            section_ids,
            ["natal", "aspects", "cycles", "request", "practice"],
        )
        natal_section = next(section for section in report["sections"] if section["id"] == "natal")
        self.assertTrue(
            any("Солнце" in (block.get("title") or "") or "Солнце" in (block.get("text") or "") for block in natal_section["blocks"])
        )
        self.assertTrue(any(block["title"].startswith("1-й дом") for block in natal_section["blocks"]))
        self.assertFalse(any(block["title"] == "Исходные данные" for block in natal_section["blocks"]))
        self.assertTrue(report["document"]["factual"]["natal"].get("wheel", {}).get("planets"))
        self.assertEqual(report["document"]["generation"]["system_prompt_id"], "paid_report")
        self.assertEqual(report["document"]["interpretive"]["status"], "fallback")
        natal_layer = report["document"]["interpretive"]["natal"]
        self.assertEqual(natal_layer["source"], "fallback")
        self.assertIn("core_portrait", natal_layer["payload"])
        self.assertIn("big_three", natal_layer["payload"])
        self.assertGreater(len(natal_layer["payload"]["big_three"]["sun"]["body"]), 120)

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

    @patch("core.services.report_natal.llm_client.is_configured", return_value=True)
    @patch("core.services.report_natal.llm_client.chat_json")
    def test_natal_generate_returns_llm_layer(self, chat_json, _configured):
        chat_json.return_value = {
            "report_type": "natal",
            "core_portrait": {
                "headline": "Слой модели",
                "summary": "Это текст, который вернул бы API скилла. Ещё одно предложение для плотности.",
            },
            "big_three": {
                "sun": {
                    "headline": "Солнце с API",
                    "body": "Развёрнутое солнце от модели. Второй абзац механизма и цены, не два слова.",
                    "why": "Солнце во Льве · дом 10",
                    "question": "Где видимость уже работа на отклик?",
                }
            },
            "sections": [
                {
                    "id": "mind",
                    "title": "Как работает твой ум",
                    "headline": "Ум",
                    "summary": "Сумма.",
                    "deep_read": ["Механизм."],
                    "why": "Меркурий",
                    "question": "Где мысль уже готова выйти?",
                }
            ],
            "reflection_questions": ["Что проверяешь в опыте?"],
        }
        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        response = self.client.post(
            "/api/me/report/natal/generate/",
            {"force": True},
            format="json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["status"], "llm")
        self.assertEqual(data["natal"]["payload"]["core_portrait"]["headline"], "Слой модели")
        self.assertIn("Развёрнутое солнце", data["natal"]["payload"]["big_three"]["sun"]["body"])
        self.assertEqual(chat_json.call_args.kwargs.get("prompt_id"), "paid_report_natal")
        natal_user = json.loads(chat_json.call_args.kwargs["user"])
        self.assertEqual(natal_user["reader"]["address"], "ты")
        self.assertEqual(natal_user["reader"]["grammatical_gender"], "unspecified")
        self.order.refresh_from_db()
        self.assertEqual(self.order.interpretive["natal"]["source"], "llm")

    @patch("core.services.report_aspects.llm_client.is_configured", return_value=True)
    @patch("core.services.report_aspects.llm_client.chat_json")
    def test_aspects_generate_returns_llm_layer(self, chat_json, _configured):
        def fake_chat_json(**kwargs):
            user = json.loads(kwargs["user"])
            return {
                "report_type": "natal_aspects",
                "intro": {
                    "headline": "Связки модели",
                    "summary": "Это слой аспектов с API, не транзит и не прогноз периода.",
                },
                "aspects": [
                    {
                        "aspect_id": row.get("id"),
                        "category": row.get("category") or "mixed",
                        "headline": "Когда две функции уже сцеплены внутри карты",
                        "summary": (
                            "Это слой аспектов с API, не транзит и не прогноз периода. "
                            "Карточка собрана целиком, без склейки со словарём."
                        ),
                        "deep_read": [
                            "Механизм связки двух функций внутри натальной карты.",
                            "Цена появляется там, где реакция становится единственным способом.",
                        ],
                        "resource": "Можно опереться на уже существующий канал между темами.",
                        "tension_or_blind_spot": "Привычная связка может начать звучать как единственный вариант.",
                        "how_to_work": "Заметить, где реакция уже не про данные, а про защиту.",
                        "reflection_questions": ["Где эта связка узнаётся в опыте, а где нет?"],
                        "a": (row.get("planet_a") or {}).get("key"),
                        "b": (row.get("planet_b") or {}).get("key"),
                        "aspect": row.get("aspect_type"),
                        "aspect_ru": row.get("aspect_type_ru"),
                        "a_name": (row.get("planet_a") or {}).get("name_ru"),
                        "b_name": (row.get("planet_b") or {}).get("name_ru"),
                    }
                    for row in (user.get("aspects") or [])
                ],
            }

        chat_json.side_effect = fake_chat_json
        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        response = self.client.post(
            "/api/me/report/aspects/generate/",
            {"force": True},
            format="json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["status"], "llm")
        self.assertEqual(data["aspects"]["payload"]["intro"]["headline"], "Связки модели")
        self.assertTrue(data["aspects"]["payload"]["aspects"])
        self.assertEqual(chat_json.call_args.kwargs.get("prompt_id"), "paid_report_aspects")
        aspects_user = json.loads(chat_json.call_args.kwargs["user"])
        self.assertEqual(aspects_user["reader"]["grammatical_gender"], "unspecified")
        self.order.refresh_from_db()
        self.assertEqual(self.order.interpretive["aspects"]["source"], "llm")

    @patch("core.services.report_cycles.llm_client.is_configured", return_value=True)
    @patch("core.services.report_cycles.llm_client.chat_json")
    def test_cycles_generate_returns_llm_layer(self, chat_json, _configured):
        def fake_chat_json(**kwargs):
            user = json.loads(kwargs["user"])
            cycles = [row for row in user.get("cycles") or [] if row.get("priority") == "primary"]
            if not cycles:
                cycles = list(user.get("cycles") or [])
            return {
                "report_type": "current_cycles",
                "period_overview": {
                    "headline": "Период модели",
                    "summary": "Это слой циклов с API, не натальный аспект и не прогноз события.",
                    "main_tension": "Где тесно",
                    "main_support": "Где канал",
                },
                "primary_cycles": [
                    {
                        "cycle_id": row["cycle_id"],
                        "category": row.get("category") or "mixed",
                        "technical_title": row.get("technical_title") or "",
                        "headline": "Когда прежняя роль становится тесной",
                        "summary": (
                            "Сгенерированный цикл от модели. Это не фолбэк и не натальный "
                            "аспект, а текущий период для наблюдения."
                        ),
                        "deep_read": (
                            "Narrative модели про активацию, реакцию и гибкость "
                            "без шаблонной слепой зоны."
                        ),
                        "protective_function": "Сгенерированная защитная функция.",
                        "tension_or_blind_spot": "Сгенерированная слепая зона этого цикла.",
                        "resource": "Сгенерированный ресурс.",
                        "how_to_work": "Сгенерированный способ работать с циклом.",
                        "reflection_questions": ["Где это уже заметно в неделях?"],
                    }
                    for row in cycles
                ],
                "secondary_cycles": [],
                "cross_cycle_synthesis": {
                    "headline": "Как периоды встречаются",
                    "narrative": "Несколько активаций могут усиливать одну реакцию.",
                    "reflection_questions": ["Что уже повторяется в этих неделях?"],
                },
            }

        chat_json.side_effect = fake_chat_json
        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        response = self.client.post(
            "/api/me/report/cycles/generate/",
            {"force": True},
            format="json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["status"], "llm")
        self.assertEqual(data["cycles"]["payload"]["period_overview"]["headline"], "Период модели")
        self.assertEqual(data["cycles"]["payload"]["report_type"], "current_cycles")
        self.assertEqual(data["cycles"]["generation_status"], "generated")
        generated = data["cycles"]["payload"]["primary_cycles"]
        self.assertTrue(generated)
        self.assertEqual(generated[0]["source"], "llm")
        blob = json.dumps(generated, ensure_ascii=False)
        self.assertNotIn("Слепая зона периода", blob)
        self.assertNotIn("ломает характер", blob)
        self.assertEqual(chat_json.call_args.kwargs.get("prompt_id"), "paid_report_cycles")
        cycles_user = json.loads(chat_json.call_args.kwargs["user"])
        self.assertEqual(cycles_user["reader"]["grammatical_gender"], "unspecified")
        self.assertIn("cycles", cycles_user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.interpretive["cycles"]["source"], "llm")

    @patch("core.services.report_jobs.llm_client.is_configured", return_value=True)
    def test_should_start_generation_when_layers_missing(self, _configured):
        from core.services.report_jobs import should_start_generation

        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        self.assertTrue(should_start_generation(self.order, retry_failed=False))
        self.order.interpretive = {"generation": {"status": "done"}}
        self.assertFalse(should_start_generation(self.order, retry_failed=False))
        self.assertTrue(should_start_generation(self.order, retry_failed=True))

    def test_schedule_is_noop_during_django_tests(self):
        from core.services.report_jobs import _inflight_orders, schedule_paid_report_generation

        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        schedule_paid_report_generation(self.order.pk, retry_failed=True)
        self.assertNotIn(self.order.pk, _inflight_orders)

    @patch("core.services.llm_client.is_configured", return_value=True)
    @patch("core.services.llm_client.chat_json")
    def test_generate_missing_layers_runs_all_sections(self, chat_json, _configured):
        from core.services import report_jobs
        from core.services.report_jobs import generate_missing_interpretive_layers

        report_jobs._section_inflight.clear()
        report_jobs._inflight_orders.clear()

        def fake_chat_json(*, prompt_id="", **kwargs):
            if prompt_id == "paid_report_natal":
                return {
                    "report_type": "natal",
                    "core_portrait": {
                        "headline": "Слой модели",
                        "summary": "Это текст, который вернул бы API скилла. Ещё одно предложение для плотности.",
                    },
                    "big_three": {
                        "sun": {
                            "headline": "Солнце с API",
                            "body": "Развёрнутое солнце от модели. Второй абзац механизма и цены, не два слова.",
                            "why": "Солнце во Льве · дом 10",
                            "question": "Где видимость уже работа на отклик?",
                        }
                    },
                    "sections": [],
                    "reflection_questions": ["Что проверяешь в опыте?"],
                }
            if prompt_id == "paid_report_aspects":
                user = json.loads(kwargs["user"])
                return {
                    "report_type": "natal_aspects",
                    "intro": {
                        "headline": "Связки модели",
                        "summary": "Это слой аспектов с API, не транзит и не прогноз периода.",
                    },
                    "aspects": [
                        {
                            "aspect_id": row.get("id"),
                            "category": row.get("category") or "mixed",
                            "headline": "Когда стержень спорит с опорой",
                            "summary": (
                                "Это слой аспектов с API, не транзит и не прогноз периода. "
                                "Карточка собрана целиком, без склейки со словарём."
                            ),
                            "deep_read": [
                                "Механизм связки двух функций внутри натальной карты.",
                                "Цена появляется там, где реакция становится единственным способом.",
                            ],
                            "a": (row.get("planet_a") or {}).get("key"),
                            "b": (row.get("planet_b") or {}).get("key"),
                            "aspect": row.get("aspect_type"),
                        }
                        for row in (user.get("aspects") or [])
                    ],
                }
            if prompt_id == "paid_report_request":
                return {
                    "report_type": "request",
                    "request": {
                        "title": "Найти опору перед следующим выбором",
                        "text": (
                            "Сейчас важно понять, какой шаг ещё ощущается своим. "
                            "Фокус держится на выборе, а не на прогнозе событий. "
                            "К астрологии приходишь, чтобы яснее увидеть пересечение."
                        ),
                    },
                    "connections": [
                        {
                            "source_id": "uranus_square_sun",
                            "source_type": "cycle",
                            "title": "Свобода от прежней роли",
                            "text": (
                                "Этот цикл уже разобран отдельно. Здесь важно другое: "
                                "в запросе о выборе он усиливает вопрос, насколько прежнее "
                                "направление ещё ощущается своим."
                            ),
                        },
                        {
                            "source_id": "saturn_square_mercury",
                            "source_type": "aspect",
                            "title": "Когда мысль должна быть слишком правильной",
                            "text": (
                                "Натальная связка помогает понять, почему перед шагом "
                                "так легко включается дополнительная проверка. "
                                "Для текущего запроса это может значить: решение откладывается "
                                "не из пустоты, а из потребности в прочности."
                            ),
                        },
                    ],
                    "core_distinction": {
                        "title": "Своё желание ↔ внешнее подтверждение",
                        "text": (
                            "Возможно, сейчас вопрос не только в том, какой вариант выбрать, "
                            "но и в том, чьё одобрение всё ещё нужно, чтобы шаг стал возможным. "
                            "Стоит проверить, где опора уже есть — а где остаётся привычка ждать сигнала."
                        ),
                        "provenance": ["uranus_square_sun", "saturn_square_mercury"],
                    },
                    "resource": {
                        "source_id": "resource_contact",
                        "source_type": "cycle",
                        "title": "На что можно опереться",
                        "text": (
                            "В карте и текущем небе уже есть канал, которым можно пользоваться "
                            "специально: не ждать идеальной ясности, а проверять маленьким шагом."
                        ),
                    },
                    "takeaway": (
                        "Возможно, сейчас важно точнее увидеть, что стоит различить перед следующим шагом. "
                        "Карта не принимает решение за тебя, но помогает не перепутать своё желание с привычкой."
                    ),
                }
            if prompt_id == "paid_report_practice":
                return {
                    "report_type": "practice",
                    "start_here": {
                        "headline": "Ясность и гарантия — не одно и то же",
                        "text": (
                            "Сейчас полезно исследовать, где желание быстрее закрыть неопределённость "
                            "связано с реальным несоответствием, а где — с потребностью снизить напряжение. "
                            "Вкладка поможет различить привычную проверку и то, что для тебя важно сохранить. "
                            "Это не ещё один разбор карты, а способ проверить найденное различение на опыте."
                        ),
                        "provenance": ["request", "uranus_square_sun"],
                    },
                    "pattern": {
                        "title": "Что может повторяться",
                        "text": (
                            "Когда исход становится менее предсказуемым, может хотеться быстрее "
                            "решить вопрос, собрать больше подтверждений или отложить действие "
                            "до полной ясности. Это наблюдаемый способ реагировать, а не ярлык."
                        ),
                        "source_ids": ["saturn_square_mercury"],
                    },
                    "protective_function": {
                        "title": "Что эта реакция может защищать",
                        "text": (
                            "Одна из возможных функций этой реакции — быстро вернуть ощущение "
                            "контроля там, где результат невозможно гарантировать. "
                            "Стоит проверить, что именно она помогает сохранить."
                        ),
                    },
                    "cost": {
                        "title": "Где это перестаёт помогать",
                        "text": (
                            "Дополнительная проверка помогает снизить риск ошибки. "
                            "Но если уверенность становится условием действия, анализ может "
                            "начать заменять реальную обратную связь."
                        ),
                    },
                    "key_distinctions": [
                        {
                            "left": "ясность",
                            "right": "гарантия",
                            "note": "Их легко смешать, когда напряжение высокое.",
                        }
                    ],
                    "values": {
                        "title": "Что здесь важно сохранить",
                        "text": (
                            "Если убрать необходимость сначала почувствовать полную уверенность, "
                            "что для тебя здесь важно не потерять? Различай желаемый исход "
                            "и способ, которым ты хочешь действовать."
                        ),
                    },
                    "reflection_questions": [
                        "Где эта реакция включается сильнее всего?",
                        "Что она помогает не чувствовать, не рисковать или сохранять?",
                        "В какой момент стратегия перестаёт помогать?",
                        "Что важно сохранить, даже если напряжение не исчезнет сразу?",
                        "Какой другой способ защитить ту же потребность возможен?",
                        "Что можно проверить в реальности вместо ещё одного круга анализа?",
                    ],
                    "experiment": {
                        "title": "Попробуй проверить",
                        "text": (
                            "Когда снова захочется решить всё сразу, отдельно запиши: "
                            "«что я хочу изменить?» и «что я хочу перестать чувствовать?». "
                            "Сравни ответы."
                        ),
                        "duration": "несколько дней",
                    },
                    "observe_over_time": [
                        "когда желание принять решение резко усиливается",
                        "какие ситуации запускают знакомую реакцию",
                        "какие действия реально дают больше ясности",
                    ],
                    "user_takeaway_prompt": "Сейчас мне важно различать…",
                }
            user = json.loads(kwargs["user"])
            cycles = [row for row in user.get("cycles") or [] if row.get("priority") == "primary"]
            if not cycles:
                cycles = list(user.get("cycles") or [])
            return {
                "report_type": "current_cycles",
                "period_overview": {
                    "headline": "Период модели",
                    "summary": "Это слой циклов с API, не натальный аспект и не прогноз события.",
                },
                "primary_cycles": [
                    {
                        "cycle_id": row["cycle_id"],
                        "category": row.get("category") or "mixed",
                        "headline": "Когда прежняя роль становится тесной",
                        "summary": (
                            "Сгенерированный цикл от модели. Это не фолбэк и не натальный "
                            "аспект, а текущий период для наблюдения."
                        ),
                        "deep_read": "Narrative модели про активацию без шаблонной слепой зоны.",
                    }
                    for row in cycles
                ],
                "secondary_cycles": [],
                "cross_cycle_synthesis": {
                    "headline": "Как периоды встречаются",
                    "narrative": "Несколько активаций могут усиливать одну реакцию.",
                },
            }

        chat_json.side_effect = fake_chat_json
        self.order.status = Order.Status.PAID
        self.order.save(update_fields=["status"])
        generate_missing_interpretive_layers(self.order)
        self.order.refresh_from_db()
        store = self.order.interpretive
        self.assertEqual(store["generation"]["status"], "done")
        self.assertEqual(store["natal"]["source"], "llm")
        self.assertEqual(store["aspects"]["source"], "llm")
        self.assertEqual(store["cycles"]["source"], "llm")
        self.assertEqual(store["request"]["source"], "llm")
        self.assertEqual(store["practice"]["source"], "llm")
        prompt_ids = [call.kwargs.get("prompt_id") for call in chat_json.call_args_list]
        self.assertEqual(
            prompt_ids,
            [
                "paid_report_natal",
                "paid_report_aspects",
                "paid_report_cycles",
                "paid_report_request",
                "paid_report_practice",
            ],
        )

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
        self.assertEqual(chat_json.call_args.kwargs.get("prompt_id"), "onboarding_insight")
        self.assertTrue(result.get("editorial_passed"))
        self.assertEqual(result.get("source"), "polza")


class LlmProviderOffTests(TestCase):
    @override_settings(LLM_PROVIDER="off", POLZA_API_KEY="test-key", GROQ_API_KEY="g")
    def test_off_disables_llm_even_with_keys(self):
        from core.services.llm_client import active_provider, is_configured

        self.assertIsNone(active_provider())
        self.assertFalse(is_configured())


class PaidReportLlmFirstOverlayTests(TestCase):
    """LLM-first GET overlay: sealed source=llm always wins; provider only gates new calls."""

    def setUp(self):
        self.client = APIClient()
        self.user, self.auth_key = _make_user(email="overlay@example.com", yandex_id="6106")
        lead = WaitlistLead.objects.create(email="overlay@example.com", user=self.user)
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
                {"house": i + 1, "sign": "scorpio", "sign_ru": "Скорпион"} for i in range(12)
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
            idempotency_key="overlay-key-0001",
            idempotency_request_hash="d" * 64,
            session=session,
            waitlist_lead=lead,
            user=self.user,
            customer_email="overlay@example.com",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.PAID,
        )

    def _report(self):
        from core.services.report import build_paid_report

        return build_paid_report(self.order)

    @override_settings(LLM_PROVIDER="auto", POLZA_API_KEY="test-key")
    def test_valid_persisted_llm_shown_when_provider_on(self):
        from core.services import llm_client

        self.assertTrue(llm_client.is_configured())
        self.order.interpretive = {
            "generation": {"status": "done"},
            "natal": {
                "status": "ready",
                "source": "llm",
                "payload": {
                    "core_portrait": {"headline": "LLM natal headline", "summary": "x" * 50},
                },
            },
        }
        self.order.save(update_fields=["interpretive"])
        natal = self._report()["document"]["interpretive"]["natal"]
        self.assertEqual(natal["source"], "llm")
        self.assertEqual(natal["payload"]["core_portrait"]["headline"], "LLM natal headline")

    @override_settings(LLM_PROVIDER="off", POLZA_API_KEY="test-key")
    def test_valid_persisted_llm_shown_when_provider_off(self):
        from core.services import llm_client

        self.assertFalse(llm_client.is_configured())
        self.order.interpretive = {
            "generation": {"status": "done"},
            "natal": {
                "status": "ready",
                "source": "llm",
                "payload": {
                    "core_portrait": {"headline": "Sealed while off", "summary": "x" * 50},
                },
            },
        }
        self.order.save(update_fields=["interpretive"])
        natal = self._report()["document"]["interpretive"]["natal"]
        self.assertEqual(natal["source"], "llm")
        self.assertEqual(natal["payload"]["core_portrait"]["headline"], "Sealed while off")

    @override_settings(LLM_PROVIDER="auto", POLZA_API_KEY="test-key")
    def test_no_persisted_llm_pending_uses_live_fallback(self):
        self.order.interpretive = {"generation": {"status": "running"}}
        self.order.save(update_fields=["interpretive"])
        interpretive = self._report()["document"]["interpretive"]
        self.assertEqual(interpretive["generation"]["status"], "running")
        for key in ("natal", "aspects", "cycles", "request", "practice"):
            self.assertEqual(interpretive[key]["source"], "fallback", key)
        self.assertTrue(interpretive["natal"]["payload"]["core_portrait"]["headline"])

    @override_settings(LLM_PROVIDER="auto", POLZA_API_KEY="test-key")
    def test_stored_fallback_error_uses_live_fallback_not_cached_payload(self):
        self.order.interpretive = {
            "generation": {"status": "done"},
            "natal": {
                "status": "ready",
                "source": "fallback",
                "error": "Polza request failed: APIStatusError",
                "payload": {
                    "core_portrait": {
                        "headline": "Stale failed payload must not win",
                        "summary": "x" * 50,
                    },
                },
            },
        }
        self.order.save(update_fields=["interpretive"])
        natal = self._report()["document"]["interpretive"]["natal"]
        self.assertEqual(natal["source"], "fallback")
        self.assertNotEqual(
            natal["payload"]["core_portrait"]["headline"],
            "Stale failed payload must not win",
        )

    @override_settings(LLM_PROVIDER="auto", POLZA_API_KEY="test-key")
    def test_mixed_llm_and_fallback_sections(self):
        self.order.interpretive = {
            "generation": {"status": "running"},
            "natal": {
                "status": "ready",
                "source": "llm",
                "payload": {
                    "core_portrait": {"headline": "Mixed natal LLM", "summary": "x" * 50},
                },
            },
            "aspects": {
                "status": "ready",
                "source": "llm",
                "payload": {
                    "aspects": [
                        {"aspect_id": "a1", "summary": "x" * 50, "headline": "Mixed aspect"}
                    ],
                },
            },
        }
        self.order.save(update_fields=["interpretive"])
        report = self._report()
        interpretive = report["document"]["interpretive"]
        self.assertEqual(interpretive["natal"]["source"], "llm")
        self.assertEqual(
            interpretive["natal"]["payload"]["core_portrait"]["headline"],
            "Mixed natal LLM",
        )
        self.assertEqual(interpretive["aspects"]["source"], "llm")
        self.assertEqual(interpretive["cycles"]["source"], "fallback")
        self.assertEqual(interpretive["request"]["source"], "fallback")
        self.assertEqual(interpretive["practice"]["source"], "fallback")
        self.assertTrue(report["document"]["sections"])

    @patch("core.services.report_jobs.kickoff_paid_report_for_order")
    def test_me_report_get_still_kickoffs_outside_assembler(self, kickoff):
        response = self.client.get(
            "/api/me/report/",
            HTTP_AUTHORIZATION=f"Bearer {self.auth_key}",
        )
        self.assertEqual(response.status_code, 200)
        kickoff.assert_called()
        report = response.json()["report"]
        self.assertIn("document", report)
        self.assertIn("natal", report["document"]["interpretive"])


class PaidReportSectionIsolationTests(TestCase):
    """Section-local unexpected exceptions must not abort remaining layers."""

    def setUp(self):
        self.user, self.auth_key = _make_user(email="isolate@example.com", yandex_id="6107")
        lead = WaitlistLead.objects.create(email="isolate@example.com", user=self.user)
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
                {"house": i + 1, "sign": "scorpio", "sign_ru": "Скорпион"} for i in range(12)
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
            idempotency_key="isolate-key-0001",
            idempotency_request_hash="e" * 64,
            session=session,
            waitlist_lead=lead,
            user=self.user,
            customer_email="isolate@example.com",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.PAID,
        )

    def _run_with_boom(self, boom: str) -> list[str]:
        from core.services import report_jobs
        from core.services.report_jobs import generate_missing_interpretive_layers

        report_jobs._section_inflight.clear()
        called: list[str] = []

        def make_section(name: str):
            def _section(order, force=False):
                called.append(name)
                if name == boom:
                    raise RuntimeError(f"unexpected {name}")
                return {}

            return _section

        with (
            patch("core.services.report.generate_natal_section", side_effect=make_section("natal")),
            patch("core.services.report.generate_aspects_section", side_effect=make_section("aspects")),
            patch("core.services.report.generate_cycles_section", side_effect=make_section("cycles")),
            patch("core.services.report.generate_request_section", side_effect=make_section("request")),
            patch("core.services.report.generate_practice_section", side_effect=make_section("practice")),
        ):
            generate_missing_interpretive_layers(self.order)
        return called

    def test_natal_raise_still_attempts_later_layers(self):
        called = self._run_with_boom("natal")
        self.assertEqual(called, ["natal", "aspects", "cycles", "request", "practice"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.interpretive["generation"]["status"], "done")
        natal = self.order.interpretive["natal"]
        self.assertEqual(natal["source"], "fallback")
        self.assertIn("unexpected natal", natal.get("error") or "")

    def test_aspects_raise_still_attempts_later_layers(self):
        called = self._run_with_boom("aspects")
        self.assertEqual(called, ["natal", "aspects", "cycles", "request", "practice"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.interpretive["aspects"]["source"], "fallback")
        self.assertIn("unexpected aspects", self.order.interpretive["aspects"].get("error") or "")

    def test_cycles_raise_still_attempts_later_layers(self):
        called = self._run_with_boom("cycles")
        self.assertEqual(called, ["natal", "aspects", "cycles", "request", "practice"])
        self.order.refresh_from_db()
        cycles = self.order.interpretive["cycles"]
        self.assertEqual(cycles["source"], "fallback")
        self.assertEqual(cycles.get("generation_status"), "generation_failed")

    def test_request_raise_still_attempts_practice(self):
        called = self._run_with_boom("request")
        self.assertEqual(called, ["natal", "aspects", "cycles", "request", "practice"])
        self.assertIn("practice", called)

    @patch("core.services.llm_client.is_configured", return_value=True)
    @patch(
        "core.services.report.generate_natal_interpretation",
        side_effect=RuntimeError("natal unexpected boom"),
    )
    @patch("core.services.report.generate_aspects_interpretation")
    @patch("core.services.report.generate_cycles_interpretation")
    @patch("core.services.report.generate_request_interpretation")
    @patch("core.services.report.generate_practice_interpretation")
    def test_layer_raise_get_shows_fallback_plus_later_llm(
        self,
        practice_interp,
        request_interp,
        cycles_interp,
        aspects_interp,
        _natal_interp,
        _configured,
    ):
        from core.services import report_jobs
        from core.services.report import build_paid_report
        from core.services.report_jobs import generate_missing_interpretive_layers

        report_jobs._section_inflight.clear()
        aspects_interp.return_value = {
            "ok": True,
            "source": "llm",
            "model": "test-model",
            "error": "",
            "payload": {
                "report_type": "natal_aspects",
                "source": "llm",
                "intro": {"headline": "LLM aspects", "summary": "x" * 50},
                "aspects": [
                    {
                        "aspect_id": "sun_conj_moon",
                        "headline": "Mixed aspect after natal crash",
                        "summary": "x" * 50,
                    }
                ],
            },
        }
        cycles_interp.return_value = {
            "ok": True,
            "source": "llm",
            "model": "test-model",
            "error": "",
            "generation_status": "generated",
            "payload": {
                "report_type": "current_cycles",
                "source": "llm",
                "period_overview": {"headline": "LLM cycles", "summary": "x" * 50},
                "primary_cycles": [],
                "secondary_cycles": [],
            },
        }
        request_interp.return_value = {
            "ok": True,
            "source": "llm",
            "model": "test-model",
            "error": "",
            "payload": {
                "report_type": "request",
                "source": "llm",
                "request": {"title": "LLM request", "text": "x" * 50},
            },
        }
        practice_interp.return_value = {
            "ok": True,
            "source": "llm",
            "model": "test-model",
            "error": "",
            "payload": {
                "report_type": "practice",
                "source": "llm",
                "start_here": {"headline": "LLM practice", "text": "x" * 50},
            },
        }

        generate_missing_interpretive_layers(self.order)
        self.order.refresh_from_db()
        self.assertEqual(self.order.interpretive["generation"]["status"], "done")
        self.assertEqual(self.order.interpretive["natal"]["source"], "fallback")
        self.assertIn("natal unexpected boom", self.order.interpretive["natal"].get("error") or "")
        for key in ("aspects", "cycles", "request", "practice"):
            self.assertEqual(self.order.interpretive[key]["source"], "llm", key)
        aspects_interp.assert_called()
        cycles_interp.assert_called()
        request_interp.assert_called()
        practice_interp.assert_called()

        interpretive = build_paid_report(self.order)["document"]["interpretive"]
        # Crash record is source=fallback → GET ignores it as LLM overlay, uses live YAML.
        self.assertEqual(interpretive["natal"]["source"], "fallback")
        self.assertTrue(interpretive["natal"]["payload"]["core_portrait"]["headline"])
        self.assertEqual(interpretive["aspects"]["source"], "llm")
        self.assertEqual(
            interpretive["aspects"]["payload"]["aspects"][0]["headline"],
            "Mixed aspect after natal crash",
        )
        self.assertEqual(interpretive["cycles"]["source"], "llm")
        self.assertEqual(interpretive["request"]["source"], "llm")
        self.assertEqual(interpretive["practice"]["source"], "llm")

    @patch("core.services.llm_client.is_configured", return_value=True)
    @patch("core.services.report.generate_natal_interpretation")
    @patch("core.services.report.generate_aspects_interpretation")
    @patch("core.services.report.generate_cycles_interpretation")
    @patch(
        "core.services.report.generate_request_interpretation",
        side_effect=RuntimeError("request unexpected boom"),
    )
    @patch("core.services.report.generate_practice_interpretation")
    def test_request_raise_practice_uses_live_request_fallback(
        self,
        practice_interp,
        _request_interp,
        cycles_interp,
        aspects_interp,
        natal_interp,
        _configured,
    ):
        from core.services import report_jobs
        from core.services.report import build_paid_report
        from core.services.report_jobs import generate_missing_interpretive_layers

        report_jobs._section_inflight.clear()
        practice_docs: list[dict] = []

        natal_interp.return_value = {
            "ok": True,
            "source": "llm",
            "model": "test-model",
            "error": "",
            "payload": {
                "report_type": "natal",
                "source": "llm",
                "core_portrait": {"headline": "LLM natal", "summary": "x" * 50},
            },
        }
        aspects_interp.return_value = {
            "ok": True,
            "source": "llm",
            "model": "test-model",
            "error": "",
            "payload": {
                "report_type": "natal_aspects",
                "source": "llm",
                "intro": {"headline": "LLM aspects", "summary": "x" * 50},
                "aspects": [{"aspect_id": "a1", "headline": "A", "summary": "x" * 50}],
            },
        }
        cycles_interp.return_value = {
            "ok": True,
            "source": "llm",
            "model": "test-model",
            "error": "",
            "generation_status": "generated",
            "payload": {
                "report_type": "current_cycles",
                "source": "llm",
                "period_overview": {"headline": "LLM cycles", "summary": "x" * 50},
                "primary_cycles": [],
                "secondary_cycles": [],
            },
        }

        def practice_side_effect(document):
            practice_docs.append(document)
            return {
                "ok": True,
                "source": "llm",
                "model": "test-model",
                "error": "",
                "payload": {
                    "report_type": "practice",
                    "source": "llm",
                    "start_here": {
                        "headline": "Практика от live request fallback",
                        "text": "x" * 50,
                    },
                },
            }

        practice_interp.side_effect = practice_side_effect
        generate_missing_interpretive_layers(self.order)
        self.order.refresh_from_db()
        self.assertEqual(self.order.interpretive["request"]["source"], "fallback")
        self.assertIn("request unexpected boom", self.order.interpretive["request"].get("error") or "")
        self.assertEqual(self.order.interpretive["practice"]["source"], "llm")
        self.assertTrue(practice_docs)
        request_layer = (practice_docs[0].get("interpretive") or {}).get("request") or {}
        self.assertEqual(request_layer.get("source"), "fallback")
        request_payload = request_layer.get("payload") or {}
        self.assertIsInstance(request_payload.get("request"), dict)
        self.assertTrue(str((request_payload.get("request") or {}).get("text") or "").strip())

        interpretive = build_paid_report(self.order)["document"]["interpretive"]
        self.assertEqual(interpretive["request"]["source"], "fallback")
        self.assertEqual(interpretive["practice"]["source"], "llm")
        self.assertEqual(
            interpretive["practice"]["payload"]["start_here"]["headline"],
            "Практика от live request fallback",
        )


class PromptModelTests(TestCase):
    def tearDown(self):
        from core.services.llm_prompts import load_prompt_file

        load_prompt_file.cache_clear()

    @override_settings(
        POLZA_MODEL="openai/gpt-5.6-luna-pro",
        LLM_MODEL_ONBOARDING_INSIGHT="",
        LLM_MODEL_EDITORIAL="",
        LLM_MODEL_PAID_REPORT="",
        LLM_MODEL_PAID_REPORT_NATAL="",
        LLM_MODEL_PAID_REPORT_ASPECTS="",
        LLM_MODEL_PAID_REPORT_CYCLES="",
        LLM_MODEL_PAID_REPORT_REQUEST="",
        LLM_MODEL_PAID_REPORT_PRACTICE="",
    )
    def test_paid_report_frontmatter_model_is_used(self):
        from core.services.editorial import load_editorial_system
        from core.services.llm_prompts import (
            PROMPT_EDITORIAL,
            PROMPT_ONBOARDING_INSIGHT,
            PROMPT_PAID_REPORT,
            PROMPT_PAID_REPORT_ASPECTS,
            PROMPT_PAID_REPORT_CYCLES,
            PROMPT_PAID_REPORT_NATAL,
            PROMPT_PAID_REPORT_PRACTICE,
            PROMPT_PAID_REPORT_REQUEST,
            UnknownPromptError,
            resolve_model,
        )

        load_editorial_system.cache_clear()
        self.assertEqual(resolve_model(PROMPT_PAID_REPORT), "openai/gpt-5.6-terra-pro")
        self.assertEqual(resolve_model(PROMPT_PAID_REPORT_NATAL), "openai/gpt-5.6-luna-pro")
        self.assertEqual(resolve_model(PROMPT_PAID_REPORT_ASPECTS), "openai/gpt-5.6-luna-pro")
        self.assertEqual(resolve_model(PROMPT_PAID_REPORT_CYCLES), "openai/gpt-5.6-luna-pro")
        self.assertEqual(resolve_model(PROMPT_PAID_REPORT_REQUEST), "openai/gpt-5.6-luna-pro")
        self.assertEqual(resolve_model(PROMPT_PAID_REPORT_PRACTICE), "openai/gpt-5.6-luna-pro")
        self.assertEqual(resolve_model(PROMPT_EDITORIAL), "openai/gpt-5.6-terra-pro")
        self.assertEqual(resolve_model(PROMPT_ONBOARDING_INSIGHT), "openai/gpt-5.6-luna-pro")
        with self.assertRaises(UnknownPromptError):
            resolve_model("not_a_prompt")

    @override_settings(LLM_MODEL_PAID_REPORT="anthropic/claude-sonnet-4-5")
    def test_env_override_beats_frontmatter(self):
        from core.services.llm_prompts import PROMPT_PAID_REPORT, resolve_model

        self.assertEqual(resolve_model(PROMPT_PAID_REPORT), "anthropic/claude-sonnet-4-5")

    @override_settings(POLZA_MODEL="openai/gpt-4o")
    def test_explicit_model_argument_wins(self):
        from core.services.llm_prompts import PROMPT_PAID_REPORT, resolve_model

        self.assertEqual(
            resolve_model(PROMPT_PAID_REPORT, model="anthropic/claude-opus-4-6"),
            "anthropic/claude-opus-4-6",
        )

    def test_editorial_body_strips_frontmatter(self):
        from core.services.editorial import load_editorial_system
        from core.services.llm_prompts import PROMPT_PAID_REPORT_NATAL, load_prompt

        load_editorial_system.cache_clear()
        body = load_editorial_system()
        self.assertFalse(body.startswith("---"))
        self.assertNotIn("id: editorial", body.split("# 1.", 1)[0])
        self.assertIn("COSMIRROR", body)
        natal = load_prompt(PROMPT_PAID_REPORT_NATAL).body
        self.assertIn("вкладка платного отчёта", natal.lower())
        self.assertNotIn("cosmirror-natal-interpreter", natal)


class NatalFallbackCopyTests(TestCase):
    def test_mercury_in_leo_is_lived_hypothesis_not_glossary(self):
        from core.services.report_lexicon import placement_sentence

        text = placement_sentence("mercury", "Лев", 11, sign="leo")
        self.assertNotIn("связано с темой", text)
        self.assertNotIn("в Лев", text)
        self.assertNotIn("Дом 11:", text)
        self.assertIn("может", text)
        self.assertIn("своих людей", text)
        self.assertTrue(text.startswith("Тебе может быть важно"))

    def test_natal_aspect_is_inner_link_not_transit(self):
        from core.services.report_lexicon import natal_aspect_sentence

        text = natal_aspect_sentence("sun", "square", "квадрат", "moon")
        self.assertIn("Солнце", text)
        self.assertIn("Луна", text)
        self.assertIn("внутренн", text)
        self.assertNotIn("Транзитный", text)

    def test_natal_fallback_is_skill_shaped_and_native(self):
        from core.services.report_blueprint import build_report_document

        document = build_report_document(
            natal={
                "has_birth_time": True,
                "planets": {
                    "sun": {"sign": "gemini", "sign_ru": "Близнецы", "sign_index": 2, "degree": 5.0, "house": 7},
                    "moon": {"sign": "taurus", "sign_ru": "Телец", "sign_index": 1, "degree": 12.0, "house": 6},
                    "mercury": {"sign": "leo", "sign_ru": "Лев", "sign_index": 4, "degree": 2.0, "house": 9},
                    "saturn": {"sign": "taurus", "sign_ru": "Телец", "sign_index": 1, "degree": 8.0, "house": 6},
                },
                "ascendant": {"sign": "scorpio", "sign_ru": "Скорпион", "sign_index": 7, "degree": 5.0},
                "houses": [{"house": i + 1, "sign": "scorpio", "sign_ru": "Скорпион"} for i in range(12)],
            },
            sky_now={"datetime_utc": "2026-08-17T12:00:00Z", "planets": {}},
        )
        natal = document["interpretive"]["natal"]["payload"]
        self.assertEqual(natal["source"], "fallback")
        keys = [row["key"] for row in natal["placements"]]
        self.assertEqual(keys[0], "sun_gemini")
        self.assertIn("moon_taurus", keys)
        self.assertIn("asc_scorpio", keys)
        self.assertIn("saturn_taurus", keys)
        sun = next(row for row in natal["placements"] if row["key"] == "sun_gemini")
        self.assertIn("движен", sun["summary"].lower() + sun["headline"].lower())
        self.assertTrue(sun["house_modifier"])
        self.assertIn("заметн", sun["house_modifier"].lower())
        moon = natal["big_three"]["moon"]["body"]
        self.assertIn("опора", moon.lower())
        self.assertGreater(len(natal["core_portrait"]["summary"]), 80)
        self.assertTrue(natal["core_portrait"]["themes"])
        theme_ids = [row["theme_id"] for row in natal["core_portrait"]["themes"]]
        self.assertTrue(set(theme_ids) & {"safety_vs_change", "pace_and_stability"})
        self.assertFalse(any(row["point_key"] == "uranus" for row in natal["placements"]))

    def test_natal_fallback_hides_ascendant_without_birth_time(self):
        from core.services.report_natal_fallback import fallback_natal_interpretation

        payload = fallback_natal_interpretation(
            {
                "factual": {
                    "natal": {
                        "has_birth_time": False,
                        "points": [
                            {"key": "sun", "name": "Солнце", "sign": "gemini", "sign_ru": "Близнецы", "house": 7},
                            {"key": "moon", "name": "Луна", "sign": "taurus", "sign_ru": "Телец", "house": 6},
                            {"key": "ascendant", "name": "Асцендент", "sign": "scorpio", "sign_ru": "Скорпион"},
                        ],
                    }
                }
            }
        )
        self.assertFalse(any(row["point_key"] == "ascendant" for row in payload["placements"]))
        self.assertTrue(payload["limitations"])
        self.assertIn("не читаем", payload["big_three"]["ascendant"]["headline"].lower())

    def test_natal_library_covers_semantic_units(self):
        from core.services.report_natal_fallback import load_natal_fallback_library

        library = load_natal_fallback_library()
        self.assertEqual(len(library["placements"]), 84)
        self.assertEqual(len(library["ascendants"]), 12)
        self.assertEqual(len(library["house_modifiers"]), 12)
        self.assertEqual(len(library["theme_synthesis"]), 16)

    def test_natal_normalize_does_not_field_merge(self):
        from core.services.report_natal import normalize_natal_payload
        from core.services.report_natal_fallback import fallback_natal_interpretation

        document = {
            "factual": {
                "natal": {
                    "has_birth_time": True,
                    "points": [
                        {"key": "sun", "name": "Солнце", "sign": "gemini", "sign_ru": "Близнецы", "house": 7},
                        {"key": "moon", "name": "Луна", "sign": "taurus", "sign_ru": "Телец", "house": 6},
                    ],
                }
            }
        }
        fallback = fallback_natal_interpretation(document)
        mixed = normalize_natal_payload(
            {
                "core_portrait": {"headline": "Только заголовок"},
                "big_three": {
                    "sun": {"headline": "Солнце модели", "body": ""},
                },
            },
            fallback,
        )
        self.assertEqual(mixed["source"], "fallback")
        self.assertEqual(mixed["placements"][0]["key"], "sun_gemini")
        self.assertNotEqual(mixed["core_portrait"]["headline"], "Только заголовок")

    def test_sealed_llm_layer_survives_cache_key_change(self):
        from types import SimpleNamespace

        from core.services.report_aspects import cached_aspects_layer
        from core.services.report_cycles import cached_cycles_layer
        from core.services.report_natal import cached_natal_layer
        from core.services.report_practice import cached_practice_layer
        from core.services.report_request import cached_request_layer

        document = {"factual": {"natal": {"points": [], "aspects": []}, "sky": {"datetime_utc": "2099-01-01T00:00:00Z"}}}
        order = SimpleNamespace(
            interpretive={
                "natal": {
                    "status": "ready",
                    "source": "llm",
                    "cache_key": "stale-key",
                    "payload": {"core_portrait": {"headline": "Sealed", "summary": "x" * 50}},
                },
                "aspects": {
                    "status": "ready",
                    "source": "llm",
                    "cache_key": "stale-key",
                    "payload": {"aspects": [{"aspect_id": "a1", "summary": "x" * 50}]},
                },
                "cycles": {
                    "status": "ready",
                    "source": "llm",
                    "cache_key": "stale-key",
                    "payload": {"report_type": "current_cycles", "primary_cycles": []},
                },
                "request": {
                    "status": "ready",
                    "source": "llm",
                    "cache_key": "stale-key",
                    "payload": {
                        "report_type": "request",
                        "request": {"title": "Sealed request", "text": "x" * 50},
                    },
                },
                "practice": {
                    "status": "ready",
                    "source": "llm",
                    "cache_key": "stale-key",
                    "payload": {
                        "report_type": "practice",
                        "start_here": {"headline": "Sealed practice", "text": "x" * 50},
                    },
                },
            }
        )
        self.assertEqual(cached_natal_layer(order, document)["payload"]["core_portrait"]["headline"], "Sealed")
        self.assertEqual(cached_aspects_layer(order, document)["payload"]["aspects"][0]["aspect_id"], "a1")
        self.assertEqual(cached_cycles_layer(order, document)["payload"]["report_type"], "current_cycles")
        self.assertEqual(
            cached_request_layer(order, document)["payload"]["request"]["title"],
            "Sealed request",
        )
        self.assertEqual(
            cached_practice_layer(order, document)["payload"]["start_here"]["headline"],
            "Sealed practice",
        )

        order.interpretive["natal"]["source"] = "fallback"
        self.assertIsNone(cached_natal_layer(order, document))
        order.interpretive["request"]["source"] = "fallback"
        self.assertIsNone(cached_request_layer(order, document))
        order.interpretive["practice"]["source"] = "fallback"
        self.assertIsNone(cached_practice_layer(order, document))


class AspectsFallbackCopyTests(TestCase):
    def test_aspects_fallback_is_skill_shaped_and_natal_not_transit(self):
        from core.services.report_aspects import fallback_aspects_interpretation
        from core.services.report_aspects_fallback import category_for

        document = {
            "factual": {
                "natal": {
                    "has_birth_time": True,
                    "points": [
                        {"key": "sun", "name": "Солнце", "sign": "gemini", "house": 7},
                        {"key": "moon", "name": "Луна", "sign": "taurus", "house": 6},
                        {"key": "mercury", "name": "Меркурий", "sign": "leo", "house": 9},
                        {"key": "saturn", "name": "Сатурн", "sign": "pisces", "house": 4},
                        {"key": "uranus", "name": "Уран", "sign": "gemini", "house": 7},
                    ],
                    "aspects": [
                        {
                            "id": "natal_mercury_square_saturn",
                            "a": "mercury",
                            "b": "saturn",
                            "a_name": "Меркурий",
                            "b_name": "Сатурн",
                            "aspect": "square",
                            "aspect_ru": "квадрат",
                            "kind": "hard",
                            "orb": 1.2,
                        },
                        {
                            "id": "natal_moon_trine_venus",
                            "a": "moon",
                            "b": "sun",
                            "a_name": "Луна",
                            "b_name": "Солнце",
                            "aspect": "trine",
                            "aspect_ru": "тригон",
                            "kind": "soft",
                            "orb": 2.4,
                        },
                        {
                            "id": "natal_sun_conjunction_uranus",
                            "a": "sun",
                            "b": "uranus",
                            "a_name": "Солнце",
                            "b_name": "Уран",
                            "aspect": "conjunction",
                            "aspect_ru": "соединение",
                            "kind": "hard",
                            "orb": 0.6,
                        },
                    ],
                }
            }
        }
        payload = fallback_aspects_interpretation(document)
        self.assertEqual(payload["report_type"], "natal_aspects")
        self.assertEqual(payload["source"], "fallback")
        by_id = {row["aspect_id"]: row for row in payload["aspects"]}
        square = by_id["natal_mercury_square_saturn"]
        self.assertEqual(square["category"], "tension")
        self.assertEqual(square["unit_key"], "mercury_square_saturn")
        self.assertEqual(square["source"], "semantic_fallback")
        self.assertIn("мысль", square["headline"].lower())
        self.assertGreater(len(square["summary"]), 80)
        self.assertGreaterEqual(len(square["deep_read"]), 2)
        self.assertGreaterEqual(len(square["reflection_questions"]), 1)
        self.assertTrue(square["resource"])
        self.assertTrue(square["blind_spot"])
        self.assertNotIn("Транзит", square["summary"])
        self.assertNotIn("сейчас этот аспект активирован", square["summary"].lower())
        self.assertEqual(by_id["natal_moon_trine_venus"]["category"], "resource")
        self.assertEqual(by_id["natal_sun_conjunction_uranus"]["unit_key"], "sun_conjunction_uranus")
        self.assertEqual(by_id["natal_sun_conjunction_uranus"]["category"], "mixed")
        self.assertEqual(category_for("square"), "tension")
        self.assertEqual(category_for("trine"), "resource")
        self.assertEqual(category_for("conjunction"), "mixed")

    def test_aspects_canonical_pair_and_no_field_merge(self):
        from core.services.report_aspects import normalize_aspects_payload
        from core.services.report_aspects_fallback import (
            canonical_unit_key,
            fallback_aspects_interpretation,
            load_aspects_fallback_library,
        )

        self.assertEqual(canonical_unit_key("mars", "sun", "square"), "sun_square_mars")
        self.assertEqual(canonical_unit_key("ascendant", "sun", "square"), "sun_square_asc")
        library = load_aspects_fallback_library()
        self.assertEqual(len(library["aspects"]), 325)
        self.assertEqual(len(library["theme_syntheses"]), 12)

        document = {
            "factual": {
                "natal": {
                    "has_birth_time": False,
                    "points": [
                        {"key": "sun", "name": "Солнце", "sign": "leo"},
                        {"key": "mars", "name": "Марс", "sign": "aries"},
                        {"key": "ascendant", "name": "Асцендент", "sign": "scorpio"},
                    ],
                    "aspects": [
                        {
                            "id": "natal_mars_square_sun",
                            "a": "mars",
                            "b": "sun",
                            "a_name": "Марс",
                            "b_name": "Солнце",
                            "aspect": "square",
                            "aspect_ru": "квадрат",
                            "orb": 1.1,
                        },
                        {
                            "id": "natal_sun_square_asc",
                            "a": "sun",
                            "b": "ascendant",
                            "a_name": "Солнце",
                            "b_name": "Асцендент",
                            "aspect": "square",
                            "aspect_ru": "квадрат",
                            "orb": 0.8,
                        },
                    ],
                }
            }
        }
        payload = fallback_aspects_interpretation(document)
        keys = [row["unit_key"] for row in payload["aspects"]]
        self.assertEqual(keys, ["sun_square_mars"])
        mixed = normalize_aspects_payload(
            {
                "intro": {"headline": "Только заголовок"},
                "aspects": [
                    {
                        "aspect_id": "natal_mars_square_sun",
                        "headline": "Заголовок модели",
                        "summary": "",
                    }
                ],
            },
            payload,
        )
        self.assertEqual(mixed["source"], "fallback")
        self.assertEqual(mixed["aspects"][0]["unit_key"], "sun_square_mars")
        self.assertNotEqual(mixed["intro"]["headline"], "Только заголовок")

    def test_blueprint_exposes_aspects_layer(self):
        from core.services.report_blueprint import build_report_document

        document = build_report_document(
            natal={
                "has_birth_time": True,
                "planets": {
                    "sun": {"sign": "gemini", "sign_ru": "Близнецы", "sign_index": 2, "degree": 5.0, "house": 7},
                    "moon": {"sign": "taurus", "sign_ru": "Телец", "sign_index": 1, "degree": 12.0, "house": 6},
                },
                "ascendant": {"sign": "scorpio", "sign_ru": "Скорпион", "sign_index": 7, "degree": 5.0},
                "houses": [{"house": i + 1, "sign": "scorpio", "sign_ru": "Скорпион"} for i in range(12)],
            },
            sky_now={"datetime_utc": "2026-08-17T12:00:00Z", "planets": {}},
        )
        layer = document["interpretive"]["aspects"]
        self.assertEqual(layer["source"], "fallback")
        self.assertEqual(layer["payload"]["report_type"], "natal_aspects")
        self.assertTrue(layer["payload"]["intro"]["summary"])


class ReaderVoiceTests(TestCase):
    def test_quiz_gender_becomes_grammatical_gender(self):
        from core.services.report_accents import grammatical_gender, reader_voice

        self.assertEqual(grammatical_gender({"gender": "female"}), "feminine")
        self.assertEqual(grammatical_gender({"gender": "male"}), "masculine")
        self.assertEqual(grammatical_gender({}), "unspecified")
        self.assertEqual(
            reader_voice({"gender": "female"}),
            {"address": "ты", "grammatical_gender": "feminine"},
        )

    def test_natal_and_aspects_llm_user_pass_reader_gender(self):
        from core.services.report_aspects import _aspects_llm_user
        from core.services.report_natal import _natal_llm_user

        document = {
            "quiz": {"gender": "female", "focus_labels": ["любовь"], "intent_label": ""},
            "factual": {
                "natal": {
                    "has_birth_time": True,
                    "house_system": "placidus",
                    "points": [
                        {
                            "key": "sun",
                            "name": "Солнце",
                            "sign": "gemini",
                            "sign_ru": "Близнецы",
                            "house": 7,
                            "degree": 5.0,
                        }
                    ],
                    "aspects": [
                        {
                            "id": "natal_mercury_square_saturn",
                            "a": "mercury",
                            "b": "saturn",
                            "a_name": "Меркурий",
                            "b_name": "Сатурн",
                            "aspect": "square",
                            "aspect_ru": "квадрат",
                            "kind": "hard",
                            "orb": 1.2,
                        }
                    ],
                    "houses": [],
                }
            },
        }
        natal_user = _natal_llm_user(document)
        self.assertEqual(natal_user["reader"]["address"], "ты")
        self.assertEqual(natal_user["reader"]["grammatical_gender"], "feminine")
        aspects_user = _aspects_llm_user(document)
        self.assertEqual(aspects_user["reader"]["grammatical_gender"], "feminine")
        from core.services.report_cycles import _cycles_llm_user

        cycles_user = _cycles_llm_user(document)
        self.assertEqual(cycles_user["reader"]["grammatical_gender"], "feminine")


class CyclesFallbackCopyTests(TestCase):
    def _cycle_document(self, *hits, has_birth_time=True):
        primary = list(hits)
        return {
            "accents": {
                "primary": primary,
                "pressure": [],
                "resource": [],
                "supporting": [],
                "upcoming": [],
            },
            "factual": {"natal": {"has_birth_time": has_birth_time}},
        }

    def _uranus_sun(self, **overrides):
        row = {
            "id": "t_uranus_conjunction_sun",
            "transit": "uranus",
            "transit_name": "Уран",
            "natal": "sun",
            "natal_name": "Солнце",
            "aspect": "conjunction",
            "aspect_ru": "соединение",
            "polarity": "mixed",
            "orb": 0.56,
            "motion": "separating",
            "weight_hint": 0.94,
            "fact": "Уран в соединении с Солнцем.",
            "window": {"span_note": "волнами 12–18 месяцев", "peak_estimate": None},
        }
        row.update(overrides)
        return row

    def test_cycles_fallback_is_skill_shaped_and_natal_not_transit_mix(self):
        from core.services.report_cycles import fallback_cycles_interpretation
        from core.services.report_cycles_fallback import category_for_polarity

        payload = fallback_cycles_interpretation(self._cycle_document(self._uranus_sun()))
        self.assertEqual(payload["report_type"], "current_cycles")
        self.assertEqual(payload["source"], "fallback")
        self.assertTrue(payload["period_overview"]["headline"])
        card = payload["primary_cycles"][0]
        self.assertEqual(card["cycle_id"], "t_uranus_conjunction_sun")
        self.assertEqual(card["unit_key"], "uranus_conjunction_sun")
        self.assertEqual(card["source"], "semantic_fallback")
        self.assertEqual(card["category"], "mixed")
        self.assertGreater(len(card["summary"]), 80)
        self.assertGreaterEqual(len(card["deep_read"]), 2)
        self.assertTrue(card["protective_hypothesis"])
        self.assertTrue(card["resource"])
        self.assertTrue(card["tension_or_blind_spot"])
        self.assertGreaterEqual(len(card["reflection_questions"]), 1)
        self.assertNotIn("натальный квадрат", card["summary"].lower())
        self.assertNotIn("Слепая зона периода", card["summary"])
        self.assertNotIn("ломает характер", json.dumps(card, ensure_ascii=False))
        self.assertEqual(category_for_polarity("pressure"), "tension")
        self.assertEqual(category_for_polarity("resource"), "support")

    def test_cycles_canonical_and_fast_transit_factual(self):
        from core.services.report_cycles_fallback import (
            canonical_unit_key,
            fallback_cycles_interpretation,
            load_cycles_fallback_library,
        )

        self.assertEqual(canonical_unit_key("uranus", "conjunction", "sun"), "uranus_conjunction_sun")
        self.assertEqual(canonical_unit_key("saturn", "square", "ascendant"), "saturn_square_asc")
        library = load_cycles_fallback_library()
        self.assertEqual(len(library["units_by_id"]), 300)
        self.assertEqual(len(library["theme_synthesis"]), 8)

        payload = fallback_cycles_interpretation(
            self._cycle_document(
                {
                    "id": "t_sun_square_mars",
                    "transit": "sun",
                    "transit_name": "Солнце",
                    "natal": "mars",
                    "natal_name": "Марс",
                    "aspect": "square",
                    "aspect_ru": "квадрат",
                    "polarity": "pressure",
                    "orb": 1.2,
                    "motion": "applying",
                    "weight_hint": 0.4,
                    "fact": "Солнце в квадрате к Марсу.",
                    "window": {},
                }
            )
        )
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("Чтобы наблюдать тему, а не ждать события", blob)
        self.assertNotIn("ломает характер", blob)
        card = payload["primary_cycles"][0]
        self.assertEqual(card["source"], "factual_fallback")
        self.assertEqual(card["unit_key"], "sun_square_mars")
        self.assertTrue(card["short_explanation"])
        self.assertEqual(card["protective_function"], "")
        self.assertEqual(len(card["reflection_questions"]), 1)

    def test_accept_llm_does_not_fill_empty_skill_fields(self):
        from core.services.report_cycles import (
            accept_generated_cycles,
            fallback_cycles_interpretation,
        )

        fallback = fallback_cycles_interpretation(self._cycle_document(self._uranus_sun()))
        cid = fallback["primary_cycles"][0]["cycle_id"]
        accepted = accept_generated_cycles(
            {
                "period_overview": {
                    "headline": "Период модели",
                    "summary": "Сгенерированный обзор текущего неба без фолбэка.",
                },
                "primary_cycles": [
                    {
                        "cycle_id": cid,
                        "summary": (
                            "Сгенерированный текст цикла достаточно длинный, "
                            "чтобы пройти валидацию слоя интерпретации."
                        ),
                        "protective_function": "",
                        "tension_or_blind_spot": "",
                        "resource": "",
                        "how_to_work": "",
                    }
                ],
            },
            fallback,
        )
        self.assertIsNotNone(accepted)
        card = accepted["primary_cycles"][0]
        self.assertEqual(card["source"], "llm")
        self.assertEqual(card["protective_function"], "")
        self.assertEqual(card["tension_or_blind_spot"], "")
        self.assertEqual(card["how_to_work"], "")
        self.assertNotIn("Слепая зона периода", card["tension_or_blind_spot"])
        self.assertNotEqual(card["summary"], fallback["primary_cycles"][0]["summary"])

    def test_invalid_llm_payload_is_rejected(self):
        from core.services.report_cycles import (
            accept_generated_cycles,
            fallback_cycles_interpretation,
        )

        fallback = fallback_cycles_interpretation(self._cycle_document(self._uranus_sun()))
        self.assertIsNone(
            accept_generated_cycles(
                {
                    "period_overview": {"headline": "Период модели", "summary": "Есть обзор."},
                    "primary_cycles": [],
                },
                fallback,
            )
        )
        self.assertIsNone(
            accept_generated_cycles(
                {
                    "period_overview": {
                        "headline": "Период модели",
                        "summary": "Сгенерированный обзор текущего неба без фолбэка.",
                    },
                    "primary_cycles": [
                        {
                            "cycle_id": fallback["primary_cycles"][0]["cycle_id"],
                            "summary": "коротко",
                        }
                    ],
                },
                fallback,
            )
        )

    @patch("core.services.report_cycles.llm_client.is_configured", return_value=True)
    @patch("core.services.report_cycles.llm_client.chat_json")
    def test_generate_failure_keeps_whole_fallback(self, chat_json, _configured):
        from core.services import llm_client
        from core.services.report_cycles import generate_cycles_interpretation

        chat_json.side_effect = llm_client.LLMError("upstream")
        result = generate_cycles_interpretation(self._cycle_document(self._uranus_sun()))
        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], "fallback")
        self.assertEqual(result["generation_status"], "generation_failed")
        card = result["payload"]["primary_cycles"][0]
        self.assertEqual(card["source"], "semantic_fallback")
        self.assertTrue(card["protective_hypothesis"])

    @patch("core.services.report_cycles.llm_client.is_configured", return_value=True)
    @patch("core.services.report_cycles.llm_client.chat_json")
    def test_invalid_llm_generate_does_not_frankenstein(self, chat_json, _configured):
        from core.services.report_cycles import generate_cycles_interpretation

        chat_json.return_value = {
            "period_overview": {"headline": "Период модели", "summary": "Обзор модели есть."},
            "primary_cycles": [
                {
                    "cycle_id": "t_uranus_conjunction_sun",
                    "summary": "коротко",
                    "protective_function": "",
                }
            ],
        }
        result = generate_cycles_interpretation(self._cycle_document(self._uranus_sun()))
        self.assertEqual(result["source"], "fallback")
        self.assertEqual(result["generation_status"], "generation_failed")
        blob = json.dumps(result["payload"], ensure_ascii=False)
        self.assertNotIn("Слепая зона периода", blob)
        self.assertEqual(result["payload"]["primary_cycles"][0]["source"], "semantic_fallback")

    def test_blueprint_exposes_cycles_layer(self):
        from core.services.report_blueprint import build_report_document

        document = build_report_document(
            natal={
                "has_birth_time": True,
                "planets": {
                    "sun": {"sign": "gemini", "sign_ru": "Близнецы", "sign_index": 2, "degree": 5.0, "house": 7},
                    "moon": {"sign": "taurus", "sign_ru": "Телец", "sign_index": 1, "degree": 12.0, "house": 6},
                },
                "ascendant": {"sign": "scorpio", "sign_ru": "Скорпион", "sign_index": 7, "degree": 5.0},
                "houses": [{"house": i + 1, "sign": "scorpio", "sign_ru": "Скорпион"} for i in range(12)],
            },
            sky_now={"datetime_utc": "2026-08-17T12:00:00Z", "planets": {}},
        )
        layer = document["interpretive"]["cycles"]
        self.assertEqual(layer["source"], "fallback")
        self.assertEqual(layer["generation_status"], "fallback")
        self.assertEqual(layer["payload"]["report_type"], "current_cycles")
        self.assertEqual(layer["payload"]["source"], "fallback")
        self.assertTrue(layer["payload"]["period_overview"]["summary"])
        for card in layer["payload"]["primary_cycles"]:
            self.assertIn(card["source"], {"semantic_fallback", "factual_fallback"})


class RequestFallbackCopyTests(TestCase):
    def _request_document(self) -> dict:
        return {
            "quiz": {
                "focus": ["love", "path"],
                "focus_labels": ["отношения", "путь"],
                "life_stage": "many-spheres",
                "life_stage_label": "многое меняется сразу",
                "intent": "potential",
                "intent_label": "понять свой потенциал",
                "astrology_trigger": "understand-self",
                "astrology_trigger_label": "хочу лучше понять себя",
            },
            "accents": {
                "primary": [
                    {
                        "id": "t_uranus_square_sun",
                        "transit_name": "Уран",
                        "aspect_ru": "квадрат",
                        "natal_name": "Солнце",
                        "natal_house": 7,
                        "fact": "Транзитный Уран в квадрате к натальному Солнцу.",
                        "theme_tags": ["freedom_and_commitment"],
                    }
                ],
                "resource": [
                    {
                        "id": "t_jupiter_trine_venus",
                        "transit_name": "Юпитер",
                        "aspect_ru": "тригон",
                        "natal_name": "Венера",
                        "fact": "Транзитный Юпитер в тригоне к Венере.",
                        "theme_tags": ["growth_and_limits"],
                    }
                ],
                "pressure": [],
            },
            "interpretive": {
                "aspects": {
                    "payload": {
                        "aspects": [
                            {
                                "aspect_id": "natal_mercury_square_saturn",
                                "category": "tension",
                                "priority": 9,
                                "theme_tags": ["mind_and_structure", "self_doubt_and_action"],
                                "headline": "Мысль против структуры",
                                "summary": "Натальный Меркурий в квадрате к Сатурну.",
                            }
                        ]
                    }
                },
                "cycles": {
                    "payload": {
                        "primary_cycles": [
                            {
                                "cycle_id": "t_uranus_square_sun",
                                "category": "pressure",
                                "priority": 10,
                                "theme_tags": ["freedom_and_commitment", "change"],
                                "technical_title": "Уран □ Солнце",
                                "headline": "Свобода и форма",
                            }
                        ],
                        "secondary_cycles": [],
                    }
                },
                "natal": {
                    "payload": {
                        "core_portrait": {
                            "headline": "Портрет",
                            "summary": "Краткий портрет.",
                            "theme_tags": ["self_understanding"],
                        }
                    }
                },
            },
            "factual": {
                "natal": {
                    "aspects": [
                        {
                            "id": "natal_mercury_square_saturn",
                            "a": "mercury",
                            "b": "saturn",
                            "a_name": "Меркурий",
                            "b_name": "Сатурн",
                            "aspect": "square",
                            "aspect_ru": "квадрат",
                            "kind": "hard",
                        }
                    ]
                }
            },
        }

    def test_request_fallback_uses_preauthored_blocks(self):
        from core.services.report_request_fallback import (
            fallback_request_interpretation,
            load_request_fallback_library,
        )

        library = load_request_fallback_library()
        self.assertEqual(len(library["canonical_themes"]), 16)
        self.assertIn("relationships", library["focus_sentences"])

        payload = fallback_request_interpretation(self._request_document())
        self.assertEqual(payload["report_type"], "request")
        self.assertEqual(payload["source"], "semantic_fallback")
        self.assertGreaterEqual(len(payload["request"]["title"]), 4)
        self.assertGreaterEqual(len(payload["request"]["text"]), 40)
        self.assertGreaterEqual(len(payload["connections"]), 2)
        self.assertLessEqual(len(payload["connections"]), 3)
        for row in payload["connections"]:
            self.assertTrue(row["title"])
            self.assertGreaterEqual(len(row["text"]), 40)
            self.assertIn(row["source_type"], {"cycle", "aspect", "natal_theme"})
            self.assertTrue(row.get("canonical_theme"))
        distinction = payload["core_distinction"]
        self.assertTrue(distinction["title"])
        self.assertGreaterEqual(len(distinction["text"]), 40)
        self.assertTrue(distinction.get("canonical_theme") or distinction.get("provenance"))
        self.assertGreaterEqual(len(payload["resource"]["text"]), 40)
        self.assertGreaterEqual(len(payload["takeaway"]), 40)
        # Whole blocks from library, not Lego quiz labels alone.
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("В фокусе: отношения, путь", blob)

    def test_blueprint_exposes_request_semantic_fallback(self):
        from core.services.report_blueprint import build_report_document

        document = build_report_document(
            natal={
                "has_birth_time": True,
                "planets": {
                    "sun": {"sign": "gemini", "sign_ru": "Близнецы", "sign_index": 2, "degree": 5.0, "house": 7},
                    "moon": {"sign": "taurus", "sign_ru": "Телец", "sign_index": 1, "degree": 12.0, "house": 6},
                },
                "ascendant": {"sign": "scorpio", "sign_ru": "Скорпион", "sign_index": 7, "degree": 5.0},
                "houses": [{"house": i + 1, "sign": "scorpio", "sign_ru": "Скорпион"} for i in range(12)],
            },
            sky_now={"datetime_utc": "2026-08-17T12:00:00Z", "planets": {}},
            quiz={
                "focus": ["love"],
                "focus_labels": ["отношения"],
                "life_stage": "transition",
                "intent": "potential",
                "intent_label": "понять свой потенциал",
            },
        )
        layer = document["interpretive"]["request"]
        self.assertEqual(layer["source"], "fallback")
        payload = layer["payload"]
        self.assertEqual(payload["report_type"], "request")
        self.assertEqual(payload["source"], "semantic_fallback")
        self.assertTrue(payload["request"]["text"])
        self.assertGreaterEqual(len(payload["connections"]), 2)


class PracticeFallbackCopyTests(TestCase):
    def test_practice_selects_whole_module_from_request_theme(self):
        from core.services.report_practice_fallback import (
            fallback_practice_interpretation,
            load_practice_fallback_library,
        )

        library = load_practice_fallback_library()
        self.assertEqual(len(library["modules"]), 17)
        self.assertIn("generic_uncertainty_and_choice", library["modules"])

        document = {
            "quiz": {
                "intent_label": "понять свой потенциал",
                "focus_labels": ["отношения"],
            },
            "interpretive": {
                "request": {
                    "payload": {
                        "report_type": "request",
                        "source": "semantic_fallback",
                        "request": {"title": "Понять себя", "text": "x" * 50},
                        "connections": [
                            {
                                "source_id": "t_uranus_square_sun",
                                "source_type": "cycle",
                                "canonical_theme": "closeness_and_autonomy",
                                "title": "Близость",
                                "text": "x" * 50,
                            }
                        ],
                        "core_distinction": {
                            "canonical_theme": "control_and_uncertainty",
                            "title": "Ясность ↔ гарантия",
                            "text": "x" * 50,
                            "provenance": ["t_uranus_square_sun"],
                        },
                        "resource": {
                            "source_id": "t_jupiter_trine_venus",
                            "text": "x" * 50,
                        },
                    }
                }
            },
        }
        payload = fallback_practice_interpretation(document)
        self.assertEqual(payload["report_type"], "practice")
        self.assertEqual(payload["source"], "semantic_fallback")
        self.assertEqual(payload["module_id"], "control_and_uncertainty")
        self.assertIn("гарантия", payload["start_here"]["headline"].lower())
        self.assertGreaterEqual(len(payload["start_here"]["text"]), 40)
        self.assertGreaterEqual(len(payload["pattern"]["text"]), 40)
        self.assertGreaterEqual(len(payload["protective_function"]["text"]), 40)
        self.assertGreaterEqual(len(payload["cost"]["text"]), 40)
        self.assertGreaterEqual(len(payload["key_distinctions"]), 1)
        self.assertGreaterEqual(len(payload["reflection_questions"]), 4)
        self.assertGreaterEqual(len(payload["experiment"]["text"]), 40)
        self.assertGreaterEqual(len(payload["observe_over_time"]), 2)
        self.assertIn("понять свой потенциал", payload["values"]["text"].lower())
        self.assertIn("t_uranus_square_sun", payload["provenance"])
        # Whole module, not Lego focus insertion.
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("Не всякое напряжение в теме", blob)

    def test_practice_falls_back_to_generic_without_theme(self):
        from core.services.report_practice_fallback import fallback_practice_interpretation

        payload = fallback_practice_interpretation({"quiz": {}, "interpretive": {}})
        self.assertEqual(payload["module_id"], "generic_uncertainty_and_choice")
        self.assertEqual(payload["source"], "semantic_fallback")
        self.assertTrue(payload["start_here"]["headline"])

    def test_blueprint_exposes_practice_semantic_fallback(self):
        from core.services.report_blueprint import build_report_document

        document = build_report_document(
            natal={
                "has_birth_time": True,
                "planets": {
                    "sun": {"sign": "gemini", "sign_ru": "Близнецы", "sign_index": 2, "degree": 5.0, "house": 7},
                    "moon": {"sign": "taurus", "sign_ru": "Телец", "sign_index": 1, "degree": 12.0, "house": 6},
                },
                "ascendant": {"sign": "scorpio", "sign_ru": "Скорпион", "sign_index": 7, "degree": 5.0},
                "houses": [{"house": i + 1, "sign": "scorpio", "sign_ru": "Скорпион"} for i in range(12)],
            },
            sky_now={"datetime_utc": "2026-08-17T12:00:00Z", "planets": {}},
            quiz={
                "focus": ["love"],
                "focus_labels": ["отношения"],
                "life_stage": "transition",
                "intent": "potential",
                "intent_label": "понять свой потенциал",
            },
        )
        layer = document["interpretive"]["practice"]
        self.assertEqual(layer["source"], "fallback")
        payload = layer["payload"]
        self.assertEqual(payload["report_type"], "practice")
        self.assertEqual(payload["source"], "semantic_fallback")
        self.assertTrue(payload.get("module_id"))
        self.assertGreaterEqual(len(payload["reflection_questions"]), 4)
        self.assertTrue(payload["experiment"]["text"])


class ReportBlueprintTests(TestCase):
    def test_uranus_sun_conjunction_is_primary_and_prompt_exists(self):
        from core.services.report_blueprint import build_report_document, load_paid_report_prompt
        from core.services.llm_prompts import load_prompt
        from core.services.report_facts import transits_now

        natal = {
            "engine": "swiss_ephemeris",
            "has_birth_time": True,
            "planets": {
                "sun": {"sign": "leo", "sign_ru": "Лев", "sign_index": 4, "degree": 6.0, "house": 10},
                "moon": {"sign": "capricorn", "sign_ru": "Козерог", "sign_index": 9, "degree": 12.0, "house": 4},
                "mercury": {"sign": "leo", "sign_ru": "Лев", "sign_index": 4, "degree": 10.0, "house": 10},
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
        self.assertIn("aspects", payload["output"]["sections"])
        self.assertIn("cycles", payload["output"]["sections"])
        self.assertIn("request", payload["output"]["sections"])
        self.assertIn("practice", payload["output"]["sections"])
        self.assertEqual(
            [tab["id"] for tab in document["presentation"]["web"]["tabs"]],
            ["natal", "aspects", "cycles", "request", "practice"],
        )
        self.assertEqual(document["schema_version"], 4)
        self.assertEqual(document["sections"]["aspects"]["title"], "Аспекты")
        self.assertEqual(document["sections"]["cycles"]["title"], "Циклы")
        self.assertEqual(document["sections"]["request"]["title"], "Запрос")
        self.assertEqual(document["sections"]["practice"]["title"], "Практика")
        self.assertTrue(
            any("внутренн" in block["text"] for block in document["sections"]["aspects"]["blocks"])
        )
        self.assertTrue(document["factual"]["natal"]["wheel"]["planets"])
        prompt = load_paid_report_prompt()
        self.assertIn("сквозная линия", prompt.lower())
        self.assertIn("Не пересчитывай небо", prompt)
        self.assertFalse(prompt.lstrip().startswith("---"))
        self.assertNotIn("model:", prompt.split("## Задача", 1)[0])
        self.assertEqual(document["generation"]["model"], "openai/gpt-5.6-terra-pro")
        self.assertEqual(document["generation"]["system_prompt_id"], "paid_report")
        natal_gen = document["generation"]["section_prompts"]["natal"]
        self.assertEqual(natal_gen["system_prompt_id"], "paid_report_natal")
        self.assertEqual(natal_gen["model"], "openai/gpt-5.6-luna-pro")
        natal_prompt = load_prompt("paid_report_natal").body
        self.assertIn("natal interpretation only", natal_prompt)
        self.assertIn("Твой внутренний фундамент", natal_prompt)
        self.assertFalse(natal_prompt.lstrip().startswith("---"))
        self.assertNotIn("icon: book-open", natal_prompt)
        aspects_gen = document["generation"]["section_prompts"]["aspects"]
        cycles_gen = document["generation"]["section_prompts"]["cycles"]
        request_gen = document["generation"]["section_prompts"]["request"]
        practice_gen = document["generation"]["section_prompts"]["practice"]
        self.assertEqual(aspects_gen["system_prompt_id"], "paid_report_aspects")
        self.assertEqual(cycles_gen["system_prompt_id"], "paid_report_cycles")
        self.assertEqual(request_gen["system_prompt_id"], "paid_report_request")
        self.assertEqual(practice_gen["system_prompt_id"], "paid_report_practice")
        aspects_prompt = load_prompt("paid_report_aspects").body
        cycles_prompt = load_prompt("paid_report_cycles").body
        request_prompt = load_prompt("paid_report_request").body
        practice_prompt = load_prompt("paid_report_practice").body
        self.assertIn("текущие транзиты", aspects_prompt)
        self.assertIn("grammatical_gender", aspects_prompt)
        self.assertIn("Natal Aspects Interpreter", aspects_prompt)
        self.assertNotIn("icon: git-branch", aspects_prompt)
        self.assertIn("внутренние аспекты", cycles_prompt)
        self.assertIn("Current Cycles Interpreter", cycles_prompt)
        self.assertNotIn("icon: orbit", cycles_prompt)
        self.assertIn("Запрос", request_prompt)
        self.assertIn("CONNECTIONS", request_prompt)
        self.assertIn("connections", request_prompt)
        self.assertIn("Практика", practice_prompt)
        self.assertIn("start_here", practice_prompt)
        natal_layer = document["interpretive"]["natal"]["payload"]
        self.assertEqual(document["interpretive"]["status"], "fallback")
        self.assertTrue(natal_layer["core_portrait"]["summary"])
        self.assertGreater(len(natal_layer["big_three"]["sun"]["body"]), 120)
        self.assertTrue(any(row["id"] == "mind" for row in natal_layer["sections"]))


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
        self.assertFalse(me.json()["has_paid_report"])
        report = self.client.get(
            "/api/me/report/",
            HTTP_AUTHORIZATION=f"Bearer {data['token']}",
        )
        self.assertEqual(report.status_code, 404)

    def test_start_without_session_token_creates_session(self):
        response = self.client.get("/api/auth/yandex/start/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("oauth.yandex.ru/authorize", response.json()["url"])

    def test_me_has_paid_report_when_order_paid(self):
        user, token = _make_user()
        session = OnboardingSession.objects.create(user=user)
        Order.objects.create(
            idempotency_key="paid-me-1",
            idempotency_request_hash="b" * 64,
            session=session,
            user=user,
            customer_email="buyer@example.com",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.PAID,
        )
        me = self.client.get("/api/me/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.json()["has_paid_report"])

    @patch("core.services.yandex_oauth._get_json")
    @patch("core.services.yandex_oauth._post_form")
    def test_yandex_get_callback_redirects_paid_user_to_account(self, post_form, get_json):
        from core.models import YandexOAuthState

        user, _token = _make_user(email="anna@yandex.ru", yandex_id="99")
        session = OnboardingSession.objects.create(user=user)
        Order.objects.create(
            idempotency_key="paid-ya-1",
            idempotency_request_hash="c" * 64,
            session=session,
            user=user,
            customer_email="anna@yandex.ru",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.PAID,
        )
        YandexOAuthState.objects.create(
            nonce="state-paid",
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
            {"code": "888", "state": "state-paid"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/", response["Location"])
        self.assertIn("#auth=", response["Location"])

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

    def test_expired_token_is_rejected_and_deleted(self):
        _user, key = _make_user()
        token = AuthToken.objects.get(key=key)
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save(update_fields=["expires_at"])
        me = self.client.get("/api/me/", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertEqual(me.status_code, 401)
        self.assertFalse(AuthToken.objects.filter(key=key).exists())

    def test_logout_deletes_token(self):
        _user, key = _make_user()
        response = self.client.post("/api/auth/logout/", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(AuthToken.objects.filter(key=key).exists())

    def test_new_login_revokes_previous_token(self):
        user, key = _make_user()
        issue_auth_token(user)
        self.assertFalse(AuthToken.objects.filter(key=key).exists())
        self.assertEqual(AuthToken.objects.filter(user=user).count(), 1)

    @override_settings(DEBUG=True)
    def test_dev_reset_deletes_orders(self):
        user, key = _make_user()
        session = OnboardingSession.objects.create(user=user)
        Order.objects.create(
            idempotency_key="dev-reset-1",
            idempotency_request_hash="d" * 64,
            session=session,
            user=user,
            customer_email="buyer@example.com",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.PAID,
        )
        response = self.client.post("/api/me/dev-reset/", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Order.objects.filter(user=user).exists())
        me = self.client.get("/api/me/", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertFalse(me.json()["has_paid_report"])

    @override_settings(DEBUG=False)
    def test_dev_reset_hidden_when_not_debug(self):
        _user, key = _make_user()
        response = self.client.post("/api/me/dev-reset/", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertEqual(response.status_code, 404)

    @override_settings(AUTH_TOKEN_TTL_DAYS=7)
    def test_token_ttl_is_seven_days(self):
        _user, key = _make_user()
        token = AuthToken.objects.get(key=key)
        delta = token.expires_at - token.created_at
        self.assertAlmostEqual(delta.total_seconds(), 7 * 86400, delta=2)

    @override_settings(DEBUG=True)
    def test_dev_login_issues_empty_session(self):
        from core.services.yandex_oauth import get_or_create_dev_user

        user = get_or_create_dev_user()
        session = OnboardingSession.objects.create(user=user)
        Order.objects.create(
            idempotency_key="dev-login-wipe",
            idempotency_request_hash="e" * 64,
            session=session,
            user=user,
            customer_email="dev@localhost",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.PAID,
        )
        response = self.client.post("/api/auth/dev-login/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["token"])
        self.assertFalse(data["user"]["has_paid_report"])
        self.assertFalse(Order.objects.filter(user=user).exists())
        me = self.client.get("/api/me/", HTTP_AUTHORIZATION=f"Bearer {data['token']}")
        self.assertEqual(me.status_code, 200)

    @override_settings(DEBUG=False)
    def test_dev_login_hidden_when_not_debug(self):
        response = self.client.post("/api/auth/dev-login/")
        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=True)
    def test_dev_login_seeds_paid_report(self):
        response = self.client.post(
            "/api/auth/dev-login/",
            {"persona": "report"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["token"])
        self.assertTrue(data["user"]["has_paid_report"])
        report = self.client.get(
            "/api/me/report/",
            HTTP_AUTHORIZATION=f"Bearer {data['token']}",
        )
        self.assertEqual(report.status_code, 200)
        payload = report.json()
        self.assertEqual(payload["status"], "paid")
        self.assertEqual(payload["report"]["schema_version"], 4)
        self.assertEqual(
            [section["id"] for section in payload["report"]["sections"]],
            ["natal", "aspects", "cycles", "request", "practice"],
        )
        quiz = payload["report"]["document"].get("quiz") or {}
        self.assertIn("love", quiz.get("focus") or [])
        self.assertNotIn("name", quiz)
        self.assertNotIn("customer_email", payload)

    @override_settings(DEBUG=True)
    def test_dev_login_seeds_insight_funnel(self):
        response = self.client.post(
            "/api/auth/dev-login/",
            {"persona": "insight"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["token"])
        self.assertTrue(data["session_token"])
        self.assertFalse(data["user"]["has_paid_report"])
        insight = self.client.get(
            f"/api/onboarding/sessions/{data['session_token']}/insight/",
        )
        self.assertEqual(insight.status_code, 200)
        natal = insight.json().get("natal") or {}
        self.assertTrue(natal.get("planets"))
        report = self.client.get(
            "/api/me/report/",
            HTTP_AUTHORIZATION=f"Bearer {data['token']}",
        )
        self.assertEqual(report.status_code, 404)


def _fake_store_chart(chart):
    from django.utils import timezone as dj_tz

    chart.birth_place = chart.birth_place or "Москва"
    chart.birth_lat = chart.birth_lat or Decimal("55.755826")
    chart.birth_lng = chart.birth_lng or Decimal("37.6173")
    chart.timezone = chart.timezone or "Europe/Moscow"
    chart.status = NatalChart.Status.READY
    chart.error_message = ""
    chart.chart_data = {
        "planets": {"sun": {"sign": "leo"}},
        "has_birth_time": bool(chart.birth_time),
        "location": {
            "place": chart.birth_place,
            "lat": float(chart.birth_lat),
            "lng": float(chart.birth_lng),
        },
        "timezone": chart.timezone,
    }
    chart.calculated_at = dj_tz.now()
    chart.save()
    return chart


class AccountCabinetTests(TestCase):
    def setUp(self):
        self.client = APIClient()
    def test_me_uses_given_name_not_email(self):
        user, key = _make_user(email="anna@yandex.ru", yandex_id="7701")
        user.first_name = "Анна"
        user.save(update_fields=["first_name"])
        user.profile.display_name = "Анна"
        user.profile.save(update_fields=["display_name"])
        OnboardingSession.objects.create(
            user=user,
            birth_date=date(1993, 8, 21),
            birth_time=time(9, 45),
            birth_place="Москва",
        )
        me = self.client.get("/api/me/", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertEqual(me.status_code, 200)
        data = me.json()
        self.assertEqual(data["email"], "anna@yandex.ru")
        self.assertEqual(data["display_name"], "Анна")
        self.assertEqual(data["profile"]["display_name"], "Анна")
        self.assertEqual(data["birth"]["birth_date"], "1993-08-21")
        self.assertEqual(data["birth"]["birth_time"], "09:45")
        self.assertEqual(data["birth"]["birth_place"], "Москва")
        self.assertEqual(data["profile"]["birth_date"], "1993-08-21")

    @patch("core.services.account.calculate_and_store_chart", side_effect=_fake_store_chart)
    def test_patch_birth_updates_profile_and_clears_report_layers(self, _mocked):
        user, key = _make_user(email="anna@yandex.ru", yandex_id="7702")
        session = OnboardingSession.objects.create(
            user=user,
            birth_date=date(1993, 8, 21),
            birth_time=time(9, 45),
            birth_place="Москва",
        )
        order = Order.objects.create(
            idempotency_key="birth-edit-1",
            idempotency_request_hash="e" * 64,
            session=session,
            user=user,
            customer_email="anna@yandex.ru",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.PAID,
            interpretive={"natal": {"source": "llm"}, "generation": {"status": "done"}},
        )
        response = self.client.patch(
            "/api/me/birth/",
            {
                "birth_date": "26.05.1995",
                "birth_time": "19:25",
                "birth_place": "Санкт-Петербург",
                "birth_lat": "59.9386",
                "birth_lng": "30.3141",
                "timezone": "Europe/Moscow",
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["birth"]["birth_date"], "1995-05-26")
        self.assertEqual(data["birth"]["birth_time"], "19:25")
        self.assertEqual(data["birth"]["birth_place"], "Санкт-Петербург")
        user.profile.refresh_from_db()
        session.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(user.profile.birth_date, date(1995, 5, 26))
        self.assertEqual(session.birth_date, date(1995, 5, 26))
        self.assertEqual(session.birth_time, time(19, 25))
        self.assertEqual(order.interpretive, {})

    @patch("core.services.account.calculate_and_store_chart", side_effect=_fake_store_chart)
    def test_patch_birth_can_clear_time(self, _mocked):
        user, key = _make_user(email="anna@yandex.ru", yandex_id="7703")
        session = OnboardingSession.objects.create(
            user=user,
            birth_date=date(1993, 8, 21),
            birth_time=time(9, 45),
            birth_place="Москва",
        )
        response = self.client.patch(
            "/api/me/birth/",
            {
                "birth_date": "1993-08-21",
                "unknown_time": True,
                "birth_place": "Москва",
                "birth_lat": "55.75",
                "birth_lng": "37.61",
                "timezone": "Europe/Moscow",
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["birth"]["has_birth_time"])
        self.assertIsNone(response.json()["birth"]["birth_time"])
        session.refresh_from_db()
        self.assertIsNone(session.birth_time)

    def test_delete_account_removes_user(self):
        user, key = _make_user(email="gone@yandex.ru", yandex_id="7704")
        session = OnboardingSession.objects.create(user=user)
        Order.objects.create(
            idempotency_key="delete-me-1",
            idempotency_request_hash="f" * 64,
            session=session,
            user=user,
            customer_email="gone@yandex.ru",
            product_sku="personal_report",
            product_name="Персональный разбор Cosmirror",
            amount=Decimal("777.00"),
            status=Order.Status.PAID,
        )
        WaitlistLead.objects.create(email="gone@yandex.ru", user=user)
        response = self.client.delete("/api/me/", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(AuthToken.objects.filter(key=key).exists())
        self.assertFalse(Order.objects.filter(idempotency_key="delete-me-1").exists())
        self.assertFalse(WaitlistLead.objects.filter(email="gone@yandex.ru").exists())



