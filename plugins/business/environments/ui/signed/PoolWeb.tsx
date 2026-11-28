import "./clusters-web.css";
import { createInstance } from "i18next";
import { createRoot } from "react-dom/client";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import PoolDashboard from "../web/admin/PoolDashboard";
import en from "../web/locales/en-US.json";
import zh from "../web/locales/zh-CN.json";

async function mount() {
  const host = window.memstack;
  const context = await host.getContext();
  const i18n = createInstance();
  await i18n.init({
    lng: context.locale.startsWith("zh") ? "zh" : "en",
    resources: {
      en: { translation: en },
      zh: { translation: zh },
    },
    interpolation: { escapeValue: false },
  });
  const router = createMemoryRouter(
    [
      { path: "/tenant/:tenantId/pool", element: <PoolDashboard /> },
      { path: "*", element: null },
    ],
    { initialEntries: [context.pathname + context.search + context.hash] },
  );
  let current = context.pathname + context.search + context.hash;
  router.subscribe(({ location }) => {
    const next = location.pathname + location.search + location.hash;
    if (current !== next) {
      current = next;
      void host.navigate(next, {
        replace: location.pathname === context.pathname,
      });
    }
  });
  createRoot(document.getElementById("root")!).render(
    <I18nextProvider i18n={i18n}>
      <RouterProvider router={router} />
    </I18nextProvider>,
  );
}
void mount();
