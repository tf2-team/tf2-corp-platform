// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { v4 } from 'uuid';

export interface ISession {
  userId: string;
  currencyCode: string;
}

const sessionKey = 'session';

const isValidSession = (session: unknown): session is ISession => {
  return (
    typeof session === 'object' &&
    session !== null &&
    typeof (session as ISession).userId === 'string' &&
    (session as ISession).userId.length > 0 &&
    typeof (session as ISession).currencyCode === 'string' &&
    (session as ISession).currencyCode.length > 0
  );
};

const createSession = (): ISession => ({
  userId: v4(),
  currencyCode: 'USD',
});

/**
 * Session is stored in localStorage so the cart survives page refresh.
 * Always call getSession() at use-time — never cache userId at module load,
 * because SSR has no localStorage and module-level capture uses a throwaway id.
 */
const SessionGateway = () => ({
  getSession(): ISession {
    // SSR / Node: no durable browser session. Callers on the server must not
    // use this for cart identity; client call-time reads will load localStorage.
    if (typeof window === 'undefined') {
      return { userId: '', currencyCode: 'USD' };
    }

    try {
      const sessionString = localStorage.getItem(sessionKey);
      if (sessionString) {
        const parsed: unknown = JSON.parse(sessionString);
        if (isValidSession(parsed)) {
          return parsed;
        }
      }
    } catch (e) {
      console.warn('Failed to read session from localStorage', e);
    }

    const session = createSession();
    try {
      localStorage.setItem(sessionKey, JSON.stringify(session));
    } catch (e) {
      console.warn('Failed to persist session to localStorage', e);
    }
    return session;
  },

  setSessionValue<K extends keyof ISession>(key: K, value: ISession[K]) {
    if (typeof window === 'undefined') {
      return;
    }
    const session = this.getSession();
    const next = { ...session, [key]: value };
    try {
      localStorage.setItem(sessionKey, JSON.stringify(next));
    } catch (e) {
      console.warn('Failed to persist session to localStorage', e);
    }
  },
});

export default SessionGateway();
