# Generated manually. Run `python manage.py migrate`.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0004_signuprequest"),
    ]
    operations = [
        migrations.CreateModel(
            name="SignupDailyCount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("ip", models.CharField(db_index=True, max_length=64)),
                ("day", models.DateField(db_index=True)),
                ("count", models.PositiveIntegerField(default=0)),
            ],
        ),
        migrations.AddConstraint(
            model_name="signupdailycount",
            constraint=models.UniqueConstraint(fields=("ip", "day"), name="uniq_signup_ip_day"),
        ),
        migrations.AddIndex(
            model_name="signupdailycount",
            index=models.Index(fields=["ip", "day"], name="inventory_si_ip_day_idx"),
        ),
    ]
