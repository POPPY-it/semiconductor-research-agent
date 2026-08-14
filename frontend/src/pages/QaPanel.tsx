import { useState } from "react";
import { Alert, Button, Card, Input, List, Spin, Typography } from "antd";
import { QuestionCircleOutlined, SendOutlined } from "@ant-design/icons";
import { askQuestion, QaResult } from "../api";

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
    </Card>
  );
}
