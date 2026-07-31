"""
castorice.utils 模块单元测试

覆盖：
- atomic_json_dump: 正常写入 / 覆盖 / 嵌套目录创建 / 无残留临时文件 / Unicode / kwargs 透传
- extract_json: 合法 JSON / 代码块 / 混合文本 / 空输入 / 无效 JSON / 嵌套
- chinese_tokenize: 空输入 / 纯英文 / 纯中文 / 中英混合 / 小写化
- chinese_text_similarity: 相同 / 完全不同 / 空输入 / 部分重叠
- _is_mostly_chinese: 空输入 / 纯中文 / 纯英文 / 中英混合 / 纯空白
"""

import json
import os

import pytest

from castorice.utils import (
    _is_mostly_chinese,
    atomic_json_dump,
    chinese_text_similarity,
    chinese_tokenize,
    extract_json,
)


# ============================================================
# atomic_json_dump
# ============================================================

class TestAtomicJsonDump:
    """原子化 JSON 写入测试"""

    def test_normal_write(self, temp_dir):
        """正常写入：数据应成功落盘"""
        path = os.path.join(temp_dir, "out.json")
        atomic_json_dump({"a": 1}, path)
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"a": 1}

    def test_overwrite_existing(self, temp_dir):
        """覆盖已存在文件：新数据应替换旧数据"""
        path = os.path.join(temp_dir, "out.json")
        atomic_json_dump({"a": 1}, path)
        atomic_json_dump({"b": 2}, path)
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"b": 2}

    def test_directory_creation(self, temp_dir):
        """嵌套目录自动创建"""
        path = os.path.join(temp_dir, "sub1", "sub2", "out.json")
        atomic_json_dump({"x": 1}, path)
        assert os.path.exists(path)

    def test_no_temp_files_left(self, temp_dir):
        """崩溃安全：成功后不应残留 .tmp 临时文件"""
        path = os.path.join(temp_dir, "out.json")
        atomic_json_dump({"a": 1}, path)
        files = os.listdir(temp_dir)
        assert all(not f.endswith(".tmp") for f in files)

    def test_crash_safety_no_partial_file(self, temp_dir):
        """崩溃安全：写入失败时不应产生损坏的目标文件。

        通过让 json.dump 抛错（不可序列化对象）验证：
        - 目标文件不应存在（或保持原内容）
        - 不应残留 .tmp 文件
        """
        path = os.path.join(temp_dir, "out.json")
        # set 不可 JSON 序列化（默认 encoder 下）
        with pytest.raises(TypeError):
            atomic_json_dump({"bad": {1, 2, 3}}, path)
        # 目标文件不应存在
        assert not os.path.exists(path)
        # 不应残留临时文件
        files = os.listdir(temp_dir)
        assert all(not f.endswith(".tmp") for f in files)

    def test_crash_safety_preserves_existing(self, temp_dir):
        """崩溃安全：写入失败时应保留原有文件内容"""
        path = os.path.join(temp_dir, "out.json")
        # 先写入正常数据
        atomic_json_dump({"original": True}, path)
        # 再尝试写入不可序列化数据，应抛错
        with pytest.raises(TypeError):
            atomic_json_dump({"bad": {1, 2, 3}}, path)
        # 原文件内容应保持不变
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"original": True}

    def test_unicode_content(self, temp_dir):
        """Unicode 内容写入（ensure_ascii=False）"""
        path = os.path.join(temp_dir, "out.json")
        data = {"name": "测试", "emoji": "🎉"}
        atomic_json_dump(data, path, ensure_ascii=False)
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == data

    def test_kwargs_passed_to_json(self, temp_dir):
        """kwargs 透传：sort_keys / indent 应生效"""
        path = os.path.join(temp_dir, "out.json")
        atomic_json_dump({"b": 2, "a": 1}, path, sort_keys=True, indent=2)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # sort_keys 后 a 应在 b 之前
        assert content.index('"a"') < content.index('"b"')
        # indent=2 应产生换行缩进
        assert "\n" in content

    def test_empty_dict(self, temp_dir):
        """空字典写入"""
        path = os.path.join(temp_dir, "out.json")
        atomic_json_dump({}, path)
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {}

    def test_nested_structure(self, temp_dir):
        """嵌套结构写入与读回"""
        path = os.path.join(temp_dir, "out.json")
        data = {"list": [1, 2, 3], "nested": {"a": {"b": [True, None]}}}
        atomic_json_dump(data, path)
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == data


