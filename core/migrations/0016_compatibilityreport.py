from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_reportsectionfeedback_admin_labels"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompatibilityReport",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "input_hash",
                    models.CharField(max_length=64, unique=True, verbose_name="Хэш входа"),
                ),
                (
                    "relationship_type",
                    models.CharField(max_length=32, verbose_name="Тип связи"),
                ),
                (
                    "reference_date",
                    models.DateField(verbose_name="Опорная дата транзитов"),
                ),
                (
                    "private_input",
                    models.JSONField(verbose_name="Вход с данными рождения"),
                ),
                (
                    "private_natals",
                    models.JSONField(verbose_name="Две натальные карты"),
                ),
                (
                    "public_document",
                    models.JSONField(verbose_name="Публичный отчёт"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Отчёт совместимости",
                "verbose_name_plural": "Отчёты совместимости",
                "ordering": ["-created_at"],
            },
        ),
    ]
