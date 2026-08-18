import { render } from 'preact';
import { loadConfig } from './config.js';
import { App } from './app.jsx';
import './styles.css';

loadConfig()
  .then(() => render(<App />, document.getElementById('app')))
  .catch((err) => {
    document.getElementById('app').textContent = 'Configuration error: ' + err.message;
  });
