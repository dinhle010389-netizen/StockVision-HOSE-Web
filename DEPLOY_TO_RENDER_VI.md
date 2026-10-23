# Triển khai StockVision HOSE Web lên Render và cài PWA trên iPhone

## Chọn đúng Blueprint

- `render.yaml`: production, web Starter + PostgreSQL Basic-256mb, dữ liệu DB bền vững, tự deploy chỉ khi CI pass. **Tạo tài nguyên có phí**. Đọc `PRODUCTION_COSTS_AND_RELIABILITY_VI.md` trước khi xác nhận.
- `render.preview.yaml`: bản preview miễn phí, `DEMO_MODE=true`, không đồng bộ nguồn. Free web có thể ngủ; Free PostgreSQL hết hạn sau 30 ngày. Chỉ dùng để xem giao diện, không giữ lịch sử.

## 1. Tạo repository GitHub riêng

Cách ít thao tác lệnh nhất:

1. Tạo tài khoản tại https://github.com/signup và xác minh email.
2. Cài GitHub Desktop tại https://desktop.github.com/ và đăng nhập.
3. Giải nén gói `StockVision-HOSE-Web-0.6-Production-Ready.zip` (bản có thư mục `.git`). Trong GitHub Desktop chọn **File → Add Local Repository**, trỏ vào thư mục giải nén.
4. Chọn **Publish repository**, đặt tên `StockVision-HOSE-Web`, bật **Keep this code private**, rồi Publish.
5. Mở tab **Actions**, chờ workflow `StockVision CI` hoàn tất thành công. Nếu CI chưa chạy, kiểm tra repository Settings → Actions.

Nếu dùng bản source ZIP không kèm `.git`, tạo repository Private ở GitHub, rồi dùng GitHub Desktop **File → Add Local Repository** sau khi khởi tạo repo local; không tải `.env` hoặc database file lên GitHub.

## 2. Tạo tài khoản và triển khai Render

1. Tạo tài khoản tại https://dashboard.render.com/register và xác minh email.
2. Chọn **New → Blueprint**, kết nối GitHub và chỉ cấp quyền repository StockVision cần thiết.
3. Chọn `StockVision-HOSE-Web`, branch `main`, Blueprint path `render.yaml`.
4. Kiểm tra danh sách resource và chi phí. Production Blueprint tạo web plan Starter và PostgreSQL Basic-256mb; ước tính tham khảo khoảng US$13/tháng trước băng thông/lưu trữ phát sinh. Kiểm tra giá hiện hành ở https://render.com/pricing. Chỉ nhấn Deploy khi đồng ý chi phí.
5. Khi Render hỏi `APP_ACCESS_PASSWORD`, tự tạo mật khẩu riêng ít nhất 16 ký tự rồi nhập trực tiếp vào Render. `APP_SESSION_SECRET` được Render tự sinh. Không commit secrets.
6. Chờ CI pass và Render deploy; mở URL service `/api/v1/health`. Cần thấy `status=ok` và `database=ok`.
7. Mở URL gốc, đăng nhập rồi kiểm tra `/api/v1/providers/status` và `/api/v1/providers/public/sync-status`.

## 3. Xác nhận đồng bộ dữ liệu trực tuyến

Không dựa chỉ vào `ready=true` hoặc việc package được cài. Cần một lần sync thực tế có `status=success` hoặc `partial`, `completed_at`, `bars_saved > 0`, danh sách `upstream_sources` quan sát được và dữ liệu nến hợp lệ. Kiểm tra thêm ngày của nến mới nhất, trường nguồn và số bản ghi bị từ chối. Nếu adapter chỉ trả cache, không coi đó là chứng minh đã gọi upstream.

Nguồn công khai chủ yếu phục vụ nến lịch sử/EOD, không cam kết realtime. Nếu provider API đổi cấu trúc hoặc từ chối truy cập, cần đọc logs và trạng thái đồng bộ trước khi đổi bộ chuẩn hóa. Điều khoản sử dụng/lưu trữ/tái phân phối vẫn phụ thuộc từng nhà cung cấp.

## 4. Cài lên iPhone

1. Mở URL HTTPS trên Safari iPhone.
2. Chọn **Chia sẻ → Thêm vào Màn hình chính → Thêm**.
3. Mở icon StockVision trên màn hình chính. Đây là PWA, không phải ứng dụng `.ipa`/App Store.

## Trạng thái bàn giao

Bộ mã và Blueprint đã kiểm tra offline. Tài khoản, repository remote, Render service, URL HTTPS và đồng bộ live **chưa được tạo/xác nhận** bởi gói zip. Chủ tài khoản phải tự xác minh/ủy quyền và duyệt chi phí; không gửi mật khẩu/tokens qua chat.
