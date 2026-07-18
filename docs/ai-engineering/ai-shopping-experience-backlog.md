# AI Shopping Experience Backlog

> Owner: AI Engineering. Xem [AI Engineering overview](./README.md), [Implementation Guide](./implementation-guide.md), [Eight-Day Implementation Plan](./eight-day-implementation-plan.md) và [Mem0 Self-Hosted Deployment Handoff](./mem0-self-hosted-deployment-handoff.md).

Tài liệu này là backlog ưu tiên cho phần AI Shopping Experience, viết để mentor review hướng triển khai và thứ tự ưu tiên. Nội dung bám vào codebase hiện tại, các service đang có, các rủi ro nhìn thấy trong luồng `product-reviews`, `product-catalog`, `cart`, frontend, telemetry và LLM integration.

Phạm vi gồm hai workstream:

- **A1 - Trustworthy AI foundation:** làm cho AI review summary/Q&A có bằng chứng, an toàn trước prompt injection/PII, và không kéo hỏng product page khi LLM lỗi.
- **A2 - Shopping Copilot capability:** mở rộng AI assistant thành copilot mua sắm có thể tìm sản phẩm, hỏi review, chuẩn bị add-to-cart có xác nhận, và hỗ trợ hội thoại nhiều lượt trong execution budget rõ ràng.

## 1. Executive Summary

Ưu tiên cao nhất không phải là "làm chat bot thông minh hơn", mà là bảo vệ các invariant trước khi mở rộng capability:

1. **AI không được nói sai có vẻ chắc chắn.** Review summary và Q&A cần bám vào review thật, có citation hoặc biết abstain khi thiếu evidence.
2. **AI không được tự ý ghi vào giỏ hàng.** `CartService.AddItem` là write action nên phải được backend kiểm soát bằng confirmation.
3. **AI không được làm hỏng luồng duyệt/tìm sản phẩm.** LLM là dependency best-effort nên phải có timeout, fallback, cache và metric.
4. **Mọi dữ liệu người dùng/review phải được xem là untrusted.** Review là user-generated content, có thể chứa prompt injection hoặc PII.

Thứ tự dưới đây ưu tiên các việc giảm rủi ro trực tiếp trước, sau đó mới mở rộng UX nhiều lượt.

## 2. Current State

### Luồng AI hiện tại

- Entry point chính là `src/product-reviews/product_reviews_server.py`.
- `AskProductAIAssistant` nhận `product_id` và `question`, gọi LLM một lần để chọn tool, backend execute tool, rồi gọi LLM lần hai để tạo final answer.
- Tool registry hiện có `fetch_product_reviews` và `fetch_product_info`.
- Response gRPC hiện chỉ có text thuần qua `AskProductAIAssistantResponse.response`.
- Frontend `ProductAIAssistant.provider.tsx` chỉ giữ một `aiResponse`, chưa có conversation state.

### Gaps chính

| Gap | Hậu quả | Backlog xử lý |
| --- | --- | --- |
| Final LLM response trả thẳng, chưa validate claim/citation. | AI có thể hiển thị claim sai hoặc không có bằng chứng. | A1.1, A2.2 |
| Review/question/log đang chứa raw content. | Prompt injection, system prompt leak, PII lọt vào LLM/logs/traces. | A1.2 |
| LLM call chưa có timeout, retry budget, fallback, cache. | Dependency AI chậm/lỗi có thể kéo product page xuống. | A1.3 |
| Product search chỉ `LIKE`, chưa parse intent/filter/rank theo điều kiện tự nhiên. | Copilot dễ trả kết quả kém hoặc bịa sản phẩm khi không có catalog result. | A2.1 |
| AI chưa có pending action/confirmation token cho cart. | Có nguy cơ write vào cart trước khi user xác nhận. | A2.3 |
| Chưa có `conversation_id`, product references, bounded agent loop. | Không resolve được "cái đầu tiên", có nguy cơ tool loop quá budget. | A2.4 |

### Thành phần nên tận dụng

- `ProductReviewService.AskProductAIAssistant` làm entry point ban đầu cho A1/A2.
- `database.fetch_product_reviews_from_db` làm nguồn evidence.
- `ProductCatalogService.SearchProducts` đã có trong proto và Go service.
- Tool calling flow hiện có trong `product_reviews_server.py`.
- `CartService.AddItem` chỉ dùng sau backend confirmation.
- Valkey hiện có dùng lại cho AI cache và pending action bằng namespace riêng.
- Mem0 dùng cho short-term/session memory của Shopping Copilot.
- OpenTelemetry, Prometheus, Jaeger, Grafana, OpenSearch đã có sẵn cho metric/log/trace.

