from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_order_fulfillment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="payment_url",
            field=models.URLField(
                blank=True, max_length=4000, verbose_name="Ссылка на оплату"
            ),
        ),
    ]
