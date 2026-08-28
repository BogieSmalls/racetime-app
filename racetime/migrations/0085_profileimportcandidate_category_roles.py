from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("racetime", "0084_profileimportcandidate"),
    ]

    operations = [
        migrations.AddField(
            model_name="profileimportcandidate",
            name="moderated_categories",
            field=models.ManyToManyField(
                blank=True,
                related_name="+",
                to="racetime.category",
            ),
        ),
        migrations.AddField(
            model_name="profileimportcandidate",
            name="owned_categories",
            field=models.ManyToManyField(
                blank=True,
                related_name="+",
                to="racetime.category",
            ),
        ),
    ]