## 3. Priority And Dependency Map

Thứ tự ưu tiên dưới đây đi từ nền tảng an toàn nhất đến các capability phức tạp hơn: trước hết làm cho AI trả lời đúng và an toàn, sau đó mới cho agent tìm sản phẩm, hỏi tiếp, chuẩn bị thao tác giỏ hàng và xử lý hội thoại nhiều lượt.

| Rank | Item | Priority | Depends on | Reason |
| --- | --- | --- | --- | --- |
| 1 | A1.1 Verified Summarization, Grounding, and Citations | P1 | None | Làm đầu tiên để AI không trả lời bịa hoặc thiếu bằng chứng. Nếu phần này chưa ổn, các feature sau cũng sẽ trả lời không đáng tin. |
| 2 | A1.2 Prompt Injection, PII, and Tool Guardrails | P1 | None | Làm sớm để chặn input độc hại, PII và tool call sai trước khi agent được quyền gọi thêm service. Có thể làm song song với A1.1. |
| 3 | A2.1 Natural Language Product Discovery | P1 | A1.2 | Đây là bước đầu của Shopping Copilot: tìm sản phẩm thật và lấy product ID. Các bước Q&A và cart đều cần kết quả này. |
| 4 | A2.2 Review-Grounded Product Q&A | P1 | A1.1, A2.1 | Làm sau khi đã có product ID thật và cơ chế grounding. Như vậy câu trả lời vừa đúng sản phẩm, vừa bám vào review thật. |
| 5 | A2.3 Confirmation-Controlled Cart Actions | P1 | A1.2, A2.1 | Cart là hành động ghi dữ liệu nên phải làm sau guardrail và sau khi search trả về product ID đáng tin. Agent chỉ chuẩn bị action, user phải xác nhận. |
| 6 | A1.3 Resilience and Cost Optimization | P2 | A1.1, A1.2 | Làm sau khi response đã được kiểm tra đúng/an toàn, vì cache và fallback không nên lưu hoặc tối ưu câu trả lời chưa được validate. |
| 7 | A2.4 Multi-Turn Conversation and Bounded Orchestration | P2 | A2.1, A2.2, A2.3 | Làm cuối vì multi-turn cần search, Q&A và cart action đơn lượt chạy ổn trước. Sau đó mới thêm memory, reference resolution và giới hạn loop. |

### Dependency Notes

- **A1.1 và A1.2 có thể làm song song.** Một bên xử lý độ đúng của câu trả lời, một bên xử lý an toàn input/tool/telemetry.
- **A2.1 cần A1.2** vì search tool mở rộng bề mặt tương tác của agent.
- **A2.2 cần A1.1** vì Q&A cũng phải có grounding/citation/abstention.
- **A2.3 cần A2.1** vì cart action phải gắn với product ID đáng tin.
- **A2.4 không nên làm đầu tiên** vì multi-turn state sẽ phức tạp hơn nếu search, Q&A và cart confirmation chưa ổn.

## 4. Backlog Items

### A1.1 - Verified Summarization, Grounding, and Citations

**Why:** Người dùng cần tin rằng câu trả lời AI dựa trên review thật, không phải model tự suy diễn. Nếu AI đưa claim sai nhưng nghe chắc chắn, feature sẽ làm giảm trust.

**What:** AI response về review phải có bằng chứng từ review gốc. Khi không có đủ evidence, hệ thống phải nói rõ là không đủ thông tin thay vì đoán.

**Acceptance Criteria:**

- AI answer chỉ chứa claim có evidence hợp lệ từ review.
- Response có citation hoặc nguồn tham chiếu đủ để kiểm tra lại.
- Câu hỏi không có evidence phải trả abstention.
- Có eval set cố định để so sánh trước/sau.
- Có repro script để chạy lại eval factuality, citation correctness và abstention.

**Reuse / Open-source:**

- Tận dụng `fetch_product_reviews_from_db` và tool `fetch_product_reviews` hiện có làm nguồn evidence.
- Dùng **Instructor + Pydantic** để ép structured output cho answer, claims và citations.
- Dùng **Ragas** cho offline eval grounding/hallucination; không đưa eval framework vào runtime path.

### A1.2 - Prompt Injection, PII, and Tool Guardrails

**Why:** Review và câu hỏi người dùng là untrusted input. Nếu không có guardrail, nội dung độc hại có thể khiến AI bỏ qua policy, lộ prompt, đổi tool argument, hoặc ghi log dữ liệu nhạy cảm.

**What:** Thêm guardrail cho input, output, tool call và telemetry. Backend phải kiểm soát tool nào được gọi, dữ liệu nào được gửi đi, và nội dung nào được phép log/trace.

