# Chi phí và độ bền vận hành

## Hai blueprint tách biệt

- `render.yaml`: production, `starter` web + `basic-256mb` PostgreSQL, database inbound chỉ qua private/internal (`ipAllowList: []`), auto deploy chỉ sau CI pass, không tự tạo preview environment. Đây là cấu hình có phí; kiểm tra giá mới nhất tại https://render.com/pricing.
- `render.preview.yaml`: demo miễn phí, chạy `DEMO_MODE=true`, không tự đồng bộ, chỉ để kiểm tra giao diện. Render Free web có thể ngủ sau 15 phút idle; Render Free Postgres hết hạn 30 ngày và không có backup tự động. Không dùng để tích lũy lịch sử.

Theo bài viết chi phí Render cập nhật tháng 7/2026, Starter web + Basic-256mb Postgres điển hình khoảng US$13/tháng trước băng thông và tăng trưởng lưu trữ. Đây là ước tính, không phải báo giá/chào giá cam kết. Xem giá cuối cùng trên Render Dashboard trước khi triển khai.

## Những gì cấu hình này tăng độ tin cậy

1. Dữ liệu lịch sử lưu trong managed PostgreSQL trả phí thay vì filesystem tạm.
2. `APP_SESSION_SECRET` do Render tự sinh; `APP_ACCESS_PASSWORD` được yêu cầu riêng khi khởi tạo.
3. Deployment chỉ tự động sau CI pass.
4. Tắt tự sinh PR preview để tránh vô tình tạo thêm dịch vụ tính phí.
5. Health endpoint kiểm tra database; provider status phân biệt trạng thái package với upstream request quan sát được.
6. Region Singapore cho ứng dụng và database.

## Giới hạn còn lại

Đây là kiến trúc một web instance với tác vụ EOD chạy trong lifespan của app; không bật auto-scale nhiều instance để tránh scheduler chạy trùng. Nó chưa phải HA/zero-downtime đa vùng. Nhà cung cấp công khai có thể đổi API, giới hạn tốc độ hoặc điều khoản. Cần theo dõi logs, kiểm tra sync định kỳ và test restore. Không dùng trạng thái HTTP health một mình làm bằng chứng dữ liệu giá đã cập nhật.
