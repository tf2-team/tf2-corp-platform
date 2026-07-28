# 5. Danh sách câu hỏi kèm câu trả lời (chuẩn bị cho buổi báo cáo)

Câu hỏi được soạn dựa trên nội dung Section 1–4 + thuật ngữ hay bị hỏi lại trong các buổi trao đổi trước. Không có nội dung buổi hỏi cụ thể trước đó để tham chiếu — nếu có câu hỏi thực tế đã hỏi mà chưa nằm trong danh sách này, bổ sung thêm vào cuối file.

## 5.1 Về evaluation / số liệu

**Q: "Research dataset" ở đây là bộ nào, có phải NAB không?**
A: Không phải NAB (Numenta Anomaly Benchmark). Hệ thống hiện dùng bộ **RE2-SS** (120 case dạng `<service>_<metric>/case/simple_metrics.csv`), nằm trong `evaluate/dataset/RE2-SS`. Topology tự ghi rõ `nab_mapping: N/A` — NAB chưa được tích hợp.

**Q: Vì sao incident precision/recall trên research dataset luôn là 1.0? Có phải engine hoàn hảo không?**
A: Không. Dataset RE2-SS không có case "bình thường" (no-incident) — mọi case đều được coi là có incident, nên `TN`/`FP` ở mức incident luôn bằng 0 một cách cấu trúc. Chỉ số này không chứng minh engine không có false positive; chỉ số đáng tin hơn là **RCA top-K hit-rate** (85% với engine thật, so với 30.8% baseline cũ).

**Q: Vì sao RCA top-K precision (0.17) thấp hơn nhiều so với recall (0.86)?**
A: Vì top-K thường chứa đúng service cần tìm **cộng thêm** vài service khác không liên quan — đây là đặc điểm thiết kế của bài toán ranking (trả nhiều candidate để tăng recall), không phải lỗi.

**Q: Số liệu Mandate 7b (precision 66.7–100%) đã submit có đáng tin chưa?**
A: Chưa dùng để báo cáo chính thức. Khi đối chiếu với raw audit log, phát hiện detector `rca_root_cause` sinh nhiều false positive không được tính vào mẫu số, và state của các scenario bị lẫn nhau. Đang chạy lại 4 scenario cách ly hoàn toàn (checkout, cart, burn-rate, ad-CPU) để có số liệu sạch — sẽ cập nhật khi xong.

**Q: Lead-time 196.7s có nhanh không, tính từ đâu tới đâu?**
A: Lead-time = thời điểm detector fire đầu tiên trừ thời điểm fault bắt đầu (không phải từ lúc user report). ~196.7s là trung bình 2 case (checkout 205.4s, cart 187.9s) trong lần đo v1 — con số này cũng đang được đo lại cùng đợt rerun 4 scenario.

## 5.2 Về thu thập dữ liệu / topology

**Q: Vì sao scrape interval là 1s, có tốn tài nguyên Prometheus không?**
A: 1s là cấu hình thật xuyên suốt (`prometheus-config.yaml`, OTel collector, app SDK export interval) để phục vụ mục tiêu phát hiện nhanh (lead-time thấp) trong môi trường demo/thử nghiệm. Với hệ thống production thật cần cân nhắc lại chi phí lưu trữ/cardinality nếu áp dụng nguyên interval này — đây là điểm CDO cần tối ưu.

**Q: AIOps có tự query Jaeger/OpenSearch liên tục để theo dõi không?**
A: Không. Jaeger/OpenSearch/Kubernetes API chỉ được query **on-demand**, sau khi đã có candidate event, để kiểm soát chi phí và tránh lộ dữ liệu nhạy cảm (log có thể chứa PII). Đây gọi là **on-demand enrichment**.

**Q: Nếu Prometheus mất dữ liệu (missing/stale) thì AIOps coi hệ thống là khỏe hay lỗi?**
A: Không bao giờ coi missing/stale là "khỏe". Đây là nguyên tắc cứng: thiếu dữ liệu tạo ra 1 loại incident riêng gọi là **monitoring-data incident**, tách biệt với incident dịch vụ thật.

**Q: Vì sao cần cả Grafana hard-rule webhook và Prometheus polling, không dùng 1 nguồn thôi?**
A: Grafana hard-rule đảm bảo alert SLO chính thức **không phụ thuộc vào AIOps** — nếu AIOps crash/mất PVC, Grafana vẫn bắn alert trực tiếp cho on-call. AIOps polling Prometheus dùng để làm phần "hiểu sâu hơn": correlation, RCA, enrichment, mà Grafana rule đơn thuần không làm được.

## 5.3 Về danh sách service/metrics

