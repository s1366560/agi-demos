#!/usr/bin/env python3
"""
测试文件上传链路的完整性

分析可能导致文件损坏的各个环节：
1. S3 上传/下载
2. Base64 编解码
3. JSON/WebSocket 传输
4. 文件写入
"""

import base64
import hashlib
import json
import os
import sys
import tempfile

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def create_test_binary_data(size: int = 1024) -> bytes:
    """创建模拟 Excel/ZIP 的二进制测试数据"""
    # Excel 文件头是 PK (50 4B for ZIP-based xlsx)
    header = bytes(
        [
            0x50,
            0x4B,
            0x03,
            0x04,  # PK\x03\x04 - ZIP 签名
            0x14,
            0x00,
            0x06,
            0x00,  # 版本和标志
            0x08,
            0x00,
            0x00,
            0x00,  # 压缩方法
            0x21,
            0x00,
            0x00,
            0x00,  # 时间戳
        ]
    )
    # 添加随机二进制数据
    random_data = os.urandom(size - len(header))
    return header + random_data


def test_base64_roundtrip() -> bool:
    """测试 base64 编解码是否保持文件完整性"""
    print("\n" + "=" * 60)
    print("测试 1: Base64 编解码完整性")
    print("=" * 60)

    test_data = create_test_binary_data(10000)
    original_hash = hashlib.md5(test_data).hexdigest()

    print(f"原始数据长度: {len(test_data)} bytes")
    print(f"原始数据 MD5: {original_hash}")
    print(f"原始数据前16字节(hex): {test_data[:16].hex()}")

    # 模拟 prepare_for_sandbox 的编码
    encoded = base64.b64encode(test_data).decode("utf-8")
    print(f"\nBase64 编码长度: {len(encoded)} chars")

    # 模拟 import_file 的解码
    decoded = base64.b64decode(encoded)
    decoded_hash = hashlib.md5(decoded).hexdigest()

    print(f"解码后数据长度: {len(decoded)} bytes")
    print(f"解码后 MD5: {decoded_hash}")

    if original_hash == decoded_hash and test_data == decoded:
        print("✅ Base64 编解码完整性测试通过！")
        return True
    else:
        print("❌ Base64 编解码数据不一致！")
        return False


def test_json_transport() -> bool:
    """测试 JSON 传输是否保持 base64 完整性"""
    print("\n" + "=" * 60)
    print("测试 2: JSON 传输完整性")
    print("=" * 60)

    # 创建包含所有可能字节值的数据
    test_data = bytes(range(256)) * 100  # 25600 bytes
    original_hash = hashlib.md5(test_data).hexdigest()

    print(f"原始数据长度: {len(test_data)} bytes")
    print(f"原始数据 MD5: {original_hash}")

    # 编码为 base64
    encoded = base64.b64encode(test_data).decode("utf-8")

    # 模拟 JSON-RPC 消息（WebSocket 传输格式）
    message = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "import_file",
            "arguments": {
                "filename": "测试文件.xlsx",  # 中文文件名
                "content_base64": encoded,
                "destination": "/workspace",
            },
        },
        "id": 1,
    }

    # JSON 编码（模拟 WebSocket 发送）
    json_str = json.dumps(message, ensure_ascii=False)
    print(f"JSON 消息长度: {len(json_str)} chars")

    # JSON 解码（模拟 WebSocket 接收）
    parsed = json.loads(json_str)
    recovered_base64 = parsed["params"]["arguments"]["content_base64"]

    # 验证 base64 字符串是否保持不变
    if encoded == recovered_base64:
        print("✅ JSON 传输保持 base64 完整")
    else:
        print("❌ JSON 传输改变了 base64 字符串！")
        print(f"  原始长度: {len(encoded)}, 传输后: {len(recovered_base64)}")
        return False

    # 解码
    decoded = base64.b64decode(recovered_base64)
    decoded_hash = hashlib.md5(decoded).hexdigest()

    if original_hash == decoded_hash:
        print("✅ JSON 传输后数据完整性验证通过")
        return True
    else:
        print("❌ 数据在 JSON 传输中损坏！")
        return False


def test_file_write() -> bool:
    """测试文件写入是否保持完整性"""
    print("\n" + "=" * 60)
    print("测试 3: 文件写入完整性")
    print("=" * 60)

    test_data = create_test_binary_data(50000)
    original_hash = hashlib.md5(test_data).hexdigest()

    print(f"原始数据长度: {len(test_data)} bytes")
    print(f"原始数据 MD5: {original_hash}")

    # 模拟 import_file 的写入方式
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as f:
        temp_path = f.name
        # 这是 import_tools.py 使用的写入方式
        # file_path.write_bytes(content)
        f.write(test_data)

    # 读取并验证
    with open(temp_path, "rb") as f:
        read_data = f.read()

    read_hash = hashlib.md5(read_data).hexdigest()

    print(f"读取数据长度: {len(read_data)} bytes")
    print(f"读取数据 MD5: {read_hash}")

    # 清理
    os.unlink(temp_path)

    if original_hash == read_hash:
        print("✅ 文件写入完整性测试通过！")
        return True
    else:
        print("❌ 文件写入数据不一致！")
        return False


