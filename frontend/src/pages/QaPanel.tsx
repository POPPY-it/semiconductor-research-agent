import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Input,
  List,
  Spin,
  Typography,
  Upload,
  message,
  Row,
  Col,
  Tag,
  Space,
  Divider,
} from "antd";
import {
  InboxOutlined,
  SendOutlined,
  FilePdfOutlined,
  CompassOutlined,
  DatabaseOutlined,
  SearchOutlined,
  LinkOutlined,
} from "@ant-design/icons";
import { askQuestion, listDocuments, QaResult, uploadDocument } from "../api";

const { Text, Title, Paragraph } = Typography;

const EXAMPLES = [
  "台积电 2026 年 7 月营收是多少？同比增速如何？",
  "NVIDIA 最近向 SEC 提交了哪些主要 8-K 和 10-Q 财报披露？",
  "ASML 2026 年第二季度总净销售额与全年业绩指引情况？",
  "知识库里有哪些关于芯片设计自动化或存内计算的学术论文？",
];

export default function QaPanel() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QaResult | null>(null);
  const [error, setError] = useState("");
  const [docs, setDocs] = useState<{ title: string; chars: number }[]>([]);
  const [uploading, setUploading] = useState(false);

  const refreshDocs = async () => {
    try {
      setDocs((await listDocuments()).documents);
    } catch {
      /* 忽略 */
    }
  };

  useEffect(() => {
    refreshDocs();
  }, []);

  const onUpload = async (file: File) => {
    setUploading(true);
    try {
      const res = await uploadDocument(file);
      message.success(`已完成解析入库并实时重建知识索引：${res.title}（${res.chars} 字符）`);
      refreshDocs();
    } catch (e) {
      message.error(String(e));
    } finally {
      setUploading(false);
    }
  };

  const submit = async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      setResult(await askQuestion(text));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Row gutter={24}>
      {/* 问答主交互区域 */}
      <Col xs={24} lg={16}>
        <Card
          className="enterprise-card"
          title={
            <div className="card-header-flex">
              <span className="card-title-text">
                <SearchOutlined style={{ color: "#2563eb" }} /> 领域知识增强精准问答 (RAG)
              </span>
              <Tag color="cyan">混合检索 + 引用闭环</Tag>
            </div>
          }
        >
          <div className="qa-hero-header">
            <Paragraph type="secondary" style={{ fontSize: 13.5, marginBottom: 16 }}>
              直接针对 SEC 官方财报全文、arXiv 论文摘要以及实时行业新闻进行证据检索式提问，回答严格保证事实溯源。
            </Paragraph>

            <Input.Search
              className="qa-search-box"
              placeholder="输入具体问题，例如：台积电 7 月合并营收与同比增幅是多少？"
              enterButton={
                <Button type="primary" icon={<SendOutlined />} loading={loading} style={{ height: 44, fontWeight: 600 }}>
                  智能检索与回答
                </Button>
              }
              size="large"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onSearch={() => submit()}
              style={{ borderRadius: 8 }}
            />

            <div style={{ marginTop: 14 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <CompassOutlined style={{ marginRight: 4 }} /> 推荐高频研判问题：
              </Text>
              <div className="topic-pills-container">
                {EXAMPLES.map((ex) => (
                  <span
                    key={ex}
                    className="topic-pill-tag"
                    onClick={() => {
                      setQuestion(ex);
                      submit(ex);
                    }}
                  >
                    {ex}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {loading && (
            <div style={{ padding: "40px 0", textAlign: "center" }}>
              <Spin size="large" tip="正在执行 BM25 与向量双路召回及 CodeAgent 归纳..." />
            </div>
          )}

          {error && <Alert style={{ marginTop: 20 }} type="error" showIcon message={error} />}

          {result && !loading && (
            <div style={{ marginTop: 20 }}>
              <Divider style={{ margin: "16px 0" }} />
              <div style={{ background: "#f8fafc", padding: "18px 20px", borderRadius: 8, border: "1px solid #e2e8f0" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                  <Tag color="blue" style={{ fontWeight: 600 }}>AGENT 回答</Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>由经过事实校验的 CodeAgent 生成</Text>
                </div>
                <div style={{ fontSize: 14.5, lineHeight: 1.8, color: "#1e293b", whiteSpace: "pre-wrap" }}>
                  {result.answer}
                </div>
              </div>

              {result.sources.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <Text strong style={{ fontSize: 13, color: "#475569" }}>
                    <LinkOutlined style={{ marginRight: 6 }} />
                    本次回答关联的关键溯源文献与官方披露：
                  </Text>
                  <div style={{ marginTop: 8 }}>
                    {result.sources.map((s, idx) => (
                      <div key={idx} className="qa-source-card">
                        <Space>
                          <Tag color="geekblue">来源 #{idx + 1}</Tag>
                          <a href={s.url} target="_blank" rel="noreferrer" style={{ fontSize: 13, color: "#2563eb", fontWeight: 500 }}>
                            {s.title || s.url}
                          </a>
                        </Space>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      </Col>

      {/* 知识库文档资产管理 */}
      <Col xs={24} lg={8}>
        <Card
          className="enterprise-card"
          title={
            <div className="card-header-flex">
              <span className="card-title-text">
                <DatabaseOutlined style={{ color: "#0891b2" }} /> 知识资产管理
              </span>
              <Tag color="purple">{docs.length} 篇已索引</Tag>
            </div>
          }
        >
          <Upload.Dragger
            accept=".pdf,.txt,.md,.html,.csv"
            showUploadList={false}
            beforeUpload={(file) => {
              onUpload(file);
              return false;
            }}
            disabled={uploading}
            style={{ padding: "16px 10px", background: "#f8fafc", borderColor: "#cbd5e1" }}
          >
            <p className="ant-upload-drag-icon" style={{ marginBottom: 8 }}>
              <InboxOutlined style={{ color: "#2563eb", fontSize: 32 }} />
            </p>
            <p className="ant-upload-text" style={{ fontSize: 13.5, fontWeight: 500 }}>
              {uploading ? "正在解析并重建向量索引..." : "上传企业研报 / 论文 (PDF/TXT)"}
            </p>
            <p className="ant-upload-hint" style={{ fontSize: 11.5 }}>
              支持 PyMuPDF 自动抽取、分块并触发多路混合检索索引更新
            </p>
          </Upload.Dragger>

          <Divider style={{ margin: "16px 0" }} />

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <Text strong style={{ fontSize: 12.5, color: "#475569" }}>
              最新解析入库资产清单
            </Text>
            <Button type="link" size="small" onClick={refreshDocs} style={{ padding: 0 }}>
              刷新
            </Button>
          </div>

          <div style={{ maxHeight: 320, overflowY: "auto" }}>
            <List
              size="small"
              dataSource={docs}
              renderItem={(d) => (
                <List.Item style={{ padding: "8px 4px", fontSize: 12.5 }}>
                  <Space style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", width: "100%", justifyContent: "space-between" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 6, maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      <FilePdfOutlined style={{ color: "#ef4444" }} />
                      <Text ellipsis title={d.title}>{d.title}</Text>
                    </span>
                    <Tag>{d.chars} 字符</Tag>
                  </Space>
                </List.Item>
              )}
            />
          </div>
        </Card>
      </Col>
    </Row>
  );
}