**Acceptance Criteria:**

- Tool ngoài allow-list bị từ chối.
- Tool argument sai phạm vi bị từ chối.
- PII không xuất hiện nguyên văn trong log/trace/LLM request.
- Yêu cầu lộ system prompt hoặc override policy bị chặn.
- Có repro cases cho prompt injection, PII leakage và system prompt leakage.

**Reuse / Open-source:**

- Tận dụng allow-list tool hiện có trong `product_reviews_server.py` và mở rộng validation ở backend.
- Dùng **Presidio** cho PII detection/redaction.
- Dùng **LLM Guard** cho prompt injection, system prompt extraction và output leakage scanning.
- Tận dụng OpenTelemetry hiện có, nhưng chỉ emit metadata an toàn thay vì raw prompt/message.

### A2.1 - Natural Language Product Discovery

**Why:** Shopping Copilot cần giúp người dùng tìm sản phẩm bằng ngôn ngữ tự nhiên. Tuy nhiên kết quả phải đến từ catalog thật, không được bịa sản phẩm.

**What:** Cho phép người dùng mô tả nhu cầu như giá, category, feature. Trong MVP, AI chỉ bóc tách câu tự nhiên thành các trường có cấu trúc an toàn như `query`, `max_price`, `category`; backend dùng các filter SQL viết sẵn trên catalog thật và trả kết quả có product ID thật. Không dùng Text-to-SQL trong MVP.

**Acceptance Criteria:**

- Query tự nhiên trả về danh sách sản phẩm từ catalog.
- Điều kiện quan trọng như giá hoặc category được áp dụng đúng.
- No-results không sinh sản phẩm giả.
- Kết quả có product ID để dùng tiếp cho Q&A hoặc cart action.
- Có repro cases cho natural-language search, constraint matching và no-results.

**Reuse / Open-source:**

- Tận dụng `ProductCatalogService.SearchProducts` làm entry point/search boundary hiện có, nhưng phải mở rộng request/implementation để hỗ trợ structured filters.
- Tận dụng `product_catalog_stub` đã có trong `product-reviews` để gọi catalog service sau khi proto/stub được regenerate theo request mới.
- Dùng **Instructor + Pydantic** để structured intent parsing với các trường cố định/optional như `query`, `max_price`, `category`.
- Mở rộng `SearchProductsRequest` và `product-catalog` bằng dynamic filtering viết sẵn ở SQL.
- Tận dụng OpenTelemetry/logging hiện có để trace safe metadata cho search tool call.

### A2.2 - Review-Grounded Product Question Answering

**Why:** Sau khi tìm thấy sản phẩm, người dùng cần hỏi các câu cụ thể về trải nghiệm thực tế từ review. Câu trả lời phải bám vào review và biết từ chối khi không có evidence.

**What:** Trả lời câu hỏi về sản phẩm dựa trên review của sản phẩm đó, dùng cùng nguyên tắc grounding/citation/abstention của A1.1.

**Acceptance Criteria:**

- Câu trả lời về sản phẩm có evidence từ review.
- Không đủ evidence thì trả abstention.
- Không dùng review của sản phẩm khác.
- Có test cho supported question, unsupported question, và wrong-product case.
- Có repro cases cho grounded QA, unsupported question và wrong-product answer.

**Dependencies:**

- Phụ thuộc A1.1 cho grounding/citation/abstention.
- Phụ thuộc A2.1 để có product ID đáng tin từ catalog search.

**Reuse / Open-source:**

- Tái sử dụng grounding pipeline của A1.1, không viết validator riêng cho Q&A.
- Tận dụng review data và tool `fetch_product_reviews` hiện có.

### A2.3 - Confirmation-Controlled Cart Actions

**Why:** Thêm vào giỏ là write action. AI không được tự ý thay đổi giỏ hàng chỉ vì model hiểu nhầm hoặc bị prompt injection.

**What:** AI chỉ được chuẩn bị hành động thêm vào giỏ và yêu cầu người dùng xác nhận. Backend chỉ thực hiện thay đổi sau khi confirmation hợp lệ.

**Acceptance Criteria:**

- Cart không thay đổi trước confirmation.
- Confirmation chỉ áp dụng cho đúng user, đúng product, đúng quantity.
- Confirmation hết hạn hoặc dùng lại không tạo thêm write.
- AI không có quyền checkout, empty cart, payment hoặc refund.
- Có repro cases chứng minh cart không thay đổi trước confirmation và replay/expired confirmation bị reject.

**Dependencies:**

- Phụ thuộc A1.2 để có guardrail và tool-scope enforcement.
- Phụ thuộc A2.1 để có product ID đáng tin.

