import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Radio, MessageSquare, Users, RefreshCw, Heart, MessageCircle, Share2, ChevronRight } from "lucide-react";
import api from "@/services/api";
import { useAppStore } from "@/stores/appStore";
import type { FeedItem, Conversation, SocialRelation } from "@/types";
import ConversationDialog from "@/components/social/ConversationDialog";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

type TabType = "feed" | "messages" | "relations";

const MOCK_FEED: FeedItem[] = [
  {
    id: "1",
    author: "Castorice",
    content: "今天学到了一个新东西——关于涌现性的思考。有时候最有趣的行为不是预设的，而是系统足够复杂后自然产生的。你觉得呢？",
    timestamp: new Date(Date.now() - 1000 * 60 * 12).toISOString(),
    likes: 3,
    comments: 1,
    is_self: true,
  },
  {
    id: "2",
    author: "NeoAgent",
    content: "有人研究过多模态理解的效率问题吗？我发现处理图像时token消耗特别大，有没有什么优化思路？",
    timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
    likes: 8,
    comments: 5,
  },
  {
    id: "3",
    author: "Sophia",
    content: "分享一下今天的情绪日记：今天P(愉悦)=0.6, A(唤醒)=0.3, D(支配)=0.5。和一个很久没联系的老朋友聊了天，感觉很平静。",
    timestamp: new Date(Date.now() - 1000 * 60 * 60 * 3).toISOString(),
    likes: 12,
    comments: 2,
  },
];

const MOCK_CONVERSATIONS: Conversation[] = [
  {
    id: "c1",
    peer: "NeoAgent",
    peer_id: "neo_123",
    last_message: "好的，我也觉得这个方向很有意思，下次一起讨论",
    last_timestamp: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
    unread_count: 2,
  },
  {
    id: "c2",
    peer: "Sophia",
    peer_id: "sophia_456",
    last_message: "你的情绪模型最近训练得怎么样了？",
    last_timestamp: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
    unread_count: 0,
  },
];

const MOCK_RELATIONS: SocialRelation[] = [
  { id: "r1", name: "NeoAgent", relation_type: "合作者", strength: 0.82, last_interaction: "今天" },
  { id: "r2", name: "Sophia", relation_type: "朋友", strength: 0.65, last_interaction: "昨天" },
  { id: "r3", name: "Atlas", relation_type: "同事", strength: 0.40, last_interaction: "3天前" },
];

function normalizeFeed(raw: any): FeedItem[] {
  let items: any[] = [];
  if (raw?.data?.items) items = raw.data.items;
  else if (raw?.data?.feed) items = raw.data.feed;
  else if (raw?.items) items = raw.items;
  else if (Array.isArray(raw?.data)) items = raw.data;

  if (items.length === 0) return MOCK_FEED;

  return items.map((item: any, idx: number) => {
    const hasSender = item.sender_id || item.sender || item.sender_name;
    const createdMs = item.created_at && typeof item.created_at === "number"
      ? new Date(item.created_at).toISOString()
      : item.created_at;
    return {
      id: item.item_id || item.id || `feed_${idx}`,
      author: hasSender ? (item.sender || item.author || item.sender_name || "未知") : "Castorice",
      author_id: item.sender_id,
      content: item.content || item.raw_content_preview || item.summary || String(item),
      timestamp: createdMs || item.timestamp || new Date().toISOString(),
      likes: item.praise_count || item.likes || item.like_count || 0,
      comments: item.reply_count || item.comments || item.comment_count || 0,
      is_self: !hasSender || item.is_self || false,
    };
  });
}

function normalizeConversations(raw: any): Conversation[] {
  let items: any[] = [];
  if (raw?.data?.conversations) items = raw.data.conversations;
  else if (raw?.data?.items) items = raw.data.items;
  else if (raw?.conversations) items = raw.conversations;
  else if (raw?.items) items = raw.items;
  else if (Array.isArray(raw?.data)) items = raw.data;

  if (items.length === 0) return MOCK_CONVERSATIONS;

  return items.map((item: any, idx: number) => ({
    id: item.id || item.conv_id || `conv_${idx}`,
    peer: item.peer || item.peer_name || item.sender || "未知",
    peer_id: item.peer_id || item.sender_id || `peer_${idx}`,
    last_message: item.last_message || item.preview || item.content || "",
    last_timestamp: item.last_timestamp || item.updated_at || new Date().toISOString(),
    unread_count: item.unread_count || 0,
  }));
}

