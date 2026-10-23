# Tạo tài khoản GitHub/Render và triển khai StockVision HOSE

## Lưu ý quyền và thanh toán

Tài khoản GitHub/Render phải được tạo và xác minh bởi chủ tài khoản. Bạn cần tự nhập email, mật khẩu, xác thực đa yếu tố nếu bật, chấp nhận điều khoản và phương thức thanh toán. Không gửi mật khẩu, mã MFA, token GitHub, token Render hoặc FireAnt qua chat.

`render.yaml` là **production Blueprint có tài nguyên tính phí**: web service Starter và Render Postgres Basic-256mb. Theo thông tin giá Render được kiểm tra ngày 23/10/2026, cấu hình tối thiểu tương tự được ước tính khoảng US$13/tháng trước băng thông/phần lưu trữ phát sinh; kiểm tra giá hiện hành ở https://render.com/pricing trước khi triển khai. Không nhấn Deploy Blueprint cho đến khi đồng ý với khoản phí.

`render.preview.yaml` là bản miễn phí để xem thử; web có thể ngủ khi idle, và PostgreSQL Free hết hạn sau 30 ngày. Không dùng nó làm hệ thống thu thập dữ liệu lâu dài.

## A. Tạo repository riêng trên GitHub

1. Tạo tài khoản tại https://github.com/signup và xác minh email.
2. Cài GitHub Desktop từ https://desktop.github.com/ rồi đăng nhập tài khoản.
3. Giải nén bộ ZIP repository-ready. Trong GitHub Desktop chọn **File → Add Local Repository**, chọn thư mục dự án (thư mục cần có `.git`).
4. Chọn **Publish repository**, đặt tên `StockVision-HOSE-Web`, chọn **Keep this code private**, rồi Publish.
5. Mở repository trên GitHub và kiểm tra tab Actions: workflow StockVision CI phải chạy. Nếu không, vào Settings → Actions bật GitHub Actions phù hợp với repository.

## B. Tạo dịch vụ Render production

1. Tạo tài khoản tại https://dashboard.render.com/register và xác minh email.
2. Render Dashboard → **New → Blueprint** → kết nối GitHub, cấp quyền chỉ cho repository `StockVision-HOSE-Web` khi được hỏi.
3. Chọn repository/branch `main`, Blueprint path `render.yaml`.
4. Đọc lại tài nguyên: web service Starter + PostgreSQL Basic-256mb. Các tài nguyên này được tính phí. Nếu chưa muốn trả phí, hủy bước này và chọn `render.preview.yaml` trong một Blueprint riêng chỉ để demo.
5. Khi Render hỏi `APP_ACCESS_PASSWORD`, tự tạo mật khẩu riêng dài tối thiểu 16 ký tự và nhập trực tiếp vào Dashboard. `APP_SESSION_SECRET` được Render sinh tự động; không thay bằng mật khẩu người dùng.
6. Kiểm tra các thay đổi và chi phí rồi mới chọn **Deploy Blueprint**. Không cần đặt FIREANT token; chương trình mặc định sử dụng public-data provider ở EOD.
7. Chờ build/deploy xong, mở URL `https://<service>.onrender.com/api/v1/health` và xác nhận `status=ok`, `database=ok`.
8. Mở URL gốc, đăng nhập bằng APP_ACCESS_PASSWORD, mở `/api/v1/providers/status`, `/api/v1/providers/public/sync-status`. Chỉ kết luận đã đồng bộ thật khi status `success`/`partial`, có `bars_saved > 0`, `upstream_sources` được quan sát và thời điểm hoàn tất mới. `package ready` hay cache hit không chứng minh kết nối mạng.
9. Kiểm tra `/api/v1/market/overview`, sau đó thử trên Safari iPhone: Share → Add to Home Screen.

## C. Vận hành lâu dài

- Theo dõi Render Events/Logs và GitHub Actions.
- Mỗi lần push lên `main`, Render tự triển khai **sau khi CI pass** (`autoDeployTrigger: checksPass`).
- Sao lưu PostgreSQL định kỳ và thử quy trình restore. Render có backup/PITR cho cơ sở dữ liệu trả phí; cần xem cửa sổ khôi phục theo workspace plan hiện hành.
- Theo dõi ngày/thời gian sync, số nến nhận/lưu/từ chối, upstream và lỗi. Nguồn công khai hiện chủ yếu là lịch sử/EOD, không cam kết realtime.
- Kiểm tra điều khoản từng nhà cung cấp trước khi lưu/tái phân phối dữ liệu. Không commit `.env` hoặc token.

## Trạng thái hiện tại

Bộ mã đã chuẩn bị và kiểm thử offline; tài liệu này không khẳng định tài khoản GitHub/Render, dịch vụ, URL HTTPS hoặc kết nối nguồn trực tuyến đã được tạo. Chủ tài khoản phải thực hiện các bước xác minh/ủy quyền/tính phí. Sau khi tích hợp GitHub/Render được kết nối và cấp quyền trong môi trường hỗ trợ, việc đẩy repository/deploy có thể tiếp tục bằng các công cụ tương ứng.
