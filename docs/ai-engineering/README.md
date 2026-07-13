# AI Engineering

Tài liệu thuộc phạm vi của AI Engineering cho TechX Corp Platform.

Team tập trung phát triển trải nghiệm mua sắm dùng LLM trên nền các service hiện có, trước mắt tại `src/product-reviews`. Phạm vi bao gồm grounding và citation, guardrails, product discovery, shopping copilot, controlled cart actions, evaluation, resilience và GenAI observability.

## Tài liệu

- [AI Shopping Experience Backlog](./ai-shopping-experience-backlog.md): phạm vi, độ ưu tiên, dependency và acceptance criteria của các workstream AI.
- [Implementation Guide](./implementation-guide.md): hướng dẫn kỹ thuật để chuyển backlog thành thiết kế và implementation trong codebase hiện tại.
- [Eight-Day Implementation Plan](./eight-day-implementation-plan.md): phân công theo ngày, dependency, Definition of Done và các integration checkpoint cuối ngày.

## Ownership boundary

- **AI Engineering:** LLM integration, prompting, tool orchestration, grounding, guardrails, evaluation, model telemetry và AI runtime reliability.
- **Service-owning teams:** business rules và API của catalog, cart, frontend, identity/session và platform infrastructure.
- Thay đổi xuyên service cần được thống nhất với service owner; model không được trở thành nơi thực thi authorization hoặc business invariants.

## Thành phần chính

- `src/product-reviews`: gRPC entry point, review data access và LLM orchestration hiện tại.
- `src/llm`: mock OpenAI-compatible API dùng cho local development và fault scenarios.
- `src/frontend`: UI và API gateway cho Product AI Assistant.
- `pb/demo.proto`: contract gRPC dùng giữa frontend và backend services.

