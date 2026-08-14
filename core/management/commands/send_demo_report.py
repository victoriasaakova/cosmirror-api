from django.core.management.base import BaseCommand, CommandError

from core.models import Order
from core.services.fulfillment import FulfillmentError, mark_paid_and_deliver
from core.services.mailer import MailerError, send_email


class Command(BaseCommand):
    help = "Отправить демо-отчёт Cosmirror на почту (локальный тест без webhook Prodamus)."

    def add_arguments(self, parser):
        parser.add_argument("--order", help="public_id заказа")
        parser.add_argument("--latest", action="store_true", help="Последний заказ")
        parser.add_argument("--email", help="Переопределить адрес или отправить письмо без заказа")
        parser.add_argument("--mark-paid", action="store_true", help="Сначала пометить заказ оплаченным")
        parser.add_argument("--force", action="store_true", help="Отправить даже если уже отправляли")

    def handle(self, *args, **options):
        order_id = options.get("order")
        latest = options.get("latest")
        email = (options.get("email") or "").strip()
        if not order_id and not latest and email:
            send_email(
                to=email,
                subject="Демо-версия астрологического отчёта — Cosmirror",
                text=(
                    "Привет.\n\n"
                    "Это тестовое письмо Cosmirror: демо-версия астрологического отчёта.\n"
                    "Если оно дошло, автоматическая отправка с нашего сервера работает.\n\n"
                    "https://cosmirror.ru\n"
                ),
                html=(
                    "<p>Привет.</p>"
                    "<p>Это тестовое письмо Cosmirror: демо-версия астрологического отчёта.</p>"
                    "<p>Если оно дошло, автоматическая отправка с нашего сервера работает.</p>"
                    "<p><a href=\"https://cosmirror.ru\">cosmirror.ru</a></p>"
                ),
            )
            self.stdout.write(self.style.SUCCESS(f"Тестовое письмо ушло на {email}"))
            return

        if latest:
            order = Order.objects.order_by("-created_at").first()
            if order is None:
                raise CommandError("Заказов ещё нет. Пройди оплату или укажи --email.")
        elif order_id:
            try:
                order = Order.objects.get(public_id=order_id)
            except Order.DoesNotExist as exc:
                raise CommandError("Заказ не найден.") from exc
        else:
            raise CommandError("Укажи --order, --latest или --email.")

        if email:
            order.customer_email = email
            order.save(update_fields=["customer_email", "updated_at"])
        try:
            if options.get("mark_paid") or order.status != Order.Status.PAID:
                sent = mark_paid_and_deliver(order, force=bool(options.get("force")))
            else:
                from core.services.fulfillment import deliver_paid_order

                sent = deliver_paid_order(order, force=bool(options.get("force")))
        except (FulfillmentError, MailerError) as exc:
            raise CommandError(str(exc)) from exc
        if sent:
            self.stdout.write(self.style.SUCCESS(f"Демо-отчёт отправлен на {order.customer_email}"))
        else:
            self.stdout.write("Письмо уже отправляли. Добавь --force, чтобы повторить.")
