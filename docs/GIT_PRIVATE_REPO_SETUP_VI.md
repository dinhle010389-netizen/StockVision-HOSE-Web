# Đưa StockVision vào GitHub Private — hướng dẫn tiếng Việt

**Không gửi mật khẩu, PAT, token FireAnt hay `DATABASE_URL` vào chat.** Tạo private repository và nhập secrets trực tiếp trong dịch vụ tương ứng.

## Cách A — Dùng Git (giữ lịch sử commit trong file bundle)
1. Tạo một repository trống tại https://github.com/new; chọn **Private**, tên gợi ý `stockvision-hose-web`. Đừng chọn tự tạo README/.gitignore/license vì repository cần trống để nhận branch có sẵn.
2. Cài Git for Windows nếu chưa có.
3. Mở PowerShell tại thư mục chứa file `StockVision-HOSE-Web-0.5.git.bundle`, chạy:

   ```powershell
   git clone --branch main .\StockVision-HOSE-Web-0.5.git.bundle stockvision-hose-web
   cd .\stockvision-hose-web
   git remote add origin https://github.com/<TEN_TAI_KHOAN>/stockvision-hose-web.git
   git push -u origin main
   ```

   Thay `<TEN_TAI_KHOAN>` bằng username GitHub. Khi Git hỏi đăng nhập, dùng luồng đăng nhập/credential manager chính thức; không đưa PAT vào lệnh hoặc chat.

## Cách B — Tạo repo qua giao diện
1. Tải `StockVision-HOSE-Web-0.5-Repo-Ready.zip` và giải nén.
2. Tạo repo Private trống tại https://github.com/new.
3. Đưa nội dung bên trong thư mục `StockVision-HOSE-Web-0.5-Repo` lên root repo bằng GitHub Desktop/Git. Nếu dùng upload trên web, bảo đảm các thư mục `.github`, `backend`, `docs`, `scripts`, `tests` và `render.yaml` nằm đúng tại root; không chỉ upload tệp ZIP.

## Sau khi push
- Mở tab Actions, chờ workflow `StockVision CI` hoàn tất.
- Không upload `.env`, database cục bộ hoặc credentials.
- Mở Render Dashboard → New → Blueprint → kết nối repo private.
- Khi được hỏi `APP_ACCESS_PASSWORD`, tự nhập mật khẩu riêng dài tối thiểu 12 ký tự. Giá trị này được đặt qua `sync: false`; không commit nó.
- Để `APP_SESSION_SECRET` do Render sinh (`generateValue: true`).
- Xem `REPOSITORY_AND_DEPLOY_STATUS_VI.md` và `REMOTE_DEPLOY_STATUS.txt` để hiểu tiêu chí kiểm chứng.
