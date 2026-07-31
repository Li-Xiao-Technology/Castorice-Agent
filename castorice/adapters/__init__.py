"""
适配器层 (Adapters)

桥接第三方生态到 Castorice 自研接口：
- LangChainToolAdapter: 将 LangChain 工具适配到自研 Tool 接口
- 统一遵循行业通用标准，不重复造轮子

设计原则：
1. 核心轻量：主循环、状态管理保持自研，不绑定第三方框架
2. 桥接兼容：通过适配器层对接外部生态
3. 渐进式引入：用户按需安装，不强制依赖
"""

from typing import Any, Dict, List, Optional, Callable
import logging

logger = logging.getLogger("Castorice.Adapters")


# ============================
# 工具适配器
# ============================

class ToolAdapterBase:
    """工具适配器基类"""
    
    def to_tool(self) -> "Tool":
        """转换为 Castorice Tool 对象"""
        raise NotImplementedError


class LangChainToolAdapter(ToolAdapterBase):
    """
    将 LangChain 工具适配到 Castorice 自研 Tool 接口
    
    使用示例：
    >>> from langchain_community.tools import WikipediaQueryRun
    >>> lc_tool = WikipediaQueryRun(api_wrapper=...)
    >>> adapter = LangChainToolAdapter(lc_tool)
    >>> tool = adapter.to_tool()
    >>> result = tool.invoke({"query": "人工智能"})
    """
    
    def __init__(self, lc_tool):
        self._lc_tool = lc_tool
        self._validate_lc_tool()
    
    def _validate_lc_tool(self):
        """验证 LangChain 工具是否符合预期接口"""
        if not hasattr(self._lc_tool, "name"):
            raise ValueError("LangChain 工具必须有 name 属性")
        if not hasattr(self._lc_tool, "description"):
            raise ValueError("LangChain 工具必须有 description 属性")
        if not callable(getattr(self._lc_tool, "invoke", None)):
            raise ValueError("LangChain 工具必须有 invoke 方法")
    
    def to_tool(self) -> "Tool":
        """转换为 Castorice Tool 对象"""
        from castorice.tools.base_tools import Tool
        
        def wrapped_func(**args):
            try:
                result = self._lc_tool.invoke(args)
                return str(result)
            except Exception as e:
                logger.warning(f"LangChain 工具 {self._lc_tool.name} 执行失败: {e}")
                return f"工具执行失败: {e}"
        
        return Tool(
            name=self._lc_tool.name,
            description=self._lc_tool.description,
            func=wrapped_func,
        )


class LangChainToolkitAdapter:
    """
    批量适配 LangChain Toolkit
    
    使用示例：
    >>> from langchain_community.agent_toolkits import GmailToolkit
    >>> toolkit = GmailToolkit()
    >>> adapter = LangChainToolkitAdapter(toolkit)
    >>> tools = adapter.to_tools()
    """
    
    def __init__(self, lc_toolkit):
        self._lc_toolkit = lc_toolkit
    
    def to_tools(self) -> List["Tool"]:
        """转换所有工具"""
        from castorice.tools.base_tools import Tool
        
        tools = []
        if hasattr(self._lc_toolkit, "get_tools"):
            for lc_tool in self._lc_toolkit.get_tools():
                try:
                    adapter = LangChainToolAdapter(lc_tool)
                    tools.append(adapter.to_tool())
                except Exception as e:
                    logger.warning(f"跳过工具 {getattr(lc_tool, 'name', 'unknown')}: {e}")
        return tools


# ============================
# 文档加载器适配器
# ============================

class DocumentLoaderAdapter:
    """
    将 LangChain DocumentLoader 适配到 Castorice 文档读取接口
    
    使用示例：
    >>> from langchain_community.document_loaders import WebBaseLoader
    >>> loader = WebBaseLoader("https://example.com")
    >>> adapter = DocumentLoaderAdapter(loader)
    >>> text = adapter.load_as_text()
    """
    
    def __init__(self, lc_loader):
        self._lc_loader = lc_loader
    
    def load_as_text(self, max_chars: int = 10000) -> str:
        """加载并返回纯文本内容"""
        try:
            docs = self._lc_loader.load()
            texts = [doc.page_content for doc in docs]
            full_text = "\n\n".join(texts)
            if len(full_text) > max_chars:
                full_text = full_text[:max_chars] + f"\n... (截断, 共 {len(full_text)} 字符)"
            return full_text
        except Exception as e:
            logger.warning(f"文档加载失败: {e}")
            return f"文档加载失败: {e}"


# ============================
# 向量存储适配器
# ============================

