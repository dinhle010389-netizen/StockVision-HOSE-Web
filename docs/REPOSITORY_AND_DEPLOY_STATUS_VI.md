# Repository riêng và triển khai Render — StockVision HOSE Web

## Trạng thái chính xác
- Bộ mã được chuẩn bị trong repository Git cục bộ và commit; mã nền Windows EXE 0.4 được giữ trong lịch sử/manifest trước đó.
- `render.yaml` là Blueprint **production có phí**: web Starter + PostgreSQL Basic-256mb ở Singapore.
- `render.preview.yaml` là bản miễn phí/demo riêng; không dùng để chạy lâu dài.
- GitHub remote chưa được tạo; tài khoản/ủy quyền GitHub không được cung cấp trong môi trường xây dựng.
- Render service chưa được tạo; chưa có HTTPS URL và chưa đặt password/secret trên Render.
- Live sync chưa được xác nhận. Các test provider sử dụng payload fixture; không có bằng chứng lấy dữ liệu upstream trực tiếp ở lượt build.

## GitHub
Tên repository đề xuất `StockVision-HOSE-Web`, visibility Private. Dùng GitHub Desktop với gói repository-ready có `.git`, bấm **Add Local Repository** rồi **Publish repository** và chọn Private. Sau đó xác nhận CI workflow `StockVision CI` pass.

## Render production
- Tạo New → Blueprint, kết nối repo private, chọn branch `main` và root `render.yaml`.
- `APP_ACCESS_PASSWORD` có `sync: false` nên người vận hành nhập trực tiếp ở bước tạo Blueprint. `APP_SESSION_SECRET` dùng `generateValue: true`.
- `DATABASE_URL` liên kết với managed Postgres nội bộ; database có `ipAllowList: []` để chặn kết nối inbound công khai, các service Render trong private network mới truy cập được.
- `autoDeployTrigger: checksPass`: chỉ triển khai theo commit khi GitHub checks/CI pass.
- Cấu hình production có phí; kiểm tra giá hiện hành trên Render trước khi xác nhận.

## Tiêu chí xác nhận sync
Cần `status=success` hoặc `partial`, thời điểm kết thúc, `bars_saved > 0`, nguồn upstream được quan sát và dữ liệu OHLCV hợp lệ. `ready=true`, package installed hay cache hit đơn thuần không chứng minh kết nối live.
