from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("racetime", "0085_profileimportcandidate_category_roles"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profileimportcandidate",
            name="twitch_id",
            field=models.BigIntegerField(blank=True, null=True, unique=True),
        ),
    ]