class VectorStoreAdapter:
    """
    将 LangChain VectorStore 适配到 Castorice MemoryInterface
    
    使用示例：
    >>> from langchain_community.vectorstores import Pinecone
    >>> vectorstore = Pinecone.from_existing_index("my-index")
    >>> adapter = VectorStoreAdapter(vectorstore)
    >>> context = adapter.get_relevant_context("查询")
    """
    
    def __init__(self, lc_vectorstore):
        self._lc_vectorstore = lc_vectorstore
    
    def add_documents(self, texts: List[str], metadatas: Optional[List[Dict]] = None):
        """添加文档"""
        try:
            from langchain_core.documents import Document
            docs = [Document(page_content=text, metadata=meta or {}) for text, meta in zip(texts, metadatas or [{}] * len(texts))]
            self._lc_vectorstore.add_documents(docs)
        except Exception as e:
            logger.warning(f"向量存储写入失败: {e}")
    
    def get_relevant_context(self, query: str, top_k: int = 5) -> str:
        """获取相关上下文"""
        try:
            results = self._lc_vectorstore.similarity_search(query, k=top_k)
            if not results:
                return ""
            return "\n---\n".join(doc.page_content for doc in results)
        except Exception as e:
            logger.warning(f"向量存储检索失败: {e}")
            return ""
    
    def clear(self):
        """清空存储"""
        try:
            if hasattr(self._lc_vectorstore, "delete"):
                self._lc_vectorstore.delete(delete_all=True)
            else:
                logger.warning("当前向量存储不支持清空操作")
        except Exception as e:
            logger.warning(f"清空向量存储失败: {e}")


# ============================
# 工具工厂：一站式获取各种生态工具
# ============================

