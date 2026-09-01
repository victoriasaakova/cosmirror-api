from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0010_order_interpretive"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReportSectionFeedback",
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
                (
                    "section",
                    models.CharField(
                        choices=[
                            ("natal", "Твоя карта"),
                            ("aspects", "Аспекты"),
                            ("cycles", "Циклы"),
                            ("request", "Запрос"),
                            ("practice", "Практика"),
                        ],
                        max_length=16,
                        verbose_name="Раздел",
                    ),
                ),
                (
                    "rating",
                    models.CharField(
                        choices=[
                            ("about_me", "Про меня"),
                            ("partial", "Частично"),
                            ("not_about_me", "Не про меня"),
                        ],
                        max_length=16,
                        verbose_name="Оценка",
                    ),
                ),
                ("comment", models.TextField(blank=True, verbose_name="Комментарий")),
                (
                    "comment_skipped",
                    models.BooleanField(default=False, verbose_name="Комментарий отложен"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="section_feedback",
                        to="core.order",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="report_section_feedback",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Фидбэк по разделу отчёта",
                "verbose_name_plural": "Фидбэк по разделам отчёта",
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="reportsectionfeedback",
            constraint=models.UniqueConstraint(
                fields=("order", "section"),
                name="uniq_report_section_feedback",
            ),
        ),
    ]
