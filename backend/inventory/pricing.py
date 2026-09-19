"""The Pro price, defined once.

Every surface that states a price — the landing page's pricing card and
structured data, the FAQ answer, the checkout page and the console's revenue
figure — reads it from here, and here it comes from ``PRO_PRICE_BDT``, the same
setting the checkout bills. The setting is environment-driven, so before this
existed, changing it would leave the marketing page advertising a price nobody
was charged.
"""

from django.conf import settings

DEFAULT_PRO_PRICE_BDT = 299


def pro_price_bdt():
    """The monthly Pro price in BDT, as an int.

    Falls back to the default rather than raising: an unusable value in an
    environment variable must not take the public landing page down. A price of
    zero or less is treated as unusable too, since the free tier is expressed
    by the separate Free plan, not by a Pro price of 0.
    """
    raw = getattr(settings, "PRO_PRICE_BDT", DEFAULT_PRO_PRICE_BDT)
    try:
        price = int(str(raw).strip())
    except (TypeError, ValueError):
        price = DEFAULT_PRO_PRICE_BDT
    return price if price > 0 else DEFAULT_PRO_PRICE_BDT
