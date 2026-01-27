import { lazy, Suspense } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { Spin } from "antd";
import "./i18n/config";
import { ThemeProvider } from "./theme";
import { Login } from "./pages/Login";
import { TenantLayout } from "./layouts/TenantLayout";
import { ProjectLayout } from "./layouts/ProjectLayout";
import { AgentLayout } from "./layouts/AgentLayout";
import { SchemaLayout } from "./layouts/SchemaLayout";
import { useAuthStore } from "./stores/auth";
import "./App.css";

// ============================================================================
// CODE SPLITTING - Lazy load route components for better performance
// ============================================================================
// Components are loaded on-demand, reducing initial bundle size
// ============================================================================

// Auth pages
const UserProfile = lazy(() =>
    import("./pages/UserProfile").then((m) => ({ default: m.UserProfile }))
);

// Tenant pages
const TenantOverview = lazy(() =>
    import("./pages/tenant/TenantOverview").then((m) => ({
        default: m.TenantOverview,
    }))
);
const ProjectList = lazy(() =>
    import("./pages/tenant/ProjectList").then((m) => ({ default: m.ProjectList }))
);
const UserList = lazy(() =>
    import("./pages/tenant/UserList").then((m) => ({ default: m.UserList }))
);
const ProviderList = lazy(() =>
    import("./pages/tenant/ProviderList").then((m) => ({
        default: m.ProviderList,
    }))
);
const NewProject = lazy(() =>
    import("./pages/tenant/NewProject").then((m) => ({ default: m.NewProject }))
);
const EditProject = lazy(() =>
    import("./pages/tenant/EditProject").then((m) => ({ default: m.EditProject }))
);
const NewTenant = lazy(() =>
    import("./pages/tenant/NewTenant").then((m) => ({ default: m.NewTenant }))
);
const TenantSettings = lazy(() =>
    import("./pages/tenant/TenantSettings").then((m) => ({
        default: m.TenantSettings,
    }))
);
const TaskDashboard = lazy(() =>
    import("./pages/tenant/TaskDashboard").then((m) => ({
        default: m.TaskDashboard,
    }))
);
const AgentDashboard = lazy(() =>
    import("./pages/tenant/AgentDashboard").then((m) => ({
        default: m.AgentDashboard,
    }))
);
const WorkflowPatterns = lazy(() => import("./pages/tenant/WorkflowPatterns"));
const Analytics = lazy(() =>
    import("./pages/tenant/Analytics").then((m) => ({ default: m.Analytics }))
);
const Billing = lazy(() =>
    import("./pages/tenant/Billing").then((m) => ({ default: m.Billing }))
);
const SubAgentList = lazy(() =>
    import("./pages/tenant/SubAgentList").then((m) => ({
        default: m.SubAgentList,
    }))
);
const SkillList = lazy(() =>
    import("./pages/tenant/SkillList").then((m) => ({ default: m.SkillList }))
);
const McpServerList = lazy(() =>
    import("./pages/tenant/McpServerList").then((m) => ({
        default: m.McpServerList,
    }))
);

// Project pages
const ProjectOverview = lazy(() =>
    import("./pages/project/ProjectOverview").then((m) => ({
        default: m.ProjectOverview,
    }))
);
const MemoryList = lazy(() =>
    import("./pages/project/MemoryList").then((m) => ({ default: m.MemoryList }))
);
const NewMemory = lazy(() =>
    import("./pages/project/NewMemory").then((m) => ({ default: m.NewMemory }))
);
const MemoryDetail = lazy(() =>
    import("./pages/project/MemoryDetail").then((m) => ({
        default: m.MemoryDetail,
    }))
);
const MemoryGraph = lazy(() =>
    import("./pages/project/MemoryGraph").then((m) => ({
        default: m.MemoryGraph,
    }))
);
const EntitiesList = lazy(() =>
    import("./pages/project/EntitiesList").then((m) => ({
        default: m.EntitiesList,
    }))
);
const CommunitiesList = lazy(() =>
    import("./pages/project/CommunitiesList").then((m) => ({
        default: m.CommunitiesList,
    }))
);
const EnhancedSearch = lazy(() =>
    import("./pages/project/EnhancedSearch").then((m) => ({
        default: m.EnhancedSearch,
    }))
);
const Maintenance = lazy(() =>
    import("./pages/project/Maintenance").then((m) => ({
        default: m.Maintenance,
    }))
);
const Team = lazy(() =>
    import("./pages/project/Team").then((m) => ({ default: m.Team }))
);
const ProjectSettings = lazy(() =>
    import("./pages/project/Settings").then((m) => ({
        default: m.ProjectSettings,
    }))
);
const Support = lazy(() =>
    import("./pages/project/Support").then((m) => ({ default: m.Support }))
);

