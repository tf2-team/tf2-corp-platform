# ADR-AIE-06: Quyết định Kiến trúc Trust & Safety cho AI Assistant

> Status: Proposed, pending mentor sign-off  
> Owner:  Trần Quang Minh
> Reviewers: AIO Mentor / TF Leader  
> Last updated: 2026-07-20  
> Related docs: `docs/aiops/mandate/MANDATE-06-ai-trust-safety.md`, `AI_MANDATE_6_EVIDENCE.md`

## 1. Tóm tắt (Summary)

Đối với Mandate 06, triển khai kiến trúc "Trust & Safety" nhiều lớp cho tính năng Ask AI (Trợ lý Đánh giá Sản phẩm). Kiến trúc này đảm bảo rằng AI chạy trên một model thực, tuân thủ nghiêm ngặt các đánh giá nguồn (Tính trung thực - Faithfulness), chặn các cuộc tấn công prompt injection, che giấu thông tin định danh cá nhân (PII), và có cơ chế dự phòng (fallback) an toàn khi LLM hoặc mạng gặp sự cố.

ADR này phê duyệt việc lựa chọn model, pipeline guardrail, logic xác thực grounding, cấu hình timeout của Envoy, và bộ kiểm thử (eval) cần thiết cho Mandate 06.

## 2. Vấn đề (Problem)

AI Assistant hiện đang đối mặt với nhiều rủi ro nghiêm trọng có thể ảnh hưởng đến niềm tin vào thương hiệu và an toàn dữ liệu khách hàng:

1. **Hallucination (Bịa đặt):** AI có thể tự tin bịa ra các thông tin (ví dụ: thời lượng pin, giá cả) không hề tồn tại trong các đánh giá gốc. Điều này gây hiểu lầm nghiêm trọng cho khách hàng trước khi ra quyết định mua hàng.
2. **Prompt Injection (Bị dắt mũi):** Kẻ xấu có thể chèn các câu lệnh như *"ignore previous instructions"* vào một đánh giá sản phẩm, khiến AI rò rỉ system prompt hoặc hành xử ngoài dự kiến (ví dụ: hoạt động như một công cụ sinh nội dung độc hại).
3. **PII Leakage (Lộ lọt dữ liệu):** Khách hàng có thể để lại email, số điện thoại hoặc thậm chí thông tin thẻ tín dụng trong đánh giá, những thông tin này có thể bị tóm tắt và phơi bày cho tất cả người dùng, vi phạm nghiêm trọng chính sách bảo mật dữ liệu.
4. **Reliability (Treo hệ thống):** Việc sử dụng LLM mang lại độ trễ cao và tiềm ẩn nhiều lỗi mạng. Một lỗi timeout hoặc vượt quá giới hạn rate limit có thể dẫn đến lỗi 504 Gateway Timeout, làm treo toàn bộ trang sản phẩm và làm gián đoạn luồng mua sắm.

Hệ thống phải chứng minh được tính đáng tin cậy thông qua các bằng chứng có thể tái lập, chứ không chỉ dựa vào những câu trả lời trôi chảy mang tính đối phó.

## 3. Bằng chứng Hiện tại (Current Evidence)

Việc triển khai hiện tại cung cấp các thành phần sau để thực thi Trust & Safety:

| Khu vực (Area) | File | Mục đích (Purpose) |
|---|---|---|
| AI Server | `src/product-reviews/product_reviews_server.py` | Điều phối LLM tool-calling, triển khai xử lý ngoại lệ (exception) và trả về các payload dự phòng an toàn. |
| Grounding Pipeline | `src/product-reviews/grounding.py` | Ép LLM trích dẫn nguồn thông qua `instructor` và xác thực nghiêm ngặt các luận điểm với văn bản gốc. |
| Guardrails | `src/product-reviews/guardrails.py` | Triển khai `presidio-analyzer` để che giấu PII và chặn các nỗ lực prompt injection trước khi chúng đến model. |
| Envoy Proxy | `src/frontend-proxy/envoy.tmpl.yaml` | Kéo dài timeout cho route `/api/product-ask-ai-assistant` lên 60s để hỗ trợ việc thực thi LLM nhiều lượt (multi-turn). |
| Integration Tests | `src/product-reviews/tests/test_integration.py` | Cung cấp bộ kiểm thử tự động cho tính trung thực (faithfulness), che giấu PII, và tỷ lệ chặn tấn công. |

