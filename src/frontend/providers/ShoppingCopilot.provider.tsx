// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React, { createContext, useContext, useState, useEffect } from 'react';
import SessionGateway from '../gateways/Session.gateway';

export interface CopilotProduct {
  productId: string;
  name: string;
  priceUnits: number;
  priceNanos: number;
  currencyCode: string;
  description?: string;
}

export interface CopilotClaim {
  text: string;
  sourceIds: string[];
}

export interface CopilotSource {
  sourceId: string;
  sourceType: string;
  productId: string;
}

export interface CopilotResponse {
  status: 'GROUNDED' | 'NO_RESULTS' | 'ABSTAINED' | 'BLOCKED' | 'FALLBACK';
  interpretedCriteria: string;
  products: CopilotProduct[];
  claims: CopilotClaim[];
  sources: CopilotSource[];
  reason: string;
  pendingActionToken: string;
}

export interface ChatTurn {
  id: string;
  userMessage: string;
  response: CopilotResponse;
  timestamp: string;
}

export interface ChatSessionData {
  id: string;
  title: string;
  turns: ChatTurn[];
  createdAt: string;
}

interface ShoppingCopilotContextType {
  loading: boolean;
  response: CopilotResponse | null;
  error: string | null;
  confirmLoading: boolean;
  confirmSuccess: boolean | null;
  confirmMessage: string | null;
  sessions: ChatSessionData[];
  activeSessionId: string;
  currentTurns: ChatTurn[];
  searchCopilot: (message: string) => Promise<void>;
  confirmCartAction: (token: string, userId?: string) => Promise<void>;
  cancelCartAction: () => void;
  clearResponse: () => void;
  createNewSession: () => void;
  selectSession: (id: string) => void;
  deleteSession: (id: string) => void;
}

const ShoppingCopilotContext = createContext<ShoppingCopilotContextType | undefined>(
  undefined
);

const DEFAULT_SESSION_ID = 'session_default';
const STORAGE_KEY = 'shopping_copilot_sessions_v2';
const ACTIVE_SESSION_KEY = 'shopping_copilot_active_session_v2';

function sanitizeCriteria(criteria: string): string {
  if (!criteria) return '';
  let cleaned = criteria;
  // Filter out SQL query leaks or prompt injection code artifacts
  if (/\b(SELECT|INSERT|UPDATE|DELETE|DROP|FROM|WHERE|JOIN|UNION|CREATE|ALTER|EXEC)\b/i.test(cleaned)) {
    return 'Search parameters processed';
  }
  cleaned = cleaned.replace(/\[?(BLOCKED|GROUNDED|ABSTAINED|FALLBACK|NO_RESULTS)\]?/gi, '').trim();
  return cleaned;
}

function sanitizeReason(reason: string): string {
  if (!reason) return '';
  let cleaned = reason;
  if (/\b(SELECT|INSERT|UPDATE|DELETE|DROP|FROM|WHERE|JOIN|UNION|CREATE|ALTER|EXEC)\b/i.test(cleaned)) {
    return 'The request could not be executed as specified.';
  }
  cleaned = cleaned.replace(/\[?(BLOCKED|GROUNDED|ABSTAINED|FALLBACK|NO_RESULTS)\]?/gi, '').trim();
  return cleaned;
}

