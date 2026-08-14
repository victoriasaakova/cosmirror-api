from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="fulfilled_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Отчёт отправлен"),
        ),
        migrations.AddField(
            model_name="order",
            name="fulfillment_error",
            field=models.TextField(blank=True, verbose_name="Ошибка отправки отчёта"),
        ),
    ]
