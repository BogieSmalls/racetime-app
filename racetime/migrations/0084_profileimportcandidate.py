from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("racetime", "0083_alter_goal_options_goal_sort_order"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfileImportCandidate",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "discord_subject",
                    models.CharField(max_length=128, unique=True),
                ),
                (
                    "racetimegg_subject",
                    models.CharField(max_length=128, unique=True),
                ),
                (
                    "twitch_id",
                    models.BigIntegerField(unique=True),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
            ],
            options={"ordering": ("discord_subject",)},
        ),
    ]