export const ShoppingCopilotProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<CopilotResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [confirmSuccess, setConfirmSuccess] = useState<boolean | null>(null);
  const [confirmMessage, setConfirmMessage] = useState<string | null>(null);

  const [sessions, setSessions] = useState<ChatSessionData[]>(() => {
    if (typeof window !== 'undefined') {
      try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
          const parsed = JSON.parse(saved);
          if (Array.isArray(parsed) && parsed.length > 0) {
            return parsed;
          }
        }
      } catch (e) {
        console.error('Failed to load sessions from localStorage', e);
      }
    }
    return [
      {
        id: DEFAULT_SESSION_ID,
        title: 'New Conversation',
        turns: [],
        createdAt: new Date().toISOString(),
      },
    ];
  });

  const [activeSessionId, setActiveSessionId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      try {
        const savedId = localStorage.getItem(ACTIVE_SESSION_KEY);
        if (savedId) return savedId;
      } catch (e) {
        console.error('Failed to load active session ID from localStorage', e);
      }
    }
    return DEFAULT_SESSION_ID;
  });

  useEffect(() => {
    if (typeof window !== 'undefined') {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
      } catch (e) {
        console.error('Failed to save sessions to localStorage', e);
      }
    }
  }, [sessions]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      try {
        localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionId);
      } catch (e) {
        console.error('Failed to save activeSessionId to localStorage', e);
      }
    }
  }, [activeSessionId]);

  const activeSession = sessions.find((s) => s.id === activeSessionId) || sessions[0];
  const currentTurns = activeSession ? activeSession.turns : [];

  const createNewSession = () => {
    const newId = `session_${Date.now()}`;
    const newSession: ChatSessionData = {
      id: newId,
      title: 'New Conversation',
      turns: [],
      createdAt: new Date().toISOString(),
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newId);
    setResponse(null);
    setError(null);
    setConfirmSuccess(null);
    setConfirmMessage(null);
  };

  const selectSession = (id: string) => {
    setActiveSessionId(id);
    const target = sessions.find((s) => s.id === id);
    if (target && target.turns.length > 0) {
      setResponse(target.turns[target.turns.length - 1].response);
    } else {
      setResponse(null);
    }
    setError(null);
    setConfirmSuccess(null);
    setConfirmMessage(null);
  };

  const deleteSession = (id: string) => {
    setSessions((prev) => {
      const filtered = prev.filter((s) => s.id !== id);
      if (filtered.length === 0) {
        const fallbackId = `session_${Date.now()}`;
        return [
          {
            id: fallbackId,
            title: 'New Conversation',
            turns: [],
            createdAt: new Date().toISOString(),
          },
        ];
      }
      return filtered;
    });

    if (activeSessionId === id) {
      const remaining = sessions.filter((s) => s.id !== id);
      const nextId = remaining.length > 0 ? remaining[0].id : DEFAULT_SESSION_ID;
      setActiveSessionId(nextId);
    }
  };

  const searchCopilot = async (message: string) => {
    setLoading(true);
    setError(null);
    setResponse(null);
    setConfirmSuccess(null);
    setConfirmMessage(null);

    try {
      const res = await fetch('/api/copilot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_message: message }),
      });
      const rawData: CopilotResponse = await res.json();
      if (!res.ok && !rawData.status) {
        throw new Error((rawData as any).error || 'Request failed');
      }

      const cleanData: CopilotResponse = {
        ...rawData,
        interpretedCriteria: sanitizeCriteria(rawData.interpretedCriteria),
        reason: sanitizeReason(rawData.reason),
      };

      setResponse(cleanData);

      const newTurn: ChatTurn = {
        id: `turn_${Date.now()}`,
        userMessage: message,
        response: cleanData,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

      setSessions((prev) =>
        prev.map((s) => {
          if (s.id === activeSessionId) {
            const isFirstTurn = s.turns.length === 0;
            const newTitle = isFirstTurn ? message.slice(0, 32) + (message.length > 32 ? '...' : '') : s.title;
            return {
              ...s,
              title: newTitle,
              turns: [...s.turns, newTurn],
            };
          }
          return s;
        })
      );
    } catch (err: any) {
      const fallbackResponse: CopilotResponse = {
        status: 'FALLBACK',
        interpretedCriteria: '',
        products: [],
        claims: [],
        sources: [],
        reason: 'Assistant is temporarily unavailable. Please try again shortly.',
        pendingActionToken: '',
      };
      setError(err?.message || 'Failed to connect to Shopping Copilot');
      setResponse(fallbackResponse);
    } finally {
      setLoading(false);
    }
  };

  const confirmCartAction = async (token: string, userId?: string) => {
    setConfirmLoading(true);
    setConfirmSuccess(null);
    setConfirmMessage(null);

    const actualUserId =
      userId && userId !== 'user_1'
        ? userId
        : SessionGateway.getSession().userId || 'user_1';

    try {
      const res = await fetch('/api/copilot/confirm-cart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pending_action_token: token, user_id: actualUserId }),
      });
      const data = await res.json();
      setConfirmSuccess(data.success);
      setConfirmMessage(
        data.success
          ? 'Item successfully added to your cart!'
          : data.reason || 'Cart confirmation failed.'
      );
    } catch (err: any) {
      setConfirmSuccess(false);
      setConfirmMessage(err?.message || 'Failed to confirm cart action.');
    } finally {
      setConfirmLoading(false);
    }
  };

  const cancelCartAction = () => {
    setConfirmSuccess(false);
    setConfirmMessage('Cart action cancelled.');
    if (response) {
      setResponse({
        ...response,
        pendingActionToken: '',
      });
    }
  };

  const clearResponse = () => {
    setResponse(null);
    setError(null);
    setConfirmSuccess(null);
    setConfirmMessage(null);
  };

  return (
    <ShoppingCopilotContext.Provider
      value={{
        loading,
        response,
        error,
        confirmLoading,
        confirmSuccess,
        confirmMessage,
        sessions,
        activeSessionId,
        currentTurns,
        searchCopilot,
        confirmCartAction,
        cancelCartAction,
        clearResponse,
        createNewSession,
        selectSession,
        deleteSession,
      }}
    >
      {children}
    </ShoppingCopilotContext.Provider>
  );
};

export const useShoppingCopilot = () => {
  const context = useContext(ShoppingCopilotContext);
  if (!context) {
    throw new Error('useShoppingCopilot must be used within ShoppingCopilotProvider');
  }
  return context;
};
