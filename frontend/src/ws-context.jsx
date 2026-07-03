import { createContext } from 'preact';
import { useContext, useEffect } from 'preact/hooks';
import { WebSocketManager } from './ws-manager.js';
import { useAuth } from './auth.jsx';

const WsContext = createContext(null);

// Single manager instance — survives HMR by attaching to window
function getManager() {
  if (!window.__wsManager) {
    window.__wsManager = new WebSocketManager();
  }
  return window.__wsManager;
}

export function WsProvider({ children }) {
  const manager = getManager();
  // Derive connection lifecycle from auth state (reactive via setUser in AuthProvider).
  // When tokens are refreshed, AuthProvider updates `user`, which triggers this effect
  // to reconnect the WebSocket with the fresh token.
  const { user } = useAuth();

  useEffect(() => {
    if (user) {
      manager.disconnect();
      manager.connect();
    } else {
      manager.disconnect();
    }
  }, [user]);

  return <WsContext.Provider value={manager}>{children}</WsContext.Provider>;
}

export function useWs() {
  return useContext(WsContext);
}
