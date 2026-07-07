import { useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  Archive,
  Box,
  Brain,
  Check,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Circle,
  Cpu,
  Database,
  FileDiff,
  FileText,
  FolderOpen,
  GitBranch,
  History,
  LayoutGrid,
  List,
  MessageSquare,
  Minus,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  Shield,
  SlidersHorizontal,
  Square,
  Terminal,
  Wrench,
  X,
  XCircle,
} from "lucide-react";

const navItems = [
  { label: "Runs", icon: Circle },
  { label: "Agents", icon: UsersIcon },
  { label: "Memory", icon: Database },
  { label: "Artifacts", icon: FileText },
  { label: "Runtime", icon: Cpu },
];

const runs = [
  { id: 42, status: "Running", time: "00:18:42", tone: "green" },
  { id: 41, status: "Completed", time: "00:27:11", tone: "amber" },
  { id: 40, status: "Completed", time: "00:15:09", tone: "green" },
  { id: 39, status: "Failed", time: "00:08:33", tone: "red" },
  { id: 38, status: "Completed", time: "00:19:52", tone: "green" },
  { id: 37, status: "Completed", time: "00:12:01", tone: "amber" },
];

const lanes = [
  {
    name: "Planner",
    state: "Active",
    icon: GitBranch,
    tone: "green",
    tasks: [
      { label: "Plan", left: 13, width: 11, tone: "green" },
      { label: "Decompose", left: 29, width: 13, tone: "green" },
      { label: "Assign", left: 45, width: 11, tone: "green" },
      { label: "Replan", left: 62, width: 13, tone: "green" },
    ],
  },
  {
    name: "Researcher",
    state: "Active",
    icon: Search,
    tone: "green",
    tasks: [
      { label: "Search docs", left: 21, width: 13, tone: "green" },
      { label: "Collect context", left: 40, width: 16, tone: "green" },
      { label: "Synthesize", left: 67, width: 16, tone: "green" },
    ],
  },
  {
    name: "Executor",
    state: "Working",
    icon: Terminal,
    tone: "amber",
    tasks: [
      { label: "Checkout repo", left: 19, width: 11, tone: "amber" },
      { label: "Apply patch", left: 33, width: 18, tone: "amber", dashed: true },
      { label: "Run tests", left: 55, width: 14, tone: "amber" },
      { label: "Build", left: 71, width: 14, tone: "amber" },
    ],
  },
  {
    name: "Verifier",
    state: "Idle",
    icon: Shield,
    tone: "slate",
    tasks: [
      { label: "Queue (2)", left: 11, width: 16, tone: "slate" },
      { label: "Static analysis", left: 30, width: 15, tone: "slate" },
      { label: "Test verify", left: 52, width: 15, tone: "slate" },
      { label: "Report", left: 78, width: 14, tone: "slate" },
    ],
  },
];

const baseEvents = [
  {
    time: "00:18:40",
    kind: "tool.call",
    source: "executor.apply_patch",
    status: "Success",
    detail: "Modified 2 files",
    latency: "412 ms",
    type: "Tools",
  },
  {
    time: "00:18:38",
    kind: "reasoning",
    source: "Executor",
    status: "",
    detail: "Patch applied cleanly. Next: run unit tests to validate...",
    latency: "",
    type: "Reasoning",
  },
  {
    time: "00:18:32",
    kind: "tool.call",
    source: "filesystem.write",
    status: "Success",
    detail: "src/engine/runner.rs",
    latency: "98 ms",
    type: "Tools",
  },
  {
    time: "00:18:31",
    kind: "reasoning",
    source: "Executor",
    status: "",
    detail: "Implement retry with exponential backoff for transient...",
    latency: "",
    type: "Reasoning",
  },
  {
    time: "00:18:28",
    kind: "tool.call",
    source: "git.diff",
    status: "Success",
    detail: "2 files",
    latency: "77 ms",
    type: "Tools",
  },
  {
    time: "00:18:25",
    kind: "message",
    source: "Planner",
    status: "",
    detail: "Consider edge cases for cancellation and timeouts.",
    latency: "",
    type: "Messages",
  },
];

