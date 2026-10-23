# StockVision HOSE Web 0.5 — Changelog

## Nền mã nguồn
- Fork/copy làm việc dựa trên `StockVision_HOSE_Windows_EXE_0.4`; giữ phần backend FastAPI, schema SQL, normalizer chung, Hermitian risk analytics, session auth, PWA, và adapters TCBS/FireAnt.
- Không sửa nhánh bản cũ tại thư mục nguồn ban đầu; bản Public Data Edition là thư mục/nhánh riêng.

## Thay đổi mới
- Thêm `PublicMarketDataClient` dựa trên `vn-market-data` v0.3.0 đã pin, gọi API thư viện `get_ohlcv()` thay vì tự đoán endpoint hoặc scrape trang.
- Thêm cache SQLite theo thư viện nguồn, chuẩn hóa kết quả và upsert nến ngày EOD vào database StockVision.
- Thêm best-effort nến lịch sử cho VNINDEX/VN30; lỗi chỉ số được báo riêng thay vì tạo dữ liệu giả.
- Thêm tác vụ đồng bộ nền theo lịch và API trạng thái/đồng bộ thủ công.
- Bổ sung UI trạng thái public-data source, số nến nhận/lưu/từ chối, nguồn nhìn thấy và lỗi an toàn.
- Default provider của nhánh web là `public`; `DEMO_MODE=true` ngăn đồng bộ tự động và chặn đồng bộ thủ công cho đến khi được tắt rõ ràng.
- Ghi provenance bảo thủ: chỉ gắn source per-row nếu payload có trường nguồn hợp lệ; nếu không, ghi `PUBLIC_MULTI` để không tuyên bố sai xuất xứ.
- Chuẩn hóa timestamp ở ranh giới lưu SQLite (UTC-naive cho SQLite, UTC-aware cho PostgreSQL) để tránh lỗi `insertmanyvalues`; test xác nhận sync lặp không sinh nến trùng.
- Giữ FireAnt/TCBS làm adapter tùy chọn; chưa tự động gọi endpoint chưa được cấu hình/cấp quyền.
- Giữ phân tích phổ ma trận/Hermitian trong quản trị rủi ro; không đưa Schrödinger/Born vào vận hành.
