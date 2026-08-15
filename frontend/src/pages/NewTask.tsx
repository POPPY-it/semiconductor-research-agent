import { useState } from "react";
import { Button, Card, Form, Input, message, Typography, Row, Col, Divider } from "antd";
import {
  RocketOutlined,
  CalendarOutlined,
  BookOutlined,
  ThunderboltOutlined,
  CompassOutlined,
  MedicineBoxOutlined,
  InfoCircleOutlined
} from "@ant-design/icons";
import { createSession } from "../api";

const { Text, Paragraph } = Typography;

const TYPE_CONFIG = [
  {
    key: "daily",
    title: "行业日报",
    desc: "300+ 字 | 今日要闻、核心动态快讯与行业数据点评",
    icon: <ThunderboltOutlined style={{ color: "#eab308" }} />
  },
  {
    key: "weekly",
    title: "行业周报",
    desc: "400+ 字 | 龙头企业动态、全周指标透视与后市展望",
    icon: <CalendarOutlined style={{ color: "#3b82f6" }} />
  },
  {
    key: "deep",
    title: "深度研报",
    desc: "600+ 字 | 行业格局、多公司对比、深度财务与风险剖析",
    icon: <BookOutlined style={{ color: "#8b5cf6" }} />
  },
  {
    key: "survey",
    title: "学术调研",
    desc: "500+ 字 | arXiv 最新文献调研、方法对比与引文规范",
    icon: <CompassOutlined style={{ color: "#10b981" }} />
  },
  {
    key: "medical_survey",
    title: "医学综述",
    desc: "500+ 字 | PubMed 文献、PICO 框架与证据等级（仅科研参考）",
    icon: <MedicineBoxOutlined style={{ color: "#ef4444" }} />
  }
];

const PRESETS = [
  "半导体行业日报：聚焦台积电 2nm 产能与存储芯片价格走势",
  "NVIDIA、Intel、ASML、台积电四巨头最新财报对比周报",
  "存内计算（Processing-in-Memory）与 DRAM 芯片学术研究现状",
  "生成式 AI 与大模型 Agent 对先进芯片制造需求的深度研报"
];

export default function NewTask({ onCreate }: { onCreate: (id: number) => void }) {
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const selectedType = Form.useWatch("report_type", form) || "daily";

  const onFinish = async (values: { topic: string; report_type: string }) => {
    setLoading(true);
    try {
      const res = await createSession(values.topic, values.report_type);
      message.success(`研报流水线已触发（会话 #${res.session_id}），正在实时协同研究...`);
      onCreate(res.session_id);
    } catch (e) {
      message.error(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Row gutter={24}>
      <Col xs={24} lg={16}>
        <Card
          className="enterprise-card"
          title={
            <div className="card-header-flex">
              <span className="card-title-text">
                <RocketOutlined style={{ color: "#2563eb" }} /> 研报生成配置流水线
              </span>
              <Text type="secondary" style={{ fontSize: 12, fontWeight: "normal" }}>
                多 Agent 自主撰写 & 质检核验
              </Text>
            </div>
          }
        >
          <Form
            form={form}
            layout="vertical"
            onFinish={onFinish}
            initialValues={{ report_type: "daily" }}
          >
            <Form.Item
              label={<Text strong>报告类型与研究框架</Text>}
              name="report_type"
            >
              <div className="report-type-grid">
                {TYPE_CONFIG.map((t) => {
                  const isSelected = selectedType === t.key;
                  return (
                    <div
                      key={t.key}
                      className={`type-select-card ${isSelected ? "selected" : ""}`}
                      onClick={() => form.setFieldsValue({ report_type: t.key })}
                    >
                      <div className="type-card-title">
                        <span>{t.title}</span>
                        {t.icon}
                      </div>
                      <div className="type-card-desc">{t.desc}</div>
                    </div>
                  );
                })}
              </div>
            </Form.Item>

            <Divider style={{ margin: "16px 0" }} />

            <Form.Item
              label={<Text strong>研究选题与核心诉求</Text>}
              name="topic"
              rules={[{ required: true, min: 4, message: "请输入至少 4 个字的研究选题" }]}
              extra="支持指定关注公司（如 NVIDIA / 台积电）、前沿器件（如 2nm / HBM）或学术主题"
            >
              <Input.TextArea
                rows={3}
                placeholder="例如：半导体行业周报：聚焦台积电 2nm 制程进展与各厂财报指引对比"
                style={{ borderRadius: 6 }}
              />
            </Form.Item>

            <div style={{ marginBottom: 20 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <InfoCircleOutlined style={{ marginRight: 4 }} /> 推荐高频研究模版：
              </Text>
              <div className="topic-pills-container">
                {PRESETS.map((p) => (
                  <span
                    key={p}
                    className="topic-pill-tag"
                    onClick={() => form.setFieldsValue({ topic: p })}
                  >
                    {p}
                  </span>
                ))}
              </div>
            </div>

            <Button
              type="primary"
              htmlType="submit"
              size="large"
              icon={<RocketOutlined />}
              loading={loading}
              style={{
                width: "100%",
                height: 44,
                fontWeight: 600,
                borderRadius: 8,
                boxShadow: "0 2px 6px rgba(37,99,235,0.3)"
              }}
            >
              启动自主研报流水线 (约 3~5 分钟)
            </Button>
          </Form>
        </Card>
      </Col>

      <Col xs={24} lg={8}>
        <Card
          className="enterprise-card"
          title={<span className="card-title-text"><InfoCircleOutlined style={{ color: "#0284c7" }} /> 流水线协同架构</span>}
        >
          <Paragraph style={{ fontSize: 13, color: "#475569", lineHeight: 1.7 }}>
            平台基于工业级 RAG 与多 Agent 协同体系构建，全流程实施严密事实溯源：
          </Paragraph>
          <ul style={{ paddingLeft: 18, fontSize: 12.5, color: "#475569", lineHeight: 2 }}>
            <li><strong>数据底座</strong>：SEC EDGAR 财报、arXiv 预印本、科技新闻。</li>
            <li><strong>混合检索</strong>：BM25 关键词匹配 + 向量相似度 + RRF 融合重排。</li>
            <li><strong>研究 Agent</strong>：通过 CodeAgent 调度知识库与计算工具自主成稿。</li>
            <li><strong>质检 Agent</strong>：执行事实一致性检验，对存疑论断触发多轮修订。</li>
          </ul>
        </Card>
      </Col>
    </Row>
  );
}