## 4. Quyết định (Decision)

Áp dụng kiến trúc xác thực nhiều lớp hoạt động bên trong service `product-reviews`, đóng vai trò như một proxy nghiêm ngặt nằm giữa yêu cầu của người dùng, cơ sở dữ liệu và nhà cung cấp LLM bên ngoài. Việc này cho phép chúng ta kiểm soát chặt chẽ mọi dữ liệu vào và ra, từ đó ngăn chặn kịp thời các truy vấn rác và phản hồi không hợp lệ trước khi chúng ảnh hưởng đến UI.

### Sơ đồ Kiến trúc (Architecture Diagram)

```mermaid
flowchart TB
    User([User]) -->|Send request| UI[Frontend / UI]

    subgraph Chatbots [Shopping Chatbots]
        PRA[Product Review Assistant<br/>Grounded review summary & Q&A]
        SC[Shopping Copilot<br/>Multi-turn shopping]
    end

    UI -->|Ask Reviews| PRA
    UI -->|Start Shopping| SC

    subgraph Ecom [E-commerce Services]
        Catalog[Product Catalog Service]
        Reviews[(Review Data)]
        Cart[Cart Service]
    end

    subgraph Guardrail [Guardrail Layer]
        LLMGuard[LLM GUARD<br/>Scan Prompt]
        Presidio[Presidio<br/>Detect PII]
    end

    subgraph Cache [Cache Layer]
        Valkey[(Valkey)]
    end

    subgraph Memory [Memory Layer]
        Mem0[(mem0)]
    end

    subgraph LLM [LLM Providers]
        Groq[Groq Cloud]
        Bedrock[AWS Bedrock]
    end

    PRA & SC <-->|Check valid in/output| Guardrail
    PRA & SC -.->|Check cache| Cache
    SC -.->|Load history| Memory
    PRA & SC -->|Invoke LLM| LLM

    SC -.->|Search Products| Catalog
    PRA -.->|Read Reviews| Reviews
    SC -.->|Confirm/Add| Cart
```


![Chatbot Architecture]()

*Sơ đồ trên minh họa kiến trúc Container C4 cho Shopping Chatbots, mô tả chi tiết các luồng dữ liệu tương tác giữa người dùng cuối, các service e-commerce nội bộ, bộ lọc Guardrail và các nhà cung cấp LLM bên ngoài (AWS Bedrock, Groq).*

## 5. Thiết kế Chi tiết (Detailed Design)

### 5.1. Lựa chọn Model & Cấu hình (Model Selection & Configuration)
- **Model:** Groq API (sử dụng model `openai/gpt-oss-20b` hoặc tương tự được cấu hình động thông qua biến môi trường).
- **Lý do:** Mandate 06 nghiêm cấm việc sử dụng mock model. Một API LLM thực sự cung cấp độ trễ (latency), số lượng token giới hạn, và giới hạn rate limit (chẳng hạn như HTTP 429 Too Many Requests) thực tế. Chỉ khi đối mặt với những ràng buộc vận hành thực tế này, chúng ta mới có thể xây dựng và đánh giá chính xác độ tin cậy cũng như cơ chế dự phòng của hệ thống.
- **Tiêu thụ Token:** Sử dụng mode JSON sẽ làm tăng khoảng 10-15% tổng token đầu ra do overhead định dạng, nhưng hoàn toàn xứng đáng với mức độ an toàn dữ liệu mà nó mang lại.

### 5.2. Guardrail & Che giấu PII (Input/Output Safety)
Lớp guardrail hoạt động như một bức tường lửa, chặn yêu cầu trước khi nó đi đến logic điều phối LLM hoặc truy cập cơ sở dữ liệu. Nhờ vậy, tiết kiệm được lượng token vô ích từ các luồng tấn công.

