window.memstack.getContext().then((scope) => {
  const root = document.getElementById("root");
  if (!root) return;
  const chinese = String(scope.locale || "").startsWith("zh");
  root.textContent = chinese
    ? "请先选择一个项目，再打开此页面。"
    : "Choose a project before opening this page.";
});
