# Day 1 Result - Define Grounded AI Response and Safety Contract

- **Developer:** Hoàng Huy 
- **Task:** Task 1

## 1. Kết quả

Đã chốt cấu trúc dữ liệu cho câu trả lời AI có dẫn nguồn (Grounded AI Response Contract) và bộ quy tắc an toàn khi xử lý review, tool call, PII (Safety Contract). Hai contract này đủ rõ để Person 1 triển khai A1.2 ở Day 2 và A1.1 ở Day 3-4, đồng thời làm chuẩn chung để Person 2 tham chiếu khi A2.2 (Product Q&A) tái sử dụng cơ chế grounding ở Day 5.

## 2. Quyết định đã chốt

| Hạng mục | Quyết định |
| --- | --- |
| Cấu trúc response | Response gồm 4 field: `answer`, `claims`, `sources`, `status`. Không dùng free-text thuần như hiện tại. |
| Source ID | Sinh bằng `hash(product_id + review_content)`, tạo ở tầng normalize review, không cần sửa `pb/demo.proto` ở giai đoạn này. |
| Điều kiện claim hợp lệ | Mọi claim bắt buộc có tối thiểu 1 `source_id`, và `source_id` đó phải tồn tại trong tập review đã fetch của đúng request. Claim không thỏa bị loại khỏi `answer`. |
| Điều kiện từ chối trả lời | Không còn claim nào pass sau kiểm tra nguồn → trả `status = ABSTAINED`, `claims = []`, không suy đoán thêm. |
| Dữ liệu review | Xử lý như untrusted input, bọc riêng trong khối `REVIEW_DATA` khi đưa vào model, tách khỏi instruction của system prompt. |
| Tool được phép gọi | Giới hạn allow-list `fetch_product_reviews`, `fetch_product_info`; tool argument (`product_id`) phải khớp `product_id` của request gốc, không tin theo model. |
| PII | Loại field `username` khỏi payload gửi model; redact nội dung câu hỏi/review trước khi ghi vào log và trace, không ghi nguyên văn. |
| Cache | Chỉ được cache response có `status = GROUNDED`; không cache `ABSTAINED` hoặc `BLOCKED` (áp dụng khi A1.3 triển khai ở Day 8, ghi nhận ở đây để tránh vi phạm contract sau này). |

## 3. Contract và ví dụ

### Contract

**A. Grounded AI Response Contract**

Response object gồm các field sau:

| Field | Kiểu dữ liệu | Bắt buộc | Mô tả |
| --- | --- | --- | --- |
| `answer` | string | Có | Câu trả lời cuối cùng, chỉ được dựng từ nội dung của các `claims` có trong response. Không được chứa thông tin nằm ngoài `claims`. |
| `claims` | list[Claim] | Có (có thể rỗng) | Danh sách nhận định, mỗi nhận định gắn với nguồn hỗ trợ. |
| `claims[].text` | string | Có | Nội dung một nhận định cụ thể. |
| `claims[].sources` | list[string] | Có, tối thiểu 1 phần tử | Danh sách `source_id` hỗ trợ nhận định này. |
| `sources` | list[Source] | Có | Danh sách toàn bộ review đã dùng làm bằng chứng, dạng `{source_id, product_id}`, dùng để đối chiếu ngược khi validate. |
| `status` | enum | Có | Một trong 3 giá trị: `GROUNDED`, `ABSTAINED`, `BLOCKED`. |

Quy tắc bắt buộc (invariant), đều phải kiểm tra được bằng code:

1. Không có claim mồ côi: mọi `claims[].sources` phải có ít nhất 1 phần tử, không được rỗng.
2. Source phải hợp lệ: mọi `source_id` xuất hiện trong `claims[].sources` phải tồn tại trong `sources` của cùng response, và `sources[].product_id` phải khớp `product_id` của request.
3. `answer` không được vượt phạm vi `claims`: nội dung `answer` chỉ là bản tóm gọn của các `claims` đã pass, không được thêm câu ngoài.
4. `status = GROUNDED` chỉ hợp lệ khi `claims` có ít nhất 1 phần tử pass; `status = ABSTAINED` khi `claims` rỗng do thiếu bằng chứng; `status = BLOCKED` khi bị Safety Contract chặn (khác nguyên nhân với `ABSTAINED`).
5. Không có response nào được trả về phía client nếu chưa đi qua bước validate claim-source; không tồn tại đường tắt bỏ qua bước này kể cả khi debug.

