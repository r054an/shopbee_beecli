"""Tests for ShopBee."""

import json
from shopbee.intent_detector import IntentDetector, ShoppingMention


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
        high_context = "I really need to buy this USB-C cable, it's expensive but worth it"
        low_context = "USB-C cable"
        high_conf = self.detector._calculate_confidence(high_context, "USB-C cable")
        low_conf = self.detector._calculate_confidence(low_context, "USB-C cable")
        assert high_conf > low_conf

    def test_analyzes_conversations(self):
        conversations = [
            {"id": "conv1", "text": "I need a new charger for my phone"},
            {"id": "conv2", "text": "Let's get some headphones"},
            {"id": "conv3", "text": "Just a regular conversation about nothing"},
        ]
        mentions = self.detector.analyze_conversations(conversations)
        assert len(mentions) >= 2

    def test_clean_product_name(self):
        assert self.detector._clean_product_name("a USB-C cable") == "USB-C cable"
        assert self.detector._clean_product_name("the new monitor") == "new monitor"

    def test_is_stop_word(self):
        assert self.detector._is_stop_word("the") is True
        assert self.detector._is_stop_word("a") is True
        assert self.detector._is_stop_word("USB-C cable") is False


class TestAmazonLookup:
    """Test Amazon product lookup."""

    def setup_method(self):
        from shopbee.amazon_lookup import AmazonLookup
        self.lookup = AmazonLookup()

    def test_parse_amazon_results(self):
        from shopbee.amazon_lookup import AmazonLookup, AmazonProduct
        lookup = AmazonLookup()
        html = """
        <div data-component-type="s-search-result" data-asin="B012345678">
            <h2 class="a-size-medium">Test Product Title</h2>
            <a class="a-link-normal s-no-outline" href="/dp/B012345678">Link</a>
            <span class="a-price"><span class="a-offscreen">$19.99</span><span class="a-price-whole">19</span></span>
            <span class="a-icon-alt">4.5 out of 5 stars</span>
        </div>
        """
        results = lookup._parse_amazon_results(html, "test query")
        assert len(results) == 1
        assert results[0].asin == "B012345678"
        assert results[0].title == "Test Product Title"
        assert results[0].price == "$19.99"
        assert results[0].rating == 4.5

    def test_lookup_asin_with_mock(self, mocker):
        from shopbee.amazon_lookup import AmazonLookup
        lookup = AmazonLookup()
        mock_html = """
        <html>
            <head><title>Mocked Product Title</title></head>
            <body><span id="productTitle">Actual Product Name</span></body>
        </html>
        """
        mocker.patch("requests.get", return_value=type('obj', (object,), {
            'text': mock_html,
            'status_code': 200
        }))

        results = lookup._lookup_asin("B012345678")
        assert len(results) == 1
        assert results[0].title == "Actual Product Name"
        assert results[0].asin == "B012345678"


class TestShoppingActions:
    """Test Alexa Shopping Actions."""

    def setup_method(self):
        from shopbee.shopping_actions import ShoppingActions
        self.actions = ShoppingActions()

    def test_create_confirmation(self):
        confirmation = self.actions.create_confirmation(
            product_title="USB-C Cable",
            asin="B08XYZABC1",
            url="https://amazon.com/dp/B08XYZABC1",
            price="$12.99",
        )
        assert confirmation.product_title == "USB-C Cable"
        assert confirmation.asin == "B08XYZABC1"

    def test_confirmation_message(self):
        confirmation = self.actions.create_confirmation(
            product_title="Test Product",
            asin="TESTASIN1234",
            url="https://amazon.com/test",
            price="$9.99",
        )
        msg = confirmation.to_message()
        assert "Test Product" in msg
        assert "$9.99" in msg

    def test_get_pending_confirmations(self):
        self.actions.create_confirmation("A", "A1", "url")
        self.actions.create_confirmation("B", "B2", "url")
        pending = self.actions.get_pending_confirmations()
        assert len(pending) == 2


class TestShopBeeSkill:
    """Test the main ShopBee skill."""

    def setup_method(self):
        from shopbee import ShopBeeSkill
        self.skill = ShopBeeSkill()

    def test_find_pending_shopping_returns_result(self):
        result = self.skill.find_pending_shopping()
        assert hasattr(result, 'success')
        assert hasattr(result, 'message')


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
