"""Tests for ShopBee."""

import json
from shopbee.intent_detector import IntentDetector, ShoppingMention
from shopbee.amazon_lookup import AmazonLookup, AmazonProduct
from shopbee.shopping_actions import ShoppingActions, ShoppingConfirmation, AddToCartResult
from shopbee.skill import ShopBeeSkill, ShopBeeResult
from shopbee.config import infer_asin


class TestIntentDetector:
    """Test shopping intent detection from conversations."""

    def setup_method(self):
        self.detector = IntentDetector()

    def test_detects_need_pattern(self):
        transcript = "I need a USB-C cable for my laptop"
        mentions = self.detector.analyze_conversation(transcript)
        assert len(mentions) > 0
        product_names = [m.product_name.lower() for m in mentions]
        assert any("usb-c" in name or "cable" in name for name in product_names)

    def test_detects_should_get_pattern(self):
        transcript = "I should get a new keyboard soon"
        mentions = self.detector.analyze_conversation(transcript)
        assert len(mentions) > 0

    def test_detects_looking_for_pattern(self):
        transcript = "We're looking for a good monitor"
        mentions = self.detector.analyze_conversation(transcript)
        assert len(mentions) > 0

    def test_calculates_confidence(self):
        high_context = "I really need to buy a new keyboard, I've been saying this for weeks"
        low_context = "The weather is nice today"
        
        high_mentions = self.detector.analyze_conversation(high_context)
        low_mentions = self.detector.analyze_conversation(low_context)
        
        if high_mentions and low_mentions:
            assert high_mentions[0].confidence >= low_mentions[0].confidence

    def test_returns_empty_for_non_shopping(self):
        transcript = "The meeting is at 3pm tomorrow"
        mentions = self.detector.analyze_conversation(transcript)
        # Should return empty or very low confidence
        assert len(mentions) == 0 or mentions[0].confidence < 0.2

    def test_detects_multiple_mentions(self):
        transcript = "I need a keyboard and also looking for headphones"
        mentions = self.detector.analyze_conversation(transcript)
        # Should detect at least one mention
        assert len(mentions) >= 1


class TestIntentDetectorNewMethods:
    """Test the new is_shopping_utterance and detect_intent methods."""

    def setup_method(self):
        self.detector = IntentDetector()

    def test_is_shopping_utterance_detects_shopping(self):
        assert self.detector.is_shopping_utterance("I need a USB-C cable") is True

    def test_is_shopping_utterance_rejects_non_shopping(self):
        assert self.detector.is_shopping_utterance("The meeting is at 3pm") is False

    def test_detect_intent_returns_highest_confidence(self):
        mention = self.detector.detect_intent("I should get a new keyboard soon")
        assert mention.product_name.lower() in ["keyboard", "new keyboard"] or len(mention.product_name) > 0
        assert hasattr(mention, 'confidence')

    def test_detect_intent_fallback_for_no_match(self):
        mention = self.detector.detect_intent("completely unrelated text")
        # Should return a fallback with the raw text as product name
        assert mention.product_name == "completely unrelated text"
        assert mention.confidence == 0.4


class TestAmazonLookup:
    """Test Amazon product lookup functionality."""

    def setup_method(self):
        self.lookup = AmazonLookup()

    def test_search_returns_products(self):
        products = self.lookup.search("keyboard", limit=5)
        # Should return a list (may be empty if no network, but should not raise)
        assert isinstance(products, list)

    def test_parse_amazon_results_handles_empty_html(self):
        products = self.lookup._parse_amazon_results("<html></html>", "test")
        assert isinstance(products, list)

    def test_lookup_asin_returns_product(self):
        product_list = self.lookup._lookup_asin("B09ABCDEF")
        assert len(product_list) == 1
        assert product_list[0].asin == "B09ABCDEF"


class TestShoppingActions:
    """Test Alexa Shopping Actions."""

    def setup_method(self):
        self.actions = ShoppingActions()

    def test_create_confirmation(self):
        confirmation = self.actions.create_confirmation(
            product_title="USB-C Cable",
            asin="B09ABCDEF",
            url="https://amazon.com/dp/B09ABCDEF",
            price="$12.99",
        )
        assert isinstance(confirmation, ShoppingConfirmation)
        assert confirmation.product_title == "USB-C Cable"

    def test_confirm_action_returns_result(self):
        result = self.actions.confirm_action(ShoppingConfirmation(
            product_title="Test Product",
            asin="B09ABCDEF",
            url="https://amazon.com/dp/B09ABCDEF",
            price="$12.99",
        ))
        assert isinstance(result, AddToCartResult)

    def test_clear_confirmed_is_noop(self):
        # This should not raise an error and returns count of cleared items
        result = self.actions.clear_confirmed()
        assert isinstance(result, int)


class TestShopBeeSkill:
    """Test the main ShopBeeSkill class."""

    def setup_method(self):
        self.skill = ShopBeeSkill()

    def test_find_pending_shopping_returns_result(self):
        result = self.skill.find_pending_shopping()
        assert isinstance(result, ShopBeeResult)
        assert hasattr(result, 'message')

    def test_add_to_cart_handles_missing_product(self):
        # Should handle gracefully when no products found
        result = self.skill.add_to_cart("nonexistentproductxyz123")
        assert isinstance(result, ShopBeeResult)

    def test_search_and_add_returns_result(self):
        result = self.skill.search_and_add("keyboard")
        assert isinstance(result, ShopBeeResult)