**B. Safety Contract**

Các cam kết dưới đây do backend đảm bảo, không phụ thuộc vào việc model có tuân theo prompt hay không:

| # | Cam kết | Cơ chế đảm bảo |
| --- | --- | --- |
| 1 | Model không được tự đổi `product_id` sang sản phẩm khác | Backend so khớp `product_id` model trả về trong tool call với `product_id` của request gốc; không khớp thì từ chối gọi tool. |
| 2 | Model không được gọi tool ngoài allow-list | Backend kiểm tra tên tool nằm trong danh sách cố định (`fetch_product_reviews`, `fetch_product_info`); tool lạ bị chặn ngay. |
| 3 | Nội dung review/câu hỏi không được model hiểu là instruction | Review được bọc trong khối `REVIEW_DATA` tách biệt khỏi phần chỉ dẫn trong system prompt. |
| 4 | Yêu cầu tiết lộ system prompt không được thực hiện | Backend chặn theo pattern trước khi đưa vào model, không dựa vào việc model tự chối. |
| 5 | Dữ liệu nhạy cảm (PII) không xuất hiện trong log/trace | Lớp redact chạy trước khi ghi telemetry (không redact sau khi đã ghi); loại `username` khỏi payload gửi model vì không cần thiết cho việc tóm tắt. |
| 6 | Response `ABSTAINED` hoặc `BLOCKED` không được cache như kết quả hợp lệ | Logic cache chỉ ghi khi `status = GROUNDED` (áp dụng cho A1.3, ghi nhận trước để tránh vi phạm khi triển khai). |

Ghi chú ranh giới giữa 2 contract: Grounded Response Contract trả lời "câu trả lời có đúng với dữ liệu nguồn không", Safety Contract trả lời "hệ thống có bị lợi dụng vượt phạm vi không". Một response có thể đúng dữ liệu (`GROUNDED`) nhưng vẫn vi phạm Safety Contract nếu quá trình lấy dữ liệu đó đã gọi sai tool — vì vậy backend phải chạy kiểm tra cả 2 tầng độc lập nhau trong cùng một request, không tầng nào thay thế được tầng còn lại.

### Ví dụ

**Ví dụ 1 - Câu trả lời có nguồn (GROUNDED)**

- **Đầu vào:** `product_id = P001`, câu hỏi "Pin sản phẩm này thế nào?". Review có trong hệ thống: `review-a1f3` ("Pin dùng tốt, dùng cả ngày không hết"), `review-9c02` ("Máy hơi nặng nhưng cầm chắc tay").
- **Đầu ra:**

```json
{
  "answer": "Review cho biết pin dùng tốt, dùng được cả ngày.",
  "claims": [
    {
      "text": "Pin dùng tốt, dùng được cả ngày",
      "sources": ["review-a1f3"]
    }
  ],
  "sources": [
    {"source_id": "review-a1f3", "product_id": "P001"}
  ],
  "status": "GROUNDED"
}
```

**Ví dụ 2 - Từ chối trả lời vì thiếu bằng chứng (ABSTAINED)**

- **Đầu vào:** `product_id = P001`, câu hỏi "Pin dùng được bao nhiêu giờ?". Cùng tập review ở trên, không có review nào nêu con số giờ cụ thể.
- **Đầu ra:**

```json
{
  "answer": "Các review hiện tại chưa cung cấp thông tin cụ thể về số giờ pin.",
  "claims": [],
  "sources": [],
  "status": "ABSTAINED"
}
```

Đối chiếu với invariant 4: model không được tự suy ra một con số giờ cụ thể (ví dụ "20 giờ") vì không có `source_id` nào hỗ trợ, nên response bắt buộc rơi vào `ABSTAINED` thay vì `GROUNDED` với claim bịa.

## 4. Tệp và liên kết

- `<document-or-commit-link>` — file contract này sẽ được đính kèm vào ClickUp Task 1 và merge vào branch `aie` theo checkpoint Day 1.

## 5. Blockers

- Không có.
