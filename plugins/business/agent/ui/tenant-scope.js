window.memstack.getContext().then(async (scope) => {
  const root = document.getElementById("root");
  if (!root) return;
  const chinese = String(scope.locale || "").startsWith("zh");
  const text = (zh, en) => (chinese ? zh : en);
  root.replaceChildren();
  const status = document.createElement("p");
  status.textContent = text("正在读取本租户的会话。", "Loading sessions in this tenant.");
  root.append(status);
  try {
    const page = await window.memstack.invoke("tenant-session-list", {});
    status.textContent = page.items.length
      ? text("选择一个会话，或先选择项目再创建。", "Choose a session, or pick a project to create one.")
      : text("还没有会话。请先选择项目。", "No sessions yet. Choose a project first.");
    const list = document.createElement("ul");
    for (const item of page.items) {
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.title || item.id;
      button.addEventListener("click", () => {
        const destination =
          "/tenant/" +
          encodeURIComponent(scope.tenantId) +
          "/project/" +
          encodeURIComponent(item.project_id) +
          "/agent-workspace/" +
          encodeURIComponent(item.id);
        window.memstack.navigate(destination).catch(() => {
          status.textContent = text("无法打开这个会话。", "This session could not be opened.");
        });
      });
      row.append(button);
      list.append(row);
    }
    root.append(list);
  } catch (error) {
    status.textContent = text(
      "请先选择一个项目，再打开此页面。",
      "Choose a project before opening this page.",
    );
  }
});
