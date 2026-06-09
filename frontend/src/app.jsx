import Router from 'preact-router';
import { AuthProvider } from './auth.jsx';
import { WsProvider } from './ws-context.jsx';
import { I18nProvider } from './i18n-context.jsx';
import { AgentProvider } from './agent-context.jsx';
import { Layout } from './components/layout.jsx';
import { ErrorBoundary } from './components/error-boundary.jsx';
import { WelcomeModal } from './components/welcome-modal.jsx';
import { ProjectsPage } from './pages/projects.jsx';
import { CreateProjectPage } from './pages/create-project.jsx';
import { ProjectDetailPage } from './pages/project-detail.jsx';
import { RiskHeatmapPage } from './pages/risk-heatmap.jsx';
import { AgentDemoPage } from './pages/review-live.jsx';
import { CallbackPage } from './pages/callback.jsx';
import { ContextsPage } from './pages/contexts.jsx';
import { AnalyticsPage } from './pages/analytics.jsx';
import { AdminPage } from './pages/admin.jsx';
import { AdminStandardsPage } from './pages/admin-standards.jsx';
import { AdminGuardrailEventsPage } from './pages/admin-guardrail-events.jsx';
import { BenchmarksPage } from './pages/benchmarks.jsx';
import { HelpPage } from './pages/help.jsx';

export function App() {
  return (
    <Router>
      <CallbackPage path="/callback" />
      <AuthenticatedApp default />
    </Router>
  );
}

function AuthenticatedApp() {
  return (
    <AuthProvider>
      <I18nProvider>
        <AgentProvider>
          <WsProvider>
            <ErrorBoundary>
              <WelcomeModal />
              <Router>
                <LayoutRoute path="/" component={ProjectsPage} />
                <LayoutRoute path="/create" component={CreateProjectPage} />
                <LayoutRoute path="/projects/:projectId" component={ProjectDetailPage} />
                <LayoutRoute path="/projects/:projectId/heatmap" component={RiskHeatmapPage} />
                <LayoutRoute path="/projects/:projectId/live/:reviewId?" component={AgentDemoPage} />
                <LayoutRoute path="/demo" component={AgentDemoPage} />
                <LayoutRoute path="/contexts" component={ContextsPage} />
                <LayoutRoute path="/analytics" component={AnalyticsPage} />
                <LayoutRoute path="/benchmarks" component={BenchmarksPage} />
                <LayoutRoute path="/admin/standards" component={AdminStandardsPage} />
                <LayoutRoute path="/admin/guardrail-events" component={AdminGuardrailEventsPage} />
                <LayoutRoute path="/admin" component={AdminPage} />
                <LayoutRoute path="/help" component={HelpPage} />
              </Router>
            </ErrorBoundary>
          </WsProvider>
        </AgentProvider>
      </I18nProvider>
    </AuthProvider>
  );
}

function LayoutRoute({ component: Component, ...props }) {
  return (
    <Layout>
      <Component {...props} />
    </Layout>
  );
}
