from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_authtoken_expires_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="interpretive",
            field=models.JSONField(
                blank=True,
                default=dict,
                verbose_name="Слои интерпретации (натал / аспекты / циклы)",
            ),
        ),
    ]
