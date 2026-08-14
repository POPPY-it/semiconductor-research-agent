import { useCallback, useEffect, useState } from "react";
import { Button, Card, Table, Tag } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { listSessions, SessionSummary } from "../api";

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  queued: { color: "default", text: "排队中" },
  running: { color: "processing", text: "生成中" },
  done: { color: "success", text: "已完成" },
  error: { color: "error", text: "失败" },
};

const TYPE_TEXT: Record<string, string> = {
  daily: "日报",
  weekly: "周报",
  deep: "深度研报",
};

export default function SessionsList({
  onOpen,
}: {
  onOpen: (id: number) => void;
}) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listSessions();
      setSessions(res.sessions);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <Card
      title="会话历史"
      extra={
        <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
          刷新
        </Button>
      }
    >
      <Table<SessionSummary>
        rowKey="id"
        dataSource={sessions}
        loading={loading}
        size="middle"
        pagination={{ pageSize: 10 }}
        onRow={(record) => ({
          onClick: () => onOpen(record.id),
          style: { cursor: "pointer" },
        })}
        columns={[
          { title: "ID", dataIndex: "id", width: 70 },
          { title: "选题", dataIndex: "topic", ellipsis: true },
          {
            title: "类型",
            dataIndex: "report_type",
            width: 100,
            render: (t: string) => TYPE_TEXT[t] ?? t,
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 100,
            render: (s: string) => {
              const st = STATUS_TAG[s] ?? STATUS_TAG.error;
              return <Tag color={st.color}>{st.text}</Tag>;
            },
          },
          { title: "创建时间", dataIndex: "created_at", width: 170 },
        ]}
      />
    </Card>
  );
}
