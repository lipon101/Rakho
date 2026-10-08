"""The optional profile + consent endpoint: ``/api/v1/profile/``.

This single view is the server half of the progressive-profiling promise:

* **Nothing is required.** With no rows in the database the GET answers with a
  blank profile whose consents are all ``false`` — the app skips every question
  and still has a working account, because absence *is* the default answer.
* **One question at a time, no forms.** Every field is independently
  patchable, so the app sends exactly the one answer the card collected and
  the server upserts only that. There is no endpoint that accepts a whole
  profile at once, because there is no screen that asks for one.
* **Reject, don't guess.** Unknown keys are refused by name. A privacy
  endpoint that silently ignores fields is how "we never collected that"
  quietly stops being true — and both sides of this API live in this repo, so
  a strict contract keeps the app and the server honest together.
* **Consent is explicit.** ``consents`` takes booleans only, is written to its
  own table with the policy version current at the moment of the toggle, and
  can never be implied by a profile answer.
* **Delete means delete.** ``DELETE`` removes the profile, preferences and
  consent rows in one stroke and answers with the now-blank payload, so the
  caller sees the same state a brand-new account would have. Inventory, sales
  and the login key are untouched — that is account deletion's separate,
  harder job.
"""

import re

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response

from .exceptions import error_response
from .models import UserConsent, UserPreference, UserProfile
from .views import PharmacyScopedAPIView

# Markup and control characters never reach the database, matching the rules
# PharmacySettingsView applies to the shop's own name and address. The licence
# number gets a stricter pattern on top: it is the one field an admin compares
# character-by-character against a paper record.
_MARKUP_RE = re.compile(r"[<>]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LICENSE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 /\-]{0,39}")

_TEXT_FIELDS = {"owner_name": 80, "district": 80, "upazila": 80}
_CHOICE_FIELDS = {
    "shop_type": {""} | set(UserProfile.ShopType.values),
    "role": {""} | set(UserProfile.Role.values),
    "size_range": {""} | set(UserProfile.SizeRange.values),
}
_CONSENT_TYPES = set(UserConsent.Type.values)
_MAX_WHOLESALERS = 10

_ALLOWED_KEYS = set(_TEXT_FIELDS) | set(_CHOICE_FIELDS) | {"license_no", "preferred_wholesalers", "consents"}


def _clean_text(value, max_len, field):
    """Trim, then refuse anything that is not a plain short string."""
    if not isinstance(value, str):
        return "", f"{field} must be text."
    text = value.strip()
    if _MARKUP_RE.search(text):
        return "", f"{field} must not contain HTML or angle brackets."
    if _CTRL_RE.search(text):
        return "", f"{field} must not contain control characters."
    if len(text) > max_len:
        return "", f"{field} must be at most {max_len} characters."
    return text, None


