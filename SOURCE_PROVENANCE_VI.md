# Xuất xứ và phạm vi nguồn dữ liệu — StockVision Web 0.5

## Nguồn mã

- Nền mã: StockVision HOSE Windows EXE 0.4 (nhánh dự án trước đó).
- Adapter công khai: `vn-market-data` được ghim ở tag `v0.3.0` từ repository `https://github.com/trangcm/vn-market-data`.
- Upstream mô tả giấy phép mã MIT và chuỗi nguồn mặc định DNSE/Vietcap/VNDirect/CafeF. Việc mã nguồn dùng giấy phép MIT không cấp quyền tái phân phối dữ liệu thị trường được lấy từ những nguồn này.

## Đường đi dữ liệu hiện tại

1. StockVision gọi API Python `get_ohlcv(symbol, lookback_days=..., ttl_s=...)` qua adapter.
2. Thư viện upstream sử dụng cache-first SQLite, rồi tự điều phối các nguồn mà thư viện hỗ trợ.
3. StockVision chuẩn hóa từng bản ghi, từ chối bản ghi OHLCV không hợp lệ và upsert nến ngày vào database chính.
4. Nến chỉ số được yêu cầu qua `get_ohlcv(..., is_index=True)` theo API thư viện; trường hợp nhà cung cấp không hỗ trợ sẽ được báo ở trạng thái sync, không giả tạo dữ liệu.
5. Nguồn cụ thể chỉ được ghi cho từng nến khi bản ghi thực sự mang trường nguồn hợp lệ. Nếu không có provenance theo từng row, StockVision gắn `PUBLIC_MULTI` thay vì khẳng định sai rằng toàn bộ batch đến từ nguồn được gọi trong lượt này.

## Giới hạn đã biết

- Bản tích hợp này chỉ dùng OHLCV lịch sử/ngày; chưa sử dụng `get_index_live`, `get_board`, `get_statements`, `get_events`, `get_market_turnover` hoặc `get_trade_tape` trong đường xử lý sản xuất.
- Chưa chạy network test trực tiếp trong môi trường đóng gói. `network_tested=false` là có chủ ý.
- Endpoint upstream, hạn mức, cấu trúc phản hồi và điều khoản có thể thay đổi; cần kiểm tra trước mỗi lần nâng phiên bản package.
- Với triển khai Render preview, cache SQLite của upstream dùng `/tmp/vn_market_data.db` và có thể mất khi instance được thay thế; dữ liệu nến StockVision đã chuẩn hóa được lưu ở PostgreSQL.
- Dữ liệu lịch sử/EOD không tương đương realtime; không đưa ra lời hứa về độ trễ nếu chưa benchmark trong môi trường được cấp phép.
