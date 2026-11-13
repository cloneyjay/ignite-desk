import { useState, useEffect, useCallback } from "react";

interface AuthState {
  token: string | null;
  expiresAt: number | null;
  isInitialized: boolean;
}

const AUTH_STORAGE_KEY = "ignite_auth_token";
const AUTH_EXPIRY_KEY = "ignite_auth_expiry";
const TOKEN_LIFETIME_MS = 24 * 60 * 60 * 1000; // 24 hours

export function generateToken(): string {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return Array.from(array, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function getStoredToken(): { token: string | null; expiresAt: number | null } {
  try {
    const token = sessionStorage.getItem(AUTH_STORAGE_KEY);
    const expiresAt = sessionStorage.getItem(AUTH_EXPIRY_KEY);
    if (token && expiresAt) {
      const expiry = parseInt(expiresAt, 10);
      if (expiry > Date.now()) {
        return { token, expiresAt: expiry };
      }
      // Token expired, clear it
      clearStoredToken();
    }
  } catch {
    // sessionStorage not available
  }
  return { token: null, expiresAt: null };
}

export function setStoredToken(token: string, expiresAt: number): void {
  try {
    sessionStorage.setItem(AUTH_STORAGE_KEY, token);
    sessionStorage.setItem(AUTH_EXPIRY_KEY, expiresAt.toString());
  } catch {
    // sessionStorage not available
  }
}

export function clearStoredToken(): void {
  try {
    sessionStorage.removeItem(AUTH_STORAGE_KEY);
    sessionStorage.removeItem(AUTH_EXPIRY_KEY);
  } catch {
    // sessionStorage not available
  }
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    token: null,
    expiresAt: null,
    isInitialized: false,
  });

  const initialize = useCallback(async () => {
    const { token, expiresAt } = getStoredToken();
    if (token && expiresAt) {
      setState({ token, expiresAt, isInitialized: true });
    } else {
      // Generate new token for this session
      const newToken = generateToken();
      const newExpiresAt = Date.now() + TOKEN_LIFETIME_MS;
      setStoredToken(newToken, newExpiresAt);
      setState({ token: newToken, expiresAt: newExpiresAt, isInitialized: true });
    }
  }, []);

  useEffect(() => {
    initialize();
  }, [initialize]);

  const getToken = useCallback(() => {
    if (state.token && state.expiresAt && state.expiresAt > Date.now()) {
      return state.token;
    }
    return null;
  }, [state.token, state.expiresAt]);

  const setToken = useCallback((token: string) => {
    const expiresAt = Date.now() + TOKEN_LIFETIME_MS;
    setStoredToken(token, expiresAt);
    setState({ token, expiresAt, isInitialized: true });
  }, []);

  const clearToken = useCallback(() => {
    clearStoredToken();
    setState({ token: null, expiresAt: null, isInitialized: true });
  }, []);

  return {
    ...state,
    getToken,
    setToken,
    clearToken,
    initialize,
  };
}

export function getAuthHeader(): { Authorization: string } | undefined {
  const { token, expiresAt } = getStoredToken();
  if (token && expiresAt && expiresAt > Date.now()) {
    return { Authorization: `Bearer ${token}` };
  }
  return undefined;
}