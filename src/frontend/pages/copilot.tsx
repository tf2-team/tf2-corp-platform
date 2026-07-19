// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React, { useState } from 'react';
import { NextPage } from 'next';
import Head from 'next/head';
import styled from 'styled-components';
import Layout from '../components/Layout';
import {
  ShoppingCopilotProvider,
  useShoppingCopilot,
} from '../providers/ShoppingCopilot.provider';
import {
  CopilotInput,
  InterpretedCriteria,
  CopilotProductCard,
  CopilotClaims,
  CopilotCartConfirm,
  CopilotStateMessage,
  CopilotSidebar,
} from '../components/ShoppingCopilot';

const MainWrapper = styled.div`
  display: flex;
  height: calc(100vh - 120px);
  min-height: 680px;
  background-color: #f8fafc;
  position: relative;
  overflow: hidden;
`;

const SidebarToggleButton = styled.button<{ isOpen: boolean }>`
  position: absolute;
  top: 16px;
  left: ${({ isOpen }) => (isOpen ? '296px' : '16px')};
  z-index: 50;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  display: flex;
  align-items: center;
  gap: 6px;

  &:hover {
    background-color: #f1f5f9;
    color: #0f172a;
    border-color: #94a3b8;
  }
`;

const ContentArea = styled.div`
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
  padding: 24px 32px;
  max-width: 1080px;
  margin: 0 auto;
  width: 100%;

  @media (max-width: 768px) {
    padding: 16px;
  }

  &::-webkit-scrollbar {
    width: 6px;
  }
  &::-webkit-scrollbar-thumb {
    background: #cbd5e1;
    border-radius: 3px;
  }
`;

const Header = styled.div`
  margin-bottom: 24px;
  padding-top: 10px;
  transition: padding-left 0.25s ease;
`;

const TitleBadge = styled.span`
  display: inline-block;
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  padding: 3px 10px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  margin-bottom: 8px;
`;

const PageTitle = styled.h1`
  font-size: 28px;
  font-weight: 800;
  color: #0f172a;
  margin: 0 0 6px 0;
  letter-spacing: -0.5px;
`;

const PageSubtitle = styled.p`
  font-size: 14.5px;
  color: #64748b;
  margin: 0;
  line-height: 1.5;
`;

const ConversationContainer = styled.div`
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-bottom: 24px;
`;

const TurnWrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.03);
`;

const UserMessageHeader = styled.div`
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
`;

const Timestamp = styled.span`
  font-size: 11px;
  color: #94a3b8;
`;

const UserMessageBubble = styled.div`
  align-self: flex-end;
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  color: #ffffff;
  padding: 12px 20px;
  border-radius: 18px 18px 4px 18px;
  font-size: 15px;
  font-weight: 500;
  max-width: 80%;
  box-shadow: 0 3px 10px rgba(37, 99, 235, 0.2);
  line-height: 1.5;
`;

const AIResponseArea = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
`;

const LoadingSkeleton = styled.div`
  padding: 20px 24px;
  background: #ffffff;
  border: 1px solid #93c5fd;
  border-radius: 14px;
  text-align: center;
  color: #1d4ed8;
  font-size: 14px;
  font-weight: 600;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.08);
  animation: pulse 1.5s infinite;

  @keyframes pulse {
    0% {
      opacity: 0.7;
    }
    50% {
      opacity: 1;
    }
    100% {
      opacity: 0.7;
    }
  }
`;

const EmptyState = styled.div`
  text-align: center;
  padding: 40px 20px;
  background: #ffffff;
  border: 1px dashed #cbd5e1;
  border-radius: 16px;
  color: #64748b;
  margin-bottom: 24px;
`;

const EmptyTitle = styled.h3`
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 8px 0;
`;

const EmptyDesc = styled.p`
  font-size: 14px;
  color: #64748b;
  margin: 0;
`;

const CopilotContent: React.FC = () => {
  const {
    loading,
    sessions,
    activeSessionId,
    currentTurns,
    createNewSession,
    selectSession,
    deleteSession,
    searchCopilot,
  } = useShoppingCopilot();

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [suggestionQuery, setSuggestionQuery] = useState<string | undefined>();

  const handleSuggestionClick = (text: string) => {
    setSuggestionQuery(text);
    searchCopilot(text);
  };

  return (
    <MainWrapper>
      <SidebarToggleButton
        isOpen={sidebarOpen}
        onClick={() => setSidebarOpen((prev) => !prev)}
      >
        {sidebarOpen ? '◀ Hide History' : '▶ Show History'}
      </SidebarToggleButton>

      <CopilotSidebar
        isOpen={sidebarOpen}
        sessions={sessions.map((s) => ({
          id: s.id,
          title: s.title,
          timestamp: s.createdAt,
        }))}
        activeSessionId={activeSessionId}
        onNewChat={createNewSession}
        onSelectSession={selectSession}
        onDeleteSession={deleteSession}
      />

      <ContentArea>
        <Header style={{ paddingLeft: sidebarOpen ? '0px' : '100px' }}>
          <TitleBadge>AI Assistant v2.2</TitleBadge>
          <PageTitle>Shopping Copilot</PageTitle>
          <PageSubtitle>
            Smart Shopping Assistant: Discover products, check grounded reviews, and manage your cart.
          </PageSubtitle>
        </Header>

        <CopilotInput externalQuery={suggestionQuery} />

        {currentTurns.length === 0 ? (
          <EmptyState>
            <EmptyTitle>Start a New Conversation</EmptyTitle>
            <EmptyDesc>
              Select a sample prompt above or type your request to start discovering products.
            </EmptyDesc>
          </EmptyState>
        ) : (
          <ConversationContainer>
            {currentTurns.map((turn) => (
              <TurnWrapper key={turn.id}>
                <UserMessageHeader>
                  <Timestamp>{turn.timestamp}</Timestamp>
                </UserMessageHeader>
                <UserMessageBubble>{turn.userMessage}</UserMessageBubble>

                <AIResponseArea>
                  <CopilotStateMessage
                    response={turn.response}
                    onSuggestionClick={handleSuggestionClick}
                  />
                  <CopilotCartConfirm pendingToken={turn.response.pendingActionToken} />
                  <CopilotProductCard products={turn.response.products} />
                  <CopilotClaims
                    claims={turn.response.claims}
                    sources={turn.response.sources}
                  />
                </AIResponseArea>
              </TurnWrapper>
            ))}
          </ConversationContainer>
        )}

        {loading && (
          <LoadingSkeleton>
            Analyzing criteria, querying catalog, and validating reviews...
          </LoadingSkeleton>
        )}
      </ContentArea>
    </MainWrapper>
  );
};

const CopilotPage: NextPage = () => {
  return (
    <Layout>
      <Head>
        <title>Shopping Copilot - TechX Corp Platform</title>
      </Head>
      <ShoppingCopilotProvider>
        <CopilotContent />
      </ShoppingCopilotProvider>
    </Layout>
  );
};

export default CopilotPage;
