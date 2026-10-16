# ShopBee — "You said you needed it. Bee remembers."

A **Bee Skill** for Amazon Shopping that detects shopping intent from your conversations and adds items to your cart via Alexa Shopping Actions.

## How It Works

1. **Capture**: When you naturally say something like *"I need a USB-C cable"* in conversation, ShopBee captures it
2. **Remember**: The mention is stored with context (conversation ID, timestamp, confidence score)
3. **Recall**: Ask *"What did I say I needed?"* and ShopBee finds the product on Amazon
4. **Act**: Confirm and add to your shopping cart via `AMAZON.AddToShoppingCart`

## Installation

```bash
# Install dependencies
pip install -e .

# Authenticate with Bee (if not already done)
npx @beeai/cli login

# Start the bee proxy for local API access
npx @beeai/cli proxy
```

## Usage

### Command Line

```bash
# Find pending shopping items
shopbee pending

# Add a product to cart
shopbee add "USB-C cable"

# Search and add in one step
shopbee search "mechanical keyboard"

# Build complete shopping cart from all sources
shopbee cart
```

### Using the Shell Script

```bash
./run.sh pending
./run.sh add "USB-C cable"
./run.sh search "mechanical keyboard"
./run.sh cart
```

### Using Make

```bash
make pending
make add PRODUCT="USB-C cable"
make search QUERY="mechanical keyboard"
make cart
```

### Programmatic Usage

```python
from shopbee import ShopBeeSkill

skill = ShopBeeSkill()

# Find what you mentioned needing
result = skill.find_pending_shopping()
print(result.message)  # Lists items with Amazon links

# Add to cart
result = skill.add_to_cart("USB-C cable")

# Search and add in one step
result = skill.search_and_add("mechanical keyboard")

# Build complete shopping cart
result = skill.build_shopping_cart()
```

## Bee Track Compatibility

- **Apple Watch + Bee**: Fully supported
- **Bee Device**: Works with the wearable Bee device
- **Access Methods**: Uses all three official Bee interfaces — CLI, MCP, and Proxy API

## Amazon Integration

- **Product Lookup**: Web scraping + Product Advertising API fallback
- **Shopping Action**: `AMAZON.AddToShoppingCart` (official Alexa directive)
- **Namespace**: `Alexa.Shopping`
- **Payload Version**: 3

## Project Structure

```
shopbee/
├── skill.py              # Main ShopBeeSkill class — core entry point
├── intent_detector.py    # Shopping intent detection from conversations
├── amazon_lookup.py      # Amazon product search and ASIN resolution
├── shopping_actions.py   # Alexa Shopping Actions (AMAZON.AddToShoppingCart)
└── config.py             # Configuration constants for URLs, timeouts, etc.
```

## Architecture

ShopBee is organized into four main components:

1. **IntentDetector** — Analyzes conversation transcripts using regex patterns and keyword matching to identify shopping mentions with confidence scores
2. **AmazonLookup** — Searches Amazon's search page via HTTP requests, parses HTML results, and resolves ASINs for products
3. **ShoppingActions** — Handles Alexa Shopping Actions by building and executing the `AMAZON.AddToShoppingCart` directive through Bee CLI
4. **ShopBeeSkill** — Orchestrates all components to provide a unified shopping experience

## Configuration

All URLs, timeouts, and constants are centralized in `shopbee/config.py`:

- **Bee Proxy URL**: Configurable via environment variable or directly in config
- **Amazon URLs**: Search, product detail, and wishlist templates
- **Timeouts**: Named constants for conversation (15s), request (5s), and product lookup (10s) timeouts

## Development

```bash
# Install dev dependencies
make install

# Run tests
make test

# Check code style
make lint

# Auto-fix issues
make fix
```

## License

MIT
