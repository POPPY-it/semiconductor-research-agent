import { useState } from "react";
import { Tabs } from "antd";
import { FileTextOutlined, PlusOutlined } from "@ant-design/icons";
import NewTask from "./pages/NewTask";
import SessionsList from "./pages/SessionsList";
import SessionDetail from "./pages/SessionDetail";

export default function App() {
  const [tab, setTab] = useState("new");
  const [openId, setOpenId] = useState<number | null>(null);
  const [listTab, setListTab] = useState("list");

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
