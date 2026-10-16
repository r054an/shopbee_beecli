#!/usr/bin/env python3
"""Demo: ShopBee in action — using real Bee data."""

import json
import subprocess


def run_bee(args):
    """Run a bee CLI command and return parsed JSON."""
    result = subprocess.run(
        ["npx", "@beeai/cli"] + args,
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        print(f"⚠️ bee {args[0]} failed: {result.stderr.strip()}")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout


def demo():
    """Run a full ShopBee demo with real Bee data."""
    from shopbee import ShopBeeSkill

    print("=" * 60)
    print("🐝 ShopBee — 'You said you needed it. Bee remembers.'")
    print("=" * 60)

    # Step 1: Check Bee connection
    print("\n[1] Checking Bee connection...")
    status = run_bee(["status"])
    if status and "Token" in str(status):
        print("   ✅ Connected to Bee (production API)")
    else:
        print("   ⚠️  Not logged in. Run 'bee login' first.")

    # Step 2: Get user profile
    print("\n[2] User profile:")
    profile = run_bee(["status"])
    if profile:
        for line in str(profile).split('\n')[:5]:
            print(f"   {line.strip()}")

    # Step 3: Get today's brief
    print("\n[3] Today's Bee context:")
    today = run_bee(["today", "--context"])
    if today:
        print(json.dumps(today, indent=4)[:500])

    # Step 4: Get recent conversations
    print("\n[4] Recent conversations (last 10):")
    convs = run_bee(["conversations", "list"])
    if convs and isinstance(convs, list):
        for i, conv in enumerate(convs[:10], 1):
            text = conv.get("text", conv.get("content", ""))[:80]
            print(f"   {i}. [{conv.get('id', '?')}] {text}")

    # Step 5: Analyze for shopping intent
    print("\n[5] Detecting shopping mentions...")
    skill = ShopBeeSkill()
    result = skill.find_pending_shopping()
    print(f"\n{result.message}")

    if result.details and "cart" in result.details:
        for item in result.details["cart"]:
            product = item["product"]
            conf = f"{item['confidence']:.0%}"
            print(f"   • {product.title} (ASIN: {product.asin}) — confidence: {conf}")

    # Step 6: Get pending todos
    print("\n[6] Pending todos:")
    todos = run_bee(["todos", "list"])
    if todos and isinstance(todos, list):
        for todo in todos[:10]:
            status_icon = "✅" if todo.get("completed") else "⬜"
            print(f"   {status_icon} {todo.get('text', '')}")

    # Step 7: Search a product on Amazon
    print("\n[7] Searching 'USB-C cable' on Amazon...")
    products = skill.amazon_lookup.search("USB-C cable", limit=3)
    for p in products:
        print(f"   • {p.title}")
        print(f"     ASIN: {p.asin}")
        print(f"     URL:  {p.url}")

    # Step 8: Create a shopping confirmation
    print("\n[8] Creating shopping confirmation...")
    if products:
        confirmation = skill.shopping_actions.create_confirmation(
            product_title=products[0].title,
            asin=products[0].asin,
            url=products[0].url,
        )
        print(f"\n{confirmation.to_message()}")

        # Step 9: Execute the shopping action
        print("\n[9] Executing AMAZON.AddToShoppingCart...")
        result = skill.shopping_actions.confirm_action(confirmation)
    else:
        confirmation = None
        result = type('obj', (object,), {'message': 'No products found to confirm.'})()

    if not products:
        print(f"   {result.message}")
    print(f"   {result.message}")

    print("\n" + "=" * 60)
    print("✅ Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    demo()
