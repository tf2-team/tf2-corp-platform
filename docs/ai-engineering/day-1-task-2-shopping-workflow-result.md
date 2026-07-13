# Day 1 Result - Designing Search, Conversation, and Cart Contracts

- **Developer:** AI Engineer 2 - Shopping Workflow
- **Task:** Task 2

## 1. Kết quả

Đã hoàn thành thiết kế và thống nhất cấu trúc của các contract dùng chung cho tính năng tìm kiếm sản phẩm bằng SQL Query, quản lý trạng thái hội thoại nhiều lượt và cơ chế xác nhận giỏ hàng. Kết quả đầu ra này đã sẵn sàng làm tài liệu tham chiếu để triển khai các tính năng A2.1, A2.3 và A2.4 từ Ngày 2.

A2.2 liên quan đến A1.1 (A2.2 cần A1.1 vì Q&A cũng phải có grounding/citation/abstention.) - chưa thực hiện trong task này.

## 2. Quyết định đã chốt

| Hạng mục | Quyết định |
| --- | --- |
| Cấu trúc Search | AI bóc tách yêu cầu thành `query` (bắt buộc), `max_price_usd` (tùy chọn) và `category` (tùy chọn). |
| Cách lọc tìm kiếm | Sử dụng **câu SQL tĩnh viết sẵn** hỗ trợ **lọc động bằng tham số (Dynamic Filtering)** ở phía database, tuyệt đối không dùng AI tự sinh SQL (Text-to-SQL) để tránh lỗi bảo mật. |
| Kết quả tìm kiếm | Trả về danh sách `product_id` thật có trong catalog. Trường hợp không tìm thấy thì trả về danh sách rỗng (không tự bịa sản phẩm). |
| Trạng thái hội thoại | Gắn mã `conversation_id` cho mỗi phiên và lưu thứ tự `product_references` ở backend để phân giải các đại từ chỉ định (ví dụ: "cái đầu tiên"). |
| Quy trình thêm vào giỏ | AI không gọi trực tiếp `CartService.AddItem`. Nó chỉ sinh ra một `pending_action` đi kèm một `token` xác nhận. |
| Quyền kiểm soát giỏ | Chỉ cho phép cập nhật giỏ hàng sau khi backend xác minh `token` hợp lệ (đúng user, đúng sản phẩm/số lượng, chưa bị replay và chưa hết hạn). AI bị cấm hoàn toàn các quyền checkout, empty cart hoặc thanh toán. |

## 3. Contract và ví dụ

### Contract

1. **Cấu trúc tìm kiếm (Mở rộng `SearchProductsRequest` và schema chi tiết trong `pb/demo.proto`):**
   ```protobuf
   message SearchProductsRequest {
       string query = 1;                 // Từ khóa tìm kiếm thô (bắt buộc)
       optional float max_price_usd = 2; // Lọc giá (null = không lọc)
       optional string category = 3;      // Lọc danh mục (null = không lọc)
   }

   message SearchProductsResponse {
       repeated Product results = 1;       // Danh sách các sản phẩm khớp với kết quả lọc
   }

   ```

2. **Cấu trúc quản lý hội thoại (Mở rộng request/response trong `pb/demo.proto`):**
   ```protobuf
   message ProductReference {
       int32 position = 1;        // Thứ tự 1-based (ví dụ: 1 = cái đầu tiên)
       string product_id = 2;
       string product_name = 3;
   }

   message PendingCartAction {
       string token = 1;         // Mã token bảo mật được ký bởi backend
       string product_id = 2;
       int32  quantity = 3;
       int64  expires_at = 4;    // Thời gian hết hạn (Unix timestamp)
   }

   message AskProductAIAssistantRequest {
       string product_id = 1;
       string question = 2;
       string conversation_id = 3;  // Để trống nếu bắt đầu cuộc hội thoại mới
   }

   message AskProductAIAssistantResponse {
       string response = 1;
       string conversation_id = 2;
       repeated ProductReference product_references = 3;
       PendingCartAction pending_action = 4;
       string status = 5; // Trạng thái: "DONE" | "WAITING" | "FALLBACK"
   }
   ```

