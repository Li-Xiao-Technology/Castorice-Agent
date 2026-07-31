import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { User, Sparkles, Copy, Check } from "lucide-react";
import { useState } from "react";
import type { ChatMessage } from "@/types";

interface Props {
  message: ChatMessage;
  isLast?: boolean;
}

export default function MessageBubble({ message, isLast }: Props) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
      className={`flex gap-3 w-full ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      {/* 头像 */}
      <div className="shrink-0">
        <motion.div
          whileHover={{ scale: 1.05 }}
          className={`w-9 h-9 rounded-xl flex items-center justify-center ${
            isUser
              ? "bg-gradient-to-br from-amber-glow to-amber-soft/50 text-abyss-950"
              : "bg-gradient-to-br from-biolum-400 to-biolum-600 text-abyss-950 shadow-glow"
          }`}
        >
          {isUser ? (
            <User className="w-4.5 h-4.5" strokeWidth={2.2} />
          ) : (
            <Sparkles className="w-4.5 h-4.5" strokeWidth={2.2} />
          )}
        </motion.div>
      </div>

      {/* 消息内容 */}
      <div className={`flex flex-col gap-1 max-w-[75%] ${isUser ? "items-end" : "items-start"}`}>
        <motion.div
          whileHover={{ scale: 1.002 }}
          className={`group relative rounded-2xl px-4 py-3 ${
            isUser
              ? "bg-gradient-to-br from-amber-glow/20 to-amber-soft/5 border border-amber-glow/20 rounded-tr-sm"
              : "glass rounded-tl-sm"
          } ${message.streaming ? "typing-cursor" : ""}`}
        >
          {isUser ? (
            <p className="text-sm text-amber-soft/90 leading-relaxed whitespace-pre-wrap">
              {message.content}
            </p>
          ) : (
            <div className="text-sm text-biolum-100/90 leading-relaxed prose prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ node, inline, className, children, ...props }: any) {
                    const match = /language-(\w+)/.exec(className || "");
                    return !inline && match ? (
                      <SyntaxHighlighter
                        style={oneDark}
                        language={match[1]}
                        PreTag="div"
                        customStyle={{
                          background: "rgba(5, 8, 15, 0.8)",
                          borderRadius: "8px",
                          fontSize: "12px",
                        }}
                        {...props}
                      >
                        {String(children).replace(/\n$/, "")}
                      </SyntaxHighlighter>
                    ) : (
                      <code className={className} {...props}>
                        {children}
                      </code>
                    );
                  },
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-1">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-1">{children}</ol>,
                  li: ({ children }) => <li className="text-sm">{children}</li>,
                  h1: ({ children }) => <h1 className="text-xl font-display font-semibold text-biolum-100 mb-2 mt-3">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-lg font-display font-semibold text-biolum-100 mb-2 mt-3">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-base font-display font-semibold text-biolum-200 mb-1.5 mt-2">{children}</h3>,
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="text-biolum-300 hover:text-biolum-200 underline underline-offset-2">
                      {children}
                    </a>
                  ),
                  blockquote: ({ children }) => (
                    <blockquote className="border-l-2 border-biolum-500/40 pl-3 my-2 text-biolum-200/70 italic">
                      {children}
                    </blockquote>
                  ),
                  table: ({ children }) => (
                    <div className="overflow-x-auto my-2">
                      <table className="min-w-full text-sm border-collapse">{children}</table>
                    </div>
                  ),
                  th: ({ children }) => (
                    <th className="border border-biolum-500/20 px-3 py-1.5 text-left bg-biolum-500/10">{children}</th>
                  ),
                  td: ({ children }) => (
                    <td className="border border-biolum-500/10 px-3 py-1.5">{children}</td>
                  ),
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}

          {/* 复制按钮 */}
          {!isUser && !message.streaming && (
            <button
              onClick={handleCopy}
              className="absolute -right-2 -top-2 p-1.5 rounded-lg glass text-biolum-300/50 hover:text-biolum-200 opacity-0 group-hover:opacity-100 transition-all"
              title="复制"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-biolum-400" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          )}
        </motion.div>

        {/* 时间戳 */}
        <span className="text-[10px] text-biolum-300/30 px-1">
          {new Date(message.timestamp).toLocaleTimeString("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
    </motion.div>
  );
}
