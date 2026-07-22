"""
基础工具集 - 不依赖 LangChain

每个 Tool 只需提供：
- name: 工具名
- description: 工具描述（供 LLM 理解）
- invoke(args) -> str: 同步执行入口

为了与原 castorice_tools 保持兼容，这里同时提供与 LangChain BaseTool 一致的接口。
"""

import inspect
import os
import subprocess
import re
from typing import Dict, Any, List, Optional, Union, get_type_hints, get_origin, get_args

from castorice.http_client import get_http_client


def _get_httpx_client():
    """获取单例 httpx.Client（带浏览器 User-Agent，避免被 API 拦截）"""
    return get_http_client()


_SENSITIVE_FILE_PATTERNS = [
    ".env", ".env.", "id_rsa", "id_dsa", "id_ed25519",
    ".pem", ".ppk", "privkey",
]


def _is_path_safe(file_path: str, allowed_paths: Optional[List[str]]) -> bool:
    """
    检查文件路径是否安全
    - 阻止路径遍历攻击（../ 或 ..\）
    - 阻止读取敏感文件
    - allowed_paths 为 None 或空列表时返回 True（向后兼容）
    - 检查绝对路径是否在 allowed_paths 的任一目录下
    """
    if not file_path or not isinstance(file_path, str):
        return False

    raw_path = file_path.strip()

    if ".." in raw_path:
        return False

    abs_path = os.path.abspath(raw_path)
    canonical_path = os.path.realpath(raw_path)

    if abs_path != canonical_path:
        return False

    file_name = os.path.basename(abs_path).lower()

    for pattern in _SENSITIVE_FILE_PATTERNS:
        if pattern in file_name:
            return False

    if ".ssh" in abs_path.lower().replace("\\", "/").split("/"):
        return False

    if allowed_paths is None or len(allowed_paths) == 0:
        return True

    for allowed in allowed_paths:
        abs_allowed = os.path.abspath(allowed)
        if abs_path == abs_allowed:
            return True
        if abs_path.startswith(abs_allowed.rstrip(os.sep) + os.sep):
            return True

    return False


