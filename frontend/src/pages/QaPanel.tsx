import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
  Input,
  List,
  message,
  Space,
  Spin,
  Tag,
  Typography,
  Upload,
} from "antd";
import {
  InboxOutlined,
  SendOutlined,
  PlusOutlined,
  MessageOutlined,
  FilePdfOutlined,
  LinkOutlined,
  RobotOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  askQuestion,
  listConversations,
  getConversation,
  listDocuments,
  uploadDocument,
  QaMessage,
  ConversationSummary,
} from "../api";

const { Text, Paragraph } = Typography;

const EXAMPLES = [
  "台积电 2026 年 7 月营收是多少？",
  "NVIDIA 最近提交了哪些财报？",
  "ASML 2026 年第二季度净销售额和全年指引？",
  "知识库里有哪些关于芯片设计自动化的论文？",
];

export default function QaPanel() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [currentConvId, setCurrentConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<QaMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [docs, setDocs] = useState<{ title: string; chars: number }[]>([]);
  const [uploading, setUploading] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const refreshDocs = async () => {
    try {
      setDocs((await listDocuments()).documents);
    } catch {
      /* 忽略 */
    }
  };

  const refreshConversations = async () => {
    try {
      setConversations((await listConversations()).conversations);
    } catch {
      /* 忽略 */
    }
  };

  useEffect(() => {
    refreshDocs();
    refreshConversations().then(() => {
      // 默认不自动打开历史，保持干净入口
    });
  }, []);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const openConversation = async (id: number) => {
    setCurrentConvId(id);
    setMessages((await getConversation(id)).messages);
    setError("");
  };

  const newConversation = () => {
    setCurrentConvId(null);
    setMessages([]);
    setError("");
    setInput("");
  };

  const send = async (text?: string) => {
    const q = (text ?? input).trim();
    if (!q || loading) return;
    setInput("");
    setLoading(true);
    setError("");
    setMessages((prev) => [...prev, { role: "user", content: q, sources: [] }]);
    try {
      const res = await askQuestion(q, currentConvId ?? undefined);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.answer, sources: res.sources },
      ]);
      if (res.conversation_id && res.conversation_id !== currentConvId) {
        setCurrentConvId(res.conversation_id);
        refreshConversations();
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const onUpload = async (file: File) => {
    setUploading(true);
    try {
      const res = await uploadDocument(file);
      message.success(`已解析入库并重建索引：${res.title}（${res.chars} 字符）`);
      refreshDocs();
    } catch (e) {
      message.error(String(e));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ display: "flex", gap: 16, minHeight: 560 }}>
      {/* 左：对话列表 */}
      <Card
        className="enterprise-card"
        style={{ width: 240, flexShrink: 0 }}
        bodyStyle={{ padding: 12 }}
        title={
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Text strong style={{ fontSize: 14 }}>研究对话</Text>
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={newConversation}>
              新建
            </Button>
          </div>
        }
      >
        <List
          size="small"
          dataSource={conversations}
          locale={{ emptyText: <Empty description="暂无对话" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          renderItem={(c) => (
            <List.Item
              onClick={() => openConversation(c.id)}
              style={{
                cursor: "pointer",
                borderRadius: 6,
                padding: "8px 10px",
                background: c.id === currentConvId ? "#eff6ff" : "transparent",
                border: c.id === currentConvId ? "1px solid #bfdbfe" : "1px solid transparent",
                marginBottom: 4,
              }}
            >
              <div style={{ width: "100%" }}>
                <div style={{ fontSize: 12.5, fontWeight: 500, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  <MessageOutlined style={{ marginRight: 6, color: "#2563eb" }} />
                  {c.title}
                </div>
                <Text type="secondary" style={{ fontSize: 11 }}>{c.msg_count} 条消息</Text>
              </div>
            </List.Item>
          )}
        />
      </Card>

      {/* 右：聊天区 */}
      <Card
        className="enterprise-card"
        style={{ flex: 1 }}
        bodyStyle={{ padding: 0, display: "flex", flexDirection: "column", height: 600 }}
      >
        <div style={{ padding: "12px 20px", borderBottom: "1px solid #e2e8f0", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Space>
            <RobotOutlined style={{ color: "#2563eb", fontSize: 18 }} />
            <Text strong style={{ fontSize: 14 }}>领域知识问答 Agent</Text>
            <Tag color="cyan">多轮上下文 · 引用溯源</Tag>
          </Space>
        </div>

        {/* 消息列表 */}
        <div ref={listRef} style={{ flex: 1, overflowY: "auto", padding: "20px 24px", background: "#fafbfd" }}>
          {messages.length === 0 && !loading && (
            <div style={{ padding: "30px 10px" }}>
              <Empty
                description={
                  <span>
                    开始一次研究对话<br />
                    <Text type="secondary" style={{ fontSize: 12 }}>支持多轮追问，例如先问"台积电营收"，再问"那 ASML 呢？"</Text>
                  </span>
                }
              />
              <div className="topic-pills-container" style={{ justifyContent: "center", marginTop: 12 }}>
                {EXAMPLES.map((ex) => (
                  <span key={ex} className="topic-pill-tag" onClick={() => send(ex)}>{ex}</span>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start", marginBottom: 16 }}>
              <div style={{ maxWidth: "78%" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
                  {m.role === "assistant" ? <RobotOutlined style={{ color: "#2563eb" }} /> : <UserOutlined style={{ color: "#64748b" }} />}
                  <Text type="secondary" style={{ fontSize: 11 }}>{m.role === "user" ? "你" : "Agent"}</Text>
                </div>
                <div style={{
                  background: m.role === "user" ? "#2563eb" : "#ffffff",
                  color: m.role === "user" ? "#fff" : "#1e293b",
                  border: m.role === "user" ? "none" : "1px solid #e2e8f0",
                  borderRadius: 10,
                  padding: "12px 16px",
                  fontSize: 13.5,
                  lineHeight: 1.7,
                  whiteSpace: "pre-wrap",
                  boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                }}>
                  {m.content}
                </div>
                {m.role === "assistant" && m.sources?.length > 0 && (
                  <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {m.sources.map((s, j) => (
                      <a key={j} href={s.url} target="_blank" rel="noreferrer" style={{ fontSize: 11.5, color: "#2563eb" }}>
                        <LinkOutlined style={{ marginRight: 3 }} />
                        {s.title?.slice(0, 40) || s.url}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#64748b" }}>
                <Spin size="small" /> Agent 正在检索与归纳...
              </div>
            </div>
          )}

          {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
        </div>

        {/* 输入区 */}
        <div style={{ padding: "14px 20px", borderTop: "1px solid #e2e8f0", background: "#fff" }}>
          <Collapse
            ghost
            size="small"
            items={[
              {
                key: "kb",
                label: <Text type="secondary" style={{ fontSize: 12 }}><InboxOutlined /> 知识资产（上传 PDF/文档，共 {docs.length} 篇）</Text>,
                children: (
                  <div>
                    <Upload.Dragger
                      accept=".pdf,.txt,.md,.html,.csv"
                      showUploadList={false}
                      beforeUpload={(f) => { onUpload(f); return false; }}
                      disabled={uploading}
                      style={{ padding: "10px" }}
                    >
                      <p style={{ margin: 0 }}><InboxOutlined style={{ fontSize: 20, color: "#2563eb" }} /> {uploading ? "解析中..." : "点击或拖拽上传"}</p>
                    </Upload.Dragger>
                    {docs.slice(0, 5).map((d) => (
                      <div key={d.title} style={{ fontSize: 12, color: "#475569", padding: "3px 0" }}>
                        <FilePdfOutlined style={{ color: "#ef4444", marginRight: 6 }} />
                        {d.title} <Tag>{d.chars} 字符</Tag>
                      </div>
                    ))}
                  </div>
                ),
              },
            ]}
          />
          <Space.Compact style={{ width: "100%", marginTop: 8 }}>
            <Input
              size="large"
              value={input}
              placeholder="输入问题，可追问（如：那 ASML 呢？）..."
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={() => send()}
              disabled={loading}
            />
            <Button type="primary" size="large" icon={<SendOutlined />} onClick={() => send()} loading={loading}>
              发送
            </Button>
          </Space.Compact>
        </div>
      </Card>
    </div>
  );
}
