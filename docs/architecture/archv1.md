---
config:
  theme: base
  themeVariables:
    primaryColor: "#4f46e5"
    primaryTextColor: "#fff"
    primaryBorderColor: "#4f46e5"
    lineColor: "#64748b"
    secondaryColor: "#f0abfc"
    tertiaryColor: "#fef3c7"
    fontFamily: arial
  layout: fixed
---

flowchart TB
subgraph Brain["🧠 核心决策引擎"]
PatternMatcher["🔍 模式匹配<br>(Pattern Matcher)"]
Planner["📝 多层规划器<br>(Task Planner)"]
Observer["👀 观察与反思<br>(Observation &amp; Reflexion)"]
end
subgraph Evolution["🧬 进化与学习闭环"]
TraceLog["📜 执行轨迹日志"]
Learner["🎓 WorkflowLearner<br>(模式提取器)"]
PatternStore[("🧠 经验模式库<br>(Interaction Patterns)")]
end
subgraph L4_Layer["🤖 L4: ReAct Agent (智能体层)"]
direction TB
Input(("用户指令"))
Brain
Evolution
end
subgraph Specialists["专职智能体"]
SA_Mem["🧠 Memory Explorer<br>(记忆专家)"]
SA_Web["🌐 Web Researcher<br>(网络研究员)"]
SA_Data["📊 Data Analyst<br>(数据分析师)"]
end
subgraph L3_Layer["👥 L3: SubAgent (子智能体层)"]
direction TB
Router["🚦 智能路由器<br>(SubAgent Router)"]
Specialists
end
subgraph SkillSets["声明式技能包 (Markdown)"]
S_Market["📈 市场调研技能"]
S_Report["📝 报告生成技能"]
S_Graph["🕸️ 图谱深度查询"]
end
subgraph L2_Layer["📚 L2: Skills (技能层)"]
direction TB
SkillExec["⚙️ 技能执行器"]
SkillSets
end
subgraph NativeTools["💎 内置原子工具"]
T_MemSearch["memory_search"]
T_GraphQuery["graph_query"]
T_Web["web_search"]
end
subgraph MCP_Integration["🔌 MCP 扩展协议"]
MCP_Client["MCP Client"]
MCP_Servers["☁️ 外部 MCP Servers<br>(Filesystem, GitHub, Slack...)"]
end
subgraph L1_Layer["🔧 L1: Tools (工具层)"]
direction TB
ToolGate["🛡️ 权限与成本网关"]
NativeTools
MCP_Integration
end
Input --> PatternMatcher
PatternMatcher -- 检索最佳实践 --> Planner
Planner -- 生成执行计划 --> Observer
Observer -. 记录轨迹 .-> TraceLog
TraceLog -- 异步分析 --> Learner
Learner -- 提炼成功模式 --> PatternStore
PatternStore -. 增强决策 .-> PatternMatcher
Observer -- 分发任务 --> Router
Router --> SA_Mem & SA_Web & SA_Data
Specialists -- 调用能力组合 --> SkillExec
SkillExec --o S_Market & S_Report & S_Graph
SkillExec -- 原子调用 --> ToolGate
ToolGate --> NativeTools & MCP_Client
MCP_Client <== 标准协议 ==> MCP_Servers
NativeTools -- 执行结果 --> Observer
MCP_Client -- 外部数据 --> Observer

     PatternMatcher:::agentLayer
     Planner:::agentLayer
     Observer:::agentLayer
     TraceLog:::learnLayer
     Learner:::learnLayer
     PatternStore:::storeLayer
     SA_Mem:::subAgentLayer
     SA_Web:::subAgentLayer
     SA_Data:::subAgentLayer
     Router:::subAgentLayer
     S_Market:::skillLayer
     S_Report:::skillLayer
     S_Graph:::skillLayer
     SkillExec:::skillLayer
     T_MemSearch:::toolLayer
     T_GraphQuery:::toolLayer
     T_Web:::toolLayer
     MCP_Client:::toolLayer
     MCP_Servers:::mcp
     ToolGate:::toolLayer
     NativeTools:::toolLayer
    classDef agentLayer fill:#eff6ff,stroke:#2563eb,stroke-width:2px,color:#1e3a8a
    classDef subAgentLayer fill:#f3e8ff,stroke:#9333ea,stroke-width:2px,color:#581c87
    classDef skillLayer fill:#fef9c3,stroke:#ca8a04,stroke-width:2px,color:#713f12
    classDef toolLayer fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#064e3b
    classDef learnLayer fill:#fff1f2,stroke:#e11d48,stroke-width:2px,stroke-dasharray: 5 5,color:#881337
    classDef storeLayer fill:#f1f5f9,stroke:#475569,stroke-width:1px,color:#0f172a
    classDef mcp fill:#0f172a,stroke:#000,stroke-width:2px,color:#fff
