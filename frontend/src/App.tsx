import { useEffect, useState } from "react";
import { Tabs, message } from "antd";
import {
  FileTextOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
} from "@ant-design/icons";
import NewTask from "./pages/NewTask";
import SessionsList from "./pages/SessionsList";
import SessionDetail from "./pages/SessionDetail";
import QaPanel from "./pages/QaPanel";
import { login } from "./api";

export default function App() {
  const [tab, setTab] = useState("new");
  const [openId, setOpenId] = useState<number | null>(null);
  const [listTab, setListTab] = useState("list");

  // 登录换取 HttpOnly Cookie（后续请求含 SSE 均自动携带）
  useEffect(() => {
    login().catch(() => message.warning("登录失败，请检查 API token 配置"));
  }, []);

  const openSession = (id: number) => {
    setOpenId(id);
    setListTab("detail");
    setTab("sessions");
  };

  return (
    <div>
      <div className="app-header">
        <FileTextOutlined />
        半导体行业研报 Agent
      </div>
      <div className="app-content">
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            {
              key: "qa",
              label: (
                <span>
                  <QuestionCircleOutlined /> 数据问答
                </span>
              ),
              children: <QaPanel />,
            },
            {
              key: "new",
              label: (
                <span>
                  <PlusOutlined /> 新建任务
                </span>
              ),
              children: <NewTask onCreate={openSession} />,
            },
            {
              key: "sessions",
              label: "会话与报告",
              children:
                listTab === "list" ? (
                  <SessionsList onOpen={openSession} />
                ) : (
                  <SessionDetail id={openId!} onBack={() => setListTab("list")} />
                ),
            },
          ]}
        />
      </div>
    </div>
  );
}
