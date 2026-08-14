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
} from "antd";
import {
  InboxOutlined,
  QuestionCircleOutlined,
  SendOutlined,
} from "@ant-design/icons";
import { askQuestion, listDocuments, QaResult, uploadDocument } from "../api";

const EXAMPLES = [
  "台积电 7 月营收是多少？",
  "NVIDIA 最近提交了哪些财报？",
  "ASML 2026 年第二季度净销售额和全年指引？",
  "最近半导体行业有哪些重要新闻？",
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
      message.success(
        `已入库并重建索引：${res.title}（${res.chars} 字）`
      );
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
    <Card title="财报 / 行业数据问答" style={{ maxWidth: 720 }}>
      <Typography.Paragraph type="secondary">
        直接向知识库提问（基于已采集的 SEC 财报全文与行业新闻，回答附来源链接）。
      </Typography.Paragraph>
      <Input.Search
        placeholder="例如：台积电 7 月营收是多少？"
        enterButton={
          <Button type="primary" icon={<SendOutlined />} loading={loading}>
            提问
          </Button>
        }
        size="large"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        onSearch={() => submit()}
      />
      <div style={{ marginTop: 12 }}>
        {EXAMPLES.map((ex) => (
          <Button
            key={ex}
            type="link"
            size="small"
            icon={<QuestionCircleOutlined />}
            onClick={() => {
              setQuestion(ex);
              submit(ex);
            }}
          >
            {ex}
          </Button>
        ))}
      </div>

      {loading && (
        <div style={{ marginTop: 24, textAlign: "center" }}>
          <Spin tip="检索知识库中..." />
        </div>
      )}

      {error && (
        <Alert style={{ marginTop: 16 }} type="error" message={error} showIcon />
      )}

      {result && !loading && (
        <div style={{ marginTop: 16 }}>
          <Alert
            type="info"
            message="回答"
            description={
              <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.8 }}>
                {result.answer}
              </div>
            }
          />
          {result.sources.length > 0 && (
            <List
              style={{ marginTop: 8 }}
              size="small"
              header={<b>参考来源</b>}
              bordered
              dataSource={result.sources}
              renderItem={(s) => (
                <List.Item>
                  <a href={s.url} target="_blank" rel="noreferrer">
                    {s.title || s.url}
                  </a>
                </List.Item>
              )}
            />
          )}
        </div>
      )}

      <Card
        size="small"
        title={`知识库文档（${docs.length}）`}
        style={{ marginTop: 24 }}
      >
        <Upload.Dragger
          accept=".pdf,.txt,.md,.html,.csv"
          showUploadList={false}
          beforeUpload={(file) => {
            onUpload(file);
            return false; // 阻止默认上传，走自定义
          }}
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">
            {uploading ? "解析并重建索引中..." : "点击或拖拽上传 PDF / 文档"}
          </p>
          <p className="ant-upload-hint">
            上传后自动解析入库并重建知识库索引，问答即可检索到
          </p>
        </Upload.Dragger>
        {docs.length > 0 && (
          <List
            style={{ marginTop: 8 }}
            size="small"
            dataSource={docs}
            renderItem={(d) => (
              <List.Item>
                {d.title}
                <Typography.Text type="secondary">
                  {d.chars} 字
                </Typography.Text>
              </List.Item>
            )}
          />
        )}
      </Card>
    </Card>
  );
}
