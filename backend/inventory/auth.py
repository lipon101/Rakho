from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import PharmacyApiKey


class PharmacyApiKeyAuthentication(BaseAuthentication):
    keyword = "X-Pharmacy-Key"

    def authenticate(self, request):
        raw_key = request.headers.get(self.keyword)
        if not raw_key:
            return None
        key_hash = PharmacyApiKey.hash_key(raw_key)
        api_key = PharmacyApiKey.objects.select_related("pharmacy").filter(key_hash=key_hash, revoked_at__isnull=True).first()
        if not api_key:
            raise AuthenticationFailed("Invalid or revoked pharmacy API key.")
        return (api_key.pharmacy, api_key)
