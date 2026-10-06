"""Shared pagination for every list endpoint.

A single paginator class means one page shape across the whole API, so the
Android client and a future integration partner parse ``count`` / ``next`` /
``previous`` / ``results`` the same way everywhere. That consistency is worth
more than per-endpoint tuning: an API where one list returns a bare array and
the next returns an envelope is the kind of thing that gets discovered in
production, by a customer, on a Friday.

The page size is capped as well as defaulted. ``?page_size=100000`` would
otherwise be a one-request denial of service against the sales table, which is
the largest thing a busy branch has.
"""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Page-number pagination with a client-tunable, bounded page size."""

    page_size = 50
    page_size_query_param = "page_size"
    #: Hard ceiling. A branch with 40,000 sales can page through them 200 at a
    #: time; nobody needs the whole history in one response, and allowing it
    #: would let an unauthenticated-ish endpoint exhaust a worker's memory.
    max_page_size = 200