3. **Cơ chế xác nhận giỏ hàng (Thêm RPC mới vào `ProductReviewService` trong `pb/demo.proto`):**
   ```protobuf
   service ProductReviewService {
       // ... Các RPC cũ ...
       rpc ConfirmCartAction(ConfirmCartActionRequest) returns (ConfirmCartActionResponse){}
   }

   message ConfirmCartActionRequest {
       string user_id = 1;        // Lấy từ session của backend sau khi xác thực
       string conversation_id = 2;
       string token = 3;
   }

   message ConfirmCartActionResponse {
       bool   success = 1;
       string message = 2;
   }
   ```

### Ví dụ

- **Ví dụ 1: Tìm kiếm tự nhiên (Natural-Language Search)**
  - **Đầu vào:** Người dùng gõ *"Tìm kính viễn vọng nào dưới 150 đô"*
  - **Đầu ra:** AI bóc tách được: `query = "telescope"`, `max_price_usd = 150.0`, `category = null`. Database của `product-catalog` thực thi câu lệnh SQL động và chỉ trả về các sản phẩm phù hợp thực tế trong catalog:
    ```json
    {
      "results": [
        { 
          "id": "OLJCESPC7Z", 
          "name": "National Park Foundation Explorascope", 
          "price_usd": { "units": 101, "nanos": 960000000 } //Giá theo format product_catelog trong database
        }
      ]
    }
    ```
  - **Bảng Schema Response của `SearchProductsResponse`:**
    | Tên trường | Kiểu dữ liệu | Mô tả / Schema định dạng |
    | --- | --- | --- |
    | `results` | `repeated Product` | Mảng chứa danh sách các sản phẩm tìm thấy phù hợp bộ lọc. |
    | `results[].id` | `string` | Mã định danh duy nhất của sản phẩm (ví dụ: `OLJCESPC7Z`). |
    | `results[].name` | `string` | Tên sản phẩm hiển thị trên giao diện storefront. |
    | `results[].description` | `string` | Mô tả chi tiết các tính năng kỹ thuật của sản phẩm. |
    | `results[].picture` | `string` | Đường dẫn/tên tệp tin ảnh sản phẩm phục vụ hiển thị. |
    | `results[].price_usd` | `Money` | Đối tượng biểu diễn giá sản phẩm bằng tiền đô la Mỹ (USD). |
    | `results[].price_usd.currency_code` | `string` | Mã tiền tệ ISO 4217, ở đây mặc định luôn là `"USD"`. |
    | `results[].price_usd.units` | `int64` | Phần tiền nguyên chẵn (ví dụ: `101`). |
    | `results[].price_usd.nanos` | `int32` | Phần tiền thập phân lẻ nhân với $10^{-9}$ (ví dụ: `960000000` = 0.96 USD). |
    | `results[].categories` | `repeated string` | Mảng các thẻ tag phân loại của sản phẩm này. |

