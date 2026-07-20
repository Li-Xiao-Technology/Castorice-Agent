"""
外部信息检索工具集

提供网页抓取、百科查询、学术搜索等能力：
- web_fetch: 抓取网页正文内容
- wikipedia_search: 维基百科查询
- arxiv_search: arXiv 论文检索
- news_search: 新闻聚合搜索
- github_search: GitHub 仓库搜索
- youtube_search: YouTube 视频搜索
- bilibili_search: Bilibili 视频搜索
- ip_info: IP/域名信息查询
- stock_price: 股票价格查询
- translate_text: 多语言翻译
"""

import re
from typing import Dict, Any, List, Optional
from .base_tools import register_tool, _get_httpx_client

# ========== 网页内容抓取 ==========

def _clean_html(html: str) -> str:
    """简单清理 HTML，提取正文文本"""
    # 移除 script/style 标签及其内容
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.IGNORECASE | re.DOTALL)
    # 移除 HTML 标签
    html = re.sub(r'<[^>]+>', ' ', html)
    # 合并空白
    html = re.sub(r'\s+', ' ', html)
    # 解码常见 HTML 实体
    for pattern, repl in [('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"')]:
        html = html.replace(pattern, repl)
    return html.strip()


@register_tool(
    name="web_fetch",
    description="抓取网页正文内容。参数: url(必填,网页URL), max_length(可选,默认3000字符)",
)
def _web_fetch(url: str, max_length: int = 3000) -> str:
    """抓取网页并提取正文文本"""
    if not url.startswith(('http://', 'https://')):
        return "URL 必须以 http:// 或 https:// 开头"

    try:
        client = _get_httpx_client()
        resp = client.get(url, follow_redirects=True, timeout=15)
        resp.raise_for_status()

        content_type = resp.headers.get('content-type', '')
        if 'pdf' in content_type.lower():
            return "[INFO] 该链接是 PDF 文件，请使用 read_document 工具下载后读取"

        html = resp.text
        text = _clean_html(html)

        if len(text) > max_length:
            text = text[:max_length] + f"\n... (截断,共 {len(text)} 字符)"

        return text if text else "(未能提取正文内容)"
    except Exception as e:
        return f"网页抓取失败: {e}"


# ========== 维基百科查询 ==========

@register_tool(
    name="wikipedia_search",
    description="查询维基百科条目。参数: query(必填,搜索词), lang(可选,语言代码,默认zh中文)",
)
def _wikipedia_search(query: str, lang: str = "zh") -> str:
    """
    查询 Wikipedia API
    - lang: zh(中文), en(英文), ja(日文) 等
    """
    try:
        client = _get_httpx_client()

        # 1. 搜索条目
        search_url = f"https://{lang}.wikipedia.org/w/api.php"
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 3,
        }
        resp = client.get(search_url, params=search_params, timeout=10)
        data = resp.json()

        results = data.get("query", {}).get("search", [])
        if not results:
            return f"未找到相关条目: {query}"

        # 2. 获取第一个条目的摘要
        page_id = results[0]["pageid"]
        extract_url = f"https://{lang}.wikipedia.org/w/api.php"
        extract_params = {
            "action": "query",
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "pageids": page_id,
            "format": "json",
        }
        resp = client.get(extract_url, params=extract_params, timeout=10)
        data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        page = pages.get(str(page_id), {})
        title = page.get("title", query)
        extract = page.get("extract", "")

        if not extract:
            return f"无法获取条目内容: {title}"

        # 截断过长的内容
        if len(extract) > 1500:
            extract = extract[:1500] + "..."

        return f"【{title}】\n{extract}\n\n来源: https://{lang}.wikipedia.org/?curid={page_id}"
    except Exception as e:
        return f"维基百科查询失败: {e}"


# ========== arXiv 论文检索 ==========

@register_tool(
    name="arxiv_search",
    description="检索 arXiv 学术论文。参数: query(必填,搜索关键词), max_results(可选,默认5)",
)
def _arxiv_search(query: str, max_results: int = 5) -> str:
    """
    检索 arXiv 论文
    - 使用 arXiv API (无需 API Key)
    """
    try:
        import urllib.parse
        client = _get_httpx_client()

        # arXiv API
        search_query = urllib.parse.quote(f"all:{query}")
        url = f"http://export.arxiv.org/api/query?search_query={search_query}&max_results={max_results}"

        resp = client.get(url, timeout=20)
        resp.raise_for_status()

        # 解析 XML
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)

        # 命名空间
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = root.findall('atom:entry', ns)
        if not entries:
            return f"未找到相关论文: {query}"

        lines = []
        for entry in entries:
            title = entry.find('atom:title', ns)
            title_text = title.text.strip().replace('\n', ' ') if title is not None else "无标题"

            summary = entry.find('atom:summary', ns)
            summary_text = summary.text.strip()[:300] + "..." if summary is not None and summary.text else ""

            authors = entry.findall('atom:author', ns)
            author_names = [a.find('atom:name', ns).text for a in authors if a.find('atom:name', ns) is not None]
            authors_str = ", ".join(author_names[:3])
            if len(author_names) > 3:
                authors_str += " 等"

            link = entry.find('atom:id', ns)
            link_text = link.text if link is not None else ""

            published = entry.find('atom:published', ns)
            date = published.text[:10] if published is not None else "未知日期"

            lines.append(
                f"标题: {title_text}\n"
                f"作者: {authors_str}\n"
                f"日期: {date}\n"
                f"摘要: {summary_text}\n"
                f"链接: {link_text}"
            )

        return "\n\n".join(lines)
    except Exception as e:
        return f"arXiv 检索失败: {e}"


# ========== 新闻聚合搜索 ==========

