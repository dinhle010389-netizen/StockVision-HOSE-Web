# GitHub + Render: thiết lập riêng cho dinhle010389-netizen

## Thông tin repository mục tiêu

- GitHub profile: https://github.com/dinhle010389-netizen
- Repository đề xuất: `dinhle010389-netizen/StockVision-HOSE-Web`
- URL remote `origin` đã được đặt trong bản mã nguồn local: `https://github.com/dinhle010389-netizen/StockVision-HOSE-Web.git`
- Trạng thái: **repository trên GitHub chưa được tạo và chưa push**. Tên/URL ở trên là mục tiêu dự kiến, không phải bằng chứng repository tồn tại.

## 1. Tạo repository riêng

1. Mở https://github.com/dinhle010389-netizen và đăng nhập bằng tài khoản của bạn.
2. Mở https://github.com/new.
3. Owner: `dinhle010389-netizen`; Repository name: `StockVision-HOSE-Web`.
4. Chọn **Private**.
5. Không chọn khởi tạo README, `.gitignore` hoặc license (mã nguồn đã có lịch sử Git).
6. Chọn **Create repository**.

Không cung cấp mật khẩu GitHub, mã MFA hoặc token trong cuộc trò chuyện. Nếu muốn ChatGPT thực hiện thao tác qua tích hợp GitHub, phải tự kết nối/ủy quyền tích hợp trong giao diện ứng dụng; chỉ username không cấp quyền ghi repository.

## 2. Đẩy mã nguồn lên GitHub

Gói ZIP repository-ready giữ thư mục `.git` và `origin` đã trỏ đến URL mục tiêu. Sau khi tạo repository rỗng ở bước 1, mở PowerShell trong thư mục đã giải nén và chạy:

```powershell
git remote -v
git push -u origin main
```

Lệnh này yêu cầu Git cài sẵn và xác thực GitHub hợp lệ trên máy của bạn. Nếu GitHub Desktop đã được cài, có thể đăng nhập trong GitHub Desktop và dùng **Repository → Push**.

Sau khi push, kiểm tra tab **Actions** xem workflow CI hoàn tất trước khi deploy.

## 3. Kết nối Render

1. Đăng nhập https://dashboard.render.com/.
2. Render Dashboard → Account Settings → Account Security / Git Deployment Credentials → kết nối GitHub.
3. Cấp quyền chỉ cho repository `StockVision-HOSE-Web` nếu Render cho phép chọn repository cụ thể.
4. Chọn **New → Blueprint**, repository `dinhle010389-netizen/StockVision-HOSE-Web`, branch `main`, Blueprint path `render.yaml`.
5. Đọc danh sách tài nguyên và giá trước khi tạo. Production Blueprint tạo web service có phí và PostgreSQL có lưu trữ bền vững.
6. Đặt `APP_ACCESS_PASSWORD` trực tiếp trong Render, dùng mật khẩu riêng mạnh (ít nhất 16 ký tự); không commit mật khẩu.
7. `APP_SESSION_SECRET` được Render tạo tự động. Không cần nhập token FireAnt; provider mặc định là dữ liệu công khai lịch sử/EOD.
8. Chỉ nhấn Deploy sau khi đã đồng ý chi phí và kiểm tra cấu hình.

Tài liệu chính thức: https://render.com/docs/git-provider, https://render.com/docs/infrastructure-as-code và https://render.com/pricing.

## 4. Kiểm tra sau triển khai

- `https://<dịch-vụ>.onrender.com/api/v1/health` phải trả `status=ok` và `database=ok`.
- Đăng nhập ở URL gốc bằng mật khẩu ứng dụng đã cài.
- Kiểm tra `/api/v1/providers/status` và `/api/v1/providers/public/sync-status`.
- Chỉ xem sync là dữ liệu live khi báo cáo có lời gọi upstream được quan sát, thời điểm sync mới và `bars_saved > 0`; cache hit đơn thuần không chứng minh kết nối mạng.
- Xác minh một vài nến FPT/VCB/HPG với nguồn tham chiếu và xem log lỗi.
- Lập lịch backup PostgreSQL và thử restore trước khi dùng lâu dài.

## 5. Trạng thái trung thực hiện tại

- Mã nguồn, CI, production Blueprint và hướng dẫn đã được chuẩn bị local.
- GitHub remote mục tiêu được khai báo; repository thật chưa được tạo vì cần thao tác trong tài khoản/ủy quyền GitHub.
- Render chưa được liên kết, chưa tạo tài nguyên, chưa có HTTPS URL và chưa có mật khẩu thật.
- Upstream public-data sync và PostgreSQL production chưa được kiểm thử live trong môi trường xây dựng này.
