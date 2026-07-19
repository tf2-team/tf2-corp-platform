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
  width: ${({ isOpen }) => (isOpen ? '260px' : '0px')};
  min-width: ${({ isOpen }) => (isOpen ? '260px' : '0px')};
  background-color: #1a1c23;
  color: #e4e6eb;
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
  border-right: 1px solid rgba(255, 255, 255, 0.08);

  @media (max-width: 768px) {
    position: absolute;
    z-index: 100;
    top: 0;
    bottom: 0;
    left: 0;
    box-shadow: 4px 0 20px rgba(0, 0, 0, 0.3);
  }
`;

const Header = styled.div`
  padding: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
`;

const Title = styled.h2`
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: #9ea3b4;
  margin: 0;
`;

const NewChatButton = styled.button`
  margin: 16px;
  padding: 10px 14px;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: transform 0.15s ease, box-shadow 0.15s ease;

  &:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
  }

  &:active {
    transform: translateY(0);
  }
`;

const SessionList = styled.div`
  flex: 1;
  overflow-y: auto;
  padding: 0 12px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;

  &::-webkit-scrollbar {
    width: 4px;
  }
  &::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 2px;
  }
`;

const SessionItem = styled.div<{ active: boolean }>`
  padding: 10px 12px;
  border-radius: 8px;
  background-color: ${({ active }) => (active ? 'rgba(255, 255, 255, 0.1)' : 'transparent')};
  color: ${({ active }) => (active ? '#ffffff' : '#b0b5c6')};
  font-size: 13px;
  font-weight: ${({ active }) => (active ? '600' : '400')};
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: background-color 0.15s ease, color 0.15s ease;
  user-select: none;

  &:hover {
    background-color: rgba(255, 255, 255, 0.07);
    color: #ffffff;
  }
`;

const SessionTitle = styled.span`
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 170px;
`;

const DeleteButton = styled.button`
  background: none;
  border: none;
  color: #83899f;
  font-size: 12px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;

  &:hover {
    color: #ef4444;
    background-color: rgba(239, 68, 68, 0.1);
  }
`;

const Footer = styled.div`
  padding: 14px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 11px;
  color: #717688;
  display: flex;
  flex-direction: column;
  gap: 4px;
`;

const StatusBadge = styled.span`
  display: inline-block;
  padding: 2px 6px;
  background-color: rgba(16, 185, 129, 0.15);
  color: #10b981;
  border-radius: 4px;
  font-weight: 600;
  width: fit-content;
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
        <Title>Chats</Title>
        <StatusBadge>Ready</StatusBadge>
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
        <span>Single-Turn Budget Execution</span>
        <span>Version 2.2.0</span>
      </Footer>
    </SidebarContainer>
  );
};

export default CopilotSidebar;