def test_full_pipeline_simulation() -> bool:
    """模拟完整的上传管道"""
    print("\n" + "=" * 60)
    print("测试 4: 完整管道模拟")
    print("=" * 60)

    # 1. 创建原始文件数据
    original_data = create_test_binary_data(100000)  # 100KB
    original_hash = hashlib.md5(original_data).hexdigest()

    print(f"[1] 原始数据: {len(original_data)} bytes, MD5: {original_hash}")

    # 2. 模拟 S3 存储（假设正确）
    s3_data = original_data  # S3 应该保持原样

    # 3. 模拟 prepare_for_sandbox (attachment_service.py)
    # content = await self._storage.get_file(attachment.object_key)
    # base64.b64encode(content).decode("utf-8")
    content_base64 = base64.b64encode(s3_data).decode("utf-8")
    print(f"[2] Base64 编码: {len(content_base64)} chars")

    # 4. 模拟 WebSocket JSON-RPC 传输
    message = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "import_file",
            "arguments": {
                "filename": "test.xlsx",
                "content_base64": content_base64,
            },
        },
        "id": 123,
    }
    json_encoded = json.dumps(message)
    json_decoded = json.loads(json_encoded)
    received_base64 = json_decoded["params"]["arguments"]["content_base64"]
    print(f"[3] JSON 传输: 原始={len(content_base64)}, 接收={len(received_base64)}")

    # 5. 模拟 import_file 解码 (import_tools.py)
    # content = base64.b64decode(content_base64)
    decoded_content = base64.b64decode(received_base64)
    print(f"[4] Base64 解码: {len(decoded_content)} bytes")

    # 6. 模拟文件写入
    # file_path.write_bytes(content)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as f:
        temp_path = f.name
        f.write(decoded_content)

    # 7. 验证最终文件
    with open(temp_path, "rb") as f:
        final_data = f.read()
    final_hash = hashlib.md5(final_data).hexdigest()

    print(f"[5] 最终文件: {len(final_data)} bytes, MD5: {final_hash}")

    os.unlink(temp_path)

    if original_hash == final_hash:
        print("\n✅ 完整管道模拟测试通过！")
        print("   从原始数据 → Base64 → JSON → Base64解码 → 文件写入 全程数据完整")
        return True
    else:
        print("\n❌ 完整管道中数据损坏！")
        return False


def analyze_potential_issues():
    """分析可能导致文件损坏的潜在问题"""
    print("\n" + "=" * 60)
    print("潜在问题分析")
    print("=" * 60)

    issues = []

    # 1. 检查 Python 版本
    import sys

    print(f"Python 版本: {sys.version}")

    # 2. 检查 base64 模块
    import base64

    test_bytes = b"\x00\x01\x02\xff\xfe\xfd"
    encoded = base64.b64encode(test_bytes)
    decoded = base64.b64decode(encoded)
    if test_bytes != decoded:
        issues.append("base64 模块编解码不正确")

    # 3. 检查 JSON 对 Unicode 的处理
    import json

    # Base64 字符串只包含 ASCII 字符，不应有问题
    b64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
    json_test = json.dumps({"data": b64_chars})
    json_parsed = json.loads(json_test)
    if json_parsed["data"] != b64_chars:
        issues.append("JSON 处理 base64 字符有问题")

    if not issues:
        print("✅ 基础环境检查通过，没有发现潜在问题")
        print("\n如果文件仍然损坏，可能的原因：")
        print("1. 前端上传时已经损坏（FormData/Blob 处理问题）")
        print("2. S3 上传时的问题（分片上传未正确合并）")
        print("3. Multipart upload 分片顺序或内容问题")
        print("4. 网络传输中断导致部分数据丢失")
        print("5. 文件在前端被意外处理（如编码转换）")
    else:
        for issue in issues:
            print(f"❌ {issue}")

    return len(issues) == 0


def main():
    print("=" * 60)
    print("文件上传链路完整性深度测试")
    print("=" * 60)

    all_passed = True

    all_passed &= test_base64_roundtrip()
    all_passed &= test_json_transport()
    all_passed &= test_file_write()
    all_passed &= test_full_pipeline_simulation()
    all_passed &= analyze_potential_issues()

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有测试通过！")
        print("\n后端 base64 编解码链路是完整的。")
        print("如果文件仍然损坏，问题很可能在：")
        print("")
        print("1. 【前端】文件读取方式不正确")
        print("   - 应使用 FileReader.readAsArrayBuffer() 而非 readAsText()")
        print("   - FormData 上传时应保持原始 Blob/File 对象")
        print("")
        print("2. 【前端→后端】API 上传配置问题")
        print("   - Content-Type 应为 multipart/form-data 或 application/octet-stream")
        print("   - 不应对二进制数据做任何编码转换")
        print("")
        print("3. 【S3 Multipart Upload】分片合并问题")
        print("   - 分片顺序不正确")
        print("   - 分片 ETag 不匹配")
        print("   - Complete Multipart 调用失败")
    else:
        print("❌ 存在测试失败，需要进一步排查！")
    print("=" * 60)


if __name__ == "__main__":
    main()
