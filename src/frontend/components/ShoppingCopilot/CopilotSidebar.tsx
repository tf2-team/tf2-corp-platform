// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import styled from 'styled-components';

export interface ChatSession {
  id: string;
  title: string;
  timestamp: string;
}

const SidebarContainer = styled.aside<{ isOpen: boolean }>`
  width: ${({ isOpen }) => (isOpen ? '280px' : '0px')};
  min-width: ${({ isOpen }) => (isOpen ? '280px' : '0px')};
  background: #0f172a;
  color: #f1f5f9;
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
  border-right: 1px solid #1e293b;
  z-index: 40;

  @media (max-width: 768px) {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    box-shadow: 8px 0 32px rgba(0, 0, 0, 0.4);
  }
`;

const Header = styled.div`
  padding: 20px 18px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #1e293b;
`;

const Title = styled.h2`
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  color: #cbd5e1;
  margin: 0;
`;

const NewChatButton = styled.button`
  margin: 16px 16px 12px 16px;
  padding: 11px 16px;
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.25);
  transition: all 0.15s ease;

  &:hover {
    background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
    transform: translateY(-1px);
    box-shadow: 0 6px 18px rgba(37, 99, 235, 0.35);
  }

  &:active {
    transform: translateY(0);
  }
`;

const SessionList = styled.div`
  flex: 1;
  overflow-y: auto;
  padding: 4px 12px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;

  &::-webkit-scrollbar {
    width: 5px;
  }
  &::-webkit-scrollbar-thumb {
    background: #334155;
    border-radius: 3px;
  }
`;

const SessionItem = styled.div<{ active: boolean }>`
  padding: 10px 12px;
  border-radius: 8px;
  background: ${({ active }) => (active ? 'rgba(37, 99, 235, 0.25)' : 'transparent')};
  border: 1px solid ${({ active }) => (active ? 'rgba(59, 130, 246, 0.5)' : 'transparent')};
  color: ${({ active }) => (active ? '#ffffff' : '#cbd5e1')};
  font-size: 13.5px;
  font-weight: ${({ active }) => (active ? '600' : '400')};
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: all 0.15s ease;
  user-select: none;

  &:hover {
    background: ${({ active }) => (active ? 'rgba(37, 99, 235, 0.35)' : 'rgba(255, 255, 255, 0.08)')};
    color: #ffffff;
  }
`;

const SessionTitle = styled.span`
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
  color: inherit;
`;

const DeleteButton = styled.button`
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 13px;
  cursor: pointer;
  padding: 3px 6px;
  border-radius: 4px;
  transition: all 0.15s ease;

  &:hover {
    color: #f87171;
    background-color: rgba(239, 68, 68, 0.15);
  }
`;

const Footer = styled.div`
  padding: 14px 18px;
  border-top: 1px solid #1e293b;
  font-size: 12px;
  color: #94a3b8;
  display: flex;
  flex-direction: column;
  gap: 4px;
`;

const StatusBadge = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  background-color: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 600;
`;

const StatusDot = styled.span`
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #34d399;
`;

interface CopilotSidebarProps {
  isOpen: boolean;
  sessions: ChatSession[];
  activeSessionId: string;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
}

export const CopilotSidebar: React.FC<CopilotSidebarProps> = ({
  isOpen,
  sessions,
  activeSessionId,
  onNewChat,
  onSelectSession,
  onDeleteSession,
}) => {
  return (
    <SidebarContainer isOpen={isOpen}>
      <Header>
        <Title>Conversations</Title>
        <StatusBadge>
          <StatusDot /> Active
        </StatusBadge>
      </Header>
      <NewChatButton onClick={onNewChat}>
        + New Conversation
      </NewChatButton>
      <SessionList>
        {sessions.map((session) => (
          <SessionItem
            key={session.id}
            active={session.id === activeSessionId}
            onClick={() => onSelectSession(session.id)}
          >
            <SessionTitle>{session.title || 'New Conversation'}</SessionTitle>
            {sessions.length > 1 && (
              <DeleteButton
                title="Delete Chat"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteSession(session.id);
                }}
              >
                ✕
              </DeleteButton>
            )}
          </SessionItem>
        ))}
      </SessionList>
      <Footer>
        <span>Shopping Copilot Assistant</span>
        <span>Version 2.2.0</span>
      </Footer>
    </SidebarContainer>
  );
};

export default CopilotSidebar;
