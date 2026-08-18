import { Component } from 'preact';
import { useI18n } from '../i18n-context.jsx';

function ErrorFallback({ error, onRetry }) {
  const { t } = useI18n();
  return (
    <div class="error-boundary">
      <div class="error-boundary-content">
        <span class="error-boundary-icon">⚠️</span>
        <h2>{t('error.title')}</h2>
        <p class="error-boundary-message">{error.message || t('error.default')}</p>
        <div class="error-boundary-actions">
          <button class="btn btn-primary" onClick={onRetry}>
            {t('error.tryAgain')}
          </button>
          <a href="/" class="btn btn-secondary">{t('error.goHome')}</a>
        </div>
      </div>
    </div>
  );
}

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught:', error, info);
  }

  render() {
    if (this.state.error) {
      return <ErrorFallback error={this.state.error} onRetry={() => this.setState({ error: null })} />;
    }
    return this.props.children;
  }
}
