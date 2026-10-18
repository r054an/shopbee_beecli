"""Amazon product lookup — finds products by name and resolves ASINs."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Optional dependencies — imported at module level for consistency with other imports.
import requests  # type: ignore[import-untyped]
from bs4 import BeautifulSoup  # type: ignore[import-untyped]

from .config import (
    BEE_CLI_PACKAGE,
    CONVERSATIONS_TIMEOUT,
    PRODUCT_LOOKUP_TIMEOUT,
    amazon_product_url,
    amazon_search_url,
    infer_asin,
)


@dataclass
class AmazonProduct:
    """A product found on Amazon."""
    title: str
    asin: str
    url: str
    price: str | None = None
    rating: float | None = None
    review_count: int | None = None
    image_url: str | None = None
    source: str = "web_scrape"  # or "pa_api", "direct_lookup"


class AmazonLookup:
    """Look up products on Amazon by name, returning ASINs and product details."""

    def __init__(self) -> None:
        self._asin_cache: dict[str, AmazonProduct] = {}
        logger.debug("AmazonLookup initialized")

    def search(self, query: str, limit: int = 5) -> list[AmazonProduct]:
        """Search Amazon for a product by name.

        Uses the Amazon search page to find products matching the query.
        Falls back to direct ASIN lookup if the query looks like an ASIN.
        """
        cache_key = f"{query}:{limit}"
        if cache_key in self._asin_cache:
            logger.debug("Cache hit for %r -> %s", query, self._asin_cache[cache_key].title)
            return [self._asin_cache[cache_key]]

        asin_match = re.match(r'^([A-Z0-9]{10})$', query.strip().upper())
        if asin_match:
            logger.debug("Query %r looks like ASIN, doing direct lookup", query)
            return self._lookup_asin(asin_match.group(1))

        products = self._search_amazon(query, limit)
        # Cache the best match (first product) under this key for future lookups.
        if products:
            self._asin_cache[cache_key] = products[0]
        logger.debug("search(%r, limit=%d) -> %d results", query, limit, len(products))
        return products

    def _search_amazon(self, query: str, limit: int = 5) -> list[AmazonProduct]:
        """Search Amazon's search page and extract product data."""
        # Use the bee CLI to get conversation context if available,
        # then use it as additional context for searching
        try:
            result = subprocess.run(
                ["npx", BEE_CLI_PACKAGE, "conversations", "list"],
                capture_output=True, text=True, timeout=CONVERSATIONS_TIMEOUT,
                check=False,
            )
            conv_data = json.loads(result.stdout) if result.returncode == 0 else []
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            logger.debug("Failed to get Bee conversation context via CLI")
            conv_data = []

        # Build search query with context from Bee conversations
        search_query = self._build_search_query(query, conv_data)
        logger.debug("Searching Amazon for %r (query: %r)", query, search_query)

        # Use Amazon's search URL to find products
        url = f"{amazon_search_url(query)}&ref=nb_sb_noss"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        try:
            response = requests.get(url, headers=headers, timeout=PRODUCT_LOOKUP_TIMEOUT)
            products = self._parse_amazon_results(response.text, query)
            logger.debug("_search_amazon(%r) -> %d products", query, len(products))
            return products[:limit]
        except (requests.RequestException, ValueError) as e:
            # Fallback: return a basic product entry
            logger.warning("Amazon search failed for %r: %s — using fallback", query, e)
            return [AmazonProduct(
                title=f"{query} on Amazon",
                asin=infer_asin(query),
                url=amazon_search_url(query),
                source="web_scrape_fallback",
            )]

    def _parse_amazon_results(self, html: str, query: str) -> list[AmazonProduct]:
        """Parse Amazon search results from HTML using BeautifulSoup."""
        products = []
        soup = BeautifulSoup(html, "html.parser")

        # Amazon search results are typically in divs with data-component-type="s-search-result"
        for result_div in soup.find_all("div", {"data-component-type": "s-search-result"}):
            try:
                # Extract ASIN
                raw_asin = result_div.get("data-asin")
                asin = str(raw_asin) if raw_asin else None
                if not asin:
                    continue

                # Extract Title
                title_tag = result_div.find("h2")
                if title_tag:
                    title = title_tag.get_text().strip()
                else:
                    # Fallback to finding any span with a-size-base class
                    title_tag = result_div.find("span", class_="a-size-base")
                    title = title_tag.get_text().strip() if title_tag else f"{query} (ASIN: {asin})"

                # Extract URL
                link_tag = result_div.find("a", class_="a-link-normal s-no-outline")
                url = amazon_product_url(asin) if link_tag else amazon_search_url(query)

                # Extract Price (optional)
                price = None
                price_offscreen = result_div.find("span", class_="a-offscreen")
                if price_offscreen:
                    price = price_offscreen.get_text().strip()
                else:
                    price_whole = result_div.find("span", class_="a-price-whole")
                    if price_whole:
                        # Try to get the whole price string (including decimals)
                        price_container = price_whole.find_parent("span", class_="a-price")
                        if price_container:
                            price = price_container.get_text().strip()

                # Extract Rating/Reviews (optional)
                rating = None
                rating_tag = result_div.find("span", class_="a-icon-alt")
                if rating_tag:
                    rating_text = rating_tag.get_text()
                    # Extract float from "4.5 out of 5 stars"
                    rating_match = re.search(r"(\d+\.?\d*)", rating_text)
                    if rating_match:
                        rating = float(rating_match.group(1))

                products.append(AmazonProduct(
                    title=title,
                    asin=asin,
                    url=url,
                    price=price,
                    rating=rating,
                    source="web_scrape",
                ))

            except (KeyError, AttributeError):
                continue  # Skip malformed product blocks

        logger.debug("_parse_amazon_results(%r) -> %d products", query, len(products))
        return products[:10]

    def _lookup_asin(self, asin: str) -> list[AmazonProduct]:
        """Look up a specific ASIN on Amazon."""
        product = AmazonProduct(
            title=f"Product (ASIN: {asin})",
            asin=asin,
            url=amazon_product_url(asin),
            source="direct_lookup",
        )

        try:
            response = requests.get(
                amazon_product_url(asin),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36"
                    ),
                },
                timeout=PRODUCT_LOOKUP_TIMEOUT,
            )

            # Use BeautifulSoup to get title from the page
            soup = BeautifulSoup(response.text, "html.parser")
            title_tag = soup.find("span", id="productTitle")
            if title_tag:
                product.title = title_tag.get_text().strip()
            elif soup.title:
                product.title = soup.title.get_text().strip()

        except (requests.RequestException, ValueError):
            pass

        return [product]

    def _build_search_query(self, query: str, conv_data: list) -> str:
        """Build an optimized search query using Bee conversation context."""
        # If we have recent conversations, use them to refine the search
        if conv_data and len(conv_data) > 0:
            # Extract relevant keywords from recent conversations
            all_text = " ".join(
                json.dumps(c.get("text", c.get("content", "")))
                for c in conv_data[:5]
            )

            # Check if the query matches any conversation context
            words = set(query.lower().split())
            common_words = words.intersection(set(all_text.split()))

            if len(common_words) > 2:
                result = f"{query} {', '.join(common_words)}"
                logger.debug("Refined search query: %r -> %r", query, result)
                return result

        return query

    def get_product_by_asin(self, asin: str) -> AmazonProduct | None:
        """Get a product by its ASIN, using cache or fetching fresh."""
        if asin in self._asin_cache:
            return self._asin_cache[asin]

        products = self._lookup_asin(asin)
        if products:
            self._asin_cache[asin] = products[0]
            return products[0]
        return None
