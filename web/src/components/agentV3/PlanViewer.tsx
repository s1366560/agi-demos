import React from "react";
import { Steps, Typography, Badge, Empty } from "antd";
import { LoadingOutlined, CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import { WorkPlan } from "../../types/agent";

const { Title, Text } = Typography;

interface PlanViewerProps {
  plan: WorkPlan | null;
}

export const PlanViewer: React.FC<PlanViewerProps> = ({ plan }) => {
  if (!plan) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-8 text-slate-400">
        <Empty description="No active plan" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        <p className="text-xs mt-2 text-center">Switch to Plan Mode or ask the agent to create a plan.</p>
      </div>
    );
  }

  const getStepStatus = (index: number) => {
    if (index < plan.current_step_index) return "finish";
    if (index === plan.current_step_index) return plan.status === "failed" ? "error" : "process";
    return "wait";
  };

  const getStepIcon = (index: number) => {
    const status = getStepStatus(index);
    switch (status) {
      case "finish": return <CheckCircleOutlined className="text-emerald-500" />;
      case "process": return <LoadingOutlined className="text-blue-500" />;
      case "error": return <CloseCircleOutlined className="text-red-500" />;
      default: return <ClockCircleOutlined className="text-slate-300" />;
    }
  };

  return (
    <div className="h-full flex flex-col bg-slate-50 border-l border-slate-200">
      <div className="p-4 border-b border-slate-200 bg-white">
        <div className="flex items-center justify-between mb-1">
          <Title level={5} className="!m-0">Work Plan</Title>
          <Badge status={plan.status === 'completed' ? 'success' : 'processing'} text={plan.status} />
        </div>
        <Text type="secondary" className="text-xs">ID: {plan.id.slice(0, 8)}</Text>
      </div>

      <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
        <Steps
          direction="vertical"
          current={plan.current_step_index}
          items={plan.steps.map((step, index) => ({
            key: step.step_number,
            title: (
              <span className={index === plan.current_step_index ? "font-semibold text-blue-600" : ""}>
                Step {step.step_number}
              </span>
            ),
            description: (
              <div className="mt-1">
                <p className="text-sm text-slate-700">{step.description}</p>
                {step.expected_output && (
                  <div className="mt-2 p-2 bg-white rounded border border-slate-100">
                    <Text type="secondary" className="text-xs uppercase font-bold block mb-1">Goal</Text>
                    <Text className="text-xs text-slate-500">{step.expected_output}</Text>
                  </div>
                )}
              </div>
            ),
            icon: getStepIcon(index),
            status: getStepStatus(index) as any,
          }))}
        />
      </div>
    </div>
  );
};
