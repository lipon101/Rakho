from django.contrib import admin
from .models import Batch, CatalogMedicine, Medicine, Pharmacy, PharmacyApiKey, Sale, SaleAllocation, SaleLine, StockMovement

admin.site.register([Pharmacy, PharmacyApiKey, CatalogMedicine, Medicine, Batch, Sale, SaleLine, SaleAllocation, StockMovement])