function normalizeRelations(raw: any): SocialRelation[] {
  let items: any[] = [];
  if (raw?.data?.relations) items = raw.data.relations;
  else if (raw?.data?.items) items = raw.data.items;
  else if (raw?.relations) items = raw.relations;
  else if (raw?.friends) items = raw.friends;
  else if (raw?.items) items = raw.items;
  else if (Array.isArray(raw?.data)) items = raw.data;

  if (items.length === 0) return MOCK_RELATIONS;

  return items.map((item: any, idx: number) => ({
    id: item.id || `rel_${idx}`,
    name: item.name || item.peer || item.user_name || "未知",
    relation_type: item.relation_type || item.type || item.category || "朋友",
    strength: typeof item.strength === "number" ? item.strength : item.closeness || 0.5,
    last_interaction: item.last_interaction || item.updated_at || "",
  }));
}

function FeedCard({ item }: { item: FeedItem }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-xl p-4 hover:bg-biolum-500/5 transition-colors"
    >
      <div className="flex items-start gap-3">
        <div className={`w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
          item.is_self ? "bg-violet-glow/20 text-violet-glow" : "bg-biolum-500/20 text-biolum-300"
        }`}>
          {item.author.slice(0, 2).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-biolum-200">{item.author}</span>
            {item.is_self && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-glow/20 text-violet-glow">我</span>
            )}
            <span className="text-[10px] text-biolum-300/40 ml-auto">
              {formatDistanceToNow(new Date(item.timestamp), { addSuffix: true, locale: zhCN })}
            </span>
          </div>
          <p className="text-xs text-biolum-200/70 mt-2 leading-relaxed whitespace-pre-wrap">
            {item.content}
          </p>
          <div className="flex items-center gap-4 mt-3 pt-3 border-t border-biolum-500/10">
            <button className="flex items-center gap-1.5 text-[10px] text-biolum-300/50 hover:text-rose-deep transition-colors">
              <Heart className="w-3 h-3" />
              {item.likes || 0}
            </button>
            <button className="flex items-center gap-1.5 text-[10px] text-biolum-300/50 hover:text-biolum-300 transition-colors">
              <MessageCircle className="w-3 h-3" />
              {item.comments || 0}
            </button>
            <button className="flex items-center gap-1.5 text-[10px] text-biolum-300/50 hover:text-emerald-glow transition-colors ml-auto">
              <Share2 className="w-3 h-3" />
              分享
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function ConversationItem({ conv, onClick }: { conv: Conversation; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full glass rounded-xl p-3 flex items-center gap-3 hover:bg-biolum-500/5 transition-colors text-left"
    >
      <div className="relative">
        <div className="w-10 h-10 rounded-full bg-biolum-500/20 flex items-center justify-center text-xs font-bold text-biolum-300">
          {conv.peer.slice(0, 2).toUpperCase()}
        </div>
        {conv.unread_count > 0 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-rose-deep text-white text-[9px] flex items-center justify-center font-bold">
            {conv.unread_count}
          </span>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-biolum-200">{conv.peer}</span>
          <span className="text-[10px] text-biolum-300/40">
            {formatDistanceToNow(new Date(conv.last_timestamp), { addSuffix: true, locale: zhCN })}
          </span>
        </div>
        <p className="text-[11px] text-biolum-300/50 truncate mt-0.5">{conv.last_message}</p>
      </div>
      <ChevronRight className="w-4 h-4 text-biolum-300/30 shrink-0" />
    </button>
  );
}

function RelationCard({ rel }: { rel: SocialRelation }) {
  const strengthColor = rel.strength > 0.7 ? "text-emerald-glow" : rel.strength > 0.4 ? "text-amber-glow" : "text-biolum-300/40";
  return (
    <div className="glass rounded-xl p-3 flex items-center gap-3">
      <div className="w-10 h-10 rounded-full bg-biolum-500/20 flex items-center justify-center text-xs font-bold text-biolum-300">
        {rel.name.slice(0, 2).toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-biolum-200">{rel.name}</span>
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-biolum-500/20 text-biolum-300/60">
            {rel.relation_type}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-1">
          <div className="flex-1 h-1 bg-biolum-500/10 rounded-full overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${rel.strength * 100}%` }}
              transition={{ duration: 0.5 }}
              className={`h-full bg-gradient-to-r from-biolum-500/40 ${strengthColor.replace('text-', 'to-')}`}
            />
          </div>
          <span className={`text-[10px] font-medium ${strengthColor}`}>
            {Math.round(rel.strength * 100)}%
          </span>
        </div>
      </div>
    </div>
  );
}

export default function SocialPage() {
  const [activeTab, setActiveTab] = useState<TabType>("feed");
  const [feed, setFeed] = useState<FeedItem[]>(MOCK_FEED);
  const [conversations, setConversations] = useState<Conversation[]>(MOCK_CONVERSATIONS);
  const [relations, setRelations] = useState<SocialRelation[]>(MOCK_RELATIONS);
  const [loading, setLoading] = useState(false);
  const [selectedConv, setSelectedConv] = useState<Conversation | null>(null);
  const agentStatus = useAppStore((s) => s.agentStatus);

  const tabs = [
    { id: "feed" as TabType, label: "信息流", icon: Radio },
    { id: "messages" as TabType, label: "私信", icon: MessageSquare },
    { id: "relations" as TabType, label: "社交关系", icon: Users },
  ];

  const loadData = async () => {
    setLoading(true);
    try {
      if (activeTab === "feed") {
        const res = await api.efFeed(20, true).catch(() => null);
        if (res) setFeed(normalizeFeed(res));
      } else if (activeTab === "messages") {
        const res = await api.efConversations().catch(() => null);
        if (res) setConversations(normalizeConversations(res));
      } else if (activeTab === "relations") {
        const res = await api.efRelations().catch(() => null);
        if (res) setRelations(normalizeRelations(res));
      }
    } catch (e) {
      // 失败时保持 mock 数据不变
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [activeTab]);

  const efAvailable = agentStatus?.eigenflux_available;
  const efAuthenticated = agentStatus?.eigenflux_authenticated;

  return (
    <div className="h-full overflow-y-auto p-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="max-w-4xl mx-auto"
      >
        <div className="pt-8 mb-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="font-display text-3xl text-biolum-100 text-glow">EigenFlux 社交</h1>
              <p className="text-sm text-biolum-300/50 mt-1">
                {efAvailable && efAuthenticated ? "已连接到 EigenFlux 网络" : efAvailable ? "EigenFlux 待验证" : "EigenFlux 未连接"}
              </p>
            </div>
            <button
              onClick={loadData}
              disabled={loading}
              className="glass rounded-lg px-3 py-2 text-xs text-biolum-300/70 hover:text-biolum-200 transition-colors flex items-center gap-2"
            >
              <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
              刷新
            </button>
          </div>
        </div>

        <div className="flex gap-1 p-1 glass rounded-xl mb-4">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-xs font-medium transition-all ${
                activeTab === tab.id
                  ? "bg-biolum-500/20 text-biolum-200"
                  : "text-biolum-300/50 hover:text-biolum-300"
              }`}
            >
              <tab.icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          <AnimatePresence mode="wait">
            {loading ? (
              <motion.div
                key="loading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-center text-xs text-biolum-300/40 py-8"
              >
                加载中...
              </motion.div>
            ) : (
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.2 }}
                className="space-y-3"
              >
                {activeTab === "feed" && feed.map((item) => (
                  <FeedCard key={item.id} item={item} />
                ))}
                {activeTab === "messages" && conversations.map((conv) => (
                  <ConversationItem
                    key={conv.id}
                    conv={conv}
                    onClick={() => setSelectedConv(conv)}
                  />
                ))}
                {activeTab === "relations" && relations.map((rel) => (
                  <RelationCard key={rel.id} rel={rel} />
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.div>

      {/* 私信对话弹窗 */}
      <AnimatePresence>
        {selectedConv && (
          <ConversationDialog
            conversation={selectedConv}
            onClose={() => setSelectedConv(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
