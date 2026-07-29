# Báo cáo tổng hợp AIOps — Mục lục

Folder này gom lại toàn bộ kết quả để dễ đóng góp/tiếp tục làm dàn báo cáo. Đọc theo thứ tự:

| # | File | Nội dung |
| --- | --- | --- |
| 1 | [`01-evaluation-results.md`](./01-evaluation-results.md) | Kết quả evaluation trên research dataset (RE2-SS) + trên hệ thống live (CDO/Mandate 7b) |
| 2 | [`02-data-collection-and-topology.md`](./02-data-collection-and-topology.md) | Câu chuyện thu thập dữ liệu (Prometheus/Grafana/Jaeger/OpenSearch/K8s) + topology/blast-radius |
| 3 | [`03-services-and-metrics.md`](./03-services-and-metrics.md) | Danh sách service + metrics sẽ lấy (trỏ tới `cdo-metrics-service-catalog.md`) |
| 4 | [`04-engine-architecture-and-algorithms.md`](./04-engine-architecture-and-algorithms.md) | Kiến trúc engine, thuật toán (EWMA/STL/IQR/RRF/PageRank/IsolationForest...), vòng đời incident, glossary |
| 5 | [`05-faq-questions-and-answers.md`](./05-faq-questions-and-answers.md) | Danh sách câu hỏi kèm câu trả lời chuẩn bị cho buổi báo cáo |

**⚠️ Trước khi dùng để báo cáo chính thức cho CDO:** Section 1.2 (evaluation trên hệ thống live) đang chờ số liệu cập nhật từ 4 scenario rerun (checkout/cart/burn-rate/ad-CPU) do phát hiện sai lệch precision ở bản v1. Xem chi tiết cảnh báo trong `01-evaluation-results.md`.

Nguồn dữ liệu gốc được trích dẫn đầy đủ ở cuối mỗi file — mọi số liệu đều đối chiếu trực tiếp với code/config/log trong repo, không suy diễn.
