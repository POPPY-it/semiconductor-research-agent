import { useEffect, useState } from "react";
import { Tabs, message, Tag, Tooltip } from "antd";
import {
  FileTextOutlined,
  PlusCircleOutlined,
  SearchOutlined,
  HistoryOutlined,
  ApiOutlined,
  CheckCircleFilled,
  SafetyCertificateOutlined
} from "@ant-design/icons";
import NewTask from "./pages/NewTask";
import SessionsList from "./pages/SessionsList";
import SessionDetail from "./pages/SessionDetail";
import QaPanel from "./pages/QaPanel";
import { login } from "./api";

export default function App() {
  const [tab, setTab] = useState("qa");
  const [openId, setOpenId] = useState<number | null>(null);
  const [listTab, setListTab] = useState("list");

  useEffect(() => {
    login().catch(() => message.warning("认证会话初始化失败，请检查 API Token 配置"));
  }, []);

  const openSession = (id: number) => {
    setOpenId(id);
    setListTab("detail");
    setTab("sessions");
  };

  return (
    <div className="app-container">
      <header className="app-navbar">
        <div className="brand-section">
          <div className="brand-logo-icon">
            <ApiOutlined />
          </div>
          <div>
            <div className="brand-title">
              半导体研究 Agent
              <Tag color="blue" style={{ fontSize: 11, padding: "0 6px", height: 20, lineHeight: "18px", border: "none", fontWeight: 600 }}>
                Enterprise v0.3.0
              </Tag>
            </div>
            <div className="brand-subtitle">
              Semiconductor Research Agent · 检索 + 规划 + 质检
            </div>
          </div>
        </div>

        <div className="navbar-badges">
          <div className="env-pill">
            <span className="status-dot"></span>
            <span>SEC EDGAR + arXiv 知识引擎就绪</span>
          </div>
          <Tooltip title="基于 smolagents CodeAgent + 事实质检编排引擎">
            <div className="env-pill" style={{ cursor: "pointer" }}>
              <SafetyCertificateOutlined style={{ color: "#38bdf8" }} />
              <span>Multi-Agent QA</span>
            </div>
          </Tooltip>
        </div>
      </header>

      <main className="app-main-content">
        <Tabs
          className="custom-main-tabs"
          activeKey={tab}
          onChange={setTab}
          size="middle"
          items={[
            {
              key: "qa",
              label: (
                <span>
                  <SearchOutlined /> 智能数据问答
                </span>
              ),
              children: <QaPanel />,
            },
            {
              key: "new",
              label: (
                <span>
                  <PlusCircleOutlined /> 新建研报任务
                </span>
              ),
              children: <NewTask onCreate={openSession} />,
            },
            {
              key: "sessions",
              label: (
                <span>
                  <HistoryOutlined /> 研报中心与历史
                </span>
              ),
              children:
                listTab === "list" ? (
                  <SessionsList onOpen={openSession} />
                ) : (
                  <SessionDetail id={openId!} onBack={() => setListTab("list")} />
                ),
            },
          ]}
        />
      </main>

      <footer className="app-footer">
        半导体行业研报与学术调研 Agent &copy; 2026 &middot; 具备自建数据管道、混合检索与事实质检的高可信研究平台
      </footer>
    </div>
  );
}
