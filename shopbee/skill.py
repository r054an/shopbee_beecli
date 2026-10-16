"""ShopBee Skill — the main entry point for Bee integration."""

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from .config import (
    BEE_CLI_PACKAGE,
    BEE_CONVERSATIONS_PATH,
    BEE_FACTS_PATH,
    BEE_ME_PATH,
    BEE_TODOS_PATH,
    CONVERSATIONS_TIMEOUT,
    REQUEST_TIMEOUT,
    amazon_search_url,
    bee_api_url,
)
from .shopping_actions import ShoppingConfirmation


@dataclass
class ShopBeeResult:
    """Result from a ShopBee operation."""
    success: bool
    message: str
    details: dict | None = None


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
        from .intent_detector import IntentDetector
        from .amazon_lookup import AmazonLookup
        from .shopping_actions import ShoppingActions

        self.intent_detector = IntentDetector()
        self.amazon_lookup = AmazonLookup()
        self.shopping_actions = ShoppingActions()

    # ── Core Operations ───────────────────────────────────────────────

    def find_pending_shopping(self) -> ShopBeeResult:
        """Find items the user mentioned needing but hasn't bought yet.

        This is the main "what did I say I needed?" query.
        Returns shopping mentions from recent Bee conversations AND todos,
        with Amazon links in the details section (not modifying todo text).
        """
        # Get pending todos first (always check these)
        todos = self._get_todos()
        
        # Analyze todos for shopping intent
        todo_items = self.intent_detector.get_pending_shopping_items(todos)

        # Get recent conversations via bee CLI
        convs = self._get_conversations(limit=20)
        mentions = []
        if convs:
            mentions = self.intent_detector.analyze_conversations(convs)

        # Combine and deduplicate
        all_items = mentions + todo_items
        seen_asins = set()
        unique_items = []
        for item in all_items:
            asin = self._infer_asin(item.product_name)
            if asin not in seen_asins:
                seen_asins.add(asin)
                unique_items.append(item)

        # Look up products on Amazon and build details
        cart_items = []
        for mention in unique_items[:10]:  # Top items from both sources
            products = self.amazon_lookup.search(mention.product_name, limit=1)
            
            if products:
                product = products[0]
                cart_items.append({
                    "product": product,
                    "source": mention.context.get("source", "conversation") if hasattr(mention, 'context') else "conversation",
                    "mentioned_in": mention.source_conversation_id,
                    "confidence": mention.confidence,
                    "raw_mention": mention.raw_utterance,
                })
            elif mention.context.get("source") == "pending_todo":
                # Include todos even if Amazon lookup fails — show raw text as title
                cart_items.append({
                    "product": type('obj', (object,), {
                        'title': mention.product_name,
                        'asin': self._infer_asin(mention.product_name),
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
            return ShopBeeResult(
                success=True,
                message="No recent conversations or pending todos found in Bee.\n\n"
                        "Try mentioning something you need during a conversation,\n"
                        "or add a todo like \"Buy a new keyboard\".",
            )

        if not cart_items:
            return ShopBeeResult(
                success=True,
                message=f"No shopping items found in your {len(todos)} pending todos.\n\n"
                        "Try saying things like:\n"
                        "- \"I need a new keyboard\"\n"
                        "- \"We should get some headphones\"",
            )

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
        # Search for the product
        products = self.amazon_lookup.search(product_name, limit=3)
        if not products:
            return ShopBeeResult(
                success=False,
                message=f"Could not find '{product_name}' on Amazon.",
            )

        best_match = products[0]

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
        products = self.amazon_lookup.search(query, limit=3)
        if not products:
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
        try:
            result = subprocess.run(
                ["npx", BEE_CLI_PACKAGE, "conversations", "list", "--json"],
                capture_output=True, text=True, timeout=CONVERSATIONS_TIMEOUT,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                # Normalize to list format (handle {"conversations": [...]} wrapper)
                if isinstance(data, dict):
                    return data.get("conversations", [])
                return data
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass

        # Fallback: try bee proxy API directly
        try:
            import requests
            response = requests.get(
                bee_api_url(BEE_CONVERSATIONS_PATH),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    return data.get("conversations", [])
                return data
        except Exception:
            pass

        return []

    def capture_conversation(self, conversation_id: str) -> ShopBeeResult:
        """Capture a specific conversation and extract shopping items.
        
        Returns structured data about the conversation including:
        - Messages with timestamps
        - Shopping mentions detected
        - Participants involved
        """
        try:
            result = subprocess.run(
                ["npx", BEE_CLI_PACKAGE, "conversations", "show", conversation_id, "--json"],
                capture_output=True, text=True, timeout=CONVERSATIONS_TIMEOUT,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                
                # Extract shopping mentions from the conversation
                messages = data.get("messages", [])
                shopping_mentions = []
                
                for msg in messages:
                    content = msg.get("content", "")
                    if self.intent_detector.is_shopping_utterance(content):
                        intent = self.intent_detector.detect_intent(content)
                        shopping_mentions.append({
                            "message": content,
                            "timestamp": msg.get("created_at"),
                            "author": msg.get("role", "unknown"),
                            "intent": intent,
                            "confidence": intent.confidence if hasattr(intent, 'confidence') else 0.5,
                        })
                
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
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass
        
        return ShopBeeResult(
            success=False,
            message=f"Could not capture conversation {conversation_id}.",
        )

    def _get_todos(self) -> list[dict]:
        """Get todos from Bee via CLI."""
        try:
            result = subprocess.run(
                ["npx", BEE_CLI_PACKAGE, "todos", "list"],
                capture_output=True, text=True, timeout=CONVERSATIONS_TIMEOUT,
            )
            if result.returncode == 0 and result.stdout.strip():
                # Parse markdown-formatted output from bee CLI
                todos = self._parse_todos_markdown(result.stdout)
                if todos:
                    return todos
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

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
                    return data.get("todos", [])
                return data
        except Exception:
            pass

        return []

    def _parse_todos_markdown(self, text: str) -> list[dict]:
        """Parse markdown-formatted todo output from bee CLI."""
        import re
        todos = []
        
        # Split by "## Open" and "## Completed" sections
        parts = re.split(r'##\s+(Open|Completed)', text)
        
        for i, part in enumerate(parts):
            if i == 0:
                continue  # Skip the first section before any header
            
            is_completed = (parts[i-1].strip() == "Completed")
            
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
        
        return todos

    def _update_todos_with_links(self, product_results: list) -> None:
        """Update pending todos with Amazon links for matching items."""
        import re
        
        # Get current todos to find which ones need updating
        todos = self._get_todos()
        
        for item in product_results:
            source = item.get("source", "conversation")
            if source != "pending_todo":
                continue
            
            todo_id_str = str(item["mentioned_in"]).replace("todo-", "")
            try:
                todo_id = int(todo_id_str)
            except (ValueError, TypeError):
                continue
            
            # Find this todo in the list
            todo = next((t for t in todos if t.get("id") == todo_id), None)
            if not todo:
                continue
            
            url = item["product"].url
            title = item["product"].title
            
            # Check if link already exists in the todo text
            current_text = todo.get("text", "")
            
            # Remove any existing Amazon links before adding new one
            cleaned_text = re.sub(r'\s*\[Amazon\]\([^)]+\)\s*', '', current_text).strip()
            cleaned_text = re.sub(r'\s*\([^)]+amazon\.com[^)]*\)\s*', '', cleaned_text).strip()
            
            # Add the Amazon link to the todo text (only if not already present)
            if '[Amazon]' in current_text:
                new_text = f"{cleaned_text} [Amazon]({url})"
            else:
                new_text = f"{current_text} [Amazon]({url})"
            
            if new_text != current_text:
                # Update the todo via bee CLI
                try:
                    subprocess.run(
                        ["npx", BEE_CLI_PACKAGE, "todos", "update", str(todo_id), "--text", new_text],
                        capture_output=True, text=True, timeout=10,
                    )
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass

    def _get_facts(self) -> list[dict]:
        """Get personal facts from Bee."""
        try:
            result = subprocess.run(
                ["npx", BEE_CLI_PACKAGE, "facts", "list"],
                capture_output=True, text=True, timeout=CONVERSATIONS_TIMEOUT,
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass

        try:
            import requests
            response = requests.get(
                bee_api_url(BEE_FACTS_PATH),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass

        return []

    def _get_user_profile(self) -> dict | None:
        """Get the Bee user profile."""
        try:
            result = subprocess.run(
                ["npx", BEE_CLI_PACKAGE, "status"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass

        try:
            import requests
            response = requests.get(
                bee_api_url(BEE_ME_PATH),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass

        return None

    # ── Helpers ───────────────────────────────────────────────────────

    def _infer_asin(self, product_name: str) -> str:
        """Infer an ASIN from a product name."""
        import hashlib
        h = hashlib.md5(product_name.encode()).hexdigest()[:10].upper()
        return f"{h[0]}{h[1:9]}{h[9]}"

    def _format_pending_shopping_message(self, cart_items: list[dict]) -> str:
        """Format a message listing pending shopping items."""
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

        return "\n".join(lines)

    def _format_shopping_confirmation(self, confirmation: ShoppingConfirmation) -> str:
        """Format a shopping confirmation message."""
        lines = ["🛒 **ShopBee** — Confirm this purchase:\n"]
        lines.append(f"**Product:** {confirmation.product_title}")
        if confirmation.price:
            lines.append(f"**Price:** {confirmation.price}")
        lines.append(f"**ASIN:** {confirmation.asin}")
        lines.append(f"[View on Amazon]({confirmation.url})")

        return "\n".join(lines)

    def build_shopping_cart(self) -> ShopBeeResult:
        """Build a complete shopping cart from all Bee sources.
        
        Combines items from conversations, todos, and facts to create
        a comprehensive shopping list with Amazon links in details.
        """
        # Get all data sources
        todos = self._get_todos()
        convs = self._get_conversations(limit=20)
        facts = self._get_facts()
        
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
            asin = self._infer_asin(item.product_name)
            if asin not in seen_asins:
                seen_asins.add(asin)
                unique_items.append(item)

        # Look up products on Amazon and build cart
        cart = []
        for mention in unique_items[:15]:  # Top items from all sources
            products = self.amazon_lookup.search(mention.product_name, limit=1)
            
            if products:
                product = products[0]
                cart.append({
                    "product": {
                        "title": product.title,
                        "asin": product.asin,
                        "url": product.url,
                        "price": product.price,
                    },
                    "source": mention.context.get("source", "conversation") if hasattr(mention, 'context') else "conversation",
                    "mentioned_in": mention.source_conversation_id,
                    "confidence": mention.confidence,
                    "raw_mention": mention.raw_utterance,
                })
            elif mention.context.get("source") == "pending_todo":
                cart.append({
                    "product": {
                        "title": mention.product_name,
                        "asin": self._infer_asin(mention.product_name),
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
        todo_items = [i for i in cart if i["source"] == "pending_todo"]
        conv_items = [i for i in cart if i["source"] == "conversation"]
        
        if todo_items:
            lines.append(f"\n📝 **From Todos** ({len(todo_items)} items)\n")
            for item in todo_items:
                product = item["product"]
                lines.append(f"  • {product['title']} - [Amazon]({product['url']})")
        
        if conv_items:
            lines.append(f"\n💬 **From Conversations** ({len(conv_items)} items)\n")
            for item in conv_items:
                product = item["product"]
                confidence = f"{item['confidence']:.0%}"
                lines.append(f"  • {product['title']} (Confidence: {confidence}) - [Amazon]({product['url']})")

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

def main():
    """Run ShopBee from the command line."""
    import sys

    skill = ShopBeeSkill()

    if len(sys.argv) < 2:
        print("ShopBee — 'You said you needed it. Bee remembers.'")
        print("\nUsage:")
        print("  shopbee pending          # Find items you mentioned needing")
        print("  shopbee add <product>    # Add product to cart")
        print("  shopbee search <query>   # Search and add in one step")
        return

    command = sys.argv[1]

    if command == "pending":
        result = skill.find_pending_shopping()
        print(result.message)

    elif command == "cart":
        result = skill.build_shopping_cart()
        print(result.message)

    elif command == "add":
        if len(sys.argv) < 3:
            print("Usage: shopbee add <product_name>")
            return
        result = skill.add_to_cart(sys.argv[2])
        print(result.message)

    elif command == "search":
        if len(sys.argv) < 3:
            print("Usage: shopbee search <query>")
            return
        result = skill.search_and_add(sys.argv[2])
        print(result.message)

    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