const artifacts = [
  {
    name: "0002-retry-backoff.patch",
    type: "Patch",
    path: "patches/0002-retry-backoff.patch",
    diff: "+45 / -12",
    time: "00:18:40",
    size: "2.1 KB",
    preview: "+ for attempt in 0..max_retries {\n- client.send(req).await?\n+ jitter.sleep(attempt).await",
  },
  {
    name: "runner.rs",
    type: "File",
    path: "src/engine/runner.rs",
    diff: "",
    time: "00:18:32",
    size: "8.7 KB",
    preview: "pub async fn run(&self) -> Result<()> {\n  let mut attempt: u32 = 0;",
  },
  {
    name: "test_retry.rs",
    type: "File",
    path: "tests/integration/test_retry.rs",
    diff: "",
    time: "00:18:10",
    size: "3.2 KB",
    preview: "#[tokio::test]\nasync fn test_retry_succeeds() {",
  },
  {
    name: "run-report.md",
    type: "Report",
    path: "reports/run-42.md",
    diff: "",
    time: "00:17:55",
    size: "12.4 KB",
    preview: "## Summary\nAll checks passed. 2 files changed.",
  },
];

function UsersIcon(props) {
  return <Activity {...props} />;
}

export function App() {
  const [selectedNav, setSelectedNav] = useState("Runs");
  const [selectedRun, setSelectedRun] = useState(42);
  const [runStatus, setRunStatus] = useState("Running");
  const [live, setLive] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const [eventFilter, setEventFilter] = useState("All");
  const [artifactFilter, setArtifactFilter] = useState("All");
  const [selectedArtifact, setSelectedArtifact] = useState("0002-retry-backoff.patch");
  const [decision, setDecision] = useState("pending");
  const [command, setCommand] = useState("");
  const [zoom, setZoom] = useState(100);
  const [viewMode, setViewMode] = useState("Timeline");
  const [customEvents, setCustomEvents] = useState([]);

  const events = useMemo(() => {
    const allEvents = [...customEvents, ...baseEvents];
    if (eventFilter === "All") return allEvents;
    return allEvents.filter((event) => event.type === eventFilter);
  }, [customEvents, eventFilter]);

  const visibleArtifacts = useMemo(() => {
    if (artifactFilter === "All") return artifacts;
    return artifacts.filter((artifact) => `${artifact.type}s` === artifactFilter);
  }, [artifactFilter]);

  function addEvent(kind, source, detail, type = "Messages") {
    setCustomEvents((current) => [
      {
        time: "now",
        kind,
        source,
        status: "",
        detail,
        latency: "",
        type,
      },
      ...current,
    ]);
  }

  function submitCommand(event) {
    event.preventDefault();
    const trimmed = command.trim();
    if (!trimmed) return;
    addEvent("message", "Operator", trimmed);
    setCommand("");
  }

  function approvePatch() {
    setDecision("approved");
    setRunStatus("Running");
    addEvent("decision", "Human decision", "Patch approved. Executor can continue the run.");
  }

  function requestChanges() {
    setDecision("changes");
    setRunStatus("Paused");
    addEvent("decision", "Human decision", "Requested changes. Executor is waiting for revision.");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Box size={22} strokeWidth={1.8} />
          <span>AGI Stack</span>
        </div>

        <nav className="nav-list" aria-label="Primary">
          {navItems.map((item) => (
            <button
              className={`nav-item ${selectedNav === item.label ? "active" : ""}`}
              key={item.label}
              type="button"
              onClick={() => setSelectedNav(item.label)}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="run-section">
          <div className="section-label">
            <span>Runs</span>
            <button
              aria-label="Create new run"
              className="icon-button"
              type="button"
              onClick={() => {
                setSelectedRun(43);
                setRunStatus("Planning");
                addEvent("message", "System", "New run #43 queued with local runtime.");
              }}
            >
              <Plus size={16} />
            </button>
          </div>
          <div className="run-list">
            {runs.map((run) => (
              <button
                className={`run-row ${selectedRun === run.id ? "selected" : ""}`}
                key={run.id}
                type="button"
                onClick={() => {
                  setSelectedRun(run.id);
                  setRunStatus(run.status);
                }}
              >
                <span className={`status-dot ${run.tone}`} />
                <span className="run-meta">
                  <strong>Run #{run.id}</strong>
                  <small>{selectedRun === run.id ? runStatus : run.status}</small>
                </span>
                <span className="run-time">{run.time}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="runtime-card">
          <div className="runtime-title">
            <strong>Local Rust Core</strong>
            <span className="healthy">Healthy</span>
          </div>
          <dl>
            <div>
              <dt>Version</dt>
              <dd>0.3.1</dd>
            </div>
            <div>
              <dt>Uptime</dt>
              <dd>2h 14m</dd>
            </div>
            <div>
              <dt>CPU</dt>
              <dd>18%</dd>
            </div>
            <div>
              <dt>Memory</dt>
              <dd>4.6 / 15.8 GB</dd>
            </div>
            <div>
              <dt>Workers</dt>
              <dd>8 / 16</dd>
            </div>
            <div>
              <dt>Queue</dt>
              <dd>3</dd>
            </div>
          </dl>
          <button className="secondary-button wide" type="button">
            Open Runtime Monitor
            <ChevronRight size={15} />
          </button>
        </div>

        <button className="profile" type="button">
          <span className="avatar">AO</span>
          <span>Alex Operator</span>
          <ChevronDown size={15} />
        </button>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Runs</span>
            <ChevronRight size={15} />
            <strong>Run #{selectedRun}</strong>
            <span className={`status-dot ${runStatus === "Failed" ? "red" : "green"}`} />
            <span>{runStatus}</span>
            <ClockLabel />
          </div>
          <div className="top-actions">
            <button
              className="control-button"
              type="button"
              onClick={() => setRunStatus(runStatus === "Paused" ? "Running" : "Paused")}
            >
              {runStatus === "Paused" ? <Play size={16} /> : <Pause size={16} />}
              {runStatus === "Paused" ? "Resume" : "Pause"}
            </button>
            <button
              className="control-button muted"
              type="button"
              onClick={() => setRunStatus("Running")}
            >
              <Play size={16} />
              Resume
            </button>
            <button className="control-button danger" type="button" onClick={() => setRunStatus("Stopped")}>
              <Square size={14} />
              Stop
            </button>
            <button className="icon-button bordered" type="button" aria-label="More run actions">
              <MoreHorizontal size={18} />
            </button>
            <label className="select-label">
              <span>Runtime</span>
              <select aria-label="Runtime">
                <option>Local Rust Core</option>
                <option>Remote staging</option>
              </select>
            </label>
            <div className="segmented">
              <button className={live ? "active" : ""} type="button" onClick={() => setLive(true)}>
                Live
              </button>
              <button className={!live ? "active" : ""} type="button" onClick={() => setLive(false)}>
                Offline
              </button>
            </div>
          </div>
        </header>

        <div className="content-grid">
          <section className="left-stack">
            <section className="panel timeline-panel" aria-label="Run graph">
              <div className="panel-toolbar">
                <label>
                  <span>Memory scope</span>
                  <select>
                    <option>Run #{selectedRun} (isolated)</option>
                    <option>Project memory</option>
                    <option>Tenant memory</option>
                  </select>
                </label>
                <label>
                  <span>Agent layout</span>
                  <div className="segmented compact">
                    <button type="button" className="active">
                      <List size={14} />
                    </button>
                    <button type="button">
                      <FolderOpen size={14} />
                    </button>
                    <button type="button">
                      <LayoutGrid size={14} />
                    </button>
                  </div>
                </label>
                <label>
                  <span>Zoom</span>
                  <div className="zoom-control">
                    <button type="button" onClick={() => setZoom(Math.max(70, zoom - 10))}>
                      <Minus size={14} />
                    </button>
                    <strong>{zoom}%</strong>
                    <button type="button" onClick={() => setZoom(Math.min(140, zoom + 10))}>
                      <Plus size={14} />
                    </button>
                  </div>
                </label>
                <label>
                  <span>View</span>
                  <select value={viewMode} onChange={(event) => setViewMode(event.target.value)}>
                    <option>Timeline</option>
                    <option>Swimlane</option>
                    <option>Compact</option>
                  </select>
                </label>
                <button className="icon-button bordered toolbar-tail" type="button" aria-label="Timeline settings">
                  <SlidersHorizontal size={17} />
                </button>
              </div>

              <div className="time-scale">
                <span>00:00</span>
                <span>00:05</span>
                <span>00:10</span>
                <span>00:15</span>
                <strong>00:18:42</strong>
                <span>00:25</span>
                <span>00:30</span>
              </div>

              <div className="lane-board" style={{ "--zoom": zoom / 100 }}>
                <div className="now-line" />
                {lanes.map((lane) => (
                  <div className="lane" key={lane.name}>
                    <div className="lane-label">
                      <lane.icon size={24} strokeWidth={1.7} />
                      <div>
                        <strong>{lane.name}</strong>
                        <span>
                          <i className={`status-dot ${lane.tone}`} />
                          {lane.state}
                        </span>
                      </div>
                    </div>
                    <div className="lane-track">
                      {lane.tasks.map((task) => (
                        <button
                          className={`task-pill ${task.tone} ${task.dashed ? "dashed" : ""}`}
                          key={`${lane.name}-${task.label}`}
                          style={{ left: `${task.left}%`, width: `${task.width}%` }}
                          type="button"
                          onClick={() => addEvent("selection", lane.name, `${task.label} selected in ${viewMode}.`)}
                        >
                          {task.tone === "green" ? <Check size={13} /> : null}
                          {task.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel events-panel" aria-label="Tool events">
              <div className="panel-title">
                <h2>Tool events</h2>
                <FilterTabs
                  active={eventFilter}
                  items={["All", "Tools", "Reasoning", "Messages", "System"]}
                  onChange={setEventFilter}
                />
                <label className="toggle-label">
                  <span>Auto-scroll</span>
                  <button
                    className={`switch ${autoScroll ? "on" : ""}`}
                    type="button"
                    aria-pressed={autoScroll}
                    onClick={() => setAutoScroll(!autoScroll)}
                  />
                </label>
                <button className="secondary-button" type="button" onClick={() => setCustomEvents([])}>
                  Clear
                </button>
              </div>
              <div className="event-list">
                {events.map((event, index) => (
                  <button className="event-row" key={`${event.time}-${event.kind}-${index}`} type="button">
                    <span className="event-time">{event.time}</span>
                    <EventIcon kind={event.kind} />
                    <strong>{event.kind}</strong>
                    <span className="event-source">{event.source}</span>
                    {event.status ? <span className="success-pill">{event.status}</span> : <span />}
                    <span className="event-detail">{event.detail}</span>
                    <span className="event-latency">{event.latency}</span>
                    <ChevronRight size={15} />
                  </button>
                ))}
              </div>
            </section>

            <section className="panel artifacts-panel" aria-label="Artifacts">
              <div className="panel-title">
                <h2>Artifacts</h2>
                <FilterTabs
                  active={artifactFilter}
                  items={["All", "Files", "Patches", "Reports", "Logs"]}
                  onChange={setArtifactFilter}
                />
                <label className="search-field">
                  <Search size={15} />
                  <input placeholder="Search artifacts..." />
                </label>
                <select className="small-select" aria-label="Artifact sort">
                  <option>Recent first</option>
                  <option>Largest first</option>
                </select>
                <button className="icon-button bordered" type="button" aria-label="Grid view">
                  <LayoutGrid size={16} />
                </button>
              </div>
              <div className="artifact-list">
                {visibleArtifacts.map((artifact) => (
                  <button
                    className={`artifact-row ${selectedArtifact === artifact.name ? "selected" : ""}`}
                    key={artifact.name}
                    type="button"
                    onClick={() => setSelectedArtifact(artifact.name)}
                  >
                    <ArtifactIcon type={artifact.type} />
                    <span className="artifact-name">
                      <strong>{artifact.name}</strong>
                      <small>{artifact.path}</small>
                    </span>
                    <span className="artifact-type">{artifact.type}</span>
                    <span className="artifact-diff">{artifact.diff}</span>
                    <span>{artifact.time}</span>
                    <span>{artifact.size}</span>
                    <code>{artifact.preview}</code>
                    <MoreHorizontal size={16} />
                  </button>
                ))}
              </div>
              <div className="panel-footer">
                <span>{visibleArtifacts.length} items</span>
                <span>Total 26.4 KB</span>
              </div>
            </section>
          </section>

          <DecisionDrawer
            decision={decision}
            onApprove={approvePatch}
            onRequestChanges={requestChanges}
            onReset={() => setDecision("pending")}
          />
        </div>
      </main>

      <form className="command-bar" onSubmit={submitCommand}>
        <button aria-label="Slash commands" className="slash-button" type="button">
          /
        </button>
        <input
          value={command}
          onChange={(event) => setCommand(event.target.value)}
          placeholder="Steer this run or start a new task..."
        />
        <select aria-label="Model">
          <option>OpenAI gpt-4o-mini</option>
          <option>Local qwen-coder</option>
        </select>
        <select aria-label="Runtime target">
          <option>Local Rust Core</option>
          <option>Staging Runtime</option>
        </select>
        <button className="send-button" type="submit" aria-label="Send command">
          <Send size={21} />
        </button>
      </form>
    </div>
  );
}

function ClockLabel() {
  return (
    <span className="clock-label">
      <History size={15} />
      00:18:42
    </span>
  );
}

function FilterTabs({ active, items, onChange }) {
  return (
    <div className="filter-tabs">
      {items.map((item) => (
        <button
          className={active === item ? "active" : ""}
          key={item}
          type="button"
          onClick={() => onChange(item)}
        >
          {item}
        </button>
      ))}
    </div>
  );
}

function EventIcon({ kind }) {
  if (kind === "tool.call") return <Wrench className="icon amber-icon" size={18} />;
  if (kind === "reasoning") return <Brain className="icon blue-icon" size={18} />;
  if (kind === "decision") return <CheckCircle className="icon green-icon" size={18} />;
  if (kind === "selection") return <Activity className="icon slate-icon" size={18} />;
  return <MessageSquare className="icon slate-icon" size={18} />;
}

function ArtifactIcon({ type }) {
  if (type === "Patch") return <FileDiff size={21} />;
  if (type === "Report") return <Archive size={21} />;
  return <FileText size={21} />;
}

function DecisionDrawer({ decision, onApprove, onRequestChanges, onReset }) {
  const resolved = decision !== "pending";
  return (
    <aside className="decision-drawer" aria-label="Human decision">
      <div className="drawer-scroll">
        <div className="drawer-header">
          <div>
            <span className="decision-kicker">
              <AlertCircle size={18} />
              Human decision
            </span>
            <small>Request from Executor</small>
          </div>
          <button className="icon-button" type="button" aria-label="Close drawer">
            <X size={17} />
          </button>
        </div>

        <div className="decision-heading">
          <h2>{resolved ? "Decision recorded" : "Approve patch"}</h2>
          <span className={resolved ? "success-pill" : "impact-pill"}>{resolved ? "Resolved" : "High impact"}</span>
        </div>

        <p className="decision-copy">
          {decision === "approved"
            ? "The run can continue with the retry patch applied to the local workspace."
            : decision === "changes"
              ? "The executor is paused and waiting for revised implementation notes."
              : "The agent wants to apply the following patch to the repository."}
        </p>

        <div className="risk-strip">
          <div>
            <FileText size={16} />
            <span>Files changed</span>
            <strong>2</strong>
          </div>
          <div>
            <GitBranch size={16} />
            <span>Insertions / Deletions</span>
            <strong className="diff-score">+45 / -12</strong>
          </div>
          <div>
            <Activity size={16} />
            <span>Estimated risk</span>
            <strong className="risk-medium">Medium</strong>
          </div>
        </div>

        <section className="drawer-section">
          <h3>Summary</h3>
          <p>
            Adds exponential backoff and jitter to retry logic in the <code>Runner</code> to improve
            resilience under transient failures.
          </p>
        </section>

        <section className="drawer-section">
          <h3>Files</h3>
          <div className="file-delta">
            <span>src/engine/runner.rs</span>
            <strong>+38 / -8</strong>
          </div>
          <div className="file-delta">
            <span>tests/integration/test_retry.rs</span>
            <strong>+7 / -4</strong>
          </div>
          <button className="secondary-button wide" type="button">
            View full diff
            <ChevronRight size={15} />
          </button>
        </section>

        <section className="drawer-section">
          <h3>Agent reasoning</h3>
          <p className="reasoning-box">
            This change reduces flakiness in CI by handling transient network and service errors with
            exponential backoff and jitter.
          </p>
        </section>

        <section className="drawer-section context-list">
          <h3>Context</h3>
          <span>
            Related issue <strong>#1287</strong>
          </span>
          <span>
            Tests <strong>8 passed</strong>
          </span>
          <span>
            Checks <strong>3 / 3 passed</strong>
          </span>
        </section>
      </div>

      <div className="decision-actions">
        <h3>Choose an action</h3>
        <button className="approve-button" type="button" onClick={onApprove}>
          <Check size={19} />
          <span>
            <strong>Approve patch</strong>
            <small>Apply changes and continue the run</small>
          </span>
        </button>
        <button className="request-button" type="button" onClick={onRequestChanges}>
          <RefreshCw size={18} />
          <span>
            <strong>Request changes</strong>
            <small>Provide feedback to the agent</small>
          </span>
        </button>
        <label className="checkbox-row">
          <input type="checkbox" defaultChecked />
          <span>Apply to this run only</span>
          <button className="secondary-button" type="button" onClick={onReset}>
            Snooze
          </button>
        </label>
      </div>
    </aside>
  );
}
