import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Skeleton,
  Steps,
  Tag,
  Typography,
  Space,
  Tooltip,
  message,
} from "antd";
import {
  ReloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  FileDoneOutlined,
  ArrowLeftOutlined,
  CodeOutlined,
  ClockCircleOutlined,
  ShareAltOutlined,
  CopyOutlined
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getReportMd,
  getSession,
  retrySession,
  streamEvents,
  SessionDetail as SessionDetailType,
} from "../api";

const { Title, Text, Paragraph } = Typography;

const STATUS_TAG: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
  queued: { color: "default", text: "排队中", icon: <ClockCircleOutlined /> },
  running: { color: "processing", text: "多 Agent 协同中", icon: <ReloadOutlined spin /> },
  done: { color: "success", text: "报告已交付", icon: <CheckCircleOutlined /> },
  error: { color: "error", text: "执行异常", icon: <CloseCircleOutlined /> },
};

const TYPE_NAME: Record<string, string> = {
  daily: "行业日报",
  weekly: "行业周报",
  deep: "深度研报",
  survey: "学术文献调研",
};

export default function SessionDetail({
  id,
  onBack,
}: {
  id: number;
  onBack?: () => void;
}) {
  const [session, setSession] = useState<SessionDetailType | null>(null);
  const [reportMd, setReportMd] = useState("");
  const [events, setEvents] = useState<{ type: string; msg: string; time: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let cancelled = false;

    const refresh = async () => {
      try {
        const s = await getSession(id);
        if (cancelled) return;
        setSession(s);
        if (s.status === "done") {
          const r = await getReportMd(id);
          if (!cancelled) setReportMd(r.report_md);
        }
      } catch {
        /* 忽略单次轮询失败 */
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    const attachStream = () => {
      esRef.current = streamEvents(id, {
        onEvent: (type, data) => {
          const msg =
            type === "phase" && data?.msg
              ? data.msg
              : type === "done"
              ? `研报产出完成并保存至：${data?.report_path ?? ""}`
              : type === "error"
              ? `流水线异常中断：${data?.message ?? ""}`
              : JSON.stringify(data);
          const time = new Date().toLocaleTimeString();
          setEvents((prev) => [...prev, { type, msg, time }]);
        },
        onEnd: () => refresh(),
      });
    };

    (async () => {
      const s = await getSession(id);
      if (cancelled) return;
      setSession(s);
      setLoading(false);
      if (s.status === "queued" || s.status === "running") {
        attachStream();
      } else if (s.status === "done") {
        const r = await getReportMd(id);
        if (!cancelled) setReportMd(r.report_md);
      }
    })();

    return () => {
      cancelled = true;
      esRef.current?.close();
    };
  }, [id, reloadKey]);

  const onRetry = async () => {
    try {
      await retrySession(id);
      message.success("任务已重新提交调度队列");
      setEvents([]);
      setReportMd("");
      setReloadKey((k) => k + 1);
    } catch (e) {
      message.error(String(e));
    }
  };

  const copyReport = () => {
    if (!reportMd) return;
    navigator.clipboard.writeText(reportMd);
    message.success("报告 Markdown 内容已复制至剪贴板");
  };

  const st = session ? STATUS_TAG[session.status] ?? STATUS_TAG.error : null;
  const currentStep =
    events.length > 0 && (session?.status === "running" || session?.status === "queued")
      ? Math.min(events.length, 3)
      : session?.status === "done"
      ? 4
      : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <Card
        className="enterprise-card"
        title={
          <div className="card-header-flex">
            <Space align="center" size={12}>
              {onBack && (
                <Button icon={<ArrowLeftOutlined />} size="small" onClick={onBack}>
                  返回列表
                </Button>
              )}
              <Text strong style={{ fontSize: 16 }}>
                会话 #{id}：{session?.topic ?? "加载中..."}
              </Text>
              <Tag color="geekblue">{TYPE_NAME[session?.report_type || ""] || session?.report_type}</Tag>
              {st && (
                <Tag color={st.color} icon={st.icon} style={{ borderRadius: 12, padding: "1px 10px" }}>
                  {st.text}
                </Tag>
              )}
            </Space>

            {session?.status === "done" && (
              <Space>
                <Tooltip title="复制 Markdown 全文">
                  <Button icon={<CopyOutlined />} size="small" onClick={copyReport}>
                    复制正文
                  </Button>
                </Tooltip>
              </Space>
            )}
          </div>
        }
      >
        {loading ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : (
          <>
            {(session?.status === "queued" || session?.status === "running") && (
              <div style={{ background: "#f8fafc", padding: "18px 24px", borderRadius: 8, marginBottom: 20, border: "1px solid #e2e8f0" }}>
                <Steps
                  current={currentStep}
                  size="small"
                  items={[
                    { title: "任务入队", description: "建立会话环境" },
                    { title: "知识检索", description: "混合多路召回" },
                    { title: "研究协同", description: "CodeAgent 自主撰写" },
                    { title: "事实质检", description: "多轮校验修订" },
                    { title: "交付报告", description: "持久化落盘" },
                  ]}
                />
              </div>
            )}

            {events.length > 0 && (
              <div className="log-terminal-container">
                <div className="log-terminal-header">
                  <span>
                    <CodeOutlined style={{ marginRight: 6 }} /> 实时 Agent 调度与执行控制台
                  </span>
                  <span>SSE Stream Monitor</span>
                </div>
                {events.map((e, i) => (
                  <div key={i} className="log-terminal-row">
                    <span style={{ color: "#64748b", fontSize: 11 }}>[{e.time}]</span>
                    <span className={`log-event-tag tag-${e.type}`}>{e.type.toUpperCase()}</span>
                    <span>{e.msg}</span>
                  </div>
                ))}
              </div>
            )}

            {session?.status === "error" && (
              <Alert
                type="error"
                showIcon
                message="流水线执行异常"
                description={events.at(-1)?.msg || "未知执行错误，请检查后端运行状态或重试。"}
                action={
                  <Button size="small" type="primary" danger icon={<ReloadOutlined />} onClick={onRetry}>
                    重新执行任务
                  </Button>
                }
                style={{ marginBottom: 20 }}
              />
            )}

            {session?.status === "done" && session.report && (
              <Alert
                type={session.report.verdict?.passed ? "success" : "warning"}
                showIcon
                icon={session.report.verdict?.passed ? <CheckCircleOutlined /> : <ExclamationCircleOutlined />}
                style={{ marginBottom: 24, borderRadius: 8 }}
                message={
                  <div style={{ fontWeight: 600, fontSize: 14 }}>
                    质检核验状态：{session.report.verdict?.passed ? "全面通过 (100% 来源核实)" : "存疑警告 (部分论断缺少直接溯源)"}
                    <span style={{ fontWeight: "normal", fontSize: 12, color: "#64748b", marginLeft: 12 }}>
                      (经过 {session.report.revision_rounds} 轮迭代修订)
                    </span>
                  </div>
                }
                description={
                  session.report.verdict?.issues?.length > 0 ? (
                    <div style={{ marginTop: 8 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>质检 Agent 标记存疑事项：</Text>
                      <ul style={{ margin: "4px 0 0 0", paddingLeft: 18, color: "#475569", fontSize: 12.5 }}>
                        {session.report.verdict.issues.map((iss, i) => (
                          <li key={i}>{iss}</li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      所有核心数据指标与技术论断均已由质检 Agent 在 SEC 财报及官方文献库中完成双向闭环核实。
                    </Text>
                  )
                }
              />
            )}

            {session?.status === "done" && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <Title level={4} style={{ margin: 0 }}>
                    <FileDoneOutlined style={{ marginRight: 8, color: "#2563eb" }} />
                    研报交付正文
                  </Title>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    生成时间: {session.report?.created_at || session.finished_at}
                  </Text>
                </div>

                {reportMd ? (
                  <div className="report-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{reportMd}</ReactMarkdown>
                  </div>
                ) : (
                  <Empty description="未能加载研报正文" />
                )}
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
