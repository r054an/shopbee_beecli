"""Intent detection for ShopBee — identifies shopping mentions in Bee conversations."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ShoppingMention:
    """A detected shopping mention from a conversation."""
    product_name: str  # e.g. "USB-C cable"
    confidence: float  # 0-1 how confident we are this is shopping intent
    source_conversation_id: str | None = None
    timestamp_ms: int | None = None
    raw_utterance: str = ""
    context: dict = field(default_factory=dict)


# Shopping-related keywords and patterns
SHOPPING_KEYWORDS = {
    "buy", "purchase", "order", "get", "need", "needs", "wanted", "want",
    "should get", "should buy", "have to get", "have to buy", "looking for",
    "recommend", "suggested", "recommended", "add to cart", "checkout",
    "amazon", "prime", "delivery", "shipping",
}

# Patterns that indicate shopping intent
SHOPPING_PATTERNS = [
    # "I need a USB-C cable" / "we need a new monitor"
    r"(?:i|we)\s+(?:need|needs|wanted|want)\s+((?:a|an|the)\s+\w[\w\s,]*?(?:cable|charger|monitor|keyboard|mouse|headphones|phone|laptop|adapter|hub|stand|case|cover|dock|drive|ssd|hdd|usb|hdmi|ethernet|webcam|microphone|speaker|battery|power|wall|brick))",
    # "I should get a new keyboard" / "we need to buy X"
    r"(?:i|we)\s+(?:should\s+get|should\s+buy|need\s+to\s+buy|have\s+to\s+get|have\s+to\s+buy)\s+(\w[\w\s,]*?(?:cable|charger|monitor|keyboard|mouse|headphones|phone|laptop|adapter|hub|stand|case|cover|dock|drive|ssd|hdd|usb|hdmi|ethernet|webcam|microphone|speaker|battery|power))",
    # "I'm looking for X" / "looking for a Y"
    r"(?:i\s+)?(?:am\s+)?(?:looking)\s+(?:for)\s+(\w[\w\s,]*?(?:cable|charger|monitor|keyboard|mouse|headphones|phone|laptop|adapter|hub|stand|case|cover|dock|drive|ssd|hdd|usb|hdmi|ethernet|webcam|microphone|speaker|battery))",
    # "X would be great" / "X is a good idea" (when X is a product)
    r"(?:the\s+)?(\w[\w\s,]*?(?:cable|charger|monitor|keyboard|mouse|headphones|phone|laptop|adapter|hub|stand|case|cover|dock|drive|ssd|hdd|usb|hdmi|ethernet|webcam|microphone|speaker|battery))\s+(?:would\s+be|is)\s+(?:a\s+)?(?:great|good|nice)",
    # "I need X for Y" / "X for my Z"
    r"(?:i|we)\s+(?:need|needs)\s+(\w[\w\s,]*?(?:cable|charger|monitor|keyboard|mouse|headphones|phone|laptop|adapter|hub|stand|case|cover|dock|drive|ssd|hdd|usb|hdmi|ethernet|webcam|microphone|speaker|battery))\s+(?:for\s+my)?",
]

# Product category keywords that help identify what was mentioned
PRODUCT_CATEGORIES = {
    "cable": ["cable", "cord", "wire"],
    "charger": ["charger", "brick", "wall charger", "fast charger"],
    "monitor": ["monitor", "screen", "display"],
    "keyboard": ["keyboard", "keypad"],
    "mouse": ["mouse", "trackball"],
    "headphones": ["headphone", "earbuds", "airpods", "wireless earbuds"],
    "phone": ["phone", "smartphone", "iphone", "android phone"],
    "laptop": ["laptop", "notebook", "macbook", "pc"],
    "adapter": ["adapter", "dongle", "converter", "hub"],
    "stand": ["stand", "holder", "mount"],
    "case": ["case", "cover", "skin"],
    "dock": ["dock", "station", "docking station"],
    "drive": ["drive", "ssd", "hdd", "external drive", "usb drive"],
    "webcam": ["webcam", "camera"],
    "microphone": ["mic", "microphone", "boom mic"],
    "speaker": ["speaker", "soundbar"],
    "battery": ["battery", "power bank", "portable charger"],
}


class IntentDetector:
    """Detects shopping intent from Bee conversation data."""

    def __init__(self) -> None:
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in SHOPPING_PATTERNS]
        logger.debug("IntentDetector initialized with %d compiled patterns", len(self._compiled_patterns))

    def analyze_conversation(self, transcript: str) -> list[ShoppingMention]:
        """Analyze a conversation transcript and return detected shopping mentions."""
        if not transcript or not transcript.strip():
            logger.debug("analyze_conversation: empty transcript")
            return []

        logger.debug("Analyzing conversation (len=%d): %.100s...", len(transcript), transcript)
        mentions = []

        # Check each pattern against the full transcript
        for i, pattern in enumerate(self._compiled_patterns):
            matches = pattern.findall(transcript)
            if matches:
                logger.debug("Pattern %d matched %d times", i + 1, len(matches))
            for match in matches:
                product_name = self._clean_product_name(match.strip())
                if len(product_name) > 2 and not self._is_stop_word(product_name):
                    confidence = self._calculate_confidence(transcript, product_name)
                    logger.debug("Found mention: %r (confidence=%.2f)", product_name, confidence)
                    mentions.append(ShoppingMention(
                        product_name=product_name,
                        confidence=confidence,
                        raw_utterance=match.strip(),
                    ))

        # Also check for keyword-based mentions (fallback)
        text_lower = transcript.lower()
        for category, keywords in PRODUCT_CATEGORIES.items():
            for kw in keywords:
                if kw in text_lower:
                    idx = text_lower.index(kw)
                    start = max(0, idx - 50)
                    end = min(len(transcript), idx + len(kw) + 50)
                    context = transcript[start:end].strip()

                    has_shopping_indicator = any(
                        word in text_lower[max(0, start-10):start+len(context)]
                        for word in SHOPPING_KEYWORDS
                    )
                    if has_shopping_indicator:
                        logger.debug("Keyword match: %r -> category=%s", kw, category)
                        mentions.append(ShoppingMention(
                            product_name=f"{category}",
                            confidence=0.45,  # Lower confidence for keyword-only matches
                            raw_utterance=context,
                        ))

        result = sorted(mentions, key=lambda m: m.confidence, reverse=True)
        logger.debug("analyze_conversation returned %d mentions", len(result))
        return result

    def analyze_conversations(self, conversations_data: list[dict]) -> list[ShoppingMention]:
        """Analyze multiple Bee conversations and return shopping mentions."""
        logger.debug("Analyzing %d conversations for shopping intent", len(conversations_data))
        all_mentions = []

        for conv in conversations_data:
            transcript = self._extract_transcript(conv)
            if not transcript or len(transcript.strip()) < 20:
                logger.debug("Skipping conversation (short transcript): id=%s", conv.get("id"))
                continue

            mentions = self.analyze_conversation(transcript)
            for m in mentions:
                m.source_conversation_id = conv.get("id")
                m.timestamp_ms = conv.get("timestamp_ms")
            all_mentions.extend(mentions)

        result = sorted(all_mentions, key=lambda m: m.confidence, reverse=True)
        logger.debug("analyze_conversations returned %d total mentions", len(result))
        return result

    def _extract_transcript(self, conversation_data: dict) -> str:
        """Extract text transcript from Bee conversation data."""
        for key in ("transcript", "text", "content"):
            value = conversation_data.get(key)
            if isinstance(value, str) and len(value.strip()) > 0:
                logger.debug("Extracted transcript from '%s' field (len=%d)", key, len(value))
                return value

        # Bee CLI --json returns a 'summary' field with rich content
        summary = conversation_data.get("summary")
        if isinstance(summary, str) and len(summary.strip()) > 0:
            logger.debug("Extracted transcript from 'summary' field (len=%d)", len(summary))
            return summary

        # If it has utterances, join them
        if "utterances" in conversation_data:
            parts = []
            for u in conversation_data["utterances"]:
                if isinstance(u, dict):
                    parts.append(u.get("text", "") or u.get("content", ""))
                elif isinstance(u, str):
                    parts.append(u)
            result = " ".join(parts)
            if len(result.strip()) > 0:
                logger.debug("Extracted transcript from 'utterances' (len=%d)", len(result))
                return result

        # Fallback: convert to string
        import json
        try:
            result = json.dumps(conversation_data)
            logger.debug("Fallback: extracted transcript via json.dumps (len=%d)", len(result))
            return result
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("json.dumps failed, using str fallback: %s", e)
            return str(conversation_data)

    def _clean_product_name(self, name: str) -> str:
        """Clean up a detected product name."""
        original = name
        name = re.sub(r"^(a|an|the)\s+", "", name.strip())
        name = " ".join(name.split())
        if original != name:
            logger.debug("Cleaned product name: %r -> %r", original, name)
        return name

    def _calculate_confidence(self, transcript: str, product_name: str) -> float:
        """Calculate confidence score for a shopping mention.

        Returns a value between 0 and 1 where higher values indicate
        stronger evidence that the utterance contains shopping intent.
        """
        text_lower = transcript.lower()
        words = product_name.split()

        base = 0.6
        boosts = []

        for keyword in ["need", "buy", "order", "purchase", "get"]:
            if keyword in text_lower:
                base += 0.15
                boosts.append(f"+{keyword}")

        has_uppercase = any(w[0].isupper() for w in words)
        is_multi_word = len(words) >= 2
        if has_uppercase or is_multi_word:
            base += 0.1
            boosts.append("+multi-word/uppercase")

        if re.search(r"\$\d+|price|cost|expensive|cheap|budget", text_lower):
            base += 0.15
            boosts.append("+price-indicator")

        result = min(base, 0.95)
        logger.debug("Confidence for %r: %.2f (base=0.6%s)", product_name, result, "".join(boosts))
        return result

    def _is_stop_word(self, name: str) -> bool:
        """Check if a detected product name is just a stop word."""
        common_stops = {"the", "a", "an", "it", "that", "this", "one"}
        return name.lower().strip() in common_stops

    def get_pending_shopping_items(self, todos_data: list[dict] | None = None) -> list[ShoppingMention]:
        """Cross-reference shopping mentions with pending todos to find unfulfilled items."""
        if not todos_data:
            logger.debug("get_pending_shopping_items: no todos data provided")
            return []

        pending_todos = [t for t in todos_data if not t.get("completed", False)]
        logger.debug("Found %d pending todos out of %d total", len(pending_todos), len(todos_data))

        mentions = []
        for todo in pending_todos:
            clean_text = todo.get("cleaned_text", todo.get("text", "")).lower()
            
            has_shopping_keyword = any(kw in clean_text for kw in ["buy", "purchase", "order", "get", "need"])
            has_product_category = any(
                cat in clean_text
                for cat in PRODUCT_CATEGORIES
            )

            if has_shopping_keyword or has_product_category:
                logger.debug("Todo %d matches shopping pattern: %r", todo.get('id'), todo.get('text', '')[:50])
                mentions.append(ShoppingMention(
                    product_name=todo.get("cleaned_text", todo.get("text", "")),
                    confidence=0.75,  # Higher confidence from explicit todo
                    source_conversation_id=f"todo-{todo.get('id')}",
                    context={"source": "pending_todo"},
                ))

        logger.debug("get_pending_shopping_items returned %d items", len(mentions))
        return sorted(mentions, key=lambda m: m.confidence, reverse=True)

    def is_shopping_utterance(self, text: str) -> bool:
        """Check if a given utterance contains shopping intent.
        
        Args:
            text: The utterance to check.
            
        Returns:
            True if the utterance appears to contain shopping intent.
        """
        mentions = self.analyze_conversation(text)
        result = len(mentions) > 0 and mentions[0].confidence >= 0.4
        logger.debug("is_shopping_utterance(%r) -> %s (top confidence=%.2f)", text, result, mentions[0].confidence if mentions else 0)
        return result

    def detect_intent(self, text: str) -> ShoppingMention:
        """Detect the primary shopping intent from an utterance.
        
        Args:
            text: The utterance to analyze.
            
        Returns:
            The highest-confidence ShoppingMention found in the text.
        """
        mentions = self.analyze_conversation(text)
        if mentions:
            logger.debug("detect_intent(%r) -> %r (confidence=%.2f)", text, mentions[0].product_name, mentions[0].confidence)
            return mentions[0]
        result = ShoppingMention(
            product_name=text.strip(),
            confidence=0.4,
            raw_utterance=text.strip(),
        )
        logger.debug("detect_intent(%r) -> fallback: %r", text, result.product_name)
        return result
