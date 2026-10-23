# Từ điển dữ liệu — StockVision HOSE 0.1

Schema bootstrap `backend/sql/001_init.sql` có 25 bảng trong schema PostgreSQL `sv`.

## Dữ liệu nguồn / thị trường

- `data_source`: mã nguồn, loại API, trạng thái quyền/giấy phép, base URL.
- `instrument`: mã CK, sàn, thông tin doanh nghiệp, ngành, tiền tệ, đơn vị giá và trạng thái niêm yết.
- `market_session`: lịch phiên theo ngày, giờ mở/đóng và trạng thái phiên.
- `ingest_job`: trạng thái job ingest, số bản ghi nhận/chèn/từ chối, watermark và lỗi.
- `raw_event`: payload gốc, hash nội dung, thời gian sự kiện/nhận, trạng thái parse; chỉ bật lưu payload theo điều khoản nguồn dữ liệu.
- `quote_snapshot`: snapshot giá, thay đổi, giá tham chiếu, khối lượng/giá trị khớp, sổ lệnh top 3 và quality flags.
- `trade_tick`: bản ghi khớp lệnh có provider ID để khử trùng lặp.
- `ohlcv_bar`: nến OHLCV nhiều timeframe; khóa theo mã, nguồn, timeframe, bar_start.
- `index_bar`: dữ liệu chỉ số/breadth. StockVision 0.1 bổ sung `change_value` và `change_pct` so với schema tham chiếu ban đầu.

## Dữ liệu doanh nghiệp / tính toán

- `corporate_action`: cổ tức, chia/tách, quyền mua và ngày hiệu lực.
- `financial_period`, `financial_metric`: báo cáo theo kỳ, ngày công bố/available-at, đơn vị và chỉ tiêu.
- `indicator_snapshot`: chỉ báo kỹ thuật được version hóa và gắn với nguồn nến.
- `feature_snapshot`: vector feature với `data_cutoff_at` và quality score.
- `model_registry`, `forecast_run`, `forecast`: mô hình, lần chạy, mục tiêu/horizon, xác suất, khoảng bất định và version dữ liệu.
- `backtest_run`, `validation_fold`: kết quả backtest, giai đoạn train/test và benchmark.

## Người dùng / vận hành

- `app_user`, `watchlist`, `watchlist_item`: cấu trúc theo dõi người dùng.
- `alert_rule`, `alert_event`: cấu hình và lịch sử cảnh báo.
- `audit_log`: nhật ký hành động với dữ liệu nhạy cảm đã loại/ẩn.

## Nguyên tắc thời gian

- `event_time`/`quote_time`/`bar_start` lưu UTC.
- `received_at` ghi thời điểm hệ thống nhận bản tin.
- `published_at` và `available_at` của báo cáo tài chính giúp kiểm soát look-ahead bias.
- `data_cutoff_at` xác định rõ dữ liệu được phép dùng khi tạo feature/dự báo.
- Thay đổi schema production cần migration có version; không sửa bảng thủ công mà thiếu migration tương ứng.