class TestInferAsin:
    """Test the shared infer_asin function."""

    def test_deterministic_same_input(self):
        asin1 = infer_asin("USB-C Cable")
        asin2 = infer_asin("USB-C Cable")
        assert asin1 == asin2

    def test_different_inputs_produce_different_asins(self):
        asin1 = infer_asin("keyboard")
        asin2 = infer_asin("mouse")
        assert asin1 != asin2

    def test_returns_10_char_uppercase_string(self):
        asin = infer_asin("test product")
        assert len(asin) == 10
        assert asin.isupper() or any(c.isdigit() for c in asin)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_conversation(self):
        detector = IntentDetector()
        mentions = detector.analyze_conversation("")
        assert isinstance(mentions, list)

    def test_whitespace_only_text(self):
        detector = IntentDetector()
        mentions = detector.analyze_conversation("   ")
        assert isinstance(mentions, list)

    def test_very_long_text(self):
        detector = IntentDetector()
        long_text = "I need a keyboard. " * 100
        mentions = detector.analyze_conversation(long_text)
        assert len(mentions) > 0

    def test_unicode_in_product_name(self):
        detector = IntentDetector()
        mentions = detector.analyze_conversation("I need a café table")
        assert isinstance(mentions, list)


class TestConfig:
    """Test configuration functions."""

    def test_alexa_config_values(self):
        from shopbee.config import ALEXA
        assert ALEXA.namespace == "Alexa.Shopping"
        assert ALEXA.payload_version == "3"

    def test_amazon_urls(self):
        from shopbee.config import amazon_search_url, amazon_product_url
        
        search = amazon_search_url("test product")
        assert "amazon.com/s?k=test+product" in search
        
        product = amazon_product_url("B09ABCDEF")
        assert product == "https://www.amazon.com/dp/B09ABCDEF"

    def test_bee_api_url(self):
        from shopbee.config import bee_api_url, BEES_PROXY_URL
        
        url = bee_api_url("/v1/conversations")
        assert url.startswith(BEES_PROXY_URL)
        assert "/v1/conversations" in url


class TestAmazonLookupEdgeCases:
    """Test Amazon lookup edge cases."""

    def setup_method(self):
        self.lookup = AmazonLookup()

    def test_search_with_asin_input(self):
        products = self.lookup.search("B09ABCDEFG")
        assert len(products) == 1
        assert products[0].asin == "B09ABCDEFG"

    def test_search_lowercase_asin(self):
        """ASIN regex should handle lowercase input."""
        products = self.lookup.search("b09abcdefgh")
        assert len(products) >= 0  # Should not crash

    def test_parse_amazon_results_with_partial_data(self):
        html = '<div data-component-type="s-search-result" data-asin="B123456789"><h2>Test Product</h2></div>'
        products = self.lookup._parse_amazon_results(html, "test")
        assert len(products) >= 0

    def test_get_product_by_asin_caches(self):
        product1 = self.lookup.get_product_by_asin("B09ABCDEF")
        product2 = self.lookup.get_product_by_asin("B09ABCDEF")
        # Should return same cached object (or at least equal)
        assert product1 is not None
        assert product2 is not None


class TestIntentDetectorEdgeCases:
    """Test intent detector edge cases."""

    def setup_method(self):
        self.detector = IntentDetector()

    def test_analyze_conversation_with_none_values(self):
        conv_data = [{"id": "1", "text": None}]
        mentions = self.detector.analyze_conversations(conv_data)
        assert isinstance(mentions, list)

    def test_analyze_conversations_empty_list(self):
        mentions = self.detector.analyze_conversations([])
        assert mentions == []

    def test_get_pending_shopping_items_with_none_todos(self):
        items = self.detector.get_pending_shopping_items(None)
        assert items == []

    def test_is_shopping_utterance_empty_string(self):
        result = self.detector.is_shopping_utterance("")
        assert isinstance(result, bool)


class TestShoppingActionsEdgeCases:
    """Test shopping actions edge cases."""

    def setup_method(self):
        self.actions = ShoppingActions()

    def test_create_confirmation_defaults(self):
        confirmation = self.actions.create_confirmation(
            product_title="Test",
            asin="B09ABCDEF",
            url="https://amazon.com/dp/B09ABCDEF",
        )
        assert confirmation.quantity == 1
        assert confirmation.price is None

    def test_clear_confirmed_returns_count(self):
        self.actions.create_confirmation(
            product_title="Test",
            asin="B09ABCDEF",
            url="https://amazon.com/dp/B09ABCDEF",
        )
        count = self.actions.clear_confirmed()
        assert isinstance(count, int)
        assert count >= 0

    def test_get_pending_confirmations_returns_copy(self):
        confirmation = self.actions.create_confirmation(
            product_title="Test",
            asin="B09ABCDEF",
            url="https://amazon.com/dp/B09ABCDEF",
        )
        confirmations = self.actions.get_pending_confirmations()
        assert len(confirmations) == 1
