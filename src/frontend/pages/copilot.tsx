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
  min-height: 650px;
  background-color: #f8fafc;
  position: relative;
  overflow: hidden;
`;

const SidebarToggleButton = styled.button`
  position: absolute;
  top: 14px;
  left: 14px;
  z-index: 50;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);

  &:hover {
    background-color: #f1f5f9;
  }
`;

const ContentArea = styled.div`
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
  padding: 24px 32px;
  max-width: 1100px;
  margin: 0 auto;

  @media (max-width: 768px) {
    padding: 16px;
  }

  &::-webkit-scrollbar {
    width: 6px;
  }
  &::-webkit-scrollbar-thumb {
    background: rgba(0, 0, 0, 0.1);
    border-radius: 3px;
  }
`;

const Header = styled.div`
  margin-bottom: 20px;
`;

const PageTitle = styled.h1`
  font-size: 24px;
  font-weight: 800;
  color: #0f172a;
  margin-bottom: 4px;
`;

const PageSubtitle = styled.p`
  font-size: 14px;
  color: #64748b;
  margin: 0;
`;

const ConversationContainer = styled.div`
  display: flex;
  flex-direction: column;
  gap: 24px;
  margin-bottom: 24px;
`;

const TurnWrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
`;

const UserMessageBubble = styled.div`
  align-self: flex-end;
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  color: #ffffff;
  padding: 12px 18px;
  border-radius: 16px 16px 4px 16px;
  font-size: 15px;
  font-weight: 500;
  max-width: 85%;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.2);
`;

const AIResponseArea = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
`;

const LoadingSkeleton = styled.div`
  padding: 24px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  text-align: center;
  color: #64748b;
  font-size: 14px;
  font-weight: 500;
  animation: pulse 1.5s infinite;

  @keyframes pulse {
    0% {
      opacity: 0.6;
    }
    50% {
      opacity: 1;
    }
    100% {
      opacity: 0.6;
    }
  }
`;

const CopilotContent: React.FC = () => {
  const {
    loading,
    response,
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
      <SidebarToggleButton onClick={() => setSidebarOpen((prev) => !prev)}>
        {sidebarOpen ? '◀ Hide History' : '▶ History'}
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
        <Header style={{ paddingLeft: sidebarOpen ? '0px' : '90px' }}>
          <PageTitle>Shopping Copilot</PageTitle>
          <PageSubtitle>
            Smart Shopping Assistant: Discover products, check grounded reviews, and manage your cart.
          </PageSubtitle>
        </Header>

        <CopilotInput externalQuery={suggestionQuery} />

        <ConversationContainer>
          {currentTurns.map((turn) => (
            <TurnWrapper key={turn.id}>
              <UserMessageBubble>{turn.userMessage}</UserMessageBubble>

              <AIResponseArea>
                <InterpretedCriteria criteria={turn.response.interpretedCriteria} />
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

        {loading && (
          <LoadingSkeleton>
            AI is analyzing your criteria, querying catalog, and validating reviews...
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
        <title>Shopping Copilot - Otel Demo</title>
      </Head>
      <ShoppingCopilotProvider>
        <CopilotContent />
      </ShoppingCopilotProvider>
    </Layout>
  );
};

export default CopilotPage;