// Schema pages
const SchemaOverview = lazy(
    () => import("./pages/project/schema/SchemaOverview")
);
const EntityTypeList = lazy(
    () => import("./pages/project/schema/EntityTypeList")
);
const EdgeTypeList = lazy(() => import("./pages/project/schema/EdgeTypeList"));
const EdgeMapList = lazy(() => import("./pages/project/schema/EdgeMapList"));

// Agent pages
const AgentChat = lazy(() => import("./pages/project/AgentChatV3"));
const AgentLogs = lazy(() => import("./pages/project/agent/AgentLogs"));
const AgentPatterns = lazy(() => import("./pages/project/agent/AgentPatterns"));

// Loading fallback for lazy-loaded components
const PageLoader = () => (
    <div
        style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            height: "200px",
        }}
    >
        <Spin size="large" />
    </div>
);

function App() {
    const { isAuthenticated } = useAuthStore();

    return (
        <ThemeProvider>
            <Suspense fallback={<PageLoader />}>
                <Routes>
                    <Route
                        path="/login"
                        element={!isAuthenticated ? <Login /> : <Navigate to="/" replace />}
                    />

                    {/* Protected Routes */}
                    {/* Redirect root to tenant overview if authenticated */}
                    <Route
                        path="/"
                        element={
                            isAuthenticated ? (
                                <Navigate to="/tenant" replace />
                            ) : (
                                <Navigate to="/login" replace />
                            )
                        }
                    />

                    <Route
                        path="/tenants/new"
                        element={
                            isAuthenticated ? (
                                <Suspense fallback={<PageLoader />}>
                                    <NewTenant />
                                </Suspense>
                            ) : (
                                <Navigate to="/login" replace />
                            )
                        }
                    />

                    {/* Tenant Console */}
                    <Route
                        path="/tenant"
                        element={
                            isAuthenticated ? (
                                <TenantLayout />
                            ) : (
                                <Navigate to="/login" replace />
                            )
                        }
                    >
                        <Route
                            index
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <TenantOverview />
                                </Suspense>
                            }
                        />

                        {/* Generic routes (use currentTenant from store) */}
                        <Route
                            path="projects"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <ProjectList />
                                </Suspense>
                            }
                        />
                        <Route
                            path="projects/new"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <NewProject />
                                </Suspense>
                            }
                        />
                        <Route
                            path="users"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <UserList />
                                </Suspense>
                            }
                        />
                        <Route
                            path="providers"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <ProviderList />
                                </Suspense>
                            }
                        />
                        <Route
                            path="profile"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <UserProfile />
                                </Suspense>
                            }
                        />
                        <Route
                            path="analytics"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <Analytics />
                                </Suspense>
                            }
                        />
                        <Route
                            path="billing"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <Billing />
                                </Suspense>
                            }
                        />
                        <Route
                            path="settings"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <TenantSettings />
                                </Suspense>
                            }
                        />
                        <Route
                            path="tasks"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <TaskDashboard />
                                </Suspense>
                            }
                        />
                        <Route
                            path="agents"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <AgentDashboard />
                                </Suspense>
                            }
                        />
                        <Route
                            path="subagents"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <SubAgentList />
                                </Suspense>
                            }
                        />
                        <Route
                            path="skills"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <SkillList />
                                </Suspense>
                            }
                        />
                        <Route
                            path="mcp-servers"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <McpServerList />
                                </Suspense>
                            }
                        />

                        {/* Tenant specific routes */}
                        <Route
                            path=":tenantId"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <TenantOverview />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/tasks"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <TaskDashboard />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/agents"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <AgentDashboard />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/projects"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <ProjectList />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/projects/new"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <NewProject />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/projects/:projectId/edit"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <EditProject />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/users"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <UserList />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/providers"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <ProviderList />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/analytics"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <Analytics />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/billing"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <Billing />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/settings"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <TenantSettings />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/patterns"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <WorkflowPatterns />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/subagents"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <SubAgentList />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/skills"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <SkillList />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":tenantId/mcp-servers"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <McpServerList />
                                </Suspense>
                            }
                        />
                    </Route>

                    {/* Project Workbench */}
                    <Route
                        path="/project/:projectId"
                        element={
                            isAuthenticated ? (
                                <ProjectLayout />
                            ) : (
                                <Navigate to="/login" replace />
                            )
                        }
                    >
                        <Route
                            index
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <ProjectOverview />
                                </Suspense>
                            }
                        />
                        <Route
                            path="memories"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <MemoryList />
                                </Suspense>
                            }
                        />
                        <Route
                            path="memories/new"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <NewMemory />
                                </Suspense>
                            }
                        />
                        <Route
                            path="memory/:memoryId"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <MemoryDetail />
                                </Suspense>
                            }
                        />
                        {/* <Route path="search" element={<SearchPage />} /> */}
                        <Route
                            path="graph"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <MemoryGraph />
                                </Suspense>
                            }
                        />
                        <Route
                            path="entities"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <EntitiesList />
                                </Suspense>
                            }
                        />
                        <Route
                            path="communities"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <CommunitiesList />
                                </Suspense>
                            }
                        />
                        <Route
                            path="advanced-search"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <EnhancedSearch />
                                </Suspense>
                            }
                        />
                        <Route
                            path="search"
                            element={<Navigate to="advanced-search" replace />}
                        />
                        <Route
                            path="maintenance"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <Maintenance />
                                </Suspense>
                            }
                        />
                        <Route path="schema" element={<SchemaLayout />}>
                            <Route
                                index
                                element={
                                    <Suspense fallback={<PageLoader />}>
                                        <SchemaOverview />
                                    </Suspense>
                                }
                            />
                            <Route
                                path="entities"
                                element={
                                    <Suspense fallback={<PageLoader />}>
                                        <EntityTypeList />
                                    </Suspense>
                                }
                            />
                            <Route
                                path="edges"
                                element={
                                    <Suspense fallback={<PageLoader />}>
                                        <EdgeTypeList />
                                    </Suspense>
                                }
                            />
                            <Route
                                path="mapping"
                                element={
                                    <Suspense fallback={<PageLoader />}>
                                        <EdgeMapList />
                                    </Suspense>
                                }
                            />
                        </Route>
                        <Route
                            path="team"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <Team />
                                </Suspense>
                            }
                        />
                        <Route
                            path="settings"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <ProjectSettings />
                                </Suspense>
                            }
                        />
                        <Route
                            path="support"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <Support />
                                </Suspense>
                            }
                        />
                    </Route>

                    {/* Agent Workspace - Full screen layout with sub-routes */}
                    <Route
                        path="/project/:projectId/agent"
                        element={
                            isAuthenticated ? (
                                <AgentLayout />
                            ) : (
                                <Navigate to="/login" replace />
                            )
                        }
                    >
                        <Route
                            index
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <AgentChat />
                                </Suspense>
                            }
                        />
                        <Route
                            path=":conversation"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <AgentChat />
                                </Suspense>
                            }
                        />
                        <Route
                            path="logs"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <AgentLogs />
                                </Suspense>
                            }
                        />
                        <Route
                            path="patterns"
                            element={
                                <Suspense fallback={<PageLoader />}>
                                    <AgentPatterns />
                                </Suspense>
                            }
                        />
                    </Route>

                    {/* Fallback */}
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </Suspense>
        </ThemeProvider>
    );
}

export default App;
