"""ShopBee Skill — the main entry point for Bee integration."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ShopBeeResult:
    """Result from a ShopBee operation."""
    success: bool
    message: str
    details: dict | None = None


# Config imports (needed at module level for type annotations and class methods)
from .config import (
    BEE_CLI_PACKAGE,
    BEE_CONVERSATIONS_PATH,
    BEE_FACTS_PATH,
    BEE_TODOS_PATH,
    CONVERSATIONS_TIMEOUT,
    REQUEST_TIMEOUT,
    amazon_search_url,
    bee_api_url,
    infer_asin,
)


class ShopBeeSkill:
    """Main ShopBee Skill that connects to Bee and handles shopping.

    This is the core skill that:
    1. Reads conversations from Bee (via CLI/MCP/API)
    2. Detects shopping intent in those conversations
    3. Looks up products on Amazon
    4. Creates confirmation prompts for the user
    5. Executes Alexa Shopping Actions when confirmed

    Works with both Bee device and Apple Watch running Bee software.
    """

    def __init__(self) -> None:
        from .amazon_lookup import AmazonLookup
        from .intent_detector import IntentDetector
        from .shopping_actions import ShoppingActions

        self.intent_detector = IntentDetector()
        self.amazon_lookup = AmazonLookup()
        self.shopping_actions = ShoppingActions()
        logger.debug("ShopBeeSkill initialized with all components")

    # ── Core Operations ───────────────────────────────────────────────

    def find_pending_shopping(self) -> ShopBeeResult:
        """Find items the user mentioned needing but hasn't bought yet.

        This is the main "what did I say I needed?" query.
        Returns shopping mentions from recent Bee conversations AND todos,
        with Amazon links in the details section (not modifying todo text).
        """
        logger.info("find_pending_shopping: starting")
        
        # Get pending todos first (always check these)
        todos = self._get_todos()
        logger.debug("Found %d todos", len(todos))
        
        # Analyze todos for shopping intent
        todo_items = self.intent_detector.get_pending_shopping_items(todos)
        logger.debug("Todo items with shopping intent: %d", len(todo_items))

        # Get recent conversations via bee CLI
        convs = self._get_conversations(limit=20)
        mentions = []
        if convs:
            mentions = self.intent_detector.analyze_conversations(convs)
            logger.debug("Conversation mentions: %d", len(mentions))
        else:
            logger.debug("No conversations found")

        # Combine and deduplicate
        all_items = mentions + todo_items
        seen_asins = set()
        unique_items = []
        for item in all_items:
            asin = infer_asin(item.product_name)
            if asin not in seen_asins:
                seen_asins.add(asin)
                unique_items.append(item)

        logger.debug("After deduplication: %d items", len(unique_items))

        # Look up products on Amazon and build details
        cart_items = []
        for mention in unique_items[:10]:  # Top items from both sources
            products = self.amazon_lookup.search(mention.product_name, limit=1)
            
            if products:
                product = products[0]
                logger.debug("Found Amazon match: %s (ASIN=%s)", product.title, product.asin)
                cart_items.append({
                    "product": product,
                    "source": getattr(mention, 'context', {}).get("source", "conversation"),
                    "mentioned_in": mention.source_conversation_id,
                    "confidence": mention.confidence,
                    "raw_mention": mention.raw_utterance,
                })
            elif getattr(mention, 'context', {}).get("source") == "pending_todo":
                # Include todos even if Amazon lookup fails — show raw text as title
                logger.debug("No Amazon match for todo: %s", mention.product_name)
                cart_items.append({
                    "product": type('obj', (object,), {
                        'title': mention.product_name,
                        'asin': infer_asin(mention.product_name),
                        'url': amazon_search_url(mention.product_name),
                    })(),
                    "source": "pending_todo",
                    "mentioned_in": mention.source_conversation_id,
                    "confidence": mention.confidence,
                    "raw_mention": mention.raw_utterance,
                })

        # Format message showing both sources
        message = self._format_pending_shopping_message(cart_items)
        
        if not cart_items and not todos:
            logger.info("find_pending_shopping: no conversations or todos")
            return ShopBeeResult(
                success=True,
                message="No recent conversations or pending todos found in Bee.\n\n"
                        "Try mentioning something you need during a conversation,\n"
                        "or add a todo like \"Buy a new keyboard\".",
            )

        if not cart_items:
            logger.info("find_pending_shopping: %d todos but no shopping items", len(todos))
            return ShopBeeResult(
                success=True,
                message=f"No shopping items found in your {len(todos)} pending todos.\n\n"
                        "Try saying things like:\n"
                        "- \"I need a new keyboard\"\n"
                        "- \"We should get some headphones\"",
            )

        logger.info("find_pending_shopping: %d items found", len(cart_items))
        return ShopBeeResult(
            success=True,
            message=message,
            details={
                "cart": cart_items,
                "total_items": len(cart_items),
                "sources": {
                    "conversations": len([i for i in cart_items if i["source"] == "conversation"]),
                    "todos": len([i for i in cart_items if i["source"] == "pending_todo"]),
                },
            },
        )

    def add_to_cart(self, product_name: str) -> ShopBeeResult:
        """Add a product to the shopping cart via Alexa Shopping Actions.

        1. Looks up the product on Amazon
        2. Creates a confirmation prompt
        3. Executes AMAZON.AddToShoppingCart directive
        """
        logger.info("add_to_cart(%r)", product_name)
        
        # Search for the product
        products = self.amazon_lookup.search(product_name, limit=3)
        if not products:
            logger.warning("No Amazon results for %r", product_name)
            return ShopBeeResult(
                success=False,
                message=f"Could not find '{product_name}' on Amazon.",
            )

        best_match = products[0]
        logger.info("Best match: %s (ASIN=%s)", best_match.title, best_match.asin)

        # Create confirmation
        confirmation = self.shopping_actions.create_confirmation(
            product_title=best_match.title,
            asin=best_match.asin,
            url=best_match.url,
        )

        # Execute the shopping action
        result = self.shopping_actions.confirm_action(confirmation)

        return ShopBeeResult(
            success=result.success,
            message=result.message,
            details={
                "asin": best_match.asin,
                "title": best_match.title,
                "url": best_match.url,
                "directive_type": result.directive_type,
            },
        )

    def search_and_add(self, query: str) -> ShopBeeResult:
        """Search for a product and add it to cart (one-step flow)."""
        logger.info("search_and_add(%r)", query)
        
        products = self.amazon_lookup.search(query, limit=3)
        if not products:
            logger.warning("No results found for %r", query)
            return ShopBeeResult(
                success=False,
                message=f"No results found for '{query}'.",
            )

        # Pick the best match and add to cart
        confirmation = self.shopping_actions.create_confirmation(
            product_title=products[0].title,
            asin=products[0].asin,
            url=products[0].url,
            price=products[0].price,
        )

        result = self.shopping_actions.confirm_action(confirmation)
        return ShopBeeResult(
            success=result.success,
            message=f"Found '{products[0].title}' and added to cart!\n\n{result.message}",
            details={"asin": products[0].asin},
        )

    # ── Bee Data Access ───────────────────────────────────────────────

    def _get_conversations(self, limit: int = 20) -> list[dict]:
        """Get recent conversations from Bee via CLI."""
        logger.debug("_get_conversations(limit=%d)", limit)
        try:
            result = subprocess.run(
                ["npx", BEE_CLI_PACKAGE, "conversations", "list", "--json"],
                capture_output=True, text=True, timeout=CONVERSATIONS_TIMEOUT,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                # Normalize to list format (handle {"conversations": [...]} wrapper)
                if isinstance(data, dict):
                    convs = data.get("conversations", [])
                    logger.debug("_get_conversations: CLI returned %d conversations", len(convs))
                    return convs[:limit]
                logger.debug("_get_conversations: CLI returned list of %d items", len(data))
                return data[:limit]
        except subprocess.TimeoutExpired:
            logger.warning("_get_conversations: CLI timed out after %ds", CONVERSATIONS_TIMEOUT)
        except json.JSONDecodeError as e:
            logger.debug("_get_conversations: JSON decode error: %s", e)
        except FileNotFoundError:
            logger.debug("_get_conversations: npx not found")

        # Fallback: try bee proxy API directly
        try:
            import requests  # type: ignore[import-untyped]
            response = requests.get(
                bee_api_url(BEE_CONVERSATIONS_PATH),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    convs = data.get("conversations", [])
                    logger.debug("_get_conversations: API returned %d conversations", len(convs))
                    return convs[:limit]
                logger.debug("_get_conversations: API returned list of %d items", len(data))
                return data[:limit]
        except (requests.RequestException, ValueError) as e:
            logger.debug("_get_conversations: API fallback failed: %s", e)

        logger.debug("_get_conversations: returning empty list")
        return []

    def capture_conversation(self, conversation_id: str) -> ShopBeeResult:
        """Capture a specific conversation and extract shopping items.
        
        Returns structured data about the conversation including:
        - Messages with timestamps
        - Shopping mentions detected
        - Participants involved
        """
        logger.info("capture_conversation(%r)", conversation_id)
        try:
            result = subprocess.run(
                ["npx", BEE_CLI_PACKAGE, "conversations", "show", conversation_id, "--json"],
                capture_output=True, text=True, timeout=CONVERSATIONS_TIMEOUT,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                
                # Extract shopping mentions from the conversation
                messages = data.get("messages", [])
                logger.debug("capture_conversation: %d messages in response", len(messages))
                shopping_mentions = []
                
                for msg in messages:
                    content = msg.get("content", "")
                    if self.intent_detector.is_shopping_utterance(content):
                        intent = self.intent_detector.detect_intent(content)
                        confidence = intent.confidence if hasattr(intent, 'confidence') else 0.5
                        shopping_mentions.append({
                            "message": content,
                            "timestamp": msg.get("created_at"),
                            "author": msg.get("role", "unknown"),
                            "intent": intent,
                            "confidence": confidence,
                        })
                
                logger.info("capture_conversation(%r): found %d shopping mentions", conversation_id, len(shopping_mentions))
                return ShopBeeResult(
                    success=True,
                    message=f"Captured conversation {conversation_id} with {len(shopping_mentions)} shopping mentions.",
                    details={
                        "conversation_id": conversation_id,
                        "messages": messages[:20],  # Top 20 messages
                        "shopping_mentions": shopping_mentions,
                        "total_messages": len(messages),
                    },
                )
        except subprocess.TimeoutExpired:
            logger.warning("capture_conversation(%r): CLI timed out", conversation_id)
        except json.JSONDecodeError as e:
            logger.debug("capture_conversation(%r): JSON decode error: %s", conversation_id, e)
        except FileNotFoundError:
            logger.debug("capture_conversation(%r): npx not found", conversation_id)
        
        return ShopBeeResult(
            success=False,
            message=f"Could not capture conversation {conversation_id}.",
        )

    def _get_todos(self) -> list[dict]:
        """Get todos from Bee via CLI."""
        logger.debug("_get_todos: starting")
        try:
            result = subprocess.run(
                ["npx", BEE_CLI_PACKAGE, "todos", "list"],
                capture_output=True, text=True, timeout=CONVERSATIONS_TIMEOUT,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                # Parse markdown-formatted output from bee CLI
                todos = self._parse_todos_markdown(result.stdout)
                logger.debug("_get_todos: parsed %d todos from CLI", len(todos))
                if todos:
                    return todos
        except subprocess.TimeoutExpired:
            logger.warning("_get_todos: CLI timed out after %ds", CONVERSATIONS_TIMEOUT)
        except FileNotFoundError:
            logger.debug("_get_todos: npx not found")

        # Fallback: try bee proxy API directly
        try:
            import requests
            response = requests.get(
                bee_api_url(BEE_TODOS_PATH),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    todos = data.get("todos", [])
                    logger.debug("_get_todos: API returned %d todos", len(todos))
                    return todos
                logger.debug("_get_todos: API returned list of %d items", len(data))
                return data
        except (requests.RequestException, ValueError) as e:
            logger.debug("_get_todos: API fallback failed: %s", e)

        logger.debug("_get_todos: returning empty list")
        return []

    def _parse_todos_markdown(self, text: str) -> list[dict]:
        """Parse markdown-formatted todo output from bee CLI."""
        logger.debug("_parse_todos_markdown: parsing %d bytes", len(text))
        import re
        todos = []
        
        # Split by "## Open" and "## Completed" sections
        parts = re.split(r'##\s+(Open|Completed)', text)
        
        for i, part in enumerate(parts):
            if i == 0:
                continue  # Skip the first section before any header
            
            # Extract todo items - they appear after ### Todo <id> blocks
            todo_blocks = re.findall(r'###\s+Todo\s+(\d+)\s*\n(.*?)(?=###\s+Todo|\Z)', part, re.DOTALL)
            
            for todo_id, content in todo_blocks:
                text_match = re.search(r'-\s*text:\s*(.+)', content)
                completed_match = re.search(r'-\s*completed:\s*(true|false)', content)
                
                if text_match:
                    # Clean up Amazon links from the text for display purposes
                    raw_text = text_match.group(1).strip()
                    cleaned_text = re.sub(r'\s*\[Amazon\]\([^)]+\)\s*', '', raw_text).strip()
                    cleaned_text = re.sub(r'\s*\([^)]+amazon\.com[^)]*\)\s*', '', cleaned_text).strip()
                    
                    todos.append({
                        "id": int(todo_id),
                        "text": raw_text,  # Keep original text with links for reference
                        "cleaned_text": cleaned_text,  # Clean version without links
                        "completed": completed_match and completed_match.group(1) == "true",
                    })
        
        logger.debug("_parse_todos_markdown: extracted %d todos", len(todos))
        return todos

    def _get_facts(self) -> list[dict]:
        """Get personal facts from Bee."""
        logger.debug("_get_facts: starting")
        try:
            result = subprocess.run(
                ["npx", BEE_CLI_PACKAGE, "facts", "list"],
                capture_output=True, text=True, timeout=CONVERSATIONS_TIMEOUT,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                facts = json.loads(result.stdout)
                logger.debug("_get_facts: CLI returned %d facts", len(facts))
                return facts
        except subprocess.TimeoutExpired:
            logger.warning("_get_facts: CLI timed out after %ds", CONVERSATIONS_TIMEOUT)
        except json.JSONDecodeError as e:
            logger.debug("_get_facts: JSON decode error: %s", e)
        except FileNotFoundError:
            logger.debug("_get_facts: npx not found")

        try:
            import requests
            response = requests.get(
                bee_api_url(BEE_FACTS_PATH),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                facts = response.json()
                logger.debug("_get_facts: API returned %d facts", len(facts))
                return facts
        except (requests.RequestException, ValueError) as e:
            logger.debug("_get_facts: API fallback failed: %s", e)

        logger.debug("_get_facts: returning empty list")
        return []

    # ── Helpers ───────────────────────────────────────────────────────

    def _format_pending_shopping_message(self, cart_items: list[dict]) -> str:
        logger.debug("_format_pending_shopping_message: formatting %d items", len(cart_items))
        if not cart_items:
            return "No pending shopping items found."

        lines = ["🛒 **ShopBee** — Items you mentioned needing:\n"]
        
        for i, item in enumerate(cart_items, 1):
            product = item["product"]
            source = item.get("source", "conversation")
            confidence = f"{item['confidence']:.0%}"
            
            if source == "pending_todo":
                lines.append(
                    f"{i}. **{product.title}** (from todo)\n"
                    f"   Confidence: {confidence}\n"
                    f"   [View on Amazon]({product.url})"
                )
            else:
                lines.append(
                    f"{i}. **{product.title}** (ASIN: {product.asin})\n"
                    f"   Confidence: {confidence}\n"
                    f"   [View on Amazon]({product.url})"
                )

        result = "\n".join(lines)
        logger.debug("_format_pending_shopping_message: formatted message (%d chars)", len(result))
        return result

    def build_shopping_cart(self) -> ShopBeeResult:
        """Build a complete shopping cart from all Bee sources.
        
        Combines items from conversations, todos, and facts to create
        a comprehensive shopping list with Amazon links in details.
        """
        logger.info("build_shopping_cart: starting")
        
        # Get all data sources
        todos = self._get_todos()
        convs = self._get_conversations(limit=20)
        facts = self._get_facts()
        logger.debug("build_shopping_cart: %d todos, %d conversations, %d facts", len(todos), len(convs), len(facts))
        
        # Analyze todos for shopping intent
        todo_items = self.intent_detector.get_pending_shopping_items(todos)

        # Analyze conversations
        mentions = []
        if convs:
            mentions = self.intent_detector.analyze_conversations(convs)

        # Combine and deduplicate
        all_items = mentions + todo_items
        seen_asins = set()
        unique_items = []
        for item in all_items:
            asin = infer_asin(item.product_name)
            if asin not in seen_asins:
                seen_asins.add(asin)
                unique_items.append(item)

        logger.debug("build_shopping_cart: %d unique items after deduplication", len(unique_items))
        
        # Look up products on Amazon and build cart
        cart: list[dict[str, Any]] = []
        for mention in unique_items[:15]:  # Top items from all sources
            products = self.amazon_lookup.search(mention.product_name, limit=1)
            
            if products:
                product = products[0]
                logger.debug("build_shopping_cart: matched %r -> %s", mention.product_name, product.title)
                cart.append({
                    "product": {
                        "title": product.title,
                        "asin": product.asin,
                        "url": product.url,
                        "price": product.price,
                    },
                    "source": getattr(mention, 'context', {}).get("source", "conversation"),
                    "mentioned_in": mention.source_conversation_id,
                    "confidence": mention.confidence,
                    "raw_mention": mention.raw_utterance,
                })
            elif getattr(mention, 'context', {}).get("source") == "pending_todo":
                cart.append({
                    "product": {
                        "title": mention.product_name,
                        "asin": infer_asin(mention.product_name),
                        "url": amazon_search_url(mention.product_name),
                        "price": None,
                    },
                    "source": "pending_todo",
                    "mentioned_in": mention.source_conversation_id,
                    "confidence": mention.confidence,
                    "raw_mention": mention.raw_utterance,
                })

        # Build summary message
        if not cart:
            logger.info("build_shopping_cart: no items in cart")
            return ShopBeeResult(
                success=True,
                message="Your shopping list is empty. Try mentioning something you need!",
                details={
                    "cart": [],
                    "total_items": 0,
                    "sources": {
                        "conversations": len(convs),
                        "todos": len(todos),
                        "facts": len(facts),
                    },
                },
            )

        lines = ["🛒 **ShopBee Shopping Cart**\n"]
        
        # Group by source
        todo_items_from_cart: list[dict[str, Any]] = [i for i in cart if i["source"] == "pending_todo"]
        conv_items: list[dict[str, Any]] = [i for i in cart if i["source"] == "conversation"]

        if todo_items_from_cart:
            lines.append(f"\n📝 **From Todos** ({len(todo_items_from_cart)} items)\n")
            for todo_item in todo_items_from_cart:
                prod_info = todo_item["product"]
                lines.append(f"  • {prod_info['title']} - [Amazon]({prod_info['url']})")

        if conv_items:
            lines.append(f"\n💬 **From Conversations** ({len(conv_items)} items)\n")
            for conv_item in conv_items:
                prod_info = conv_item["product"]
                confidence = f"{conv_item['confidence']:.0%}"
                lines.append(f"  • {prod_info['title']} (Confidence: {confidence}) - [Amazon]({prod_info['url']})")

        logger.info("build_shopping_cart: %d items total (%d from todos, %d from conversations)", len(cart), len(todo_items_from_cart), len(conv_items))
        return ShopBeeResult(
            success=True,
            message="\n".join(lines),
            details={
                "cart": cart,
                "total_items": len(cart),
                "sources": {
                    "conversations": len(conv_items),
                    "todos": len(todo_items),
                    "facts": len(facts),
                },
            },
        )

# ── CLI Entry Point ──────────────────────────────────────────────────

VERSION = "1.0.0"


def _check_version() -> str | None:
    """Check if a newer version is available on PyPI."""
    try:
        result = subprocess.run(
            ["pip", "index", "versions", "shopbee"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            match = re.search(r"shopbee \(([^)]+)\)", result.stdout)
            if match:
                latest = match.group(1).split(",")[0].strip()
                return latest
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        logger.debug("Failed to check version via pip index")
    return None


def _check_update_available() -> tuple[str, bool]:
    """Check for updates and return (latest_version, is_outdated)."""
    import subprocess
    try:
        result = subprocess.run(
            ["pip", "show", "shopbee"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode == 0:
            installed = None
            for line in result.stdout.splitlines():
                if line.startswith("Version:"):
                    installed = line.split(":", 1)[1].strip()
                    break

            latest = _check_version()
            if installed and latest and installed != latest:
                return (latest, True)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        logger.debug("Failed to check update availability")
    return (VERSION, False)


def main():
    """Run ShopBee from the command line."""
    import sys
    
    # Enable verbose logging if -v flag is passed
    from .config import setup_logging
    log = setup_logging()

    skill = ShopBeeSkill()

    if len(sys.argv) < 2:
        print("ShopBee — 'You said you needed it. Bee remembers.'")
        print(f"\nVersion: {VERSION}")
        latest, outdated = _check_update_available()
        if outdated:
            print(f"Update available: {latest} (current: {VERSION})")
            print("\nUsage:")
            print("  shopbee pending          # Find items you mentioned needing")
            print("  shopbee add <product>    # Add product to cart")
            print("  shopbee search <query>   # Search and add in one step")
            print("  shopbee version          # Show current version")
            print("  shopbee update           # Update to latest version")
        else:
            print("\nUsage:")
            print("  shopbee pending          # Find items you mentioned needing")
            print("  shopbee add <product>    # Add product to cart")
            print("  shopbee search <query>   # Search and add in one step")
        return

    command = sys.argv[1]

    if command == "pending":
        log.info("Running: pending")
        result = skill.find_pending_shopping()
        print(result.message)

    elif command == "cart":
        log.info("Running: cart")
        result = skill.build_shopping_cart()
        print(result.message)

    elif command == "add":
        if len(sys.argv) < 3:
            print("Usage: shopbee add <product_name>")
            return
        product = sys.argv[2]
        log.info("Running: add %r", product)
        result = skill.add_to_cart(product)
        print(result.message)

    elif command == "search":
        if len(sys.argv) < 3:
            print("Usage: shopbee search <query>")
            return
        query = sys.argv[2]
        log.info("Running: search %r", query)
        result = skill.search_and_add(query)
        print(result.message)

    elif command == "version":
        latest, outdated = _check_update_available()
        if outdated:
            print(f"Installed: {VERSION}")
            print(f"Latest:    {latest}")
            print("\nRun 'shopbee update' to upgrade.")
        else:
            print(f"ShopBee v{VERSION} (up to date)")

    elif command == "update":
        latest, outdated = _check_update_available()
        if not outdated:
            print("You're already on the latest version!")
            return
        print(f"Updating from {VERSION} → {latest}...")
        result = subprocess.run(
            ["pip", "install", "--upgrade", "shopbee"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if result.returncode == 0:
            print(f"Updated to v{latest}!")
        else:
            print("Update failed. Try running manually:")
            print("  pip install --upgrade shopbee")

    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