# ============================================================
# extract_json
# ============================================================

class TestExtractJson:
    """JSON 提取测试"""

    def test_valid_json(self):
        """纯 JSON 文本"""
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_json_in_json_code_block(self):
        """```json 代码块"""
        text = '```json\n{"a": 1}\n```'
        assert extract_json(text) == {"a": 1}

    def test_json_in_plain_code_block(self):
        """``` 无语言标识的代码块"""
        text = '```\n{"a": 1}\n```'
        assert extract_json(text) == {"a": 1}

    def test_json_with_surrounding_text(self):
        """JSON 前后有文本"""
        text = '这是响应：\n{"a": 1}\n结束'
        assert extract_json(text) == {"a": 1}

    def test_empty_input(self):
        """空字符串"""
        assert extract_json("") == {}

    def test_none_input(self):
        """None 输入（falsy 兜底）"""
        assert extract_json(None) == {}

    def test_no_json_returns_empty(self):
        """无 JSON 内容"""
        assert extract_json("no json here") == {}

    def test_invalid_json_returns_empty(self):
        """不完整的 JSON 应返回空字典"""
        assert extract_json('{"a": ') == {}

    def test_no_closing_brace_returns_empty(self):
        """缺少右大括号应返回空字典"""
        assert extract_json('{"a": 1') == {}

    def test_nested_json(self):
        """嵌套 JSON"""
        text = '{"a": {"b": [1, 2, 3]}}'
        assert extract_json(text) == {"a": {"b": [1, 2, 3]}}

    def test_json_with_array_value(self):
        """JSON 中包含数组"""
        text = '{"items": [1, 2, 3], "name": "test"}'
        result = extract_json(text)
        assert result["items"] == [1, 2, 3]
        assert result["name"] == "test"

    def test_code_block_invalid_json_falls_back(self):
        """代码块内 JSON 解析失败时应回退到全文查找"""
        # 代码块内是无效 JSON，但代码块外有有效 JSON
        text = '```json\n{invalid}\n```\n{"valid": 1}'
        result = extract_json(text)
        # 应回退并提取到 {"valid": 1}
        assert result == {"valid": 1}

    @pytest.mark.parametrize("text,expected", [
        ('{"x": 1}', {"x": 1}),
        ('{"x": "中文"}', {"x": "中文"}),
        ('```json\n{"k": "v"}\n```', {"k": "v"}),
        ('', {}),
        ('no json', {}),
        ('{"a": 1', {}),
        (None, {}),
    ])
    def test_parametrized_cases(self, text, expected):
        """参数化边界用例"""
        assert extract_json(text) == expected


# ============================================================
# chinese_tokenize
# ============================================================

