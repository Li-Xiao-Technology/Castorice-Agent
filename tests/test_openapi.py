"""
OpenAPI 文档生成器测试
"""
import json
import os
import tempfile
import pytest
from castorice.openapi_generator import (
    generate_openapi_spec,
    export_openapi_json,
    export_openapi_to_file,
    ENDPOINTS,
    SCHEMAS,
)


class TestOpenAPIGenerator:
    def test_basic_structure(self):
        """测试基本结构"""
        spec = generate_openapi_spec()
        assert spec["openapi"].startswith("3.0")
        assert "info" in spec
        assert "paths" in spec
        assert "components" in spec

    def test_info_section(self):
        """测试 info 部分"""
        spec = generate_openapi_spec()
        assert spec["info"]["title"] == "Castorice Agent API"
        assert "version" in spec["info"]
        assert "description" in spec["info"]

    def test_all_endpoints_present(self):
        """测试所有端点存在"""
        spec = generate_openapi_spec()
        expected_paths = {e["path"] for e in ENDPOINTS}
        actual_paths = set(spec["paths"].keys())
        assert expected_paths <= actual_paths

    def test_endpoint_methods(self):
        """测试端点方法"""
        spec = generate_openapi_spec()
        for endpoint in ENDPOINTS:
            path = endpoint["path"]
            method = endpoint["method"].lower()
            assert method in spec["paths"][path]
            op = spec["paths"][path][method]
            assert "summary" in op
            assert "responses" in op

    def test_schemas_defined(self):
        """测试 Schemas 定义"""
        spec = generate_openapi_spec()
        assert "ChatRequest" in spec["components"]["schemas"]
        assert "ChatResponse" in spec["components"]["schemas"]
        assert "StatusResponse" in spec["components"]["schemas"]

    def test_security_schemes(self):
        """测试安全方案"""
        spec = generate_openapi_spec()
        schemes = spec["components"]["securitySchemes"]
        assert "ApiKeyAuth" in schemes
        assert schemes["ApiKeyAuth"]["type"] == "apiKey"
        assert schemes["ApiKeyAuth"]["in"] == "header"

    def test_chat_endpoint_has_request_body(self):
        """测试 chat 端点有 request body"""
        spec = generate_openapi_spec()
        chat = spec["paths"]["/chat"]["post"]
        assert "requestBody" in chat
        schema_ref = chat["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        assert "ChatRequest" in schema_ref

    def test_history_has_path_param(self):
        """测试 history 端点有路径参数"""
        spec = generate_openapi_spec()
        history = spec["paths"]["/history/{session_id}"]["get"]
        params = history.get("parameters", [])
        path_params = [p for p in params if p["in"] == "path"]
        assert len(path_params) >= 1
        assert path_params[0]["name"] == "session_id"

    def test_clear_memory_has_query_param(self):
        """测试 clear_memory 端点有 query 参数"""
        spec = generate_openapi_spec()
        clear = spec["paths"]["/clear_memory"]["post"]
        params = clear.get("parameters", [])
        query_params = [p for p in params if p["in"] == "query"]
        assert len(query_params) >= 1
        confirm_param = next(p for p in query_params if p["name"] == "confirm")
        assert confirm_param["schema"]["type"] == "boolean"

    def test_json_export(self):
        """测试 JSON 导出"""
        json_str = export_openapi_json()
        spec = json.loads(json_str)
        assert spec["openapi"].startswith("3.0")

    def test_file_export(self, tmp_path):
        """测试文件导出"""
        out_file = tmp_path / "openapi.json"
        export_openapi_to_file(str(out_file))
        assert out_file.exists()
        with open(out_file, "r", encoding="utf-8") as f:
            spec = json.load(f)
        assert spec["openapi"].startswith("3.0")

    def test_endpoint_count(self):
        """测试端点数量"""
        assert len(ENDPOINTS) >= 9  # 至少 9 个端点
        assert len(ENDPOINTS) == 19  # 当前 19 个（含 WebSocket + Electron API）

    def test_valid_json_structure(self):
        """测试 JSON 结构有效"""
        spec = generate_openapi_spec()
        json_str = json.dumps(spec)
        # 重新解析应成功
        parsed = json.loads(json_str)
        assert parsed == spec

    def test_status_response_includes_emotion(self):
        """测试 status 响应包含情感字段"""
        spec = generate_openapi_spec()
        status_schema = spec["components"]["schemas"]["StatusResponse"]
        props = status_schema["properties"]
        # 情感相关字段应存在
        assert "emotion_enabled" in props
        assert "emotion_pleasure" in props
        assert "emotion_arousal" in props
        assert "emotion_dominance" in props
