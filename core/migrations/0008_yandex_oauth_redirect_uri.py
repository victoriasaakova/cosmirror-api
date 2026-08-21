from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_yandex_auth"),
    ]

    operations = [
        migrations.AddField(
            model_name="yandexoauthstate",
            name="redirect_uri",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