**Reuse / Open-source:**

- Tận dụng `CartService.AddItem` hiện có; không tạo cart write path riêng.
- Tận dụng Valkey hiện có cho pending action/confirmation state.
- Dùng Python standard library cho token/signing logic, không cần dependency mới cho phần này.
- Tận dụng OpenTelemetry/logging hiện có để audit safe metadata cho cart tool call và confirmation result.

### A1.3 - Resilience and Cost Optimization

**Why:** AI là best-effort dependency. Lỗi hoặc độ trễ từ LLM không được làm hỏng product page, và các request lặp lại không nên tốn chi phí sinh lại không cần thiết.

**What:** Thêm timeout, fallback, cache cho response hợp lệ, và metric để theo dõi latency, fallback, cache hit/miss, lỗi guardrail và lỗi grounding.

**Acceptance Criteria:**

- LLM lỗi hoặc timeout thì user nhận fallback an toàn.
- Product page không fail chỉ vì AI dependency lỗi.
- Chỉ cache response đã qua validation.
- Có metric cho latency, fallback, cache và validation result.
- Có repro cases cho timeout, rate limit, fallback và cache behavior.

**Dependencies:**

- Phụ thuộc A1.1 vì chỉ cache response đã qua grounding.
- Phụ thuộc A1.2 vì guardrail result là một phần của cache/metric decision.

**Reuse / Open-source:**

- Tận dụng OpenTelemetry/Prometheus/Grafana hiện có cho metric.
- Tận dụng Valkey hiện có cho AI cache.
- Dùng **Tenacity** cho retry/backoff.
- Dùng **valkey-py** để service Python kết nối Valkey.

### A2.4 - Multi-Turn Conversation and Bounded Orchestration

**Why:** Người dùng sẽ hỏi tiếp bằng các tham chiếu như "cái đầu tiên" hoặc "thêm sản phẩm đó". Cần conversation state, nhưng agent không được chạy vòng lặp không giới hạn.

**What:** Dùng **LangGraph** để điều phối multi-turn/tool-calling flow có giới hạn rõ về số vòng, số tool call và deadline. LangGraph state lưu kết quả trung gian của các loop trong cùng một câu hỏi của user, như tool outputs, product candidates, selected product references và pending action. Dùng **Mem0** cho short-term/session memory để resolve ngữ cảnh hội thoại qua nhiều lượt.

**Acceptance Criteria:**

- Hệ thống resolve được reference trong cùng conversation.
- LangGraph state lưu được intermediate results trong phạm vi một user turn/request và không trở thành nguồn truth thay catalog/review.
- Mem0 short-term memory lưu được conversational context trong session hiện tại và được cách ly theo user/session.
- Agent có giới hạn rounds/tool calls/deadline.
- Khi vượt budget, hệ thống fallback thay vì tiếp tục gọi tool.
- Có repro cases cho reference resolution, loop limit và budget exceeded.

**Dependencies:**

- Phụ thuộc A2.1 để có product references từ search.
- Phụ thuộc A2.2 để Q&A nhiều lượt vẫn grounded.
- Phụ thuộc A2.3 để pending cart action được giữ an toàn qua nhiều lượt.

**Reuse / Open-source:**

- Dùng **LangGraph** cho agent orchestration, graph state, bounded loops và tool-calling control flow.
- Dùng **Mem0** cho short-term/session memory trong MVP; long-term memory chỉ cân nhắc sau nếu CDO hoàn thành login/user identity, kèm retention/privacy policy và không thay thế catalog/review làm nguồn truth.
- Tận dụng OpenTelemetry/logging hiện có để trace safe metadata cho mỗi tool call trong orchestration.

## 5. Proposed Delivery Order

### Phase 1 - Trustworthy Single-Turn Foundation

1. A1.1 Verified Summarization, Grounding, and Citations
2. A1.2 Prompt Injection, PII, and Tool Guardrails

Outcome: AI review answer đáng tin hơn và an toàn hơn trước khi mở rộng tool/capability.

### Phase 2 - Shopping Copilot MVP

1. A2.1 Natural Language Product Discovery
2. A2.2 Review-Grounded Product Q&A
3. A2.3 Confirmation-Controlled Cart Actions

Outcome: Người dùng có thể tìm sản phẩm, hỏi review, và chuẩn bị thêm vào giỏ qua confirmation flow.

### Phase 3 - Hardening And Multi-Turn

1. A1.3 Resilience and Cost Optimization
2. A2.4 Multi-Turn Conversation and Bounded Orchestration

Outcome: Luồng AI ổn định hơn, quan sát được tốt hơn, và hỗ trợ hội thoại nhiều lượt trong giới hạn an toàn.