class ProfilePrivacyView(PharmacyScopedAPIView):
    """GET / PATCH / DELETE the optional profile for the caller's own shop."""

    def get(self, request):
        return Response(self._payload(self.pharmacy))

    def patch(self, request):
        data = request.data
        if not isinstance(data, dict):
            return error_response("Body must be a JSON object of profile fields.", status.HTTP_400_BAD_REQUEST)

        unknown = sorted(set(data) - _ALLOWED_KEYS)
        if unknown:
            return error_response(
                f"Unknown field(s): {', '.join(unknown)}. Allowed: {', '.join(sorted(_ALLOWED_KEYS))}.",
                status.HTTP_400_BAD_REQUEST,
            )

        # Validate everything before writing anything: a card that sends two
        # answers with one typo must leave the profile exactly as it was,
        # rather than half-applied.
        profile_updates = {}
        preference_updates = {}
        consent_updates = {}

        for field, max_len in _TEXT_FIELDS.items():
            if field not in data:
                continue
            raw = data[field]
            if raw is None:
                # JSON null means "no value supplied", not "clear this field" —
                # the Android client serialises its whole DTO, and treating
                # null as a wipe would delete an answer on every unrelated edit.
                continue
            value, error = _clean_text(raw, max_len, field)
            if error:
                return error_response(error, status.HTTP_400_BAD_REQUEST)
            profile_updates[field] = value

        for field, allowed in _CHOICE_FIELDS.items():
            if field not in data:
                continue
            raw = data[field]
            if raw is None:
                continue
            if not isinstance(raw, str) or raw not in allowed:
                options = ", ".join(sorted(x for x in allowed if x))
                return error_response(f"{field} must be one of: {options} (or empty to clear).", status.HTTP_400_BAD_REQUEST)
            profile_updates[field] = raw

        if "license_no" in data and data["license_no"] is not None:
            value, error = _clean_text(data["license_no"], 40, "license_no")
            if error:
                return error_response(error, status.HTTP_400_BAD_REQUEST)
            if value and not _LICENSE_RE.fullmatch(value):
                return error_response(
                    "license_no may contain only letters, digits, spaces, slashes and hyphens.",
                    status.HTTP_400_BAD_REQUEST,
                )
            profile_updates["license_no"] = value

        if "preferred_wholesalers" in data and data["preferred_wholesalers"] is not None:
            raw = data["preferred_wholesalers"]
            if not isinstance(raw, list):
                return error_response("preferred_wholesalers must be a list of names.", status.HTTP_400_BAD_REQUEST)
            if len(raw) > _MAX_WHOLESALERS:
                return error_response(f"preferred_wholesalers may hold at most {_MAX_WHOLESALERS} names.", status.HTTP_400_BAD_REQUEST)
            cleaned = []
            for item in raw:
                value, error = _clean_text(item, 80, "preferred_wholesalers")
                if error:
                    return error_response(error, status.HTTP_400_BAD_REQUEST)
                if value:
                    cleaned.append(value)
            # Preserve the tap order, drop repeats from a double-tapped chip.
            preference_updates["preferred_wholesalers"] = list(dict.fromkeys(cleaned))

        if "consents" in data and data["consents"] is not None:
            raw = data["consents"]
            if not isinstance(raw, dict):
                return error_response("consents must be an object of consent_type: true|false.", status.HTTP_400_BAD_REQUEST)
            unknown_types = sorted(set(raw) - _CONSENT_TYPES)
            if unknown_types:
                return error_response(
                    f"Unknown consent type(s): {', '.join(unknown_types)}. Allowed: {', '.join(sorted(_CONSENT_TYPES))}.",
                    status.HTTP_400_BAD_REQUEST,
                )
            for consent_type, granted in raw.items():
                if not isinstance(granted, bool):
                    return error_response(f"consents.{consent_type} must be true or false.", status.HTTP_400_BAD_REQUEST)
                consent_updates[consent_type] = granted

        pharmacy = self.pharmacy

        if profile_updates:
            profile, _ = UserProfile.objects.get_or_create(pharmacy=pharmacy)
            for field, value in profile_updates.items():
                if field == "license_no":
                    # The property setter encrypts; plaintext never lands in
                    # the model, let alone in the row.
                    profile.license_no = value
                else:
                    setattr(profile, field, value)
            profile.save()

        if "preferred_wholesalers" in data:
            preference, _ = UserPreference.objects.get_or_create(pharmacy=pharmacy)
            preference.preferred_wholesalers = preference_updates.get("preferred_wholesalers", preference.preferred_wholesalers)
            preference.save()

        for consent_type, granted in consent_updates.items():
            UserConsent.objects.update_or_create(
                pharmacy=pharmacy,
                type=consent_type,
                defaults={"granted": granted, "policy_version": settings.PRIVACY_POLICY_VERSION},
            )

        return Response(self._payload(pharmacy))

    def delete(self, request):
        """Drop the optional layer only: profile, preferences, consents.

        Inventory, sales, the API key and the pharmacy record stay — this is
        the "take back what I optionally told you" button, not account
        closure.
        """
        pharmacy = self.pharmacy
        UserProfile.objects.filter(pharmacy=pharmacy).delete()
        UserPreference.objects.filter(pharmacy=pharmacy).delete()
        UserConsent.objects.filter(pharmacy=pharmacy).delete()
        return Response(self._payload(pharmacy))

    @staticmethod
    def _payload(pharmacy) -> dict:
        """Everything the settings/privacy screen renders, in one object."""
        profile = UserProfile.objects.filter(pharmacy=pharmacy).first()
        preference = UserPreference.objects.filter(pharmacy=pharmacy).first()

        # Default-deny: absent rows read exactly like an explicit "no".
        consents = dict.fromkeys(UserConsent.Type.values, False)
        for row in UserConsent.objects.filter(pharmacy=pharmacy):
            consents[row.type] = row.granted

        return {
            "owner_name": profile.owner_name if profile else "",
            "district": profile.district if profile else "",
            "upazila": profile.upazila if profile else "",
            "shop_type": profile.shop_type if profile else "",
            "role": profile.role if profile else "",
            "size_range": profile.size_range if profile else "",
            # Decrypted here and nowhere else: the caller already proved
            # ownership of the shop with its own API key.
            "license_no": profile.license_no if profile else "",
            "profile_completeness": profile.profile_completeness if profile else 0,
            "preferred_wholesalers": preference.preferred_wholesalers if preference else [],
            "consents": consents,
            "policy_version": settings.PRIVACY_POLICY_VERSION,
        }