@register_tool(
    name="news_search",
    description="搜索实时新闻。参数: query(必填,新闻关键词), max_results(可选,默认5)",
)
def _news_search(query: str, max_results: int = 5) -> str:
    """
    使用 DuckDuckGo 新闻搜索
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "未安装搜索库，请执行: pip install ddgs"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))

        if not results:
            return f"未找到相关新闻: {query}"

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            body = r.get("body", "")[:200] + "..." if len(r.get("body", "")) > 200 else r.get("body", "")
            url = r.get("url", "")
            source = r.get("source", "")
            date = r.get("date", "")

            lines.append(
                f"{i}. {title}\n"
                f"   来源: {source} | {date}\n"
                f"   {body}\n"
                f"   {url}"
            )

        return "\n\n".join(lines)
    except Exception as e:
        return f"新闻搜索失败: {e}"


# ========== GitHub 仓库搜索 ==========

@register_tool(
    name="github_search",
    description="搜索 GitHub 开源仓库。参数: query(必填,搜索关键词), max_results(可选,默认5)",
)
def _github_search(query: str, max_results: int = 5) -> str:
    """
    使用 GitHub API 搜索仓库（无需认证，匿名访问有速率限制）
    """
    try:
        import urllib.parse
        client = _get_httpx_client()

        encoded_query = urllib.parse.quote(query)
        url = f"https://api.github.com/search/repositories?q={encoded_query}&per_page={max_results}&sort=stars&order=desc"

        resp = client.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        if not items:
            return f"未找到相关仓库: {query}"

        lines = []
        for item in items[:max_results]:
            name = item.get("full_name", "")
            desc = item.get("description", "")[:150] + "..." if len(item.get("description", "")) > 150 else item.get("description", "")
            stars = item.get("stargazers_count", 0)
            forks = item.get("forks_count", 0)
            url = item.get("html_url", "")
            lang = item.get("language", "")

            lines.append(
                f"仓库: {name}\n"
                f"描述: {desc}\n"
                f"语言: {lang} | Stars: {stars} | Forks: {forks}\n"
                f"链接: {url}"
            )

        return "\n\n".join(lines)
    except Exception as e:
        return f"GitHub 搜索失败: {e}"


# ========== YouTube 视频搜索 ==========

@register_tool(
    name="youtube_search",
    description="搜索 YouTube 视频。参数: query(必填,搜索关键词), max_results(可选,默认5)",
)
def _youtube_search(query: str, max_results: int = 5) -> str:
    """
    使用 DuckDuckGo 搜索 YouTube 视频
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "未安装搜索库，请执行: pip install ddgs"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.videos(query, max_results=max_results))

        if not results:
            return f"未找到相关视频: {query}"

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            channel = r.get("channel", "")
            duration = r.get("duration", "")
            url = r.get("url", "")
            date = r.get("date", "")

            lines.append(
                f"{i}. {title}\n"
                f"   频道: {channel} | 时长: {duration} | {date}\n"
                f"   {url}"
            )

        return "\n\n".join(lines)
    except Exception as e:
        return f"YouTube 搜索失败: {e}"


# ========== Bilibili 视频搜索 ==========

@register_tool(
    name="bilibili_search",
    description="搜索 Bilibili 视频。参数: query(必填,搜索关键词), max_results(可选,默认5)",
)
def _bilibili_search(query: str, max_results: int = 5) -> str:
    """
    使用 Bilibili API 搜索视频（无需 API Key）
    """
    try:
        import urllib.parse
        client = _get_httpx_client()

        encoded_query = urllib.parse.quote(query)
        url = f"https://api.bilibili.com/x/web-interface/search/all/v2?keyword={encoded_query}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://search.bilibili.com/",
        }

        resp = client.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        result = data.get("data", {})
        videos = result.get("result", [])

        video_items = []
        for item in videos:
            if item.get("result_type") == "video":
                video_items.extend(item.get("data", []))

        if not video_items:
            return f"未找到相关视频: {query}"

        lines = []
        for item in video_items[:max_results]:
            title = item.get("title", "").replace("<em class=\"keyword\">", "").replace("</em>", "")
            author = item.get("author", "")
            play = item.get("play", 0)
            duration = item.get("duration", "")
            bvid = item.get("bvid", "")
            url = f"https://www.bilibili.com/video/{bvid}"

            lines.append(
                f"标题: {title}\n"
                f"UP主: {author} | 播放: {play} | 时长: {duration}\n"
                f"链接: {url}"
            )

        return "\n\n".join(lines)
    except Exception as e:
        return f"Bilibili 搜索失败: {e}"


# ========== IP/域名信息查询 ==========

@register_tool(
    name="ip_info",
    description="查询 IP 地址或域名的详细信息。参数: target(必填,IP地址或域名)",
)
def _ip_info(target: str) -> str:
    """
    使用 ip-api.com 查询 IP/域名信息（免费，无需 API Key）
    """
    try:
        import urllib.parse
        client = _get_httpx_client()

        encoded_target = urllib.parse.quote(target)
        url = f"http://ip-api.com/json/{encoded_target}?lang=zh-CN"

        resp = client.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "success":
            return f"查询失败: {data.get('message', '未知错误')}"

        info = []
        info.append(f"目标: {target}")
        info.append(f"IP: {data.get('query', '')}")
        info.append(f"国家: {data.get('country', '')}")
        info.append(f"地区: {data.get('regionName', '')}")
        info.append(f"城市: {data.get('city', '')}")
        info.append(f"运营商: {data.get('isp', '')}")
        info.append(f"组织: {data.get('org', '')}")
        info.append(f"ASN: {data.get('as', '')}")
        info.append(f"时区: {data.get('timezone', '')}")

        return "\n".join(info)
    except Exception as e:
        return f"IP 查询失败: {e}"


# ========== 股票价格查询 ==========

