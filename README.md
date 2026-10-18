<div align="center"><img width="300" height="150" alt="Bee Rounded@2x" src="https://github.com/user-attachments/assets/d24ad62a-aad7-487a-a634-efde561194fe" />
<img width="300" height="150" alt="logo" src="logo.jpg" />
</div>

# ShopBee — "You said you needed it. Bee remembers."

A **Bee Skill** for Amazon Shopping that detects shopping intent from your conversations and adds items to your cart via Alexa Shopping Actions.

## Features

- 🛒 Detects shopping mentions in Bee conversations using regex patterns and keyword matching
- 🔍 Looks up products on Amazon with ASIN resolution
- ✅ Creates confirmation prompts before adding to cart
- 📱 Works with both Bee device and Apple Watch running Bee software
- 🔄 Three integration interfaces: CLI, MCP, and Proxy API

## How It Works

1. **Capture** — When you say *"I need a USB-C cable"* in conversation, ShopBee captures the mention
2. **Remember** — The item is stored with context (conversation ID, timestamp, confidence score)
3. **Recall** — Ask *"What did I say I needed?"* and ShopBee finds it on Amazon
4. **Act** — Confirm and add to your shopping cart via `AMAZON.AddToShoppingCart`

## Installation

```bash
pip install -e .
npx @beeai/cli login
npx @beeai/cli proxy
```

## Usage

### Command Line

```bash
shopbee pending          # Find items you mentioned needing
shopbee add "USB-C cable"   # Add product to cart
shopbee search "keyboard"    # Search and add in one step
shopbee cart               # Build complete shopping cart from all sources
shopbee version            # Show current version
shopbee update             # Update to latest version
```

### Programmatic Usage

```python
from shopbee import ShopBeeSkill

skill = ShopBeeSkill()
result = skill.find_pending_shopping()  # Lists items with Amazon links
result = skill.add_to_cart("USB-C cable")
result = skill.search_and_add("mechanical keyboard")
result = skill.build_shopping_cart()    # Complete cart from all sources
```

## Bee Integration

ShopBee integrates with [Bee](https://github.com/melvinlsl/Bee) through three interfaces — CLI, MCP, and Proxy API — ensuring it works regardless of how you run Bee.

### Configuration Example

Add ShopBee to your `bee.json`:

```json
{
  "skills": {
    "shopbee": {
      "enabled": true,
      "type": "skill",
      "description": "Detects shopping intent from conversations and adds items to Amazon cart via Alexa Shopping Actions.",
      "invoke": ["shopbee pending"],
      "fallback_invoke": ["npx @beeai/cli execute --directive '{\"directive\":{\"header\":{\"namespace\":\"Alexa.Shopping\",\"name\":\"AddToShoppingCart\",\"payloadVersion\":3},\"payload\":{\"products\":[{\"asin\":\"B09V3KXJP2\",\"quantity\":1,\"title\":\"USB-C Cable\"}],\"shoppingListName\":\"Default\"}}}'"],
      "config": {
        "bee_proxy_url": "http://127.0.0.1:8787",
        "amazon_search_url": "https://www.amazon.com/s?k={query}",
        "conversations_timeout": 15,
        "product_lookup_timeout": 10
      }
    }
  }
}
```

## Architecture

ShopBee consists of four components:

- **IntentDetector** — Analyzes conversation transcripts using regex patterns and keyword matching to identify shopping mentions with confidence scores.
- **AmazonLookup** — Searches Amazon's search page via HTTP requests, parses HTML results, and resolves ASINs for products.
- **ShoppingActions** — Handles Alexa Shopping Actions by building and executing the `AMAZON.AddToShoppingCart` directive through Bee CLI.
- **ShopBeeSkill** — Orchestrates all components to provide a unified shopping experience with deduplication via deterministic ASIN hashing.

## Project Structure

```
shopbee/
├── skill.py              # Main ShopBeeSkill class and CLI entry point
├── intent_detector.py    # Shopping intent detection from conversations
├── amazon_lookup.py      # Amazon product search and ASIN resolution
├── shopping_actions.py   # Alexa Shopping Actions (AMAZON.AddToShoppingCart)
└── config.py             # Configuration constants for URLs, timeouts, etc.
```

## Development

```bash
make install    # Install dev dependencies
make test       # Run tests (40 tests)
make lint       # Check code style
make fix        # Auto-fix issues
```

## License

MIT
