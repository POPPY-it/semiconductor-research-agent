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
  message,
} from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getReportMd,
  getSession,
  retrySession,
  streamEvents,
  SessionDetail as SessionDetailType,
} from "../api";

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  queued: { color: "default", text: "排队中" },
  running: { color: "processing", text: "生成中" },
  done: { color: "success", text: "已完成" },
  error: { color: "error", text: "失败" },
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
  const [events, setEvents] = useState<{ type: string; msg: string }[]>([]);
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
              ? `报告生成完成：${data?.report_path ?? ""}`
              : type === "error"
              ? `任务失败：${data?.message ?? ""}`
              : type;
          setEvents((prev) => [...prev, { type, msg }]);
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
      message.success("已重新入队");
      setEvents([]);
      setReportMd("");
      setReloadKey((k) => k + 1);
    } catch (e) {
      message.error(String(e));
    }
  };

  const st = session ? STATUS_TAG[session.status] ?? STATUS_TAG.error : null;
  const current =
    events.length > 0 && (session?.status === "running" || session?.status === "queued")
      ? events.length
      : session?.status === "done"
      ? events.length + 1
      : 0;

  return (
    <Card
      title={
        <span>
          {onBack && (
            <a onClick={onBack} style={{ marginRight: 12 }}>
              ← 返回列表
            </a>
          )}
          会话 #{id} · {session?.topic ?? "..."}
          {st && <Tag color={st.color} style={{ marginLeft: 8 }}>{st.text}</Tag>}
        </span>
      }
    >
      {loading ? (
        <Skeleton active />
      ) : (
        <>
          {(session?.status === "queued" || session?.status === "running") && (
            <Steps
              current={current}
              size="small"
              items={[
                { title: "任务入队" },
                { title: "知识库检索" },
                { title: "研究 Agent 撰写" },
                { title: "质检与修订" },
                { title: "交付" },
              ]}
              style={{ marginBottom: 16 }}
            />
          )}
          {events.length > 0 && (
            <Alert
              type="info"
              style={{ marginBottom: 16 }}
              message="执行动态"
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {events.map((e, i) => (
                    <li key={i}>
                      <Tag>{e.type}</Tag>
                      {e.msg}
                    </li>
                  ))}
                </ul>
              }
            />
          )}
          {session?.status === "error" && (
            <Alert
              type="error"
              message="任务失败"
              description={events.at(-1)?.msg}
              action={
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  onClick={onRetry}
                >
                  重试
                </Button>
              }
            />
          )}
          {session?.status === "done" && session.report && (
            <Alert
              type={session.report.verdict.passed ? "success" : "warning"}
              style={{ marginBottom: 16 }}
              message={`质检结论：${session.report.verdict.passed ? "通过" : "未通过（已附问题清单）"}，修订 ${session.report.revision_rounds} 轮`}
              description={
                session.report.verdict.issues.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {session.report.verdict.issues.map((iss, i) => (
                      <li key={i}>{iss}</li>
                    ))}
                  </ul>
                ) : undefined
              }
            />
          )}
          {session?.status === "done" && (
            <Typography.Title level={5} style={{ marginTop: 8 }}>
              研报正文
            </Typography.Title>
          )}
          {session?.status === "done" && reportMd ? (
            <div className="report-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{reportMd}</ReactMarkdown>
            </div>
          ) : session?.status === "done" ? (
            <Empty description="报告为空" />
          ) : null}
        </>
      )}
    </Card>
  );
}
