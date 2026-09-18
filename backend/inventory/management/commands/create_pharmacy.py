from django.core.management.base import BaseCommand
from inventory.models import Pharmacy, PharmacyApiKey


class Command(BaseCommand):
    help = "Creates a pharmacy tenant and prints its API key once."

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--label", default="Primary")

    def handle(self, *args, **options):
        pharmacy = Pharmacy.objects.create(name=options["name"])
        _, raw_key = PharmacyApiKey.create_key(pharmacy, options["label"])
        self.stdout.write(self.style.SUCCESS(f"Pharmacy created: {pharmacy.id}"))
        self.stdout.write(self.style.WARNING("Save this API key now; it will not be shown again:"))
        self.stdout.write(raw_key)