class ToolFactory:
    """
    工具工厂：统一入口获取各种生态的工具
    
    设计理念：
    - 核心工具：自研实现，无第三方依赖
    - LangChain 工具：通过适配器桥接，按需加载
    - 支持动态注册和扩展
    """
    
    _registered_tools: Dict[str, Callable] = {}
    
    @classmethod
    def register(cls, name: str, func: Callable):
        """注册自定义工具"""
        cls._registered_tools[name] = func
    
    @classmethod
    def get_core_tools(cls) -> List["Tool"]:
        """获取自研核心工具（无第三方依赖）"""
        from castorice.tools.base_tools import get_base_tools
        return get_base_tools()
    
    @classmethod
    def get_langchain_tools(cls, tool_names: Optional[List[str]] = None) -> List["Tool"]:
        """
        获取 LangChain 生态工具
        
        支持的工具名：
        - "wikipedia": 维基百科查询
        - "arxiv": 学术论文查询
        - "news": 新闻搜索
        - "google_search": Google 搜索
        - "bing_search": Bing 搜索
        - "searx_search": Searx 搜索
        - "webloader": 网页内容加载
        - "python_runner": Python 代码执行器
        - "shell_exec": Shell 命令执行
        - "file_read": 文件读取
        - "file_write": 文件写入
        - "sql_query": SQL 数据库查询
        - "email_send": 发送邮件
        - "calculator": 计算器
        - "pal_math": 高级数学解题
        - "pal_code": 代码生成与执行
        - "weather": 天气查询
        - "maps": 地图/地理编码
        - "github": GitHub 操作
        - "slack": Slack 消息
        - "discord": Discord 消息
        - "trello": Trello 任务管理
        - "jira": Jira 问题管理
        - "confluence": Confluence 文档
        - "notion": Notion 操作
        - "zapier": Zapier 自动化
        - "browser": 浏览器操作
        - "youtube": YouTube 操作
        - "twitter": Twitter 操作
        - "facebook": Facebook 操作
        - "linkedin": LinkedIn 操作
        - "gcalendar": Google 日历
        - "gdrive": Google Drive
        - "gmail": Gmail 操作
        - "google_translate": Google 翻译
        - "google_images": Google 图片搜索
        - "google_maps": Google Maps
        - "openweather": OpenWeatherMap 天气
        - "stock": Yahoo 股票查询
        - "alphavantage": Alpha Vantage 股票
        - "arxiv_papers": ArXiv 论文搜索
        - "pubmed": PubMed 医学论文
        - "semantic_scholar": Semantic Scholar 学术搜索
        - "websearch": DuckDuckGo 搜索
        - "metaphor": Metaphor 搜索
        - "arxiv_lookup": ArXiv 详细查询
        - "wolfram_alpha": Wolfram Alpha 计算
        - "wolfram_alpha_tool": Wolfram Alpha 工具
        """
        tools = []
        
        if tool_names is None:
            tool_names = []
        
        for name in tool_names:
            result = cls._create_langchain_tool(name)
            if result:
                if isinstance(result, list):
                    tools.extend(result)
                else:
                    tools.append(result)
        
        return tools
    
    # ============================================================
    # LangChain 工具工厂函数
    # ============================================================
    # 每个工厂均为无参静态方法，内部完成懒加载导入并返回适配后的 Tool 或
    # List[Tool]。通过 _LANGCHAIN_TOOL_FACTORIES 注册表进行 名称 → 工厂 的
    # 映射，由 _create_langchain_tool 统一分发，避免冗长的 if-elif 链。
    # 实现一致的工具（如 weather / openweather）共享同一工厂以避免重复代码。

    # ----- 知识搜索类 -----

    @staticmethod
    def _factory_wikipedia():
        from langchain_community.tools import WikipediaQueryRun
        from langchain_community.utilities import WikipediaAPIWrapper
        api_wrapper = WikipediaAPIWrapper()
        lc_tool = WikipediaQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_arxiv():
        from langchain_community.tools import ArxivQueryRun
        from langchain_community.utilities import ArxivAPIWrapper
        api_wrapper = ArxivAPIWrapper()
        lc_tool = ArxivQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_arxiv_papers():
        from langchain_community.tools import ArxivQueryRun
        from langchain_community.utilities import ArxivAPIWrapper
        api_wrapper = ArxivAPIWrapper(top_k_results=5)
        lc_tool = ArxivQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_pubmed():
        from langchain_community.tools import PubMedQueryRun
        from langchain_community.utilities import PubMedAPIWrapper
        api_wrapper = PubMedAPIWrapper()
        lc_tool = PubMedQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_semantic_scholar():
        from langchain_community.tools import SemanticScholarQueryRun
        from langchain_community.utilities import SemanticScholarAPIWrapper
        api_wrapper = SemanticScholarAPIWrapper()
        lc_tool = SemanticScholarQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    # ----- 搜索类 -----

    @staticmethod
    def _factory_news():
        from langchain_community.tools import NewsSearchResults
        from langchain_community.utilities import NewsAPIWrapper
        api_wrapper = NewsAPIWrapper()
        lc_tool = NewsSearchResults(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_google_search():
        from langchain_community.tools import GoogleSearchResults
        lc_tool = GoogleSearchResults()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_bing_search():
        from langchain_community.tools import BingSearchResults
        lc_tool = BingSearchResults()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_searx_search():
        from langchain_community.tools import SearxSearchResults
        lc_tool = SearxSearchResults()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_websearch():
        from langchain_community.tools import DuckDuckGoSearchResults
        lc_tool = DuckDuckGoSearchResults()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_metaphor():
        from langchain_community.tools import MetaphorSearchResults
        lc_tool = MetaphorSearchResults()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_google_images():
        from langchain_community.tools import GoogleImageSearch
        lc_tool = GoogleImageSearch()
        return LangChainToolAdapter(lc_tool).to_tool()

    # ----- 工具类 -----

    @staticmethod
    def _factory_webloader():
        from langchain_community.tools import WebBaseLoaderTool
        lc_tool = WebBaseLoaderTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_calculator():
        from langchain_community.tools import Calculator
        lc_tool = Calculator()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_python_runner():
        from langchain_community.tools import PythonREPLTool
        lc_tool = PythonREPLTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_shell_exec():
        from langchain_community.tools import ShellTool
        lc_tool = ShellTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_file_read():
        from langchain_community.tools import FileReadTool
        lc_tool = FileReadTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_file_write():
        from langchain_community.tools import FileWriteTool
        lc_tool = FileWriteTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_sql_query():
        # SQL 工具需要数据库连接配置
        from langchain_community.tools import SQLDatabaseToolkit
        from langchain_community.utilities import SQLDatabase
        try:
            db = SQLDatabase.from_uri("sqlite:///./example.db")
            toolkit = SQLDatabaseToolkit(db=db)
            return LangChainToolkitAdapter(toolkit).to_tools()
        except Exception:
            logger.warning("SQL 工具需要数据库连接配置")
            return None

    # ----- 高级工具 -----
    # pal_math 与 pal_code 实现一致，注册表中共享 _factory_pal_math

    @staticmethod
    def _factory_pal_math():
        from langchain_experimental.tools import PythonAstREPLTool
        lc_tool = PythonAstREPLTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_wolfram_alpha():
        from langchain_community.tools import WolframAlphaQueryRun
        from langchain_community.utilities import WolframAlphaAPIWrapper
        api_wrapper = WolframAlphaAPIWrapper()
        lc_tool = WolframAlphaQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_wolfram_alpha_tool():
        from langchain_community.tools import WolframAlphaTool
        lc_tool = WolframAlphaTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    # ----- 天气类 -----
    # weather 与 openweather 实现一致，注册表中共享 _factory_openweather

    @staticmethod
    def _factory_openweather():
        from langchain_community.tools import OpenWeatherMapQueryRun
        from langchain_community.utilities import OpenWeatherMapAPIWrapper
        api_wrapper = OpenWeatherMapAPIWrapper()
        lc_tool = OpenWeatherMapQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    # ----- 金融类 -----

    @staticmethod
    def _factory_stock():
        from langchain_community.tools import YahooFinanceQueryRun
        from langchain_community.utilities import YahooFinanceAPIWrapper
        api_wrapper = YahooFinanceAPIWrapper()
        lc_tool = YahooFinanceQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_alphavantage():
        from langchain_community.tools import AlphaVantageQueryRun
        from langchain_community.utilities import AlphaVantageAPIWrapper
        api_wrapper = AlphaVantageAPIWrapper()
        lc_tool = AlphaVantageQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    # ----- 地图类 -----
    # maps 与 google_maps 实现一致，注册表中共享 _factory_google_maps

    @staticmethod
    def _factory_google_maps():
        from langchain_community.tools import GoogleMapsQueryRun
        from langchain_community.utilities import GoogleMapsAPIWrapper
        api_wrapper = GoogleMapsAPIWrapper()
        lc_tool = GoogleMapsQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    # ----- 翻译类 -----

    @staticmethod
    def _factory_google_translate():
        from langchain_community.tools import GoogleTranslateQueryRun
        from langchain_community.utilities import GoogleTranslateAPIWrapper
        api_wrapper = GoogleTranslateAPIWrapper()
        lc_tool = GoogleTranslateQueryRun(api_wrapper=api_wrapper)
        return LangChainToolAdapter(lc_tool).to_tool()

    # ----- 邮件类 -----

    @staticmethod
    def _factory_email_send():
        from langchain_community.tools import SendEmailTool
        lc_tool = SendEmailTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_gmail():
        from langchain_community.agent_toolkits import GmailToolkit
        toolkit = GmailToolkit()
        return LangChainToolkitAdapter(toolkit).to_tools()

    # ----- 日历/云盘 -----

    @staticmethod
    def _factory_gcalendar():
        from langchain_community.agent_toolkits import GoogleCalendarToolkit
        toolkit = GoogleCalendarToolkit()
        return LangChainToolkitAdapter(toolkit).to_tools()

    @staticmethod
    def _factory_gdrive():
        from langchain_community.agent_toolkits import GoogleDriveToolkit
        toolkit = GoogleDriveToolkit()
        return LangChainToolkitAdapter(toolkit).to_tools()

    # ----- 协作工具 -----

    @staticmethod
    def _factory_github():
        from langchain_community.agent_toolkits import GitHubToolkit
        toolkit = GitHubToolkit()
        return LangChainToolkitAdapter(toolkit).to_tools()

    @staticmethod
    def _factory_slack():
        from langchain_community.tools import SlackMessageTool
        lc_tool = SlackMessageTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_discord():
        from langchain_community.tools import DiscordTool
        lc_tool = DiscordTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_trello():
        from langchain_community.agent_toolkits import TrelloToolkit
        toolkit = TrelloToolkit()
        return LangChainToolkitAdapter(toolkit).to_tools()

    @staticmethod
    def _factory_jira():
        from langchain_community.agent_toolkits import JiraToolkit
        toolkit = JiraToolkit()
        return LangChainToolkitAdapter(toolkit).to_tools()

    @staticmethod
    def _factory_confluence():
        from langchain_community.agent_toolkits import ConfluenceToolkit
        toolkit = ConfluenceToolkit()
        return LangChainToolkitAdapter(toolkit).to_tools()

    @staticmethod
    def _factory_notion():
        from langchain_community.agent_toolkits import NotionToolkit
        toolkit = NotionToolkit()
        return LangChainToolkitAdapter(toolkit).to_tools()

    @staticmethod
    def _factory_zapier():
        from langchain_community.agent_toolkits import ZapierToolkit
        toolkit = ZapierToolkit()
        return LangChainToolkitAdapter(toolkit).to_tools()

    # ----- 社交媒体 -----

    @staticmethod
    def _factory_twitter():
        from langchain_community.tools import TwitterTool
        lc_tool = TwitterTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_facebook():
        from langchain_community.tools import FacebookTool
        lc_tool = FacebookTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_linkedin():
        from langchain_community.tools import LinkedInTool
        lc_tool = LinkedInTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    @staticmethod
    def _factory_youtube():
        from langchain_community.agent_toolkits import YouTubeToolkit
        toolkit = YouTubeToolkit()
        return LangChainToolkitAdapter(toolkit).to_tools()

    # ----- 浏览器 -----

    @staticmethod
    def _factory_browser():
        from langchain_community.tools import PlaywrightBrowserTool
        lc_tool = PlaywrightBrowserTool()
        return LangChainToolAdapter(lc_tool).to_tool()

    # ============================================================
    # LangChain 工具工厂注册表
    # ============================================================
    # 名称 → 工厂函数的映射表，_create_langchain_tool 通过查表分发。
    # 实现一致的工具（weather/openweather、maps/google_maps、pal_math/pal_code）
    # 共享同一工厂以避免重复代码。
    _LANGCHAIN_TOOL_FACTORIES: Dict[str, Callable[[], Any]] = {
        # 知识搜索类
        "wikipedia": _factory_wikipedia,
        "arxiv": _factory_arxiv,
        "arxiv_papers": _factory_arxiv_papers,
        "pubmed": _factory_pubmed,
        "semantic_scholar": _factory_semantic_scholar,
        # 搜索类
        "news": _factory_news,
        "google_search": _factory_google_search,
        "bing_search": _factory_bing_search,
        "searx_search": _factory_searx_search,
        "websearch": _factory_websearch,
        "metaphor": _factory_metaphor,
        "google_images": _factory_google_images,
        # 工具类
        "webloader": _factory_webloader,
        "calculator": _factory_calculator,
        "python_runner": _factory_python_runner,
        "shell_exec": _factory_shell_exec,
        "file_read": _factory_file_read,
        "file_write": _factory_file_write,
        "sql_query": _factory_sql_query,
        # 高级工具（pal_code 与 pal_math 实现一致）
        "pal_math": _factory_pal_math,
        "pal_code": _factory_pal_math,
        "wolfram_alpha": _factory_wolfram_alpha,
        "wolfram_alpha_tool": _factory_wolfram_alpha_tool,
        # 天气类（weather 与 openweather 实现一致）
        "weather": _factory_openweather,
        "openweather": _factory_openweather,
        # 金融类
        "stock": _factory_stock,
        "alphavantage": _factory_alphavantage,
        # 地图类（maps 与 google_maps 实现一致）
        "maps": _factory_google_maps,
        "google_maps": _factory_google_maps,
        # 翻译类
        "google_translate": _factory_google_translate,
        # 邮件类
        "email_send": _factory_email_send,
        "gmail": _factory_gmail,
        # 日历/云盘
        "gcalendar": _factory_gcalendar,
        "gdrive": _factory_gdrive,
        # 协作工具
        "github": _factory_github,
        "slack": _factory_slack,
        "discord": _factory_discord,
        "trello": _factory_trello,
        "jira": _factory_jira,
        "confluence": _factory_confluence,
        "notion": _factory_notion,
        "zapier": _factory_zapier,
        # 社交媒体
        "twitter": _factory_twitter,
        "facebook": _factory_facebook,
        "linkedin": _factory_linkedin,
        "youtube": _factory_youtube,
        # 浏览器
        "browser": _factory_browser,
    }

    @classmethod
    def _create_langchain_tool(cls, name: str) -> Optional["Tool"]:
        """创建单个 LangChain 工具

        通过 _LANGCHAIN_TOOL_FACTORIES 注册表查找对应工厂函数并调用。
        工厂函数内部完成懒加载导入；未注册名称或导入失败时返回 None。
        """
        factory = cls._LANGCHAIN_TOOL_FACTORIES.get(name)
        if factory is None:
            logger.warning(f"未知的 LangChain 工具: {name}")
            return None
        try:
            return factory()
        except ImportError as e:
            missing_pkg = str(e).split("'")[1] if "'" in str(e) else "langchain-community"
            logger.warning(f"工具 {name} 依赖缺失: {missing_pkg}，请安装: pip install {missing_pkg}")
            return None
        except Exception as e:
            logger.warning(f"创建 LangChain 工具 {name} 失败: {e}")
            return None
    
    @classmethod
    def get_all_tools(cls, include_langchain: bool = False, langchain_tools: Optional[List[str]] = None) -> List["Tool"]:
        """
        获取所有工具
        
        参数：
            include_langchain: 是否包含 LangChain 工具
            langchain_tools: 指定要加载的 LangChain 工具列表
        """
        tools = cls.get_core_tools()
        
        if include_langchain:
            lc_tools = cls.get_langchain_tools(langchain_tools)
            tools.extend(lc_tools)
        
        return tools
