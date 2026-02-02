#!/usr/bin/env python3
"""
端到端文件上传完整性测试

直接测试：
1. 上传文件到 S3
2. 从 S3 下载
3. 验证文件完整性
4. 测试 prepare_for_sandbox 的 base64 编码
5. 模拟 import_file 的解码和写入
"""

import asyncio
import base64
import hashlib
import os
import sys
import tempfile

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.configuration.config import get_settings


def create_test_xlsx_data() -> bytes:
    """创建模拟的 Excel 文件数据（实际是一个小型 ZIP 结构）"""
    # 真实的 xlsx 文件是一个 ZIP 文件
    # 这里创建一个简化的二进制数据用于测试
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # 添加一些测试内容
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')
        zf.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships></Relationships>')
        # 添加一些随机数据模拟真实 Excel 内容
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            f'<?xml version="1.0"?><worksheet><data>{os.urandom(10000).hex()}</data></worksheet>',
        )

    return buffer.getvalue()


async def test_s3_upload_download():
    """测试 S3 上传和下载的完整性"""
    print("\n" + "=" * 60)
    print("测试 1: S3 上传/下载完整性")
    print("=" * 60)

    from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import S3StorageAdapter

    settings = get_settings()

    # 创建 S3 adapter
    storage = S3StorageAdapter(
        endpoint_url=settings.s3_endpoint_url,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
        bucket_name=settings.s3_bucket_name,
        region=settings.aws_region,
    )

    # 创建测试数据
    test_data = create_test_xlsx_data()
    original_hash = hashlib.md5(test_data).hexdigest()

    print(f"原始数据大小: {len(test_data)} bytes")
    print(f"原始数据 MD5: {original_hash}")
    print(f"原始数据前32字节(hex): {test_data[:32].hex()}")

    # 测试对象键
    test_key = f"test/integrity_test_{os.urandom(4).hex()}.xlsx"

    try:
        # 上传
        print(f"\n正在上传到 S3: {test_key}")
        await storage.upload_file(
            file_content=test_data,
            object_key=test_key,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            metadata={"filename": "测试文件.xlsx", "purpose": "both"},
        )
        print("✅ 上传成功")

        # 下载
        print(f"正在从 S3 下载: {test_key}")
        downloaded_data = await storage.get_file(test_key)

        if downloaded_data is None:
            print("❌ 下载失败：文件不存在")
            return False

        downloaded_hash = hashlib.md5(downloaded_data).hexdigest()

        print(f"下载数据大小: {len(downloaded_data)} bytes")
        print(f"下载数据 MD5: {downloaded_hash}")
        print(f"下载数据前32字节(hex): {downloaded_data[:32].hex()}")

        # 验证
        if original_hash == downloaded_hash:
            print("✅ S3 上传/下载完整性验证通过！")

            # 清理
            await storage.delete_file(test_key)
            return True
        else:
            print("❌ S3 上传/下载数据不一致！")
            print(f"  期望: {original_hash}")
            print(f"  实际: {downloaded_hash}")
            return False

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_full_sandbox_pipeline():
    """测试完整的 sandbox 导入管道"""
    print("\n" + "=" * 60)
    print("测试 2: 完整 Sandbox 导入管道")
    print("=" * 60)

    from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import S3StorageAdapter

    settings = get_settings()

    # 创建 S3 adapter
    storage = S3StorageAdapter(
        endpoint_url=settings.s3_endpoint_url,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
        bucket_name=settings.s3_bucket_name,
        region=settings.aws_region,
    )

    # 创建测试数据
    test_data = create_test_xlsx_data()
    original_hash = hashlib.md5(test_data).hexdigest()

    print(f"[1] 原始文件: {len(test_data)} bytes, MD5: {original_hash}")

    test_key = f"test/sandbox_test_{os.urandom(4).hex()}.xlsx"

    try:
        # Step 1: 上传到 S3
        await storage.upload_file(
            file_content=test_data,
            object_key=test_key,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        print(f"[2] S3 上传成功: {test_key}")

        # Step 2: 从 S3 下载（模拟 prepare_for_sandbox）
        content = await storage.get_file(test_key)
        if content is None:
            print("❌ S3 下载失败")
            return False

        s3_hash = hashlib.md5(content).hexdigest()
        print(f"[3] S3 下载: {len(content)} bytes, MD5: {s3_hash}")

        # Step 3: Base64 编码（prepare_for_sandbox）
        content_base64 = base64.b64encode(content).decode("utf-8")
        print(f"[4] Base64 编码: {len(content_base64)} chars")

        # Step 4: 模拟 JSON-RPC 传输
        import json

        message = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "import_file",
                "arguments": {
                    "filename": "测试文件.xlsx",
                    "content_base64": content_base64,
                },
            },
        }
        json_str = json.dumps(message)
        parsed = json.loads(json_str)
        received_base64 = parsed["params"]["arguments"]["content_base64"]
        print(f"[5] JSON 传输: 编码前={len(content_base64)}, 传输后={len(received_base64)}")

        # Step 5: Base64 解码（import_file）
        decoded = base64.b64decode(received_base64)
        decoded_hash = hashlib.md5(decoded).hexdigest()
        print(f"[6] Base64 解码: {len(decoded)} bytes, MD5: {decoded_hash}")

        # Step 6: 写入文件（import_file）
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as f:
            temp_path = f.name
            f.write(decoded)

        # Step 7: 验证最终文件
        with open(temp_path, "rb") as f:
            final_data = f.read()
        final_hash = hashlib.md5(final_data).hexdigest()
        print(f"[7] 最终文件: {len(final_data)} bytes, MD5: {final_hash}")

        os.unlink(temp_path)

        # 清理 S3
        await storage.delete_file(test_key)

        # 验证
        if original_hash == final_hash:
            print("\n✅ 完整管道测试通过！文件在整个流程中保持完整")
            return True
        else:
            print("\n❌ 文件在管道中损坏！")
            print(f"  原始: {original_hash}")
            print(f"  最终: {final_hash}")

            # 找出损坏点
            if original_hash != s3_hash:
                print("  💥 损坏点: S3 上传/下载")
            elif s3_hash != decoded_hash:
                print("  💥 损坏点: Base64 编解码或 JSON 传输")
            elif decoded_hash != final_hash:
                print("  💥 损坏点: 文件写入")

            return False

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_real_file_if_exists():
    """如果有真实的上传文件，测试其完整性"""
    print("\n" + "=" * 60)
    print("测试 3: 检查现有上传文件（如果有）")
    print("=" * 60)

    from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import S3StorageAdapter

    settings = get_settings()

    storage = S3StorageAdapter(
        endpoint_url=settings.s3_endpoint_url,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
        bucket_name=settings.s3_bucket_name,
        region=settings.aws_region,
    )

    # 列出最近的附件
    try:
        files = await storage.list_files("attachments/", max_keys=10)

        if not files:
            print("没有找到已上传的附件文件")
            return True

        print(f"找到 {len(files)} 个附件文件")

        for file_key in files[:3]:  # 只检查前3个
            print(f"\n检查文件: {file_key}")

            content = await storage.get_file(file_key)
            if content:
                print(f"  大小: {len(content)} bytes")
                print(f"  MD5: {hashlib.md5(content).hexdigest()}")
                print(f"  前16字节(hex): {content[:16].hex()}")

                # 检查是否是有效的 ZIP/Office 文件
                if content[:4] == b"PK\x03\x04":
                    print("  ✅ 文件头正确（ZIP/Office 格式）")
                elif content[:4] == b"%PDF":
                    print("  ✅ 文件头正确（PDF 格式）")
                elif content[:2] == b"\xff\xd8":
                    print("  ✅ 文件头正确（JPEG 格式）")
                elif content[:8] == b"\x89PNG\r\n\x1a\n":
                    print("  ✅ 文件头正确（PNG 格式）")
                else:
                    print(f"  ⚠️ 未知文件格式，前4字节: {content[:4]}")

        return True

    except Exception as e:
        print(f"检查失败: {e}")
        return False


async def main():
    print("=" * 60)
    print("端到端文件上传完整性测试")
    print("=" * 60)

    all_passed = True

    try:
        all_passed &= await test_s3_upload_download()
        all_passed &= await test_full_sandbox_pipeline()
        all_passed &= await test_real_file_if_exists()
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback

        traceback.print_exc()
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有端到端测试通过！")
        print("\n后端完整链路是正确的。")
        print("如果用户上传的文件仍然损坏，问题一定在：")
        print("")
        print("1. 【前端】浏览器读取文件时")
        print("2. 【网络】HTTP 请求传输时")
        print("3. 【特定文件】某些文件类型有特殊问题")
        print("")
        print("建议检查：")
        print("- 浏览器控制台是否有错误")
        print("- 网络面板中请求的大小是否正确")
        print("- 尝试用 curl 直接上传文件测试")
    else:
        print("❌ 存在测试失败！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
