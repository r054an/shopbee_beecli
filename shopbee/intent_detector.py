"""Intent detection for ShopBee — identifies shopping mentions in Bee conversations."""

import re
from dataclasses import dataclass, field
from datetime import datetime


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

    def __init__(self):
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in SHOPPING_PATTERNS]

    def analyze_conversation(self, transcript: str) -> list[ShoppingMention]:
        """Analyze a conversation transcript and return detected shopping mentions."""
        mentions = []
        product_name = ""  # Initialize so it's available in the fallback block

        # Check each pattern against the full transcript
        for i, pattern in enumerate(self._compiled_patterns):
            matches = pattern.findall(transcript)
            for match in matches:
                product_name = self._clean_product_name(match.strip())
                if len(product_name) > 2 and not self._is_stop_word(product_name):
                    mentions.append(ShoppingMention(
                        product_name=product_name,
                        confidence=self._calculate_confidence(transcript, product_name),
                        raw_utterance=match.strip(),
                    ))

        # Also check for keyword-based mentions (fallback)
        text_lower = transcript.lower()
        for category, keywords in PRODUCT_CATEGORIES.items():
            for kw in keywords:
                if kw in text_lower:
                    # Find the context around this keyword
                    idx = text_lower.index(kw)
                    start = max(0, idx - 50)
                    end = min(len(transcript), idx + len(kw) + 50)
                    context = transcript[start:end].strip()

                    # Check if there's a shopping indicator nearby
                    has_shopping_indicator = any(
                        word in text_lower[max(0, start-10):start+len(context)]
                        for word in SHOPPING_KEYWORDS
                    )
                    if has_shopping_indicator:
                        mentions.append(ShoppingMention(
                            product_name=product_name or f"{category}",
                            confidence=0.45,  # Lower confidence for keyword-only matches
                            raw_utterance=context,
                        ))

        return sorted(mentions, key=lambda m: m.confidence, reverse=True)

    def analyze_conversations(self, conversations_data: list[dict]) -> list[ShoppingMention]:
        """Analyze multiple Bee conversations and return shopping mentions."""
        all_mentions = []

        for conv in conversations_data:
            # Extract transcript from conversation data
            transcript = self._extract_transcript(conv)
            if not transcript or len(transcript.strip()) < 20:
                continue

            mentions = self.analyze_conversation(transcript)
            for m in mentions:
                m.source_conversation_id = conv.get("id")
                m.timestamp_ms = conv.get("timestamp_ms")
            all_mentions.extend(mentions)

        return sorted(all_mentions, key=lambda m: m.confidence, reverse=True)

    def _extract_transcript(self, conversation_data: dict) -> str:
        """Extract text transcript from Bee conversation data."""
        # Try different possible structures for conversation data
        if "transcript" in conversation_data:
            return conversation_data["transcript"]
        elif "text" in conversation_data:
            return conversation_data["text"]
        elif "content" in conversation_data:
            return conversation_data["content"]

        # Bee CLI --json returns a 'summary' field with rich content
        if "summary" in conversation_data and conversation_data["summary"]:
            summary = conversation_data["summary"]
            # If it's already a string (from JSON output), use it directly
            if isinstance(summary, str):
                return summary

        # If it has utterances, join them
        if "utterances" in conversation_data:
            parts = []
            for u in conversation_data["utterances"]:
                if isinstance(u, dict):
                    parts.append(u.get("text", "") or u.get("content", ""))
                elif isinstance(u, str):
                    parts.append(u)
            return " ".join(parts)

        # Fallback: convert to string
        import json
        try:
            return json.dumps(conversation_data)
        except Exception:
            return str(conversation_data)

    def _clean_product_name(self, name: str) -> str:
        """Clean up a detected product name."""
        # Remove leading articles and common prefixes
        name = re.sub(r"^(a|an|the)\s+", "", name.strip())
        # Clean up extra whitespace
        name = " ".join(name.split())
        return name

    def _calculate_confidence(self, transcript: str, product_name: str) -> float:
        """Calculate confidence score for a shopping mention.

        Returns a value between 0 and 1 where higher values indicate
        stronger evidence that the utterance contains shopping intent.
        """
        text_lower = transcript.lower()
        product_lower = product_name.lower()

        # Base confidence from pattern match quality
        base = 0.6

        # Boost if the product name appears with strong shopping indicators
        for keyword in ["need", "buy", "order", "purchase", "get"]:
            if keyword in text_lower:
                base += 0.15

        # Boost if it's a specific product (not just a category)
        words = product_name.split()
        if len(words) >= 2 and any(w[0].isupper() or w.isalpha() for w in words):
            base += 0.1

        # Check for price/quantity indicators nearby
        if re.search(r"\$\d+|price|cost|expensive|cheap|budget", text_lower):
            base += 0.15

        return min(base, 0.95)

    def _is_stop_word(self, name: str) -> bool:
        """Check if a detected product name is just a stop word."""
        common_stops = {"the", "a", "an", "it", "that", "this", "one"}
        return name.lower().strip() in common_stops

    def get_pending_shopping_items(self, todos_data: list[dict] | None = None) -> list[ShoppingMention]:
        """Cross-reference shopping mentions with pending todos to find unfulfilled items."""
        if not todos_data:
            return []

        pending_todos = [t for t in todos_data if not t.get("completed", False)]
        
        # Use cleaned_text if available (without Amazon links), otherwise use raw text
        todo_texts = " ".join(t.get("cleaned_text", t.get("text", "")) for t in pending_todos).lower()

        mentions = []
        for todo in pending_todos:
            # Prefer cleaned text, fall back to raw text
            clean_text = todo.get("cleaned_text", todo.get("text", "")).lower()
            
            # Check if this todo matches a shopping pattern
            has_shopping_keyword = any(kw in clean_text for kw in ["buy", "purchase", "order", "get", "need"])
            has_product_category = any(
                cat in clean_text
                for cat in PRODUCT_CATEGORIES.keys()
            )

            if has_shopping_keyword or has_product_category:
                mentions.append(ShoppingMention(
                    product_name=todo.get("cleaned_text", todo.get("text", "")),
                    confidence=0.75,  # Higher confidence from explicit todo
                    source_conversation_id=f"todo-{todo.get('id')}",
                    context={"source": "pending_todo"},
                ))

        return sorted(mentions, key=lambda m: m.confidence, reverse=True)