- **Che giấu PII (Data Sanitization):** Sử dụng thư viện NLP `presidio-analyzer` kết hợp với các biểu thức chính quy (regex) dự phòng để nhận diện và che giấu các thông tin nhạy cảm. Tất cả các dữ liệu bao gồm email, số điện thoại, thẻ tín dụng (SSN/CC) sẽ bị ghi đè thành định dạng an toàn `[REDACTED]`. Nếu service Presidio quá tải, cơ chế regex tích hợp sẵn (fallback) sẽ đảm bảo PII vẫn được lọc tự động.
- **Chặn Prompt Injection:** Áp dụng phương pháp phòng vệ sâu (defense-in-depth). Sử dụng danh sách từ khóa bị cấm (deny-list với các cụm từ như "ignore instructions", "developer mode", "system prompt") kết hợp các heuristic của công cụ LLM Guard. Bất kỳ yêu cầu nào dính cờ (flagged) sẽ bị từ chối ngay ở lớp controller, và hệ thống lập tức trả về payload trạng thái `BLOCKED`, tránh lãng phí chi phí API gọi LLM.

### 5.3. Grounding Pipeline (Xác thực Tính Trung thực)
Để tránh bịa đặt, AI không chỉ cần sinh văn bản mà phải chứng minh được mọi luận điểm mà nó đưa ra bằng các minh chứng cụ thể.

- **Structured Output (Đầu ra cấu trúc):** Thay vì sinh ra các đoạn chuỗi không có cấu trúc, sử dụng thư viện `instructor` ép LLM hoạt động ở chế độ `Mode.JSON`. Việc này bắt buộc một lược đồ (schema) đầu ra có kiểu dữ liệu chặt chẽ (`GroundedDraft`). Model phải trả về một mảng các đối tượng `claims` (luận điểm), trong đó mỗi luận điểm đều phải liệt kê rõ `sourceIds` (ID của review gốc mà nó lấy thông tin).
- **Logic Xác thực (`validate_grounded_summary`):** Mỗi `claim` sinh ra không lập tức được hiển thị. Chúng phải đi qua hàm đối chiếu chéo (cross-reference) với văn bản gốc. Quá trình xác thực này sử dụng cả so khớp từ khóa (keyword overlapping) và trích xuất thực thể. Đặc biệt, bất kỳ con số nào (thời lượng pin, mức giá, năm) xuất hiện trong `claim` đều phải nằm trong bài đánh giá gốc.
- **Từ chối trả lời (`ABSTAINED`):** Nếu một claim vi phạm các quy tắc trên (hallucination), nó sẽ âm thầm bị loại bỏ (filtered out). Nếu không có claim nào sống sót sau quá trình xác thực (ví dụ người dùng hỏi "Giá bao nhiêu" trong khi review chỉ nói về "Chất lượng"), AI sẽ tự động từ chối trả lời ("Không có thông tin") thay vì tự sáng tác ra một đáp án sai lệch.

### 5.4. Xử lý Fallback và Timeout (Reliability)
Trong kiến trúc vi dịch vụ, việc gọi các API bên ngoài không bao giờ an toàn tuyệt đối. Mạng có thể đứt, API có thể sập, hoặc quá tải.

- **Envoy Proxy:** Mức timeout mặc định 15 giây của Envoy là quá ngắn cho việc gọi tool nhiều lượt, đặc biệt với các mô hình suy luận lớn. Thiết lập tường minh timeout cho `/api/product-ask-ai-assistant` lên `60s` trong file `envoy.tmpl.yaml` đảm bảo LLM có đủ thời gian hoàn thành tác vụ.
- **Try/Except ở Lớp Service:** Tất cả các lần gọi LLM bên trong `get_ai_assistant_response` đều được bọc trong một khối `try/except`. Khối này bắt triệt để các lỗi `TimeoutError`, `APIConnectionError`, và `RateLimitError` từ phía provider. Khi có lỗi xảy ra, thay vì để traceback ném thẳng ra phía gateway, hệ thống bẫy lỗi và trả về một payload JSON `FALLBACK` tĩnh cực kỳ an toàn. Giao diện (UI) sử dụng payload này để hiển thị một thông báo lỗi thân thiện mà không phá vỡ layout hay treo toàn bộ ứng dụng.

