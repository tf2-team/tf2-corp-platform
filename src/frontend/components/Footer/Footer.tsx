// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from 'react';
import * as S from './Footer.styled';
import SessionGateway from '../../gateways/Session.gateway';
import { CypressFields } from '../../utils/enums/CypressFields';
import PlatformFlag from '../PlatformFlag';

const currentYear = new Date().getFullYear();

const Footer = () => {
  const [sessionId, setSessionId] = useState('');

  useEffect(() => {
    // Read after mount so we use the localStorage-backed session, not SSR empty id.
    setSessionId(SessionGateway.getSession().userId);
  }, []);

  return (
    <S.Footer>
      <div>
        <p>This website is hosted for demo purpose only. It is not an actual shop.</p>
        <p>
          <span data-cy={CypressFields.SessionId}>session-id: {sessionId}</span>
        </p>
      </div>
      <p>
        @ {currentYear} TechX Corp
      </p>
      <PlatformFlag />
    </S.Footer>
  );
};

export default Footer;
