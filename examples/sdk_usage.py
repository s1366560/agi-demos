"""
Basic usage example using the MemStack SDK.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add SDK to path
sdk_path = Path(__file__).parent.parent / "sdk" / "python"
sys.path.insert(0, str(sdk_path))

from memstack import MemStackAsyncClient


async def main():
    """Run basic SDK usage example."""

    # Get API key from environment or use default for development
    api_key = os.getenv("MEMSTACK_API_KEY", "ms_sk_default_dev_key")
    base_url = os.getenv("MEMSTACK_BASE_URL", "http://localhost:8000")

    print("🚀 MemStack SDK Basic Usage Example")
    print("=" * 50)

    async with MemStackAsyncClient(api_key=api_key, base_url=base_url) as client:
        # Check health
        print("\n1. Checking API health...")
        try:
            health = await client.health_check()
            print(f"✅ API is healthy: {health}")
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            return

        # Create episodes
        print("\n2. Creating episodes...")

        episode1 = await client.create_episode(
            name="User Preference - Hiking",
            content="User mentioned they love hiking in the mountains and enjoy outdoor activities during weekends.",
            source_type="text",
            source_description="User conversation",
            group_id="user_demo",
        )
        print(f"✅ Created episode 1: {episode1.id}")

        episode2 = await client.create_episode(
            name="User Preference - Food",
            content="User said they prefer Italian cuisine and enjoy cooking pasta dishes at home.",
            source_type="text",
            source_description="User conversation",
            group_id="user_demo",
        )
        print(f"✅ Created episode 2: {episode2.id}")

        episode3 = await client.create_episode(
            name="User Preference - Travel",
            content="User is planning a trip to Japan next month and is interested in visiting historical temples.",
            source_type="text",
            source_description="User conversation",
            group_id="user_demo",
        )
        print(f"✅ Created episode 3: {episode3.id}")

        # Wait a bit for processing (in production, this would be handled by callbacks)
        print("\n⏳ Waiting for episode processing...")
        await asyncio.sleep(5)

        # Search memories
        print("\n3. Searching memories...")

        queries = [
            "What outdoor activities does the user enjoy?",
            "What type of cuisine does the user prefer?",
            "Where is the user planning to travel?",
        ]

        for query in queries:
            print(f"\n🔍 Query: {query}")
            try:
                results = await client.search_memory(query=query, limit=3)
                print(f"   Found {results.total} results:")

                for i, result in enumerate(results.results, 1):
                    print(f"   {i}. [Score: {result.score:.2f}] {result.content[:100]}...")

            except Exception as e:
                print(f"   ❌ Search failed: {e}")

    print("\n" + "=" * 50)
    print("✅ Example completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
