# Repository riêng và triển khai Render — StockVision HOSE Web 0.5

## Trạng thái
- Đây là bản **repo-ready** được giữ tách riêng khỏi mã nguồn gốc Windows EXE 0.4.
- Có `render.yaml` tại root, `.github/workflows/ci.yml`, script kiểm tra secrets, test suite và báo cáo kiểm thử song song 100 worker.
- Chưa tạo GitHub private remote và chưa deploy Render: môi trường hiện tại không có quyền tài khoản đã được xác thực/ủy quyền. Không có URL HTTPS để báo lại.
- Đồng bộ nguồn công khai live chưa được xác nhận: môi trường chạy công cụ không phân giải được DNS outbound, và package `vn-market-data` không được cài trong môi trường test. Các test provider đang dùng payload giả lập.

## Tạo repository riêng
1. Tạo repository **Private** trống trên GitHub, tên gợi ý `stockvision-hose-web`.
2. Đưa nội dung thư mục này lên branch `main` bằng Git hoặc GitHub UI.
3. Đảm bảo `.env` và database runtime không được commit; chỉ `.env.example` được chia sẻ.
4. Xác nhận workflow **StockVision CI** chạy thành công trước khi deploy.

## Deploy bằng Render Blueprint
1. Vào Render Dashboard, chọn New > Blueprint, kết nối private repo vừa tạo và chọn `render.yaml` ở root.
2. Khi Render yêu cầu `APP_ACCESS_PASSWORD` (`sync: false`), tự nhập mật khẩu riêng tối thiểu 12 ký tự. **Không lưu mật khẩu trong Git**.
3. Giữ `APP_SESSION_SECRET` do Render sinh ngẫu nhiên bằng `generateValue: true`.
4. Kiểm tra biến `DATABASE_URL` được liên kết với database `stockvision-db`.
5. Deploy và kiểm tra `/api/v1/health`, đăng nhập, sau đó mở `/api/v1/providers/status` và `/api/v1/providers/public/sync-status`.

## Tiêu chí để xác nhận sync thật
Không coi `installed=true` hoặc `ready=true` là bằng chứng đã lấy dữ liệu. Cần một lần sync đã chạy, `status=success` hoặc `partial`, `completed_at` khác rỗng, `bars_saved > 0`, có `upstream_sources` quan sát được; kiểm tra nến mới nhất, source attribution, giá OHLC hợp lệ và số bản ghi bị từ chối. Cache hit đơn thuần không chứng minh vừa gọi nguồn ngoài.

## Hạn chế Render Free
Render ghi rõ free web service ngủ sau 15 phút không có traffic và filesystem cục bộ là ephemeral; Render PostgreSQL Free hết hạn sau 30 ngày. Do vậy, Blueprint hiện tại là preview; không phù hợp cho đồng bộ liên tục hoặc lưu lịch sử lâu dài. Trước khi theo dõi ổn định, chọn dịch vụ/datastore có vòng đời phù hợp. Nguồn: https://render.com/docs/free