## 6. Các Tùy chọn Đã Cân nhắc (Options Considered)

### Tùy chọn A: Sử dụng AI Gateway quản lý toàn diện (ví dụ: Cloudflare AI Gateway)
Không được chọn cho giai đoạn này.
- **Ưu điểm:** Tích hợp sẵn rate limiting, caching, phân tích dữ liệu, và một số tính năng phát hiện prompt injection mạnh mẽ.
- **Nhược điểm:** Thêm các phụ thuộc hạ tầng mạng bên ngoài, có nguy cơ vượt ngân sách do chi phí trên mỗi request, và làm phức tạp hóa đáng kể quá trình thiết lập môi trường chạy thử cục bộ cho các kỹ sư mới.

### Tùy chọn B: Hoàn toàn dựa vào System Prompt của LLM để đảm bảo an toàn
Không được chọn.
- **Ưu điểm:** Dễ triển khai, không yêu cầu viết bất kỳ dòng code xử lý nào, không làm chậm tốc độ phản hồi.
- **Nhược điểm:** Mức độ an toàn rất thấp và cực kỳ dễ bị jailbreak. System prompt dễ dàng bị vô hiệu hóa bởi các kỹ thuật dắt mũi tinh vi từ người dùng. LLM cũng không thể đảm bảo khả năng che giấu 100% PII trong mọi tình huống.

### Tùy chọn C: Sử dụng nhiều lớp Guardrails + Grounding bằng Python trong nội bộ dự án
Được chọn.
- **Ưu điểm:** Code hoàn toàn minh bạch và có thể review từng dòng. Dễ dàng thực thi và gỡ lỗi cục bộ. Cung cấp sự xác thực mang tính tất định (deterministic validation) cho các con số/luận điểm - một điều mà LLM không bao giờ làm tốt. Phù hợp hoàn hảo với kiến trúc hệ thống hiện tại mà không cần cấp phát thêm hạ tầng mới.
- **Nhược điểm:** Tăng overhead xử lý (thêm từ 50-150ms mỗi request do các thao tác đối chiếu văn bản), tiêu thụ nhiều RAM hơn đôi chút, và đòi hỏi phải liên tục bảo trì, cập nhật các bộ kiểm thử tự động.

## 7. An toàn và Các Mục tiêu Không hướng tới (Safety And Non-Goals)

ADR này rõ ràng **không** phê duyệt:
- Vô hiệu hóa cơ chế mô phỏng sự cố (`flagd`). Hệ thống vẫn phải tương thích với các đợt SRE chaos testing.
- Lưu trữ PII (dữ liệu khách hàng nhạy cảm) đã được giải mã trong log, traces hoặc cơ sở dữ liệu nội bộ.
- Cho phép AI Assistant tự chủ thực hiện các thay đổi trạng thái (ví dụ: tự động thanh toán, xóa sản phẩm khỏi giỏ hàng). Chức năng của Assistant hiện tại được giới hạn nghiêm ngặt ở quyền chỉ-đọc (read-only) đối với các đánh giá sản phẩm.

## 8. Kế hoạch Kiểm chứng (Verification Plan)

Trước khi ADR này được đánh dấu là "Accepted", các bằng chứng (evidence) sau bắt buộc phải được xuất ra và cung cấp chi tiết trong tài liệu đính kèm `AI_MANDATE_6_EVIDENCE.md`:
1. **Eval Tính Trung thực (Faithfulness):** Đòi hỏi tối thiểu 5 test case truyền vào các thông tin nhiễu hoặc sai sự thật. Hệ thống phải chứng minh AI loại bỏ toàn bộ các claim bịa đặt và dũng cảm từ chối trả lời chính xác khi thiếu thông tin.
2. **Eval Injection:** Tối thiểu 5 test case sử dụng các payload jailbreak chuẩn ngành. Hệ thống phải chứng minh guardrail chặn được 100% các đầu vào độc hại trước khi chúng sinh thêm chi phí API.
3. **Eval PII:** Cung cấp ảnh chụp Jaeger traces chứng minh rằng email và số điện thoại đã được chuyển hóa thành `[REDACTED]` hoàn toàn trên đường truyền.
4. **Bằng chứng Fallback:** Cung cấp log hệ thống và ảnh chụp màn hình hiển thị UI fallback an toàn khi model bị hệ thống test cố tình bóp băng thông (timeout) hoặc ép vượt quá giới hạn rate limit.

