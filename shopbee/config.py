"""ShopBee configuration — centralized constants for URLs, timeouts, and settings."""

from dataclasses import dataclass


# ── Bee Proxy ───────────────────────────────────────────────────────────

#: Base URL of the Bee proxy server.
BEES_PROXY_URL = "http://127.0.0.1:8787"

#: Bee API endpoints (relative to BEES_PROXY_URL).
BEE_CONVERSATIONS_PATH = "/v1/conversations"
BEE_TODOS_PATH = "/v1/todos"
BEE_FACTS_PATH = "/v1/facts"
BEE_ME_PATH = "/v1/me"


# ── Amazon URLs ─────────────────────────────────────────────────────────

#: Base URL for Amazon product search.
AMAZON_SEARCH_URL = "https://www.amazon.com/s?k={query}"

#: Template for a single Amazon product detail page (replace {asin}).
AMAZON_PRODUCT_DETAIL_TEMPLATE = "https://www.amazon.com/dp/{asin}"

#: Template for an Amazon wishlist link (replace {asin}).
AMAZON_WISHLIST_TEMPLATE = "https://www.amazon.com/hz/wishlist/ls/{asin}"


# ── Alexa Shopping Actions ──────────────────────────────────────────────

@dataclass(frozen=True)
class AlexaConfig:
    """Configuration for Alexa Shopping directive payloads.

    Attributes:
        namespace: The Alexa directive namespace (e.g., "Alexa.Shopping").
        payload_version: The version string of the directive payload schema.
        default_shopping_list_name: Default name used when creating a shopping list item.
    """
    namespace: str = "Alexa.Shopping"
    payload_version: str = "3"
    default_shopping_list_name: str = "Shopping List"


# ── Bee CLI Package ─────────────────────────────────────────────────────

#: The npm package name for the Bee CLI tool.
BEE_CLI_PACKAGE = "@beeai/cli"


# ── Timeout Defaults ────────────────────────────────────────────────────

CONVERSATIONS_TIMEOUT: int = 15
"""Default timeout (seconds) for subprocess calls to bee CLI."""

REQUEST_TIMEOUT: float = 5.0
"""Default timeout (seconds) for HTTP requests via the `requests` library."""

PRODUCT_LOOKUP_TIMEOUT: float = 10.0
"""Timeout (seconds) when fetching product details from Amazon."""


# ── Convenience Accessors ───────────────────────────────────────────────

def amazon_search_url(query: str) -> str:
    """Return a fully-formed Amazon search URL for *query*.

    Args:
        query: The search term to encode into the URL.

    Returns:
        A string like ``https://www.amazon.com/s?k=keyboard``.
    """
    return AMAZON_SEARCH_URL.format(query=query.replace(" ", "+"))


def amazon_product_url(asin: str) -> str:
    """Return a fully-formed Amazon product detail URL for *asin*.

    Args:
        asin: The 10-character ASIN string.

    Returns:
        A string like ``https://www.amazon.com/dp/B09ABCDEF``.
    """
    return AMAZON_PRODUCT_DETAIL_TEMPLATE.format(asin=asin)


def amazon_wishlist_url(asin: str) -> str:
    """Return a fully-formed Amazon wishlist URL for *asin*.

    Args:
        asin: The 10-character ASIN string.

    Returns:
        A string like ``https://www.amazon.com/hz/wishlist/ls/B09ABCDEF``.
    """
    return AMAZON_WISHLIST_TEMPLATE.format(asin=asin)


def bee_api_url(path: str) -> str:
    """Return a fully-formed Bee API URL for *path*.

    Args:
        path: A relative endpoint such as ``/v1/conversations``.

    Returns:
        A string like ``http://127.0.0.1:8787/v1/conversations``.
    """
    return f"{BEES_PROXY_URL}{path}"


# ── Shared Instance ─────────────────────────────────────────────────────

#: Singleton Alexa configuration used across the codebase.
ALEXA = AlexaConfig()
