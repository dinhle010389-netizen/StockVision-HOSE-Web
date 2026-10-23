# Kiểm thử TCBS thực + PostgreSQL thật (chạy phía máy chủ)

Bộ stress test 100 x 1.000 chỉ kiểm tra logic/offline. Tài liệu này dành cho kiểm thử tích hợp với một PostgreSQL thật và TCBS OpenAPI có token hợp lệ.

## Điều kiện bắt buộc

- Môi trường máy chủ mà bạn quản lý, có Python và cài `requirements.txt`.
- PostgreSQL thật đã được khởi tạo bằng `backend/sql/001_init.sql`; schema bắt buộc là `sv`.
- `TCBS_API_TOKEN` hợp lệ, đã được cấp qua TCInvest/TCBS; không gửi token/API key/OTP vào chat, ticket hoặc commit Git.
- Quyền truy cập mạng outbound tới `openapi.tcbs.com.vn` và kết nối TCP tới PostgreSQL.
- Xác nhận điều khoản dữ liệu TCBS và quyền lưu dữ liệu trước khi ghi vào kho dài hạn.

TCBS docs hiện mô tả endpoint daily OHLCV `GET /nyx/v2/stock/bars-long-term` với `ticker`, `type=stock`, `resolution=D`, `to` (epoch giây) và `countBack`; token gửi qua `Authorization: Bearer ...`.

## Chạy kiểm tra chỉ đọc

Đặt secrets bằng secret manager của máy chủ, Docker secrets hoặc biến môi trường; không chèn bí mật vào lệnh shell được lưu history. Ví dụ tên biến cần được đặt trong môi trường tiến trình:

- `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME`
- `TCBS_API_TOKEN=<token hợp lệ>`
- `TCBS_BASE_URL=https://openapi.tcbs.com.vn`
- `SV_RUN_LIVE_INTEGRATION=1`

Cài dependencies và chạy:

```bash
python -m pip install -r requirements.txt
PYTHONPATH=backend python scripts/live_integration_check.py --symbol FPT --count-back 5
```

Mặc định probe chỉ đọc PostgreSQL và lấy tối đa 5 nến daily từ TCBS; không ghi nến, không lưu raw payload, không in token. JSON report nằm ở `reports/live_integration_report.json` và không chứa bí mật.

## Kiểm tra ghi ORM mà không lưu dữ liệu

Chỉ chạy trên staging/test database sau khi có snapshot/backup. Tùy chọn này thực hiện insert source + instrument + bar trong transaction, kiểm tra ràng buộc rồi rollback và xác nhận hàng QA không còn tồn tại:

```bash
PYTHONPATH=backend python scripts/live_integration_check.py --symbol FPT --count-back 5 --transactional-write-probe
```

Dù rollback, sequence PostgreSQL có thể vẫn tăng và extension/trigger tùy biến có thể có side effects; vì vậy không khuyến nghị chạy probe ghi trên production nếu chưa được DBA chấp thuận.

## Diễn giải kết quả

- `PASS`: endpoint phản hồi payload thật có cấu trúc đúng, rows vượt normalizer và PostgreSQL/schema đọc được.
- `FAIL`: một trong hai hệ thống thất bại hoặc payload không đúng contract; xem trường `failure` trong report đã được làm sạch bí mật.
- `BLOCKED`: chưa bật `SV_RUN_LIVE_INTEGRATION`, thiếu `TCBS_API_TOKEN`, hoặc thiếu `DATABASE_URL`.
- `postgresql_orm_write_rollback=NOT_RUN`: mặc định vì probe ghi cần được cho phép rõ ràng.

Không gọi test pass trước khi chạy trên tài khoản TCBS và database cụ thể. Chạy live cần token chưa hết hạn, quyền API phù hợp, schema `sv` đã áp dụng và network route. Không gửi thông tin đăng nhập của server hoặc TCBS vào cuộc trò chuyện.
