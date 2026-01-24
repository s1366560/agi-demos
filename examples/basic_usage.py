"""示例：如何使用 VIP Memory API"""

import asyncio

import httpx


async def main():
    """演示 VIP Memory API 的基本用法"""
    base_url = "http://localhost:8000/api/v1"

    async with httpx.AsyncClient(timeout=120.0) as client:
        # 1. 检查服务健康状态
        print("1. 检查服务健康状态...")
        response = await client.get("http://localhost:8000/health")
        print(f"   状态: {response.json()}\n")

        # 2. 创建第一个 Episode
        print("2. 创建第一个 Episode（用户偏好）...")
        episode1 = {
            "content": "John prefers dark mode in the application.",
            "source_type": "text",
            "metadata": {"user_id": "user_123", "category": "preference"},
        }
        response = await client.post(f"{base_url}/episodes/", json=episode1)
        print(f"   响应: {response.json()}\n")

        # 3. 创建第二个 Episode
        print("3. 创建第二个 Episode（用户信息）...")
        episode2 = {
            "content": "Alice is a software engineer at TechCorp, working on AI projects.",
            "source_type": "text",
            "metadata": {"user_id": "user_456", "category": "profile"},
        }
        response = await client.post(f"{base_url}/episodes/", json=episode2)
        print(f"   响应: {response.json()}\n")

        # 4. 创建第三个 Episode（JSON 数据）
        print("4. 创建第三个 Episode（结构化数据）...")
        episode3 = {
            "content": '{"event": "purchase", "user": "John", "product": "Pro Plan", "price": 99.99}',
            "source_type": "json",
            "metadata": {"event_type": "transaction"},
        }
        response = await client.post(f"{base_url}/episodes/", json=episode3)
        print(f"   响应: {response.json()}\n")

        # 等待一下，让 Graphiti 处理 episodes
        print("5. 等待 Graphiti 处理 episodes（30秒）...\n")
        await asyncio.sleep(30)

        # 6. 搜索记忆 - 查询用户偏好
        print("6. 搜索：John 的偏好是什么？")
        query = {"query": "What does John prefer?", "limit": 5}
        response = await client.post(f"{base_url}/memory/search", json=query)
        results = response.json()
        print(f"   找到 {results['total']} 条记忆:")
        for item in results["results"]:
            print(f"   - {item['content']} (评分: {item['score']:.2f})")
        print()

        # 7. 搜索记忆 - 查询 Alice 的信息
        print("7. 搜索：Alice 是谁？")
        query = {"query": "Who is Alice?", "limit": 5}
        response = await client.post(f"{base_url}/memory/search", json=query)
        results = response.json()
        print(f"   找到 {results['total']} 条记忆:")
        for item in results["results"]:
            print(f"   - {item['content']} (评分: {item['score']:.2f})")
        print()

        # 8. 搜索记忆 - 查询购买记录
        print("8. 搜索：有哪些购买记录？")
        query = {"query": "purchase transactions", "limit": 5}
        response = await client.post(f"{base_url}/memory/search", json=query)
        results = response.json()
        print(f"   找到 {results['total']} 条记忆:")
        for item in results["results"]:
            print(f"   - {item['content']} (评分: {item['score']:.2f})")
        print()


if __name__ == "__main__":
    print("=" * 80)
    print("VIP Memory API 使用示例")
    print("=" * 80)
    print()
    print("确保服务正在运行: python -m server.main")
    print("或使用 Docker Compose: docker-compose up")
    print()
    print("=" * 80)
    print()

    try:
        asyncio.run(main())
        print("=" * 80)
        print("示例运行完成！")
        print("=" * 80)
    except httpx.ConnectError:
        print("❌ 无法连接到服务。请确保 VIP Memory API 正在运行。")
        print("   启动命令: python -m server.main")
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback

        traceback.print_exc()
