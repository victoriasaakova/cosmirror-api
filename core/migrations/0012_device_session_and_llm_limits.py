from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone


def clamp_token_ttl(apps, schema_editor):
    AuthToken = apps.get_model("core", "AuthToken")
    cap = timezone.now() + timedelta(days=2)
    AuthToken.objects.filter(expires_at__gt=cap).update(expires_at=cap)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_reportsectionfeedback"),
    ]

    operations = [
        migrations.AddField(
            model_name="authtoken",
            name="device_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Стабильный id браузера. Пусто — старая сессия, привяжется с первого запроса.",
                max_length=64,
                verbose_name="Устройство",
            ),
        ),
        migrations.AddField(
            model_name="yandexoauthstate",
            name="device_id",
            field=models.CharField(
                blank=True,
                default="",
                max_length=64,
                verbose_name="Устройство",
            ),
        ),
        migrations.CreateModel(
            name="LlmRateBucket",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=160, unique=True)),
                ("window_started_at", models.DateTimeField()),
                ("count", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "Окно лимита LLM",
                "verbose_name_plural": "Окна лимитов LLM",
            },
        ),
        migrations.RunPython(clamp_token_ttl, migrations.RunPython.noop),
    ]