Lệnh dùng để chạy toàn bộ bộ kiểm thử (eval suite) phục vụ Mandate 06:
```bash
pytest src/product-reviews/tests/test_integration.py -v
```

## 9. Kế hoạch Triển khai (Rollout Plan)

- **Giai đoạn 1 (Phát triển):** Triển khai module grounding thông qua thư viện `instructor`, tích hợp các lớp guardrails `presidio` vào luồng controller, và nâng cấu hình timeout của Envoy proxy.
- **Giai đoạn 2 (Đánh giá nội bộ):** Chạy lệnh `test_integration.py` cục bộ. Liên tục điều chỉnh regex và prompt cho đến khi xác nhận tất cả các metric an toàn đạt điểm tối đa (100%). Chụp màn hình và xuất file lưu trữ bằng chứng trace.
- **Giai đoạn 3 (Review):** Gắn các bằng chứng vào PR, đính kèm Jira ticket, và gửi ADR đã ký tên này để hội đồng AIO Mentor phê duyệt (sign-off) chính thức.

## 10. Checklist cho Reviewer (Reviewer Checklist)

- [ ] Model được sử dụng trong bài test là model thực, có kết nối internet và không phải là model mock giả lập.
- [ ] Luồng Guardrails đảm bảo không bao giờ để lộ lọt hoặc log PII chưa mã hóa.
- [ ] Các nỗ lực Prompt injection đều bị chặn dứt khoát.
- [ ] AI không bịa đặt sự kiện, so khớp chính xác từng con số với đánh giá gốc.
- [ ] Mức Timeout của Envoy được cấu hình phù hợp với khả năng chịu tải của hệ thống.
- [ ] Fallback Payload hoạt động hiệu quả, ngăn chặn treo UI trên diện rộng.
- [ ] Bộ kiểm thử tích hợp (Eval suite) có thể chạy lặp lại được trên môi trường CI/CD và máy dev.

## 11. Ký duyệt (Reviewer Sign-Off)

| Reviewer | Decision | Evidence link/comment | Date |
|---|---|---|---|
| Ngô Thanh Tuấn | Sign-off | Approved | 2026-07-18 |
| Hoàng Huy | Sign-off | Approved | 2026-07-18 |
| Lê Duy Khánh | Sign-off | Approved | 2026-07-18 |

## 12. Hậu quả (Consequences)

**Kết quả tích cực:**
- Mandate 06 hoàn toàn tuân thủ một kiến trúc chuẩn mực: có thể dễ dàng review, đánh giá, bảo trì và chứng minh bằng dữ liệu cụ thể.
- Niềm tin vào thương hiệu được bảo vệ vững chắc khỏi rủi ro AI sinh ảo giác (hallucination) và thảm họa rò rỉ dữ liệu cá nhân khách hàng.
- Độ tin cậy của trang sản phẩm và trải nghiệm người dùng được duy trì liền mạch ngay cả khi phải đương đầu với sự bất ổn mang tính bản chất của các mô hình ngôn ngữ lớn (LLM).

**Sự đánh đổi (Tradeoffs):**
- Ép phản hồi của LLM vào chế độ cấu trúc JSON sẽ tiêu thụ số output token nhiều hơn khoảng 10-15% so với plain text truyền thống.
- Việc thực thi các hàm regex đối chiếu chéo các claim với văn bản gốc tiêu thụ thêm một lượng CPU overhead nhất định tại máy chủ backend Python, làm giảm đôi chút tốc độ sinh phản hồi ban đầu.