@register_tool(
    name="stock_price",
    description="查询股票实时价格。参数: symbol(必填,股票代码,如600036.SH表示A股浦发银行, AAPL表示美股苹果)",
)
def _stock_price(symbol: str) -> str:
    """
    使用 Yahoo Finance 查询股票价格（免费，无需 API Key）
    """
    try:
        import urllib.parse
        client = _get_httpx_client()

        encoded_symbol = urllib.parse.quote(symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"

        resp = client.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        chart = data.get("chart", {})
        result = chart.get("result", [])
        if not result:
            return f"未找到股票信息: {symbol}"

        meta = result[0].get("meta", {})
        quote = meta.get("regularMarketPrice", "")
        change = meta.get("regularMarketChange", "")
        change_percent = meta.get("regularMarketChangePercent", "")
        currency = meta.get("currency", "")
        exchange = meta.get("exchangeName", "")
        name = meta.get("shortName", "")

        info = []
        info.append(f"股票: {name} ({symbol})")
        info.append(f"交易所: {exchange}")
        info.append(f"当前价格: {quote} {currency}")
        if change:
            info.append(f"涨跌幅: {change} ({change_percent:.2f}%)")

        return "\n".join(info)
    except Exception as e:
        return f"股票查询失败: {e}"


# ========== 多语言翻译 ==========

@register_tool(
    name="translate_text",
    description="文本翻译。参数: text(必填,待翻译文本), target_lang(可选,目标语言,默认zh中文), source_lang(可选,源语言,默认auto)",
)
def _translate_text(text: str, target_lang: str = "zh", source_lang: str = "auto") -> str:
    """
    使用 Google 翻译 API（免费，无需 API Key）
    """
    try:
        import urllib.parse
        client = _get_httpx_client()

        encoded_text = urllib.parse.quote(text)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q={encoded_text}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        resp = client.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list) and len(data) > 0:
            translations = []
            for item in data[0]:
                if item and isinstance(item[0], str):
                    translations.append(item[0])
            return "\n".join(translations)

        return f"翻译失败: 无法解析响应"
    except Exception as e:
        return f"翻译失败: {e}"


# ========== MyAnimeList 动漫数据库 ==========

