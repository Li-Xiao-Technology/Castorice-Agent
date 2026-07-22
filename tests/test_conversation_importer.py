"""
P2 对话导入器测试
"""
import os
import tempfile
import json
import pytest
from castorice.conversation_importer import (
    ImportFormat,
    ConversationImporter,
    get_conversation_importer,
)


class TestImportFormat:
    def test_formats_exist(self):
        """测试所有格式存在"""
        assert ImportFormat.JSONL.value == "jsonl"
        assert ImportFormat.JSON.value == "json"
        assert ImportFormat.WECHAT.value == "wechat"
        assert ImportFormat.TEXT.value == "text"


class TestConversationImporter:
    def test_jsonl_import(self):
        """测试 JSONL 格式导入"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write('{"role": "user", "content": "你好"}\n')
            f.write('{"role": "assistant", "content": "你好！有什么可以帮你的？"}\n')
            path = f.name
        try:
            importer = ConversationImporter()
            result = importer.import_from_file(path, ImportFormat.JSONL)
            assert result.get("success") is True
            assert result.get("imported_count") == 2
        finally:
            os.remove(path)

    def test_json_import(self):
        """测试 JSON 数组格式导入"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            data = [
                {"role": "user", "content": "问题1"},
                {"role": "assistant", "content": "回答1"},
            ]
            json.dump(data, f, ensure_ascii=False)
            path = f.name
        try:
            importer = ConversationImporter()
            result = importer.import_from_file(path, ImportFormat.JSON)
            assert result.get("success") is True
            assert result.get("imported_count") == 2
        finally:
            os.remove(path)

    def test_wechat_import(self):
        """测试微信格式导入"""
        content = """张三 2024-01-01 10:00:00
你好，在吗？
李四 2024-01-01 10:01:00
在的，什么事？
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(content)
            path = f.name
        try:
            importer = ConversationImporter()
            result = importer.import_from_file(path, ImportFormat.WECHAT)
            assert result.get("success") is True
            assert result.get("imported_count") >= 2
        finally:
            os.remove(path)

    def test_text_import(self):
        """测试纯文本格式导入"""
        content = """User: 你好
Assistant: 你好！很高兴见到你。
User: 今天天气如何？
Assistant: 我无法获取实时天气，建议查看天气预报。
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(content)
            path = f.name
        try:
            importer = ConversationImporter()
            result = importer.import_from_file(path, ImportFormat.TEXT)
            assert result.get("success") is True
            assert result.get("imported_count") >= 4
        finally:
            os.remove(path)

    def test_missing_file(self):
        """测试文件不存在"""
        importer = ConversationImporter()
        result = importer.import_from_file("/nonexistent/file.json")
        assert "error" in result

    def test_auto_detect_format(self):
        """测试自动检测格式"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write('{"role": "user", "content": "test"}\n')
            path = f.name
        try:
            importer = ConversationImporter()
            result = importer.import_from_file(path, format_type=None)
            assert result.get("success") is True
        finally:
            os.remove(path)

    def test_imported_count_accumulates(self):
        """测试累计导入计数"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write('{"role": "user", "content": "a"}\n')
            path1 = f.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write('{"role": "user", "content": "b"}\n{"role": "user", "content": "c"}\n')
            path2 = f.name
        try:
            importer = ConversationImporter()
            importer.import_from_file(path1, ImportFormat.JSONL)
            result = importer.import_from_file(path2, ImportFormat.JSONL)
            assert result.get("total_imported") == 3
        finally:
            os.remove(path1)
            os.remove(path2)


class TestConversationImporterSingleton:
    def test_singleton(self):
        """测试全局单例"""
        i1 = get_conversation_importer()
        i2 = get_conversation_importer()
        assert i1 is i2
