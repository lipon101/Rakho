# Generated manually. Run `python manage.py migrate`.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0003_playpurchaseevent_subscription"),
    ]
    operations = [
        migrations.CreateModel(
            name="SignupRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner_name", models.CharField(max_length=120)),
                ("pharmacy_name", models.CharField(max_length=180)),
                ("whatsapp", models.CharField(blank=True, max_length=32)),
                ("plan", models.CharField(default="free", max_length=16)),
                ("trx_id", models.CharField(blank=True, max_length=64)),
                ("status", models.CharField(
                    choices=[("pending", "Pending review"), ("key_issued", "Key issued (free)"),
                             ("paid_review", "Payment to verify"), ("active", "Active"),
                             ("rejected", "Rejected")],
                    default="pending", max_length=16)),
                ("lookup_token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("note", models.CharField(blank=True, max_length=255)),
                ("pharmacy", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name="signups", to="inventory.pharmacy")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="signuprequest",
            index=models.Index(fields=["status", "-created_at"], name="signupreq_status_created"),
        ),
    ]
