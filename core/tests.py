from decimal import Decimal
from unittest.mock import patch
from urllib.parse import unquote_plus

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import OnboardingSession, Order, WaitlistLead
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


@override_settings(
    PRODAMUS_FORM_URL="https://cosmirror.payform.ru/",
    PRODAMUS_SECRET_KEY="test-secret",
    PRODAMUS_DEMO_MODE=True,
    FRONTEND_URL="http://localhost:3000",
)
class ShortLinkTests(TestCase):
    @patch("core.services.prodamus.urllib.request.urlopen")
    def test_create_payment_link_uses_do_link(self, mocked_open):
        mocked_open.return_value.__enter__.return_value.read.return_value = (
            b"https://payform.ru/u8zDE/"
        )
        url = create_payment_link(
            order_id="abc-123",
            product_name="Персональный разбор Cosmirror",
            product_price="777.00",
            product_sku="personal_report",
            customer_email="buyer@example.com",
            paid_content="Персональный астрологический отчёт Cosmirror",
        )
        self.assertEqual(url, "https://payform.ru/u8zDE/")
        request = mocked_open.call_args[0][0]
        called = request.full_url
        self.assertIn("do=link", called)
        self.assertNotIn("do=pay", called)
        self.assertNotIn("localhost", called)
        self.assertIn("abc-123", called)
        self.assertIn("paid_content", called)
        self.assertIn("астрологический отчёт", unquote_plus(called))

    def test_do_pay_url_is_stale(self):
        from core.services.orders import _payment_url_is_stale

        self.assertTrue(
            _payment_url_is_stale(
                "https://cosmirror.payform.ru/?do=pay&order_id=1&signature=abc"
            )
        )
        self.assertTrue(_payment_url_is_stale("https://payform.ru/x/?urlSuccess=http://localhost:3000/"))
        self.assertFalse(_payment_url_is_stale("https://payform.ru/u8zDE/"))


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
)
class OrderApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.lead = WaitlistLead.objects.create(
            email="buyer@example.com",
            telegram="buyername",
            name="Вика",
        )
        self.session = OnboardingSession.objects.create(waitlist_lead=self.lead)

    def _create(self, key="idem-key-0001", token=None, **kwargs):
        return self.client.post(
            "/api/orders/",
            {"session_token": str(token or self.session.token)},
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

    @patch("core.services.orders.create_payment_link", return_value="https://payform.ru/u8zDE/")
    def test_creates_order_and_prodamus_link(self, mocked):
        response = self._create()
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["status"], "awaiting_payment")
        self.assertEqual(data["payment_url"], "https://payform.ru/u8zDE/")
        self.assertEqual(data["amount"], "777.00")
        order = Order.objects.get(public_id=data["id"])
        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["order_id"], str(order.public_id))
        self.assertEqual(kwargs["customer_email"], "buyer@example.com")
        self.assertIn("астрологический отчёт", kwargs["paid_content"])

    @patch("core.services.orders.create_payment_link", return_value="https://payform.ru/u8zDE/")
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
        side_effect=["https://payform.ru/old/", "https://payform.ru/fresh/"],
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
        self.assertEqual(again.json()["payment_url"], "https://payform.ru/fresh/")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELED)
        self.assertEqual(mocked.call_count, 2)

    @patch("core.services.orders.create_payment_link", return_value="https://payform.ru/short/")
    def test_stale_do_pay_url_is_rebuilt(self, mocked):
        first = self._create(key="rebuild-key-1")
        self.assertEqual(first.status_code, 201)
        order = Order.objects.get(public_id=first.json()["id"])
        order.payment_url = "https://cosmirror.payform.ru/?do=pay&order_id=old&signature=x"
        order.save(update_fields=["payment_url"])
        mocked.reset_mock()
        again = self._create(key="rebuild-key-1")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["payment_url"], "https://payform.ru/short/")
        mocked.assert_called_once()

    @patch("core.services.orders.create_payment_link", return_value="https://payform.ru/u8zDE/")
    def test_same_key_different_session_conflicts(self, _mocked):
        other = OnboardingSession.objects.create(
            waitlist_lead=WaitlistLead.objects.create(email="other@example.com")
        )
        first = self._create(key="shared-key-1")
        self.assertEqual(first.status_code, 201)
        conflict = self._create(key="shared-key-1", token=other.token)
        self.assertEqual(conflict.status_code, 409)

    @patch("core.services.orders.create_payment_link", return_value="https://payform.ru/paid/")
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
        self.assertIn("Демо-версия", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["buyer@example.com"])
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
