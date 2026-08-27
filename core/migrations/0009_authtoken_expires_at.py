from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone


def backfill_expires_at(apps, schema_editor):
    AuthToken = apps.get_model("core", "AuthToken")
    ttl = timedelta(days=30)
    now = timezone.now()
    for token in AuthToken.objects.all().iterator():
        token.expires_at = (token.created_at or now) + ttl
        token.save(update_fields=["expires_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_yandex_oauth_redirect_uri"),
    ]

    operations = [
        migrations.AddField(
            model_name="authtoken",
            name="expires_at",
            field=models.DateTimeField(null=True, verbose_name="Истекает"),
        ),
        migrations.RunPython(backfill_expires_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="authtoken",
            name="expires_at",
            field=models.DateTimeField(verbose_name="Истекает"),
        ),
    ]