**Q: Vì sao không cần điền tham số bucket khi đưa metric cho CDO?**
A: CDO chỉ cần biết **tên metric gốc** (ví dụ `rpc_server_duration_milliseconds_bucket`) để cấu hình scrape/remote-write; câu truy vấn `histogram_quantile(...)` với `le` bucket là logic tính toán phía AIOps, không cần lặp lại trong danh sách bàn giao.

**Q: Vì sao tên metric khác nhau giữa các service (http vs grpc vs traces_span_metrics)?**
A: Vì các service dùng SDK/ngôn ngữ khác nhau: `cart` (.NET, HTTP) phát `http_server_request_duration_seconds_*`; `checkout`/`product-catalog`/`ad` (gRPC native) phát `rpc_server_duration_milliseconds_*`; các service còn lại đi qua **spanmetrics connector** của OTel Collector nên phát `traces_span_metrics_*`. Đây là do cách instrument từng service, không phải thiết kế tùy tiện.

**Q: Có service nào chưa có metric CPU/memory/latency chuẩn không?**
A: Có — 10 service (`load-generator`, `image-provider`, `llm`, `flagd`, `flagd-ui`, `mem0`, `grafana`, `jaeger`, `prometheus`, `opensearch`, `aiops`) chưa được đăng ký thành signal RED/Resource chuẩn trong `prometheus_queries.json`. Chúng vẫn phát metric hạ tầng qua host/docker receiver nhưng cần một vòng rà soát riêng nếu CDO cần đủ cả nhóm này.

## 5.4 Về Engine / thuật toán

**Q: AIOps có tự động restart/scale service khi phát hiện lỗi không?**
A: Không, theo mặc định. Chế độ mặc định là **dry-run**: chỉ ghi đề xuất hành động (target, lý do, verification query, rollback criteria), **không mutate** gì. Hành động thật chỉ được phép qua một executor riêng biệt, sau khi có ADR (`ADR-LIVE-001`) riêng, RBAC hẹp, và rollback rõ ràng — không nằm trong runtime AIOps hiện tại.

**Q: EWMA, STL, IQR, RRF, PageRank là gì (giải thích 1 câu)?**
A: Xem bảng Glossary ở Section 4.7 — tóm gọn: **EWMA** = trung bình trượt trọng số giảm dần; **STL** = tách time series thành trend/seasonal/residual; **IQR** = khoảng phân vị 75–25%, đo độ phân tán bền với outlier; **RRF** = kỹ thuật gộp nhiều bảng xếp hạng thành 1 bảng cuối; **PageRank** = thuật toán tính độ trung tâm của node trong graph (ở đây dùng cho graph topology service).

**Q: Tại sao 1 incident có thể có occurrence_count tăng liên tục mà không tạo incident mới?**
A: Vì incident được nhận diện bằng **fingerprint** (`environment + detector_id + customer_flow + primary_service + likely_dependency`) — không dùng timestamp/giá trị metric. Nếu cùng fingerprint, các lần detector fire tiếp theo chỉ tăng `occurrence_count` trên incident cũ (trong window dedup 300s), tránh spam alert.

**Q: `flagd` là gì và vì sao AIOps không được đụng vào?**
A: `flagd` là feature-flag engine, đồng thời là công cụ SRE dùng để **inject fault có kiểm soát** (ví dụ bật `local-paymentFailure` để test detection). Nếu AIOps được phép mutate `flagd`, nó có thể vô tình tắt fault injection đang chạy hoặc can thiệp vào bài test — vì vậy đây là **protected path**: AIOps chỉ quan sát triệu chứng, không mutate/redirect/bypass.

**Q: Auto-detector-generation là gì, có rủi ro gì?**
A: Là cơ chế tự sinh detector `auto_<service>_error_rate`/`latency_p95`/`latency_p99` cho từng service trong registry, dùng threshold mặc định thay vì phải khai báo tay từng detector. Rủi ro: threshold mặc định (`error_rate=5%`) có thể không phù hợp với mọi service, dễ sinh false positive nếu service đó có traffic pattern đặc biệt — đây từng là nguyên nhân một phần gây nhiễu số liệu precision ở Mandate 7b (xem Section 1.2).

**Q: RCA có tuyên bố "chắc chắn root cause" không?**
A: Không. RCA chỉ trả `likely_dependency = <service>` kèm điểm `confidence` (ngưỡng tối thiểu 0.5 để không trả `unknown`), không bao giờ khẳng định chắc chắn nếu chưa đủ bằng chứng (trace/log/K8s corroboration).

---

*Ghi chú: file này nên được cập nhật thêm sau mỗi buổi review nếu có câu hỏi mới chưa được cover.*
