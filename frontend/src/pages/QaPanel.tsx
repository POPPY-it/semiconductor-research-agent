import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
  Input,
  List,
  message,
  Modal,
  Select,
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
  listMemories,
  clearMemories,
  mcpStatus,
  mcpCall,
  addMcpServer,
  deleteMcpServer,
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
  const [memories, setMemories] = useState<string[]>([]);
  const [retrieval, setRetrieval] = useState<{ method: string; top_k: number; corpus_size: number } | null>(null);
  const [mcpServers, setMcpServers] = useState<{ name: string; tools: string[] }[]>([]);
  const [mcpTools, setMcpTools] = useState<{ server: string; tool: string; description: string; inputSchema: Record<string, { type?: string; description?: string }> }[]>([]);
  const [mcpTesting, setMcpTesting] = useState(false);
  const [mcpName, setMcpName] = useState("");
  const [mcpCommand, setMcpCommand] = useState("");
  const [mcpArgs, setMcpArgs] = useState("");
  const [testOpen, setTestOpen] = useState(false);
  const [testServer, setTestServer] = useState("");
  const [testTool, setTestTool] = useState("");
  const [testArgsText, setTestArgsText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const refreshMcp = async () => {
    try {
      const st = await mcpStatus();
      setMcpServers(st.servers);
      setMcpTools(st.tools);
    } catch {
      /* 忽略 */
    }
  };

  const onAddMcp = async () => {
    if (!mcpName.trim() || !mcpCommand.trim()) {
      message.warning("请填写 Server 名称和启动命令");
      return;
    }
    try {
      const args = mcpArgs.split(",").map((s) => s.trim()).filter(Boolean);
      await addMcpServer(mcpName.trim(), mcpCommand.trim(), args);
      message.success(`已添加 MCP Server：${mcpName}`);
      setMcpName(""); setMcpCommand(""); setMcpArgs("");
      refreshMcp();
    } catch (e) {
      message.error(String(e));
    }
  };

  const onDeleteMcp = async (name: string) => {
    try {
      await deleteMcpServer(name);
      message.success(`已删除 ${name}`);
      refreshMcp();
    } catch (e) {
      message.error(String(e));
    }
  };

  // 打开某个 Server 的测试弹窗：默认选第一个工具，按 schema 预填示例参数
  const openMcpTest = (server: string) => {
    const tools = mcpTools.filter((t) => t.server === server);
    const first = tools[0];
    setTestServer(server);
    setTestTool(first?.tool || "");
    if (first) {
      const props = first.inputSchema || {};
      const sample: Record<string, string> = {};
      for (const [k, v] of Object.entries(props)) {
        if (v?.type === "string" && Object.keys(sample).length < 2) {
          sample[k] = k === "q" || k === "query" ? "台积电 2nm 产能" : "示例值";
        }
      }
      setTestArgsText(JSON.stringify(sample, null, 2));
    } else {
      setTestArgsText("{}");
    }
    setTestOpen(true);
  };

  const runMcpTest = async () => {
    if (!testTool) return;
    let args: object;
    try {
      args = JSON.parse(testArgsText || "{}");
    } catch {
      message.error("参数必须是合法 JSON");
      return;
    }
    setMcpTesting(true);
    try {
      const r = await mcpCall(testTool, args);
      message.success("MCP 工具调用成功");
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `**MCP 工具实测** \`${testTool}\`（${testServer}）：\n\n` + r.result.slice(0, 4000),
          sources: [],
        },
      ]);
      setTestOpen(false);
    } catch (e) {
      message.error(String(e));
    } finally {
      setMcpTesting(false);
    }
  };

  const refreshMemories = async () => {
    try {
      setMemories((await listMemories()).memories);
    } catch {
      /* 忽略 */
    }
  };

  const onClearMemories = async () => {
    try {
      const r = await clearMemories();
      message.success(`已清空 ${r.cleared} 条长期记忆`);
      refreshMemories();
    } catch (e) {
      message.error(String(e));
    }
  };

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
    refreshMemories();
    refreshMcp();
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
      setRetrieval(res.retrieval ?? null);
      if (res.conversation_id && res.conversation_id !== currentConvId) {
        setCurrentConvId(res.conversation_id);
        refreshConversations();
      }
      refreshMemories(); // 回答后可能抽取了新记忆
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
                  boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                }}>
                  {m.role === "user" ? (
                    <span style={{ whiteSpace: "pre-wrap" }}>{m.content}</span>
                  ) : (
                    <div className="qa-answer-md">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                    </div>
                  )}
                </div>
                {m.role === "assistant" && m.sources?.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    {retrieval && (
                      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>
                        🔍 {retrieval.method} · 知识库 {retrieval.corpus_size} 个分块 · 命中 Top {retrieval.top_k}
                      </div>
                    )}
                    {m.sources.map((s, j) => (
                      <div key={j} className="qa-source-card" style={{ marginBottom: 6 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <Tag color="geekblue" style={{ fontSize: 10, lineHeight: "16px", margin: 0 }}>
                            {s.source_type || "知识库"}
                          </Tag>
                          {typeof s.relevance === "number" && (
                            <span style={{ fontSize: 11, color: "#2563eb", fontWeight: 600 }}>
                              相关度 {s.relevance}%
                            </span>
                          )}
                          <a href={s.url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "#2563eb", fontWeight: 500, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            <LinkOutlined style={{ marginRight: 4 }} />
                            {s.title?.slice(0, 50) || s.url}
                          </a>
                        </div>
                        {s.snippet && (
                          <div style={{ fontSize: 11.5, color: "#64748b", marginTop: 4, lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                            {s.snippet}
                          </div>
                        )}
                      </div>
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
                key: "mcp",
                label: <Text type="secondary" style={{ fontSize: 12 }}>🔌 MCP 工具生态（{mcpServers.length} 个 Server）</Text>,
                children: (
                  <div>
                    {mcpServers.length === 0 ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>未检测到 MCP Server</Text>
                    ) : (
                      mcpServers.map((s) => (
                        <div key={s.name} style={{ marginBottom: 8, padding: "6px 8px", background: "#f8fafc", borderRadius: 6, border: "1px solid #e2e8f0" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <Tag color="blue" style={{ fontWeight: 600, margin: 0 }}>{s.name}</Tag>
                            <Space size={4}>
                              <Button size="small" type="link" style={{ padding: 0 }} onClick={() => openMcpTest(s.name)}>测试</Button>
                              <Button size="small" danger type="link" style={{ padding: 0 }} onClick={() => onDeleteMcp(s.name)}>删除</Button>
                            </Space>
                          </div>
                          <div style={{ paddingLeft: 4, marginTop: 4 }}>
                            {s.tools.map((t) => (
                              <Tag key={t} style={{ fontSize: 11, margin: "2px" }}>{t}</Tag>
                            ))}
                          </div>
                        </div>
                      ))
                    )}

                    <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed #e2e8f0" }}>
                      <Text strong style={{ fontSize: 12 }}>➕ 添加 MCP Server</Text>
                      <Input size="small" placeholder="名称（如 weather）" value={mcpName} onChange={(e) => setMcpName(e.target.value)} style={{ marginTop: 6 }} />
                      <Input size="small" placeholder="启动命令（如 npx -y @modelcontextprotocol/server-weather 或 python -m xxx）" value={mcpCommand} onChange={(e) => setMcpCommand(e.target.value)} style={{ marginTop: 6 }} />
                      <Input size="small" placeholder="参数，逗号分隔（可空）" value={mcpArgs} onChange={(e) => setMcpArgs(e.target.value)} style={{ marginTop: 6 }} />
                      <Button size="small" type="primary" onClick={onAddMcp} style={{ marginTop: 6 }}>添加</Button>
                      <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 4 }}>
                        例：命令填 npx -y @modelcontextprotocol/server-weather，参数填 --help
                      </Text>
                    </div>
                  </div>
                ),
              },
              {
                key: "mem",
                label: <Text type="secondary" style={{ fontSize: 12 }}>🧠 长期记忆（跨会话个性化，共 {memories.length} 条）</Text>,
                children: (
                  <div style={{ maxHeight: 120, overflowY: "auto" }}>
                    {memories.length === 0 ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>暂无记忆，Agent 会在对话中自动学习你的偏好</Text>
                    ) : (
                      <>
                        {memories.map((m, i) => (
                          <div key={i} style={{ fontSize: 12, color: "#475569", padding: "3px 0" }}>
                            · {m}
                          </div>
                        ))}
                        <Button size="small" danger type="link" onClick={onClearMemories} style={{ padding: 0 }}>
                          清空记忆
                        </Button>
                      </>
                    )}
                  </div>
                ),
              },
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

      <Modal
        title={`测试 MCP 工具（${testServer}）`}
        open={testOpen}
        onCancel={() => setTestOpen(false)}
        onOk={runMcpTest}
        okText="调用"
        confirmLoading={mcpTesting}
        width={520}
      >
        <Text strong style={{ fontSize: 12 }}>工具</Text>
        <Select
          style={{ width: "100%", margin: "4px 0 10px" }}
          size="small"
          value={testTool}
          onChange={(v) => {
            setTestTool(v);
            const t = mcpTools.find((x) => x.tool === v);
            const props = t?.inputSchema || {};
            const sample: Record<string, string> = {};
            for (const [k, vv] of Object.entries(props)) {
              if (vv?.type === "string" && Object.keys(sample).length < 2) {
                sample[k] = k === "q" || k === "query" ? "台积电 2nm 产能" : "示例值";
              }
            }
            setTestArgsText(JSON.stringify(sample, null, 2));
          }}
          options={mcpTools
            .filter((t) => t.server === testServer)
            .map((t) => ({ value: t.tool, label: t.tool }))}
        />
        <Text strong style={{ fontSize: 12 }}>参数（JSON）</Text>
        <Input.TextArea
          rows={4}
          style={{ marginTop: 4, fontFamily: "monospace", fontSize: 12 }}
          value={testArgsText}
          onChange={(e) => setTestArgsText(e.target.value)}
          placeholder='{"query": "台积电 2nm 产能"}'
        />
        <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 6 }}>
          结果会追加到下方对话区。调用实时搜索会消耗网关 credits。
        </Text>
      </Modal>
    </div>
  );
}
