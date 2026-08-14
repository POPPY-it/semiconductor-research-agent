import { useState } from "react";
import { Button, Card, Form, Input, Radio, message } from "antd";
import { SendOutlined } from "@ant-design/icons";
import { createSession } from "../api";

export default function NewTask({ onCreate }: { onCreate: (id: number) => void }) {
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: { topic: string; report_type: string }) => {
    setLoading(true);
    try {
      const res = await createSession(values.topic, values.report_type);
      message.success(`任务已创建（会话 #${res.session_id}），开始生成...`);
      onCreate(res.session_id);
    } catch (e) {
      message.error(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card title="新建研报任务" style={{ maxWidth: 640 }}>
      <Form
        layout="vertical"
        onFinish={onFinish}
        initialValues={{ report_type: "daily" }}
      >
        <Form.Item
          label="选题"
          name="topic"
          rules={[{ required: true, min: 4, message: "选题至少 4 个字" }]}
        >
          <Input.TextArea
            rows={3}
            placeholder="例如：半导体行业日报：今日重点动态（聚焦台积电 2nm 与存储芯片价格）"
          />
        </Form.Item>
        <Form.Item label="报告类型" name="report_type">
          <Radio.Group>
            <Radio.Button value="daily">日报</Radio.Button>
            <Radio.Button value="weekly">周报</Radio.Button>
            <Radio.Button value="deep">深度研报</Radio.Button>
            <Radio.Button value="survey">学术调研</Radio.Button>
          </Radio.Group>
        </Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          icon={<SendOutlined />}
          loading={loading}
        >
          生成研报（约 3~5 分钟）
        </Button>
      </Form>
    </Card>
  );
}