class TestChineseTokenize:
    """中英文混合分词测试"""

    def test_empty_input(self):
        """空字符串"""
        assert chinese_tokenize("") == set()

    def test_whitespace_only(self):
        """纯空白"""
        assert chinese_tokenize("   ") == set()

    def test_english_text(self):
        """纯英文：按空格拆分"""
        tokens = chinese_tokenize("hello world foo bar")
        assert "hello" in tokens
        assert "world" in tokens
        assert "foo" in tokens
        assert "bar" in tokens

    def test_chinese_bigrams(self):
        """纯中文：生成 bigrams"""
        tokens = chinese_tokenize("我喜欢编程")
        # 应包含连续 bigram
        assert "我喜" in tokens
        assert "喜欢" in tokens
        assert "欢编" in tokens
        assert "编程" in tokens

    def test_chinese_trigrams(self):
        """纯中文：生成 trigrams"""
        tokens = chinese_tokenize("我喜欢编程")
        assert "我喜欢" in tokens
        assert "喜欢编" in tokens
        assert "欢编程" in tokens

    def test_single_chinese_char(self):
        """单字中文段：直接作为 token"""
        tokens = chinese_tokenize("啊")
        assert "啊" in tokens

    def test_lowercase_normalization(self):
        """英文应小写化"""
        tokens = chinese_tokenize("Hello WORLD")
        assert "hello" in tokens
        assert "world" in tokens
        # 不应包含大写形式
        assert "Hello" not in tokens

    def test_mixed_chinese_english(self):
        """中英混合：CJK bigrams + 英文单词"""
        tokens = chinese_tokenize("我喜欢 python 编程")
        # 中文 bigrams
        assert "我喜" in tokens or "喜欢" in tokens
        assert "编程" in tokens
        # 英文单词（长度 >= 2）
        assert "python" in tokens

    def test_single_english_letter_filtered(self):
        """单字母英文噪声应被过滤（中文模式下）"""
        # "我 a b" 中 a、b 是单字母，应被过滤
        tokens = chinese_tokenize("我 a b 测")
        # 单字母不应作为 token
        assert "a" not in tokens
        assert "b" not in tokens

    def test_returns_set_type(self):
        """返回类型应为 set"""
        result = chinese_tokenize("hello")
        assert isinstance(result, set)


# ============================================================
# chinese_text_similarity
# ============================================================

class TestChineseTextSimilarity:
    """中英文相似度测试"""

    def test_identical_text(self):
        """完全相同：相似度 1.0"""
        sim = chinese_text_similarity("hello world", "hello world")
        assert sim == 1.0

    def test_disjoint_text(self):
        """完全不同：相似度 0.0"""
        sim = chinese_text_similarity("apple", "banana")
        assert sim == 0.0

    def test_empty_a_returns_zero(self):
        """空输入 A：相似度 0.0"""
        assert chinese_text_similarity("", "test") == 0.0

    def test_empty_b_returns_zero(self):
        """空输入 B：相似度 0.0"""
        assert chinese_text_similarity("test", "") == 0.0

    def test_both_empty_returns_zero(self):
        """双空输入：相似度 0.0"""
        assert chinese_text_similarity("", "") == 0.0

    def test_partial_overlap(self):
        """部分重叠：相似度在 (0, 1) 区间"""
        sim = chinese_text_similarity("hello world", "hello there")
        assert 0.0 < sim < 1.0

    def test_chinese_similarity(self):
        """中文相似度：相同文本应为 1.0"""
        sim = chinese_text_similarity("我喜欢编程", "我喜欢编程")
        assert sim == 1.0

    def test_similarity_range(self):
        """相似度应在 [0, 1] 区间"""
        sim = chinese_text_similarity("abc def", "def ghi")
        assert 0.0 <= sim <= 1.0


# ============================================================
# _is_mostly_chinese
# ============================================================

class TestIsMostlyChinese:
    """中文主导判断测试"""

    def test_empty(self):
        """空字符串"""
        assert _is_mostly_chinese("") is False

    def test_pure_chinese(self):
        """纯中文"""
        assert _is_mostly_chinese("我喜欢编程") is True

    def test_pure_english(self):
        """纯英文"""
        assert _is_mostly_chinese("hello world") is False

    def test_mixed_mostly_chinese(self):
        """中英混合但中文占主导"""
        assert _is_mostly_chinese("我喜欢 python 编程") is True

    def test_whitespace_only(self):
        """纯空白（non_space == 0 兜底）"""
        assert _is_mostly_chinese("   ") is False

    def test_mostly_english(self):
        """英文占主导（中文比例 ≤ 0.3）"""
        # 1 个中文字符 + 4 个英文字符 = 1/5 = 0.2 < 0.3
        assert _is_mostly_chinese("a啊bcd") is False

    @pytest.mark.parametrize("text,expected", [
        ("", False),
        ("我喜欢", True),
        ("hello", False),
        ("   ", False),
        ("我 a", True),  # 1 CJK / 2 non-space = 0.5 > 0.3
    ])
    def test_parametrized(self, text, expected):
        """参数化边界用例"""
        assert _is_mostly_chinese(text) is expected