- **Ví dụ 2: Phân giải tham chiếu ngữ cảnh (Product Reference Resolution)**
  - **Đầu vào:** Người dùng hỏi tiếp *"Cái đó dùng có tốt không?"*
  - **Đầu ra:** AI sử dụng bộ nhớ ngắn hạn và danh sách `product_references` lưu ở lượt trước để nhận diện *"cái đó"* chính là sản phẩm có `product_id = "OLJCESPC7Z"`, sau đó gọi tool đọc review của sản phẩm này.
  - **Bảng Schema Response tương ứng của `AskProductAIAssistantResponse`:**
    | Tên trường | Kiểu dữ liệu | Mô tả / Schema định dạng |
    | --- | --- | --- |
    | `response` | `string` | Câu trả lời của AI dựa trên thông tin review thu thập được từ sản phẩm được chỉ định. |
    | `conversation_id` | `string` | Mã ID định danh phiên hội thoại đang tiếp diễn (ví dụ: `conv-12345`). |
    | `product_references` | `repeated ProductReference` | Danh sách các sản phẩm xuất hiện trong câu trả lời để làm cơ sở cho lượt hỏi tiếp theo. |
    | `product_references[].position` | `int32` | Thứ tự xuất hiện của sản phẩm trong hội thoại (1-based index). |
    | `product_references[].product_id` | `string` | Mã ID thực tế của sản phẩm tham chiếu trong database. |
    | `product_references[].product_name` | `string` | Tên thực tế của sản phẩm được tham chiếu. |
    | `pending_action` | `PendingCartAction` | Trạng thái thêm giỏ hàng chờ xác nhận. Trong lượt hỏi đáp review này, giá trị là `null`. |
    | `status` | `string` | Trạng thái lượt hội thoại, ở đây là `"DONE"`. |

- **Ví dụ 3: Hành động chờ xác nhận giỏ hàng (Pending Cart Action)**
  - **Đầu vào:** Người dùng nói *"Thêm nó vào giỏ hàng giúp tôi"*
  - **Đầu ra:** Giỏ hàng chưa bị thay đổi. AI phản hồi yêu cầu xác nhận cùng mã token:
    ```json
    {
      "response": "Bạn có chắc chắn muốn thêm 1 sản phẩm 'National Park Foundation Explorascope' vào giỏ hàng không?",
      "conversation_id": "conv-12345",
      "status": "WAITING",
      "pending_action": {
        "token": "secure_signed_token_example_123",
        "product_id": "OLJCESPC7Z",
        "quantity": 1,
        "expires_at": 1783940000
      }
    }
    ```
  - **Bảng Schema chi tiết của `PendingCartAction` trong Response:**
    | Tên trường | Kiểu dữ liệu | Mô tả / Schema định dạng |
    | --- | --- | --- |
    | `response` | `string` | Câu thoại AI đề nghị người dùng bấm xác nhận hành động. |
    | `conversation_id` | `string` | Mã phiên hội thoại hiện tại. |
    | `status` | `string` | Ghi nhận trạng thái `"WAITING"` báo hiệu hệ thống đang đợi nút bấm xác nhận từ frontend. |
    | `pending_action` | `PendingCartAction` | Đối tượng mang dữ liệu của hành động ghi đang ở trạng thái chờ duyệt. |
    | `pending_action.token` | `string` | Token ký số chứa thông tin mã hóa an toàn do backend tạo ra để đối chiếu khi xác nhận. |
    | `pending_action.product_id` | `string` | ID sản phẩm mà người dùng đồng ý thêm vào giỏ. |
    | `pending_action.quantity` | `int32` | Số lượng sản phẩm muốn thêm. |
    | `pending_action.expires_at` | `int64` | Mốc thời gian hết hạn của token xác nhận (Unix timestamp tính bằng giây). |

## 4. Tệp và liên kết

- [pb/demo.proto](file:///d:/Xbrain_BT/tf2-corp-platform/pb/demo.proto) (File proto giao tiếp chính để định nghĩa các contract)
- [docs/ai-engineering/day-1-task-2-shopping-workflow-result.md](file:///d:/Xbrain_BT/tf2-corp-platform/docs/ai-engineering/day-1-task-2-shopping-workflow-result.md) (File kết quả này)

## 5. Blockers

- Cần thống nhất với Developer 1 (Trustworthiness) về cách thức truyền nhận `user_id` giữa Frontend và Backend thông qua gRPC (gửi qua metadata context hay định nghĩa field tường minh trong Request) nhằm đảm bảo tính bảo mật và xác thực của user session khi thực hiện `ConfirmCartAction`.
