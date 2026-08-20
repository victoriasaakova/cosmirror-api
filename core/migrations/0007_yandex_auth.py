from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0006_order_payment_url_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="yandex_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=32,
                null=True,
                unique=True,
                verbose_name="Яндекс ID",
            ),
        ),
        migrations.CreateModel(
            name="AuthToken",
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
                ("key", models.CharField(db_index=True, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="auth_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Токен входа",
                "verbose_name_plural": "Токены входа",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="YandexOAuthState",
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
                ("nonce", models.CharField(db_index=True, max_length=64, unique=True)),
                ("code_verifier", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="yandex_oauth_states",
                        to="core.onboardingsession",
                    ),
                ),
            ],
            options={
                "verbose_name": "OAuth state Яндекса",
                "verbose_name_plural": "OAuth state Яндекса",
                "ordering": ["-created_at"],
            },
        ),
    ]
