import { useCallback, useEffect, useState } from "react";
import { Button, Card, Table, Tag, Typography, Space, Input } from "antd";
import {
  ReloadOutlined,
  SearchOutlined,
  FileTextOutlined,
  CalendarOutlined,
  BookOutlined,
  CompassOutlined,
  RightOutlined
} from "@ant-design/icons";
import { listSessions, SessionSummary } from "../api";

const { Text } = Typography;

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  queued: { color: "default", text: "排队中" },
  running: { color: "processing", text: "生成中" },
  done: { color: "success", text: "已完成" },
  error: { color: "error", text: "异常" },
};

const TYPE_CONFIG: Record<string, { text: string; color: string; icon: React.ReactNode }> = {
  daily: { text: "行业日报", color: "gold", icon: <FileTextOutlined /> },
  weekly: { text: "行业周报", color: "blue", icon: <CalendarOutlined /> },
  deep: { text: "深度研报", color: "purple", icon: <BookOutlined /> },
  survey: { text: "学术调研", color: "cyan", icon: <CompassOutlined /> },
};

export default function SessionsList({
  onOpen,
}: {
  onOpen: (id: number) => void;
}) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchKw, setSearchKw] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listSessions(50);
      setSessions(res.sessions);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const filtered = sessions.filter(s =>
    !searchKw || s.topic.toLowerCase().includes(searchKw.toLowerCase()) || String(s.id).includes(searchKw)
  );

  return (
    <Card
      className="enterprise-card"
      title={
        <div className="card-header-flex">
          <span className="card-title-text">
            <FileTextOutlined style={{ color: "#2563eb" }} /> 历史会话与已交付研报
          </span>
          <Space>
            <Input
              prefix={<SearchOutlined style={{ color: "#94a3b8" }} />}
              placeholder="搜索选题或编号..."
              size="middle"
              allowClear
              value={searchKw}
              onChange={e => setSearchKw(e.target.value)}
              style={{ width: 220, borderRadius: 6 }}
            />
            <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
              刷新列表
            </Button>
          </Space>
        </div>
      }
    >
      <Table<SessionSummary>
        rowKey="id"
        dataSource={filtered}
        loading={loading}
        size="middle"
        pagination={{ pageSize: 8, showTotal: (total) => `共计 ${total} 份历史研报记录` }}
        onRow={(record) => ({
          onClick: () => onOpen(record.id),
          style: { cursor: "pointer" },
        })}
        columns={[
          {
            title: "编号",
            dataIndex: "id",
            width: 80,
            render: (id) => <Text strong style={{ color: "#64748b" }}>#{id}</Text>,
          },
          {
            title: "研报选题与研究方向",
            dataIndex: "topic",
            render: (text) => (
              <span style={{ fontWeight: 500, color: "#1e293b" }}>{text}</span>
            ),
          },
          {
            title: "类型",
            dataIndex: "report_type",
            width: 130,
            render: (t: string) => {
              const conf = TYPE_CONFIG[t] || { text: t, color: "default", icon: null };
              return (
                <Tag color={conf.color} icon={conf.icon}>
                  {conf.text}
                </Tag>
              );
            },
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 110,
            render: (s: string) => {
              const st = STATUS_TAG[s] ?? STATUS_TAG.error;
              return <Tag color={st.color} style={{ borderRadius: 10 }}>{st.text}</Tag>;
            },
          },
          {
            title: "创建时间",
            dataIndex: "created_at",
            width: 180,
            render: (time) => <Text type="secondary" style={{ fontSize: 13 }}>{time}</Text>,
          },
          {
            title: "操作",
            key: "action",
            width: 90,
            render: () => (
              <Button type="link" size="small" style={{ padding: 0 }}>
                查看 <RightOutlined style={{ fontSize: 10 }} />
              </Button>
            ),
          },
        ]}
      />
    </Card>
  );
}
