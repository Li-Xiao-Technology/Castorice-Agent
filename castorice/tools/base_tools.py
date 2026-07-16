"""
基础工具集 - 不依赖 LangChain

每个 Tool 只需提供：
- name: 工具名
- description: 工具描述（供 LLM 理解）
- invoke(args) -> str: 同步执行入口

为了与原 castorice_tools 保持兼容，这里同时提供与 LangChain BaseTool 一致的接口。
"""

import os
import subprocess
import re
from typing import Dict, Any, List, Optional


class Tool:
    """极简工具基类（自研版，替代 LangChain BaseTool）"""

    def __init__(self, name: str, description: str, func):
        self.name = name
        self.description = description
        self.func = func

    def invoke(self, args: Dict[str, Any]) -> str:
        """执行工具，自动适配位置参数与关键字参数"""
        if isinstance(args, dict):
            return self.func(**args)
        return self.func(args)


# ========== 1. 联网搜索 ==========
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
    "Moderate or heavy snow showers": "中到大雪阵雨",
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


def _get_weather(city: str, lang: str = "zh") -> str:
    """
    查询实时天气（基于 wttr.in 免费 API，无需 API Key）
    比 web_search 更准确、更快，返回实时气温、天气状况、风速等
    """
    import httpx
    import urllib.parse

    try:
        encoded_city = urllib.parse.quote(city)
        url = f"https://wttr.in/{encoded_city}?format=j1&lang={lang}"

        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers={"User-Agent": "castorice-agent/2.0"})
            resp.raise_for_status()
            data = resp.json()

        current = data["current_condition"][0]
        weather_today = data["weather"][0]

        temp_c = current.get("temp_C", "N/A")
        feels_like = current.get("FeelsLikeC", "N/A")

        # 天气描述：优先用官方中文翻译，若翻译缺失（值等于英文）则手动翻译
        desc = ""
        lang_key = f"lang_{lang}"
        en_desc = current.get("weatherDesc", [{}])[0].get("value", "")
        if lang_key in current and current[lang_key]:
            lang_desc = current[lang_key][0].get("value", "")
            # wttr.in 有些语言翻译缺失，lang_zh 返回的也是英文
            if lang_desc and lang_desc.lower() != en_desc.lower():
                desc = lang_desc
        if not desc:
            desc = _weather_zh(en_desc)

        humidity = current.get("humidity", "N/A")
        wind_speed = current.get("windspeedKmph", "N/A")
        wind_dir = current.get("winddir16Point", "")

        maxtemp = weather_today.get("maxtempC", "N/A")
        mintemp = weather_today.get("mintempC", "N/A")

        # 未来3天预报
        forecast_lines = []
        for day in data["weather"][:3]:
            date = day.get("date", "")
            max_c = day.get("maxtempC", "?")
            min_c = day.get("mintempC", "?")
            hourly = day.get("hourly", [])
            midday = hourly[len(hourly) // 2] if hourly else {}

            day_desc = ""
            day_en_desc = midday.get("weatherDesc", [{}])[0].get("value", "")
            if lang_key in midday and midday[lang_key]:
                day_lang_desc = midday[lang_key][0].get("value", "")
                if day_lang_desc and day_lang_desc.lower() != day_en_desc.lower():
                    day_desc = day_lang_desc
            if not day_desc:
                day_desc = _weather_zh(day_en_desc)

            forecast_lines.append(f"{date}: {day_desc}, {min_c}°C ~ {max_c}°C")

        return (
            f"【{city} 实时天气】\n"
            f"当前温度: {temp_c}°C（体感 {feels_like}°C）\n"
            f"天气状况: {desc}\n"
            f"今日气温: {mintemp}°C ~ {maxtemp}°C\n"
            f"湿度: {humidity}%\n"
            f"风速: {wind_speed} km/h {wind_dir}\n"
            f"\n【未来3天预报】\n"
            + "\n".join(forecast_lines)
        )
    except httpx.TimeoutException:
        return "天气查询超时，请稍后重试"
    except Exception as e:
        return f"天气查询失败: {e}"


# ========== 2. 读文件 ==========
def _read_file(file_path: str, max_lines: int = 200) -> str:
    try:
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
def _write_file(file_path: str, content: str) -> str:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入 {len(content)} 字符到 {file_path}"
    except Exception as e:
        return f"写入失败: {e}"


# ========== 4. 终端命令 ==========
def _terminal(command: str, timeout: int = 30) -> str:
    """执行 shell 命令（带安全限制）"""
    # 危险命令拦截
    blocked = ["rm -rf /", "mkfs", "format c:", "del /f /s /q c:\\", ":(){:|:&};:"]
    cmd_lower = command.lower().strip()
    for b in blocked:
        if b in cmd_lower:
            return f"[BLOCKED] 危险命令被拦截: {command}"

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
def _python_repl(code: str, timeout: int = 30) -> str:
    """受限的 Python 代码执行"""
    # 黑名单模块
    blocked = ["os.system", "subprocess", "shutil.rmtree", ":()"]
    for b in blocked:
        if b in code:
            return f"[BLOCKED] 检测到危险代码片段: {b}"

    try:
        import sys
        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            exec(code, {"__builtins__": __builtins__}, {})
        finally:
            output = sys.stdout.getvalue()
            sys.stdout = old_stdout
        return output if output else "(无输出)"
    except Exception as e:
        return f"执行出错: {type(e).__name__}: {e}"


# ========== 6. 文档读取（PDF/DOCX/XLSX） ==========
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


# ========== 工具注册入口 ==========
def get_base_tools(config: Optional[Dict[str, Any]] = None) -> List[Tool]:
    """获取所有基础工具实例列表"""
    return [
        Tool(
            name="web_search",
            description="联网搜索信息。参数: query(必填,搜索关键词), max_results(可选,默认5)",
            func=_web_search,
        ),
        Tool(
            name="get_weather",
            description="查询城市实时天气及未来3天预报。参数: city(必填,城市名,如'大连'、'北京')",
            func=_get_weather,
        ),
        Tool(
            name="read_file",
            description="读取文本文件内容。参数: file_path(必填,文件路径), max_lines(可选,默认200)",
            func=_read_file,
        ),
        Tool(
            name="write_file",
            description="将内容写入文件。参数: file_path(必填), content(必填,文本内容)",
            func=_write_file,
        ),
        Tool(
            name="terminal",
            description="执行 shell 命令(Windows/PowerShell/cmd)。参数: command(必填), timeout(可选,默认30秒)",
            func=_terminal,
        ),
        Tool(
            name="python_repl",
            description="执行 Python 代码片段(受限沙箱)。参数: code(必填,Python 代码)",
            func=_python_repl,
        ),
        Tool(
            name="read_document",
            description="读取 PDF/Word/Excel 文档内容。参数: file_path(必填,文档路径)",
            func=_read_document,
        ),
    ]
