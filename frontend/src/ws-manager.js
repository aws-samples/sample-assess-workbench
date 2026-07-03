// Shared WebSocket manager — single connection, multiple subscribers
import { getConfig } from './config.js';
import { getIdToken } from './auth.jsx';

export class WebSocketManager {
  constructor() {
    this._ws = null;
    this._subscribers = new Set();
    this._statusSubscribers = new Set();
    this._status = 'disconnected';
    this._reconnectTimer = null;
    this._reconnectDelay = 1000;
    this._maxReconnectDelay = 30000;
    this._intentionallyClosed = false;
  }

  get status() { return this._status; }

  connect() {
    if (this._ws && (this._ws.readyState === WebSocket.OPEN || this._ws.readyState === WebSocket.CONNECTING)) {
      return; // already connected or connecting
    }

    const token = getIdToken();
    if (!token) {
      // Token expired or missing — stop reconnect attempts.
      // WsProvider will call connect() again when auth refreshes.
      this._setStatus('disconnected');
      return;
    }

    this._intentionallyClosed = false;
    this._setStatus('connecting');

    const wsUrl = getConfig().websocketUrl + '?token=' + encodeURIComponent(token);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      this._reconnectDelay = 1000; // reset backoff
      this._setStatus('connected');
    };

    ws.onclose = () => {
      this._ws = null;
      this._setStatus('disconnected');
      if (!this._intentionallyClosed) {
        this._scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // onclose will fire after onerror, so reconnect is handled there
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        this._subscribers.forEach((fn) => fn(data));
      } catch (err) {
        console.warn('WebSocket message parse error:', err);
      }
    };

    this._ws = ws;
  }

  disconnect() {
    this._intentionallyClosed = true;
    clearTimeout(this._reconnectTimer);
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
    this._setStatus('disconnected');
  }

  send(data) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(typeof data === 'string' ? data : JSON.stringify(data));
      return true;
    }
    return false;
  }

  subscribe(fn) {
    this._subscribers.add(fn);
    return () => this._subscribers.delete(fn);
  }

  onStatus(fn) {
    this._statusSubscribers.add(fn);
    fn(this._status); // immediately notify current status
    return () => this._statusSubscribers.delete(fn);
  }

  _setStatus(s) {
    this._status = s;
    this._statusSubscribers.forEach((fn) => fn(s));
  }

  _scheduleReconnect() {
    clearTimeout(this._reconnectTimer);
    this._reconnectTimer = setTimeout(() => {
      this.connect();
    }, this._reconnectDelay);
    this._reconnectDelay = Math.min(this._reconnectDelay * 2, this._maxReconnectDelay);
  }
}
