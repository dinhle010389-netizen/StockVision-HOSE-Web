# Cấu hình FireAnt Online Sync (Windows Desktop)

StockVision đồng bộ nến OHLCV ngày ở thời điểm khởi chạy và có nút đồng bộ thủ công. Tính năng chỉ hoạt động sau khi có thông tin API/DataFeed được FireAnt cấp cho tài khoản của bro.

## Phải xác nhận từ FireAnt

- API/DataFeed base URL và đường dẫn endpoint lịch sử nến ngày được cấp phép.
- Cơ chế xác thực (ví dụ Bearer token nếu đúng với gói được cấp).
- Tên query parameters và cách phân trang/số nến được yêu cầu.
- JSON response envelope và tên trường ngày, open, high, low, close, volume (cùng trường value/adjusted close nếu có).
- Phạm vi sử dụng/lưu dữ liệu, giới hạn tốc độ và cách cấp/đổi token.

FireAnt công bố REST API và các dịch vụ dữ liệu/DataFeed, nhưng tài liệu công khai không khẳng định rằng mọi endpoint hoặc gói cá nhân đều có quyền OHLCV DataFeed. Không dùng endpoint nội bộ/không được cấp quyền và không vượt giới hạn truy cập.

## Cấu hình

Mở `CONFIG_FIREANT.bat`, sửa các biến `FIREANT_*` trong `.env`, lưu rồi khởi động lại app. Các trường bắt buộc:

- `FIREANT_API_TOKEN`: token được cấp.
- `FIREANT_LICENSE_CONFIRMED=true`: chỉ đặt true sau khi đã xác nhận được quyền truy cập/lưu dữ liệu.
- `FIREANT_BARS_PATH`: đường dẫn tương đối endpoint chính thức; không bao gồm host hoặc query string.
- `FIREANT_BARS_QUERY_JSON`: object JSON cho query. Placeholder hỗ trợ `{symbol}`, `{count_back}`, `{to_epoch}` trong giá trị chuỗi.
- `FIREANT_BARS_DATA_KEY`: đường dẫn JSON chấm, ví dụ `data` hoặc `result.items` nếu phù hợp response thực tế.
- `FIREANT_BAR_FIELD_MAP_JSON`: map trường đích StockVision `date/open/high/low/close/volume` sang đường dẫn trong record FireAnt.
- `FIREANT_AUTH_SCHEME`: scheme token được FireAnt chỉ định.

**Không dùng ví dụ payload trong test như hợp đồng API thực.** Chúng chỉ là dữ liệu fixture.

## Khi mở chương trình

- Nếu cấu hình còn thiếu: không gọi FireAnt; dashboard hiện DEMO.
- Nếu cấu hình đầy đủ: app gọi endpoint đã cấu hình cho các mã trong `FIREANT_SYMBOLS`, kiểm tra và chuẩn hóa các nến, rồi lưu vào SQLite local.
- Payload sai OHLC/time/volume bị loại; số bản ghi nhận/lưu/bị loại và lỗi đã làm sạch hiển thị trong Cài đặt dữ liệu.
- HTTP 401/403: kiểm tra token và entitlement. HTTP 429: giảm số mã/nhịp gọi và hỏi giới hạn FireAnt. Lỗi không ghi token hoặc raw body vào status UI.
- `FIREANT_COUNT_BACK` là số nến tối đa mỗi mã (1–5000, API có thể giới hạn thấp hơn). Điều chỉnh trong `.env`.

Nến ngày có thể là EOD hoặc delayed, không nên gọi là realtime nếu hợp đồng dữ liệu không xác nhận realtime.