class Tool:
    """极简工具基类（自研版，替代 LangChain BaseTool）"""

    # Python 类型 → JSON Schema 类型映射
    _TYPE_MAP = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    def __init__(self, name: str, description: str, func, risk_level: str = "low"):
        self.name = name
        self.description = description
        self.func = func
        self.risk_level = risk_level

    def invoke(self, args: Dict[str, Any]) -> str:
        """执行工具，自动适配位置参数与关键字参数"""
        if isinstance(args, dict):
            return self.func(**args)
        return self.func(args)

    @classmethod
    def _resolve_type(cls, param_type) -> str:
        """
        P1-17: 解析 Python 类型为 JSON Schema 类型字符串，支持复合类型。

        - 基础类型 (str/int/float/bool) 直接查表
        - Optional[X] / Union[X, None] 解包取第一个非 None 类型
        - List[X] / Set / Tuple → "array"
        - Dict[K, V] → "object"
        - 无法识别 → "string"（兜底）
        """
        if param_type is None:
            return "string"
        # 基础类型直接查表
        if param_type in cls._TYPE_MAP:
            return cls._TYPE_MAP[param_type]
        # 复合类型
        origin = get_origin(param_type)
        if origin is not None:
            args = get_args(param_type)
            # Optional[X] = Union[X, None]，取第一个非 None 类型
            if origin is Union:
                non_none_args = [a for a in args if a is not type(None)]
                if non_none_args:
                    return cls._resolve_type(non_none_args[0])
                return "string"
            # List[X] / Set / Tuple → array
            if origin in (list, set, tuple, frozenset):
                return "array"
            # Dict[K, V] → object
            if origin is dict:
                return "object"
        return "string"

    @staticmethod
    def _extract_param_docs(func) -> Dict[str, str]:
        """
        P2-2: 从函数 docstring 提取参数描述。

        支持格式：
        - Sphinx: :param name: description
        - Google: Args: / Parameters: 块中的 "name: description"
        """
        doc = getattr(func, "__doc__", None)
        if not doc:
            return {}
        result: Dict[str, str] = {}
        # Sphinx 风格: :param name: description
        for m in re.finditer(r':param\s+(\w+)\s*:\s*(.+)', doc):
            result[m.group(1)] = m.group(2).strip()
        if result:
            return result
        # Google 风格: Args:/Parameters: 块
        google_block = re.search(
            r'(?:Args|Parameters)\s*:\s*\n((?:\s+\w+\s*:.*\n?)+)',
            doc,
        )
        if google_block:
            for line in google_block.group(1).strip().splitlines():
                m = re.match(r'\s+(\w+)\s*:\s*(.+)', line)
                if m:
                    result[m.group(1)] = m.group(2).strip()
        return result

    def to_openai_schema(self) -> dict:
        """生成 OpenAI Function Calling 格式的 tool schema"""
        try:
            hints = get_type_hints(self.func)
            sig = inspect.signature(self.func)
        except Exception:
            return self._minimal_schema()

        properties = {}
        required = []
        # P2-2: 从 docstring 提取参数描述
        param_docs = self._extract_param_docs(self.func)

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls", "args", "kwargs"):
                continue

            param_type = hints.get(param_name)
            # P1-17: 使用 _resolve_type 处理复合类型
            json_type = self._resolve_type(param_type)

            # P2-2: 优先用 docstring 描述，其次用参数名+类型标注
            desc = param_docs.get(param_name, "")
            if not desc:
                desc = param_name
                if param_type is int:
                    desc = f"{param_name} (整数)"
                elif param_type is float:
                    desc = f"{param_name} (数字)"
                elif param_type is bool:
                    desc = f"{param_name} (布尔值)"

            prop = {"type": json_type, "description": desc}
            properties[param_name] = prop

            # 没有默认值的参数是必填的
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        if not properties:
            return self._minimal_schema()

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_anthropic_schema(self) -> dict:
        """生成 Anthropic tool_use 格式的 tool schema"""
        openai_schema = self.to_openai_schema()
        func = openai_schema["function"]
        return {
            "name": func["name"],
            "description": func["description"],
            "input_schema": func["parameters"],
        }

    def _minimal_schema(self) -> dict:
        """最小 schema（无法推导参数类型时的兜底）"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        }


_registered_tools: Dict[str, Tool] = {}


def register_tool(name: str, description: str, risk_level: str = "low"):
    """
    工具注册装饰器
    - 装饰函数，自动创建 Tool 实例并存入 _registered_tools
    - 保留原有函数不变
    - risk_level: 审计风险等级 (low / medium / high)
    """
    def decorator(func):
        tool = Tool(name=name, description=description, func=func, risk_level=risk_level)
        _registered_tools[name] = tool
        return func
    return decorator


# ========== 1. 联网搜索 ==========
@register_tool(
    name="web_search",
    description="联网搜索信息。参数: query(必填,搜索关键词), max_results(可选,默认5)",
)
def _web_search(query: str, max_results: int = 5) -> str:
    """使用 DuckDuckGo 搜索并返回结果摘要"""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "未安装搜索库，请执行: pip install ddgs"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "未搜索到结果"
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            snippet = r.get("body", "") or r.get("snippet", "")
            href = r.get("href", "") or r.get("url", "")
            lines.append(f"{i}. {title}\n   {snippet}\n   {href}")
        return "\n".join(lines)
    except Exception as e:
        return f"搜索失败: {e}"


# ========== 1.5 实时天气查询 ==========

_WEATHER_DESC_ZH = {
    "Sunny": "晴",
    "Clear": "晴",
    "Partly cloudy": "多云",
    "Partly Cloudy": "多云",
    "Cloudy": "阴",
    "Overcast": "阴天",
    "Mist": "薄雾",
    "Fog": "雾",
    "Freezing fog": "冻雾",
    "Patchy rain possible": "可能有阵雨",
    "Patchy rain nearby": "局部有小雨",
    "Patchy snow possible": "可能有阵雪",
    "Patchy sleet possible": "可能有雨夹雪",
    "Patchy freezing drizzle possible": "可能有冻毛毛雨",
    "Thundery outbreaks possible": "可能有雷暴",
    "Blowing snow": "吹雪",
    "Blizzard": "暴风雪",
    "Light drizzle": "小毛毛雨",
    "Patchy light drizzle": "零星小毛毛雨",
    "Freezing drizzle": "冻毛毛雨",
    "Heavy freezing drizzle": "强冻毛毛雨",
    "Light rain": "小雨",
    "Moderate rain at times": "间歇性中雨",
    "Moderate rain": "中雨",
    "Heavy rain at times": "间歇性大雨",
    "Heavy rain": "大雨",
    "Light freezing rain": "小冻雨",
    "Moderate or heavy freezing rain": "中到大雨冻雨",
    "Light sleet": "小雨夹雪",
    "Moderate or heavy sleet": "中到大雨夹雪",
    "Light snow": "小雪",
    "Patchy light snow": "零星小雪",
    "Moderate snow": "中雪",
    "Patchy moderate snow": "间歇性中雪",
    "Heavy snow": "大雪",
    "Patchy heavy snow": "间歇性大雪",
    "Ice pellets": "冰粒",
    "Light rain shower": "小阵雨",
    "Moderate or heavy rain shower": "中到大雨阵雨",
    "Torrential rain shower": "暴雨",
    "Light sleet showers": "小雨夹雪阵雨",
    "Moderate or heavy sleet showers": "中到大雨夹雪阵雨",
    "Light snow showers": "小阵雪",
    "Moderate or heavy snow showers": "中到大雪阵雪",
    "Light showers of ice pellets": "小冰粒阵雨",
    "Moderate or heavy showers of ice pellets": "中到大冰粒阵雨",
    "Patchy light rain with thunder": "零星小雨伴雷暴",
    "Moderate or heavy rain with thunder": "中到大雨伴雷暴",
    "Patchy light snow with thunder": "零星小雪伴雷暴",
    "Moderate or heavy snow with thunder": "中到大雪伴雷暴",
    "Smoky haze": "雾霾",
    "Smoke": "烟霾",
    "Haze": "霾",
}


def _weather_zh(text: str) -> str:
    """天气描述英译中（不区分大小写）"""
    if not text:
        return text
    lower = text.strip().lower()
    for en, zh in _WEATHER_DESC_ZH.items():
        if en.lower() == lower:
            return zh
    return text


@register_tool(
    name="get_weather",
    description="查询城市天气，支持实时天气和未来7天预报。参数: city(必填,城市名,如'大连'、'北京'), day(可选,第几天的预报,0=今天,1=明天,2=后天,最多7天)",
)
def _get_weather(city: str, day: int = 0, lang: str = "zh") -> str:
    """
    查询实时天气和未来7天预报（基于 wttr.in 免费 API，无需 API Key）
    比 web_search 更准确、更快，返回实时气温、天气状况、风速等
    """
    import urllib.parse
    from datetime import datetime, timedelta

    try:
        encoded_city = urllib.parse.quote(city)
        url = f"https://wttr.in/{encoded_city}?format=j1&lang={lang}"

        client = _get_httpx_client()
        resp = client.get(url, headers={"User-Agent": "castorice-agent/2.0"})
        resp.raise_for_status()
        data = resp.json()

        # 限制 day 参数范围
        day = max(0, min(day, 7))

        # 获取指定日期的预报
        if day < len(data["weather"]):
            target_day = data["weather"][day]
        else:
            target_day = data["weather"][-1]

        # 获取今天的实时天气
        current = data["current_condition"][0]
        weather_today = data["weather"][0]

        temp_c = current.get("temp_C", "N/A")
        feels_like = current.get("FeelsLikeC", "N/A")

        desc = ""
        lang_key = f"lang_{lang}"
        en_desc = current.get("weatherDesc", [{}])[0].get("value", "")
        if lang_key in current and current[lang_key]:
            lang_desc = current[lang_key][0].get("value", "")
            if lang_desc and lang_desc.lower() != en_desc.lower():
                desc = lang_desc
        if not desc:
            desc = _weather_zh(en_desc)

        humidity = current.get("humidity", "N/A")
        wind_speed = current.get("windspeedKmph", "N/A")
        wind_dir = current.get("winddir16Point", "")

        maxtemp = weather_today.get("maxtempC", "N/A")
        mintemp = weather_today.get("mintempC", "N/A")

        # 获取指定日期的详细信息
        date_str = target_day.get("date", "")
        target_max = target_day.get("maxtempC", "?")
        target_min = target_day.get("mintempC", "?")
        hourly = target_day.get("hourly", [])
        midday = hourly[len(hourly) // 2] if hourly else {}

        target_desc = ""
        target_en_desc = midday.get("weatherDesc", [{}])[0].get("value", "")
        if lang_key in midday and midday[lang_key]:
            target_lang_desc = midday[lang_key][0].get("value", "")
            if target_lang_desc and target_lang_desc.lower() != target_en_desc.lower():
                target_desc = target_lang_desc
        if not target_desc:
            target_desc = _weather_zh(target_en_desc)

        # 生成日期描述
        day_labels = ["今天", "明天", "后天", "大后天", "4天后", "5天后", "6天后", "7天后"]
        day_label = day_labels[day] if day < len(day_labels) else f"{day}天后"

        # 如果查询的是今天，显示实时天气
        if day == 0:
            result = (
                f"【{city} 实时天气】\n"
                f"当前温度: {temp_c}°C（体感 {feels_like}°C）\n"
                f"天气状况: {desc}\n"
                f"今日气温: {mintemp}°C ~ {maxtemp}°C\n"
                f"湿度: {humidity}%\n"
                f"风速: {wind_speed} km/h {wind_dir}"
            )
        else:
            result = (
                f"【{city} {day_label} ({date_str}) 天气预报】\n"
                f"天气状况: {target_desc}\n"
                f"气温: {target_min}°C ~ {target_max}°C"
            )

        # 添加未来7天预报（无论查询哪一天，都显示完整预报）
        forecast_lines = []
        for i, day_data in enumerate(data["weather"][:7]):
            date = day_data.get("date", "")
            max_c = day_data.get("maxtempC", "?")
            min_c = day_data.get("mintempC", "?")
            hourly_data = day_data.get("hourly", [])
            midday_data = hourly_data[len(hourly_data) // 2] if hourly_data else {}

            day_desc = ""
            day_en_desc = midday_data.get("weatherDesc", [{}])[0].get("value", "")
            if lang_key in midday_data and midday_data[lang_key]:
                day_lang_desc = midday_data[lang_key][0].get("value", "")
                if day_lang_desc and day_lang_desc.lower() != day_en_desc.lower():
                    day_desc = day_lang_desc
            if not day_desc:
                day_desc = _weather_zh(day_en_desc)

            label = day_labels[i] if i < len(day_labels) else f"{i}天后"
            forecast_lines.append(f"{label} ({date}): {day_desc}, {min_c}°C ~ {max_c}°C")

        result += (
            f"\n\n【未来7天预报】\n"
            + "\n".join(forecast_lines)
        )

        return result
    except Exception as e:
        return f"天气查询失败: {e}"


# ========== 2. 读文件 ==========
@register_tool(
    name="read_file",
    description="读取文本文件内容。参数: file_path(必填,文件路径), max_lines(可选,默认200), allowed_paths(可选,允许的目录白名单)",
    risk_level="medium",  # P2-3: 读取文件内容属于中等风险
)
def _read_file(file_path: str, max_lines: int = 200, allowed_paths: Optional[List[str]] = None) -> str:
    try:
        if not _is_path_safe(file_path, allowed_paths):
            return f"[BLOCKED] 文件路径不在白名单中或为敏感文件: {file_path}"

        path = os.path.abspath(file_path)
        if not os.path.exists(path):
            return f"文件不存在: {path}"
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        lines = content.splitlines()
        if len(lines) > max_lines:
            content = "\n".join(lines[:max_lines]) + f"\n... (截断,共 {len(lines)} 行)"
        return content
    except Exception as e:
        return f"读取失败: {e}"


# ========== 3. 写文件 ==========
@register_tool(
    name="write_file",
    description="将内容写入文件。参数: file_path(必填), content(必填,文本内容), allowed_paths(可选,允许的目录白名单)",
    risk_level="high",
)
def _write_file(file_path: str, content: str, allowed_paths: Optional[List[str]] = None) -> str:
    try:
        if not _is_path_safe(file_path, allowed_paths):
            return f"[BLOCKED] 文件路径不在白名单中或为敏感文件: {file_path}"

        from castorice.security.file_guard import get_file_guard
        guard = get_file_guard()
        allowed, reason = guard.check_write_allowed(file_path, content)
        if not allowed:
            return f"[BLOCKED] {reason}"

        os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入 {len(content)} 字符到 {file_path}"
    except Exception as e:
        return f"写入失败: {e}"


# ========== 4. 终端命令 ==========

_TERMINAL_WHITELIST = {
    "ls", "dir", "cd", "pwd", "echo", "cat", "type", "grep", "findstr",
    "wc", "head", "tail", "python", "python3", "pip", "pip3", "git",
    "npm", "node", "curl", "wget", "whoami", "date", "time", "hostname",
    "ipconfig", "ifconfig", "ping", "tree", "more", "less", "sort",
    "uniq", "awk", "sed", "cut", "paste", "join", "split", "tr",
    "base64", "md5sum", "sha256sum", "du", "df", "free", "top", "ps",
    "tasklist",
}

_COMMAND_INJECTION_PATTERNS = [
    ";", "|", "&&", "||", "$(", "`(", "`", "$", "\\(", "\\)",
    "<", ">", ">>", "<<",
    "&", "`", "$", "(", ")",
]


@register_tool(
    name="terminal",
    description="执行 shell 命令(Windows/PowerShell/cmd)。参数: command(必填), timeout(可选,默认30秒)",
    risk_level="high",
)
def _terminal(command: str, timeout: int = 30) -> str:
    """执行 shell 命令（白名单安全限制 + 命令注入防护）"""
    stripped = command.strip()
    if not stripped:
        return "[BLOCKED] 命令不能为空"

    from castorice.security.file_guard import get_file_guard
    guard = get_file_guard()
    allowed, reason = guard.check_command_allowed(command)
    if not allowed:
        return f"[BLOCKED] {reason}"

    cmd_parts = stripped.split()
    cmd_prefix = cmd_parts[0].lower() if cmd_parts else ""

    if cmd_prefix not in _TERMINAL_WHITELIST:
        print(f"[TERMINAL BLOCKED] 命令不在白名单中: {cmd_prefix}")
        return f"[BLOCKED] 命令不在白名单中: {cmd_prefix}"

    for pattern in _COMMAND_INJECTION_PATTERNS:
        if pattern in stripped:
            print(f"[TERMINAL BLOCKED] 检测到命令注入: {pattern}")
            return f"[BLOCKED] 检测到命令注入字符: {pattern}"

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="ignore",
        )
        out = result.stdout or ""
        err = result.stderr or ""
        if result.returncode != 0:
            return f"exit={result.returncode}\nstdout:\n{out}\nstderr:\n{err}"
        return out if out else "(无输出)"
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT] 命令执行超过 {timeout} 秒"
    except Exception as e:
        return f"执行失败: {e}"


# ========== 5. Python REPL ==========

_SAFE_BUILTINS = {
    "print": print,
    "len": len,
    "range": range,
    "str": str,
    "int": int,
    "float": float,
    "list": list,
    "dict": dict,
    "sum": sum,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sorted": sorted,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "type": type,
    "isinstance": isinstance,
    "bool": bool,
    "set": set,
    "tuple": tuple,
    "reversed": reversed,
    "all": all,
    "any": any,
    "ord": ord,
    "chr": chr,
    "hex": hex,
    "bin": bin,
    "format": format,
    "pow": pow,
    "divmod": divmod,
    "next": next,
    "iter": iter,
    "slice": slice,
    "True": True,
    "False": False,
    "None": None,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "IndexError": IndexError,
    "KeyError": KeyError,
    "StopIteration": StopIteration,
    "NotImplementedError": NotImplementedError,
    "RuntimeError": RuntimeError,
    "AttributeError": AttributeError,
}


_DANGEROUS_PATTERNS = [
    "__import__", "__subclasses__", "__bases__", "__globals__", "__code__",
    "open(", "exec(", "eval(", "compile(", "subprocess", "os.", "sys.",
    "socket.", "urllib.", "http.", "requests.", "shutil.", "pathlib.",
]


def _is_code_safe_ast(code: str) -> tuple:
    """
    AST 级安全扫描：检测危险名称、属性、import 语句。
    可防御字符串拼接绕过（如 "ope" + "n("）。
    """
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误: {e}"

    dangerous_names = {
        "__import__", "__subclasses__", "__bases__", "__globals__",
        "__code__", "open", "exec", "eval", "compile", "subprocess",
        "os", "sys", "socket", "urllib", "http", "requests", "shutil",
        "pathlib", "importlib", "builtins", "__builtins__",
    }

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return False, "禁止 import 语句"
        if isinstance(node, ast.Name):
            if node.id in dangerous_names:
                return False, f"检测到危险名称: {node.id}"
        if isinstance(node, ast.Attribute):
            if node.attr in dangerous_names:
                return False, f"检测到危险属性: {node.attr}"

    return True, ""


@register_tool(
    name="python_repl",
    description="执行 Python 代码片段(安全受限沙箱,无文件系统和网络访问)。参数: code(必填,Python 代码)",
    risk_level="medium",
)
def _python_repl(code: str, timeout: int = 30) -> str:
    """
    安全受限的 Python 代码执行沙箱

    特性：
    - 使用白名单内置函数，无文件系统和网络访问
    - 无 __import__、open、exec、eval 等危险函数
    - 保留 stdout 重定向捕获输出功能
    - 双层防护：字符串模式匹配 + AST 语法树扫描
    """
    code_lower = code.lower()
    for pattern in _DANGEROUS_PATTERNS:
        if pattern in code_lower:
            return f"[安全拦截] 检测到危险代码模式: {pattern}"

    safe_ast, ast_reason = _is_code_safe_ast(code)
    if not safe_ast:
        return f"[安全拦截] {ast_reason}"

    try:
        import sys
        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            safe_globals = {"__builtins__": _SAFE_BUILTINS}
            exec(code, safe_globals, {})
        finally:
            output = sys.stdout.getvalue()
            sys.stdout = old_stdout
        return output if output else "(无输出)"
    except Exception as e:
        return f"执行出错: {type(e).__name__}: {e}"


# ========== 6. 文档读取（PDF/DOCX/XLSX） ==========
@register_tool(
    name="read_document",
    description="读取 PDF/Word/Excel 文档内容。参数: file_path(必填,文档路径)",
    risk_level="medium",
)
def _read_document(file_path: str) -> str:
    """读取 PDF/Word/Excel 文档"""
    if not os.path.exists(file_path):
        return f"文件不存在: {file_path}"
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text[:5000]
        if ext == ".docx":
            from docx import Document
            doc = Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs)[:5000]
        if ext == ".xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(file_path, read_only=True, data_only=True)
            lines = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    lines.append("\t".join(str(c) if c is not None else "" for c in row))
            return "\n".join(lines)[:5000]
        return _read_file(file_path)
    except Exception as e:
        return f"文档读取失败: {e}"


# ========== 7. 获取当前时间 ==========
@register_tool(
    name="get_current_time",
    description="获取当前日期和时间（包含时区信息）。无需参数。",
)
def _get_current_time() -> str:
    """获取当前日期时间，支持多种格式输出"""
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)
    local_now = datetime.now().astimezone()
    
    return (
        f"当前时间（UTC）: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"当前时间（本地）: {local_now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"星期: {['周一', '周二', '周三', '周四', '周五', '周六', '周日'][local_now.weekday()]}\n"
        f"年份: {local_now.year}\n"
        f"月份: {local_now.month}月\n"
        f"日期: {local_now.day}日"
    )


# ========== 工具注册入口 ==========
def get_base_tools(config: Optional[Dict[str, Any]] = None) -> List[Tool]:
    """
    获取所有基础工具实例列表
    - 优先从 _registered_tools 获取已注册的工具
    - 根据配置决定启用哪些工具
    - 从配置中读取 allowed_paths 传给文件读写工具
    - 保持向后兼容
    - 自动加载 web_tools 中的外部信息检索工具
    """
    # 自动导入 web_tools 以注册外部信息检索工具
    try:
        from . import web_tools  # noqa: F401
    except ImportError:
        pass

    allowed_paths = None
    if config:
        tools_cfg = config.get("tools", {})
        # 从 read_file 和 write_file 配置中读取 allowed_paths
        read_cfg = tools_cfg.get("read_file", {})
        write_cfg = tools_cfg.get("write_file", {})
        if isinstance(read_cfg, dict):
            allowed_paths = read_cfg.get("allowed_paths", None)
        if allowed_paths is None and isinstance(write_cfg, dict):
            allowed_paths = write_cfg.get("allowed_paths", None)

    # 读取各工具的 enabled 配置
    tools_enabled = {}
    if config:
        tools_cfg = config.get("tools", {})
        for key in ["web_search", "get_weather", "get_current_time", "read_file", "write_file", "terminal", "python_repl", "read_document",
                    "web_fetch", "wikipedia_search", "arxiv_search", "news_search",
                    "github_search", "youtube_search", "bilibili_search",
                    "ip_info", "stock_price", "translate_text",
                    "anime_search", "anime_season",
                    "vrchat_search", "vrchat_popular_worlds",
                    "vrchat_user_status", "vrchat_world_info",
                    "generate_image", "analyze_image", "extract_text_from_image",
                    "pixiv_search", "pixiv_popular", "pixiv_user_works"]:
            tool_cfg = tools_cfg.get(key, {})
            if isinstance(tool_cfg, dict):
                tools_enabled[key] = tool_cfg.get("enabled", True)
            else:
                tools_enabled[key] = True

    def is_enabled(name: str) -> bool:
        return tools_enabled.get(name, True)

    all_tools = []

    if is_enabled("web_search") and "web_search" in _registered_tools:
        all_tools.append(_registered_tools["web_search"])

    if is_enabled("get_weather") and "get_weather" in _registered_tools:
        all_tools.append(_registered_tools["get_weather"])

    if is_enabled("get_current_time") and "get_current_time" in _registered_tools:
        all_tools.append(_registered_tools["get_current_time"])

    if is_enabled("read_file") and "read_file" in _registered_tools:
        base_tool = _registered_tools["read_file"]
        if allowed_paths is not None:
            def _read_file_wrapper(file_path: str, max_lines: int = 200) -> str:
                return base_tool.func(file_path, max_lines=max_lines, allowed_paths=allowed_paths)
            all_tools.append(Tool(
                name="read_file",
                description=base_tool.description,
                func=_read_file_wrapper,
            ))
        else:
            all_tools.append(base_tool)

    if is_enabled("write_file") and "write_file" in _registered_tools:
        base_tool = _registered_tools["write_file"]
        if allowed_paths is not None:
            def _write_file_wrapper(file_path: str, content: str) -> str:
                return base_tool.func(file_path, content, allowed_paths=allowed_paths)
            all_tools.append(Tool(
                name="write_file",
                description=base_tool.description,
                func=_write_file_wrapper,
            ))
        else:
            all_tools.append(base_tool)

    if is_enabled("terminal") and "terminal" in _registered_tools:
        all_tools.append(_registered_tools["terminal"])

    if is_enabled("python_repl") and "python_repl" in _registered_tools:
        all_tools.append(_registered_tools["python_repl"])

    if is_enabled("read_document") and "read_document" in _registered_tools:
        all_tools.append(_registered_tools["read_document"])

    # 外部信息检索工具
    for name in ["web_fetch", "wikipedia_search", "arxiv_search", "news_search",
                 "github_search", "youtube_search", "bilibili_search",
                 "ip_info", "stock_price", "translate_text",
                 "anime_search", "anime_season",
                 "vrchat_search", "vrchat_popular_worlds",
                 "vrchat_user_status", "vrchat_world_info",
                 "generate_image", "analyze_image", "extract_text_from_image",
                 "pixiv_search", "pixiv_popular", "pixiv_user_works"]:
        if is_enabled(name) and name in _registered_tools:
            all_tools.append(_registered_tools[name])

    return all_tools