@register_tool(
    name="anime_search",
    description="搜索动漫信息(使用AniList数据库)。参数: query(必填,动漫名), type(可选,类型:ANIME/MANGA,默认ANIME), max_results(可选,默认5)",
)
def _anime_search(query: str, type: str = "ANIME", max_results: int = 5) -> str:
    """
    使用 AniList GraphQL API 搜索动漫
    - 免费，无需 API Key
    - 官方 API，稳定可靠
    """
    try:
        client = _get_httpx_client()

        # AniList GraphQL API
        graphql_query = '''
        query ($search: String, $type: MediaType, $perPage: Int) {
            Page(page: 1, perPage: $perPage) {
                media(search: $search, type: $type, sort: POPULARITY_DESC) {
                    id
                    title { romaji native english }
                    type
                    format
                    status
                    episodes
                    averageScore
                    popularity
                    seasonYear
                    season
                    genres
                    description(asHtml: false)
                    siteUrl
                    coverImage { medium }
                }
            }
        }
        '''

        variables = {
            "search": query,
            "type": type.upper(),
            "perPage": max_results
        }

        resp = client.post(
            "https://graphql.anilist.co",
            json={"query": graphql_query, "variables": variables},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("data", {}).get("Page", {}).get("media", [])
        if not results:
            return f"未找到相关动漫: {query}"

        lines = []
        for item in results:
            titles = item.get("title", {})
            title = titles.get("romaji") or titles.get("native") or titles.get("english", "")
            title_jp = titles.get("native", "")
            title_en = titles.get("english", "")

            item_type = item.get("format", "")
            status = item.get("status", "")
            episodes = item.get("episodes", "?")
            score = item.get("averageScore", "N/A")
            popularity = item.get("popularity", 0)
            year = item.get("seasonYear", "")
            season = item.get("season", "")
            genres = item.get("genres", [])
            synopsis = item.get("description", "")
            if synopsis and len(synopsis) > 200:
                synopsis = synopsis[:200] + "..."
            url = item.get("siteUrl", "")

            # 获取封面图
            cover_image = item.get("coverImage", {})
            image_url = cover_image.get("medium", "") if cover_image else ""

            aired = ""
            if season and year:
                season_cn = {"WINTER": "冬", "SPRING": "春", "SUMMER": "夏", "FALL": "秋"}
                aired = f"{season_cn.get(season, season)} {year}"

            status_cn = {
                "FINISHED": "已完结",
                "RELEASING": "连载中",
                "NOT_YET_RELEASED": "未开播",
                "CANCELLED": "已取消"
            }

            # 输出包含图片链接（Markdown 格式）
            line_parts = [
                f"标题: {title}",
                (f"日文名: {title_jp}" if title_jp and title_jp != title else None),
                (f"英文名: {title_en}" if title_en and title_en != title else None),
                f"类型: {item_type} | 集数: {episodes} | 状态: {status_cn.get(status, status)}",
                (f"播出时间: {aired}" if aired else None),
                f"评分: {score} | 人气: {popularity}",
                (f"标签: {', '.join(genres[:5])}" if genres else None),
                (f"简介: {synopsis}" if synopsis else None),
                f"链接: {url}",
            ]
            # 添加图片（Markdown 格式，QQ 机器人可识别）
            if image_url:
                line_parts.append(f"封面: ![封面]({image_url})")

            lines.append("\n".join([p for p in line_parts if p]))

        return "\n\n".join(lines)
    except Exception as e:
        return f"动漫搜索失败: {e}"


@register_tool(
    name="anime_season",
    description="查询当季新番或指定季度动漫。参数: year(可选,年份,不填则当前年), season(可选,季节: WINTER/SPRING/SUMMER/FALL,不填则当前季度)",
)
def _anime_season(year: str = "", season: str = "") -> str:
    """
    使用 AniList GraphQL API 查询当季新番
    """
    try:
        from datetime import datetime
        client = _get_httpx_client()

        # 如果没有指定年份和季度，使用当前时间计算
        if not year or not season:
            now = datetime.now()
            year = year or str(now.year)
            if not season:
                month = now.month
                if month in [1, 2, 3]:
                    season = "WINTER"
                elif month in [4, 5, 6]:
                    season = "SPRING"
                elif month in [7, 8, 9]:
                    season = "SUMMER"
                else:
                    season = "FALL"

        graphql_query = '''
        query ($season: MediaSeason, $year: Int, $perPage: Int) {
            Page(page: 1, perPage: $perPage) {
                media(season: $season, seasonYear: $year, type: ANIME, sort: POPULARITY_DESC) {
                    id
                    title { romaji native english }
                    format
                    status
                    episodes
                    averageScore
                    genres
                    description(asHtml: false)
                    siteUrl
                }
            }
        }
        '''

        variables = {
            "season": season.upper(),
            "year": int(year),
            "perPage": 10
        }

        resp = client.post(
            "https://graphql.anilist.co",
            json={"query": graphql_query, "variables": variables},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("data", {}).get("Page", {}).get("media", [])
        if not results:
            return f"未找到 {year}年 {season} 季度动漫数据"

        lines = []
        for item in results:
            titles = item.get("title", {})
            title = titles.get("romaji") or titles.get("native") or titles.get("english", "")
            item_type = item.get("format", "")
            episodes = item.get("episodes", "?")
            score = item.get("averageScore", "N/A")
            genres = item.get("genres", [])
            synopsis = item.get("description", "")
            if synopsis and len(synopsis) > 150:
                synopsis = synopsis[:150] + "..."
            url = item.get("siteUrl", "")

            lines.append(
                f"标题: {title}\n"
                f"类型: {item_type} | 集数: {episodes} | 评分: {score}\n"
                + (f"标签: {', '.join(genres[:3])}\n" if genres else "")
                + (f"简介: {synopsis}\n" if synopsis else "")
                + f"链接: {url}"
            )

        season_cn = {"WINTER": "冬季", "SPRING": "春季", "SUMMER": "夏季", "FALL": "秋季"}
        header = f"【{year}年 {season_cn.get(season.upper(), season)} 新番】\n\n"
        return header + "\n\n".join(lines)
    except Exception as e:
        return f"季度动漫查询失败: {e}"


# ========== VRChat 工具 ==========

# VRChat 认证缓存
_vrchat_auth_client = None
_vrchat_auth_expires = 0


def _get_vrchat_client() -> Optional[Any]:
    """获取已认证的 VRChat HTTP 客户端（带 cookie 持久化）"""
    global _vrchat_auth_client, _vrchat_auth_expires

    import time
    # cookie 有效期 30 分钟
    if _vrchat_auth_client and time.time() < _vrchat_auth_expires:
        return _vrchat_auth_client

    import os
    username = os.environ.get("VRCHAT_USERNAME", "")
    password = os.environ.get("VRCHAT_PASSWORD", "")

    if not username or not password:
        return None

    try:
        import httpx
        # P0-4: 替换旧客户端前先关闭，避免 TCP 连接和 socket 泄漏
        if _vrchat_auth_client is not None:
            try:
                _vrchat_auth_client.close()
            except Exception:
                pass
            _vrchat_auth_client = None

        client = httpx.Client(
            base_url="https://api.vrchat.cloud/api/1",
            auth=(username, password),
            headers={
                "User-Agent": "CastoriceAgent/3.0",
            },
            timeout=15,
            follow_redirects=True,
        )

        # 登录获取 cookie
        resp = client.get("/auth/user")
        if resp.status_code == 200:
            _vrchat_auth_client = client
            _vrchat_auth_expires = time.time() + 1800  # 30 分钟
            return client
        elif resp.status_code == 401:
            data = resp.json()
            error_msg = data.get("error", {}).get("message", "")
            # 检查是否需要 2FA 验证或新设备验证
            if "2FA" in error_msg or "two-factor" in error_msg.lower() or "otp" in error_msg.lower() or "new" in error_msg.lower() or "email" in error_msg.lower():
                print(f"\n[VRChat] {error_msg}")
                print("[VRChat] 验证码已发送至你的邮箱，请在控制台输入验证码")
                # P1-14: 用 asyncio.to_thread 包装 input 避免阻塞事件循环
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    otp_code = loop.run_in_executor(None, lambda: input("[VRChat] 请输入邮箱验证码: ").strip())
                    otp_code = asyncio.run_coroutine_threadsafe(
                        asyncio.wait_for(otp_code, timeout=120), loop
                    ).result()
                except RuntimeError:
                    # 不在事件循环中，直接同步调用
                    otp_code = input("[VRChat] 请输入邮箱验证码: ").strip()
                if not otp_code:
                    print("[VRChat] 未输入验证码，登录取消")
                    client.close()
                    return None

                # 提交验证码
                verify_resp = client.post(
                    "/auth/twofactorauth/emailotp/verify",
                    json={"code": otp_code}
                )
                if verify_resp.status_code == 200:
                    print("[VRChat] 验证码验证成功！")
                    _vrchat_auth_client = client
                    _vrchat_auth_expires = time.time() + 1800
                    return client
                else:
                    print(f"[VRChat] 验证码验证失败: {verify_resp.text}")
                    client.close()
                    return None
            else:
                print(f"[VRChat] 认证失败: {error_msg}")
                client.close()
                return None
        else:
            client.close()
            return None
    except Exception as e:
        print(f"[VRChat] 登录异常: {e}")
        return None


@register_tool(
    name="vrchat_search",
    description="搜索VRChat世界或头像。参数: query(必填,关键词), type(可选,类型:world/avatar,默认world), max_results(可选,默认5)",
)
def _vrchat_search(query: str, type: str = "world", max_results: int = 5) -> str:
    """
    使用 VRChat 官方 API 搜索世界或头像
    需要 VRChat 账号认证（.env 中配置 VRCHAT_USERNAME 和 VRCHAT_PASSWORD）
    """
    try:
        client = _get_vrchat_client()
        if not client:
            return "VRChat 认证失败：请在 .env 中配置 VRCHAT_USERNAME 和 VRCHAT_PASSWORD"

        import urllib.parse
        encoded_query = urllib.parse.quote(query)
        resp = client.get(f"/search?query={encoded_query}&type={type}&n={max_results}")
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            return f"未找到相关{type}: {query}"

        lines = []
        for item in results:
            name = item.get("name", "")
            author = item.get("authorName", "")
            id = item.get("id", "")
            visits = item.get("visits", 0)
            likes = item.get("likes", 0)
            popularity = item.get("popularity", 0)
            tags = item.get("tags", [])
            description = item.get("description", "")
            if description and len(description) > 150:
                description = description[:150] + "..."
            
            # 获取图片
            image_url = item.get("thumbnailImageUrl", "") or item.get("imageUrl", "")

            line_parts = [
                f"名称: {name}",
                f"作者: {author}",
                f"ID: {id}",
                f"访问量: {visits} | 点赞: {likes} | 人气: {popularity}",
                (f"标签: {', '.join(tags[:5])}" if tags else None),
                (f"简介: {description}" if description else None),
                f"链接: https://vrchat.com/home/{type}/{id}",
            ]
            # 添加图片（Markdown 格式，QQ 机器人可识别）
            if image_url:
                line_parts.append(f"封面: ![封面]({image_url})")

            lines.append("\n".join([p for p in line_parts if p]))

        return "\n\n".join(lines)
    except Exception as e:
        return f"VRChat搜索失败: {e}"


@register_tool(
    name="vrchat_popular_worlds",
    description="获取VRChat热门世界列表。参数: limit(可选,默认10)",
)
def _vrchat_popular_worlds(limit: int = 10) -> str:
    """
    获取 VRChat 当前热门世界
    """
    try:
        client = _get_vrchat_client()
        if not client:
            return "VRChat 认证失败：请在 .env 中配置 VRCHAT_USERNAME 和 VRCHAT_PASSWORD"

        resp = client.get(f"/worlds/popular?n={limit}")
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            return "未获取到热门世界数据"

        lines = []
        for i, item in enumerate(results, 1):
            name = item.get("name", "")
            author = item.get("authorName", "")
            id = item.get("id", "")
            visits = item.get("visits", 0)
            likes = item.get("likes", 0)
            currentUsers = item.get("currentUsers", 0)
            tags = item.get("tags", [])

            lines.append(
                f"{i}. {name}\n"
                f"   作者: {author}\n"
                f"   当前在线: {currentUsers} | 访问量: {visits} | 点赞: {likes}\n"
                + (f"   标签: {', '.join(tags[:3])}\n" if tags else "")
                + f"   链接: https://vrchat.com/home/world/{id}"
            )

        return "【VRChat 热门世界】\n\n" + "\n\n".join(lines)
    except Exception as e:
        return f"获取热门世界失败: {e}"


@register_tool(
    name="vrchat_user_status",
    description="查询VRChat用户状态。参数: username(必填,VRChat用户名)",
)
def _vrchat_user_status(username: str) -> str:
    """
    查询 VRChat 用户在线状态和所在世界
    """
    try:
        client = _get_vrchat_client()
        if not client:
            return "VRChat 认证失败：请在 .env 中配置 VRCHAT_USERNAME 和 VRCHAT_PASSWORD"

        import urllib.parse
        encoded_name = urllib.parse.quote(username)
        resp = client.get(f"/users?search={encoded_name}")
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            return f"未找到用户: {username}"

        user = results[0]
        displayName = user.get("displayName", "")
        status = user.get("status", "")
        statusDescription = user.get("statusDescription", "")
        state = user.get("state", "")
        location = user.get("location", "")
        last_login = user.get("last_login", "")
        joinDate = user.get("joinDate", "")
        bio = user.get("bio", "")
        if bio and len(bio) > 200:
            bio = bio[:200] + "..."
        
        # 获取用户头像
        user_image = user.get("currentAvatarImageUrl", "") or user.get("profilePicOverride", "")
        user_thumb = user.get("currentAvatarThumbnailImageUrl", "")

        status_map = {
            "online": "在线",
            "offline": "离线",
            "busy": "忙碌",
            "away": "离开",
            "ask me": "可询问"
        }

        state_map = {
            "online": "在线",
            "offline": "离线",
            "busy": "忙碌",
            "away": "离开"
        }

        result_parts = [
            f"用户名: {displayName}",
            f"状态: {status_map.get(status, status)}",
            f"状态描述: {statusDescription}",
            f"在线状态: {state_map.get(state, state)}",
            (f"所在位置: {location}" if location and location != "private" else None),
            (f"上次登录: {last_login}" if last_login else None),
            (f"加入时间: {joinDate}" if joinDate else None),
            (f"个人简介: {bio}" if bio else None),
        ]
        # 添加头像图片（Markdown 格式）
        if user_thumb:
            result_parts.append(f"头像: ![头像]({user_thumb})")
        elif user_image:
            result_parts.append(f"头像: ![头像]({user_image})")

        result = "\n".join([p for p in result_parts if p])

        return result
    except Exception as e:
        return f"查询用户状态失败: {e}"


@register_tool(
    name="vrchat_world_info",
    description="获取VRChat世界详细信息。参数: world_id(必填,世界ID)",
)
def _vrchat_world_info(world_id: str) -> str:
    """
    获取 VRChat 世界详细信息
    """
    try:
        client = _get_vrchat_client()
        if not client:
            return "VRChat 认证失败：请在 .env 中配置 VRCHAT_USERNAME 和 VRCHAT_PASSWORD"

        resp = client.get(f"/worlds/{world_id}")
        resp.raise_for_status()
        data = resp.json()

        name = data.get("name", "")
        author = data.get("authorName", "")
        authorId = data.get("authorId", "")
        visits = data.get("visits", 0)
        likes = data.get("likes", 0)
        popularity = data.get("popularity", 0)
        currentUsers = data.get("currentUsers", 0)
        capacity = data.get("capacity", 0)
        tags = data.get("tags", [])
        description = data.get("description", "")
        if description and len(description) > 300:
            description = description[:300] + "..."
        releaseStatus = data.get("releaseStatus", "")
        version = data.get("version", "")
        platform = data.get("platform", "")

        release_map = {
            "public": "公开",
            "private": "私有",
            "friends": "好友可见"
        }

        result = (
            f"世界名称: {name}\n"
            f"作者: {author}\n"
            f"作者ID: {authorId}\n"
            f"版本: {version}\n"
            f"状态: {release_map.get(releaseStatus, releaseStatus)}\n"
            f"平台: {platform}\n"
            f"容量: {currentUsers}/{capacity}\n"
            f"访问量: {visits} | 点赞: {likes} | 人气: {popularity}\n"
            + (f"标签: {', '.join(tags)}\n" if tags else "")
            + (f"简介: {description}\n" if description else "")
            + f"链接: https://vrchat.com/home/world/{world_id}"
        )

        return result
    except Exception as e:
        return f"获取世界信息失败: {e}"


# ========== 图片生成工具 ==========

@register_tool(
    name="generate_image",
    description="AI生成新图片（不是找已有图片）。仅当用户明确要求'生成'、'画一张'、'创作'图片时使用。找已有角色/动漫图片请用 pixiv_search。参数: prompt(必填,图片描述), width(可选,默认1024), height(可选,默认1024), seed(可选,随机种子)",
)
def _generate_image(prompt: str, width: int = 1024, height: int = 1024, seed: int = 0) -> str:
    """
    使用 Pollinations AI 免费生成图片
    返回图片URL，可直接在浏览器或QQ中查看
    """
    try:
        import urllib.parse
        import random

        if seed == 0:
            seed = random.randint(1, 999999)

        encoded_prompt = urllib.parse.quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&seed={seed}&nologo=true"

        # 验证图片可访问
        client = _get_httpx_client()
        resp = client.head(image_url, timeout=30, follow_redirects=True)
        if resp.status_code == 200:
            return (
                f"图片生成成功！\n"
                f"描述: {prompt}\n"
                f"尺寸: {width}x{height}\n"
                f"种子: {seed}\n"
                f"图片链接: {image_url}\n"
                f"\n![生成图片]({image_url})"
            )
        else:
            return f"图片生成服务暂时不可用 (HTTP {resp.status_code})"
    except Exception as e:
        return f"图片生成失败: {e}"


# ========== 图片理解工具 ==========

@register_tool(
    name="analyze_image",
    description="分析图片内容，理解图片中的物体、场景、文字、人物表情等。当用户发送图片或提供图片URL并询问图片内容时使用。参数: image_url(必填,图片URL)",
)
def _analyze_image(image_url: str) -> str:
    """
    使用多模态LLM分析图片内容
    使用 Gemini API（免费可用）进行图片理解
    """
    try:
        import os
        import urllib.parse

        gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        if not gemini_api_key:
            return """图片分析服务需要配置 GEMINI_API_KEY 环境变量。
请在 .env 文件中添加:
GEMINI_API_KEY=your_api_key

获取方式: https://ai.google.dev/
免费额度: 每月15万次请求"""

        encoded_url = urllib.parse.quote(image_url)
        prompt = "请详细描述这张图片的内容，包括：\n1. 图片中的主要物体和场景\n2. 人物的表情和动作（如果有人物）\n3. 图片的整体氛围和风格\n4. 图片中包含的文字信息\n5. 任何值得注意的细节"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent?key={gemini_api_key}"
        
        import base64
        from io import BytesIO
        
        client = _get_httpx_client()
        try:
            resp = client.get(image_url, timeout=30)
            resp.raise_for_status()
            image_data = base64.b64encode(resp.content).decode('utf-8')
            
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": resp.headers.get('content-type', 'image/jpeg'), "data": image_data}}
                    ]
                }]
            }
            
            response = client.post(url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            
            if "candidates" in result and result["candidates"]:
                text_parts = []
                for part in result["candidates"][0].get("content", {}).get("parts", []):
                    if "text" in part:
                        text_parts.append(part["text"])
                if text_parts:
                    return "\n\n".join(text_parts)
                return "图片分析返回结果为空"
            else:
                return f"图片分析失败: {result.get('error', {}).get('message', '未知错误')}"
                
        except Exception as e:
            return f"图片分析失败: {e}"

    except ImportError:
        return "图片分析需要 httpx 库，请安装: pip install httpx"


@register_tool(
    name="extract_text_from_image",
    description="从图片中提取文字（OCR）。当用户需要识别图片中的文字内容时使用。参数: image_url(必填,图片URL)",
)
def _extract_text_from_image(image_url: str) -> str:
    """
    使用免费OCR服务提取图片中的文字
    """
    try:
        import os
        client = _get_httpx_client()

        ocr_api_key = os.environ.get("OCR_SPACE_API_KEY", "K85276029688957")  # 默认使用免费公共key，可通过环境变量覆盖

        url = "https://api.ocr.space/parse/image"
        payload = {
            "url": image_url,
            "apikey": ocr_api_key,
            "language": "chs",
            "isOverlayRequired": "false",
        }
        
        resp = client.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        
        if result.get("IsErroredOnProcessing"):
            return f"OCR识别失败: {result.get('ErrorMessage', '未知错误')}"
            
        if "ParsedResults" in result and result["ParsedResults"]:
            texts = []
            for item in result["ParsedResults"]:
                texts.append(item.get("ParsedText", ""))
            if texts:
                return "\n".join(texts).strip() or "图片中未识别到文字"
            return "图片中未识别到文字"
        else:
            return "OCR识别返回结果为空"
            
    except Exception as e:
        return f"OCR识别失败: {e}"


# ========== Pixiv 插画工具 ==========

@register_tool(
    name="pixiv_search",
    description="在Pixiv搜索已有的插画/动漫/角色图片作品（不是AI生成）。当用户要找某个角色、动漫、插画的图片时使用。参数: query(必填,搜索关键词如'卡芙卡 崩坏星穹铁道'), max_results(可选,默认10)",
)
def _pixiv_search(query: str, max_results: int = 10) -> str:
    """
    使用 Pixiv 公开 API 搜索插画
    注意：Pixiv 对未登录访问有限制，部分功能可能受限
    """
    try:
        import urllib.parse
        client = _get_httpx_client()

        encoded_query = urllib.parse.quote(query)
        url = f"https://www.pixiv.net/ajax/search/artworks/{encoded_query}?word={encoded_query}&order=date_d&mode=all&p=1&s_mode=s_tag&type=all&lang=zh"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.pixiv.net/",
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        resp = client.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("error"):
            error_msg = data.get("message", "未知错误")
            return f"Pixiv 搜索失败: {error_msg}（可能需要登录，Pixiv 限制了未登录搜索）"

        body = data.get("body", {})
        illust_data = body.get("illustManga", {}).get("data", [])

        if not illust_data:
            return f"未找到相关插画: {query}"

        lines = []
        for item in illust_data[:max_results]:
            illust_id = item.get("id", "")
            title = item.get("title", "")
            user_name = item.get("userName", "")
            user_id = item.get("userId", "")
            tags = item.get("tags", [])
            total_view = item.get("totalView", 0)
            total_bookmarks = item.get("totalBookmarks", 0)
            illust_type = item.get("illustType", 0)
            page_count = item.get("pageCount", 1)
            width = item.get("width", 0)
            height = item.get("height", 0)
            url = item.get("url", "")

            type_map = {0: "插画", 1: "漫画", 2: "动图"}
            type_cn = type_map.get(illust_type, "其他")

            # 使用 pixiv.cat 代理获取可访问的图片
            image_url = f"https://pixiv.cat/{illust_id}.jpg" if illust_id else ""

            line_parts = [
                f"标题: {title}",
                f"作者: {user_name} (ID: {user_id})",
                f"作品ID: {illust_id}",
                f"类型: {type_cn} | 尺寸: {width}x{height} | 页数: {page_count}",
                f"浏览: {total_view} | 收藏: {total_bookmarks}",
                (f"标签: {', '.join(tags[:8])}" if tags else None),
                f"链接: https://www.pixiv.net/artworks/{illust_id}",
            ]
            # 添加预览图
            if image_url:
                line_parts.append(f"预览: ![预览]({image_url})")

            lines.append("\n".join([p for p in line_parts if p]))

        return "\n\n".join(lines)
    except Exception as e:
        return f"Pixiv 搜索失败: {e}"


@register_tool(
    name="pixiv_popular",
    description="获取Pixiv热门排行榜插画。参数: mode(可选,排行类型:daily/weekly/monthly/male/female/rookie/original,默认daily), max_results(可选,默认10)",
)
def _pixiv_popular(mode: str = "daily", max_results: int = 10) -> str:
    """
    使用 Pixiv 公开排行 API 获取热门插画
    - mode: daily(日榜), weekly(周榜), monthly(月榜), male(男性向), female(女性向), rookie(新人), original(原创)
    """
    try:
        client = _get_httpx_client()

        # 支持的模式
        valid_modes = ["daily", "weekly", "monthly", "male", "female", "rookie", "original"]
        if mode not in valid_modes:
            return f"无效的排行模式: {mode}，支持的模式: {', '.join(valid_modes)}"

        # Pixiv 排行 API（mode 映射）
        mode_param_map = {
            "daily": "daily",
            "weekly": "weekly",
            "monthly": "monthly",
            "male": "male",
            "female": "female",
            "rookie": "rookie",
            "original": "original",
        }

        url = f"https://www.pixiv.net/ranking.php?format=json&mode={mode_param_map[mode]}&content=illust&p=1"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.pixiv.net/",
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        resp = client.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        contents = data.get("contents", [])
        if not contents:
            return "未获取到排行榜数据"

        mode_cn = {
            "daily": "日榜", "weekly": "周榜", "monthly": "月榜",
            "male": "男性向", "female": "女性向", "rookie": "新人榜", "original": "原创榜"
        }

        lines = [f"【Pixiv {mode_cn.get(mode, mode)} TOP{min(max_results, len(contents))}】\n"]

        for i, item in enumerate(contents[:max_results], 1):
            illust_id = item.get("illust_id", "")
            title = item.get("title", "")
            user_name = item.get("user_name", "")
            user_id = item.get("user_id", "")
            tags = item.get("tags", [])
            total_view = item.get("total_view", 0)
            total_bookmarks = item.get("total_bookmarks", 0)
            illust_type = item.get("illust_type", 0)
            width = item.get("width", 0)
            height = item.get("height", 0)
            rank = item.get("rank", i)
            yes_rank = item.get("yes_rank", 0)

            type_map = {0: "插画", 1: "漫画", 2: "动图"}
            type_cn = type_map.get(illust_type, "其他")

            # 使用 pixiv.cat 代理获取可访问的图片
            image_url = f"https://pixiv.cat/{illust_id}.jpg" if illust_id else ""

            # 排名变化
            rank_change = ""
            if yes_rank and rank:
                diff = yes_rank - rank
                if diff > 0:
                    rank_change = f" ↑{diff}"
                elif diff < 0:
                    rank_change = f" ↓{abs(diff)}"
                else:
                    rank_change = " -"

            line_parts = [
                f"{i}. #{rank}{rank_change} {title}",
                f"   作者: {user_name} | 浏览: {total_view} | 收藏: {total_bookmarks}",
                f"   类型: {type_cn} | 尺寸: {width}x{height}",
                (f"   标签: {', '.join(tags[:5])}" if tags else None),
                f"   链接: https://www.pixiv.net/artworks/{illust_id}",
            ]
            # 添加预览图
            if image_url:
                line_parts.append(f"   预览: ![预览]({image_url})")

            lines.append("\n".join([p for p in line_parts if p]))

        return "\n\n".join(lines)
    except Exception as e:
        return f"获取 Pixiv 排行榜失败: {e}"


@register_tool(
    name="pixiv_user_works",
    description="获取Pixiv用户的作品列表。参数: user_id(必填,Pixiv用户ID), max_results(可选,默认10)",
)
def _pixiv_user_works(user_id: str, max_results: int = 10) -> str:
    """
    获取 Pixiv 用户的公开作品列表
    """
    try:
        client = _get_httpx_client()

        url = f"https://www.pixiv.net/ajax/user/{user_id}/profile/all?lang=zh"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.pixiv.net/",
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        resp = client.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("error"):
            error_msg = data.get("message", "未知错误")
            return f"获取用户作品失败: {error_msg}"

        body = data.get("body", {})
        illusts = body.get("illusts", {})
        mangas = body.get("manga", {})

        if not illusts and not mangas:
            return f"用户 {user_id} 没有公开作品，或用户不存在"

        # 合并插画和漫画，按 ID 排序取最新的
        all_works = []
        for iid in illusts:
            all_works.append((iid, "illust"))
        for mid in mangas:
            all_works.append((mid, "manga"))

        # 按 ID 降序排列（最新的在前）
        all_works.sort(key=lambda x: int(x[0]), reverse=True)
        all_works = all_works[:max_results]

        # 获取每件作品的详细信息
        lines = [f"【Pixiv 用户 {user_id} 的作品（共 {len(illusts) + len(mangas)} 件）】\n"]

        for work_id, work_type in all_works:
            try:
                detail_url = f"https://www.pixiv.net/ajax/illust/{work_id}?lang=zh"
                detail_resp = client.get(detail_url, headers=headers, timeout=10)
                detail_resp.raise_for_status()
                detail_data = detail_resp.json()

                if detail_data.get("error"):
                    lines.append(f"作品 {work_id}: 获取详情失败")
                    continue

                detail_body = detail_data.get("body", {})
                title = detail_body.get("title", "无标题")
                user_name = detail_body.get("userName", "")
                tags_data = detail_body.get("tags", {}).get("tags", [])
                tags = [t.get("tag", "") for t in tags_data if t.get("tag")]
                total_view = detail_body.get("totalView", 0)
                total_bookmarks = detail_body.get("totalBookmarks", 0)
                illust_type = detail_body.get("illustType", 0)
                page_count = detail_body.get("pageCount", 1)
                create_date = detail_body.get("createDate", "")
                width = detail_body.get("width", 0)
                height = detail_body.get("height", 0)

                type_map = {0: "插画", 1: "漫画", 2: "动图"}
                type_cn = type_map.get(illust_type, "其他")
                work_type_cn = "漫画" if work_type == "manga" else type_cn

                # 使用 pixiv.cat 代理获取可访问的图片
                image_url = f"https://pixiv.cat/{work_id}.jpg"

                line_parts = [
                    f"标题: {title}",
                    f"作者: {user_name}",
                    f"作品ID: {work_id}",
                    f"类型: {work_type_cn} | 尺寸: {width}x{height} | 页数: {page_count}",
                    f"浏览: {total_view} | 收藏: {total_bookmarks}",
                    (f"日期: {create_date[:10]}" if create_date else None),
                    (f"标签: {', '.join(tags[:8])}" if tags else None),
                    f"链接: https://www.pixiv.net/artworks/{work_id}",
                ]
                # 添加预览图
                if image_url:
                    line_parts.append(f"预览: ![预览]({image_url})")

                lines.append("\n".join([p for p in line_parts if p]))
                lines.append("")  # 空行分隔
            except Exception as e:
                lines.append(f"作品 {work_id}: 获取详情失败 ({e})")

        return "\n".join(lines)
    except Exception as e:
        return f"获取 Pixiv 用户作品失败: {e}"


# ========== 工具获取函数 ==========

def get_web_tools(config: Optional[Dict[str, Any]] = None) -> List:
    """获取所有网络检索工具"""
    from .base_tools import _registered_tools

    tools = []
    for name in ["web_fetch", "wikipedia_search", "arxiv_search", "news_search",
                 "github_search", "youtube_search", "bilibili_search",
                 "ip_info", "stock_price", "translate_text",
                 "anime_search", "anime_season",
                 "vrchat_search", "vrchat_popular_worlds",
                 "vrchat_user_status", "vrchat_world_info",
                 "generate_image",
                 "pixiv_search", "pixiv_popular", "pixiv_user_works"]:
        if name in _registered_tools:
            tools.append(_registered_tools[name])
    return tools