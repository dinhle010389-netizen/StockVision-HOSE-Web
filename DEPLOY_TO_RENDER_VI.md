# Đưa StockVision HOSE lên HTTPS và cài trên iPhone

## Trạng thái chính xác

- Gói này **đã chuẩn bị cấu hình triển khai Render** (`render.yaml`) và gộp frontend PWA với FastAPI cùng một origin.
- HTTPS, hostname và PostgreSQL chỉ được tạo khi người vận hành đăng nhập Render và triển khai Blueprint. Chúng chưa được tạo từ môi trường này.
- Lần đầu `DEMO_MODE=true`; biểu đồ/mã giá vẫn là mô phỏng rõ nhãn. Không có FireAnt token hay quyền DataFeed nào được nhúng trong mã.
- Blueprint chọn Render Postgres Free phục vụ thử nghiệm. Theo tài liệu Render hiện hành, cơ sở dữ liệu Free hết hạn sau 30 ngày; nâng cấp database sang gói trả phí nếu cần giữ dữ liệu lâu hơn. Web service Free có thể ngủ khi không dùng.

## Điều kiện bắt buộc

1. Tài khoản GitHub để chứa mã nguồn (repo có thể để private).
2. Tài khoản Render được phép đọc repo GitHub và tạo web service/database.
3. Với giá FireAnt thật: hợp đồng/quyền DataFeed phù hợp và tài liệu kỹ thuật chỉ rõ endpoint nến, tham số, xác thực, response schema/field map. FireAnt token không gửi trong chat.

## Cách triển khai không dùng Docker/PowerShell trên máy cá nhân

1. Tải `StockVision_HOSE_Cloud_0.2.zip`, giải nén.
2. Tạo một repository private mới trong GitHub. Trong trang repo, dùng **Add file → Upload files** để upload nội dung bên trong thư mục dự án (bao gồm `render.yaml`, `Dockerfile`, `requirements.txt`, `backend/`, `scripts/`, `tests/`, `docs/`). Commit.
3. Đăng nhập Render → **New + → Blueprint** → chọn repository vừa tạo. Render đọc `render.yaml`, trình bày các dịch vụ `stockvision-hose` và `stockvision-db`; kiểm tra các tài nguyên/chi phí trước khi bấm deploy.
4. Chờ lần build đầu hoàn tất. Render cấp URL HTTPS dạng `https://<tên-dịch-vụ>.onrender.com`; tự mở `/api/v1/health` và `/api/v1/providers/status` để kiểm tra trạng thái.
5. Khi Render yêu cầu `APP_ACCESS_PASSWORD`, nhập một mật khẩu dài và riêng chỉ dùng cho StockVision (không gửi vào chat). `APP_SESSION_SECRET` được Render tự sinh. Hãy chọn mật khẩu dài tối thiểu 12 ký tự; backend giới hạn 10 lần đăng nhập sai trong cửa sổ 15 phút cho mỗi IP (best-effort của MVP). Mở web URL; màn hình đăng nhập bảo vệ API phân tích. Giao diện tự gọi API cùng domain sau khi đăng nhập. Dữ liệu phải ghi **DEMO** cho đến khi nạp dữ liệu đã được cấp phép.

Nếu GitHub/Render được kết nối qua ChatGPT, có thể dùng luồng triển khai có hỗ trợ thay vì upload thủ công; mọi bước tạo cloud resource vẫn cần người dùng phê duyệt trong tài khoản.

## Thiết lập FireAnt — chỉ sau khi được cấp quyền

Mở Render → service `stockvision-hose` → Environment. Đặt những giá trị chỉ khi FireAnt xác nhận/đưa vào gói của bro:

- `FIREANT_API_TOKEN`: secret DataFeed ở phía server.
- `FIREANT_LICENSE_CONFIRMED=true`: xác nhận nội bộ sau khi đã có quyền sử dụng/lưu trữ dữ liệu; đây không thay hợp đồng.
- `FIREANT_BARS_PATH`, `FIREANT_BARS_QUERY_JSON`, `FIREANT_BARS_DATA_KEY`, `FIREANT_BAR_FIELD_MAP_JSON`, `FIREANT_AUTH_SCHEME`: cấu hình đúng từng ký tự theo technical spec được cấp. Không tự đoán endpoint.
- `MARKET_DATA_PROVIDER=fireant`.

Giữ `DEMO_MODE=true` cho đến khi đã xác minh payload live, lưu dữ liệu vào PostgreSQL, đối chiếu timestamp/đơn vị/giấy phép và chạy kiểm thử. Chỉ sau đó mới đổi `DEMO_MODE=false`. Adapter hiện tập trung ở dữ liệu OHLCV; chưa tuyên bố feed bảng giá realtime nếu FireAnt chưa cung cấp một spec được cấp phép cho chức năng đó.

## Cài app trên iPhone vật lý

1. Sau khi Render deploy xong, mở URL HTTPS bằng **Safari** trên iPhone.
2. Nhấn **Chia sẻ → Thêm vào Màn hình chính**.
3. Bật **Open as Web App / Mở dưới dạng ứng dụng** nếu tùy chọn này xuất hiện, rồi nhấn **Thêm**.
4. Mở biểu tượng StockVision trên màn hình chính. Trên cùng origin, PWA sẽ gọi `/api/v1/market/overview` tự động; API không được cache khi offline.

Đây là một **PWA cài từ Safari**, không phải file native `.ipa`/App Store. Muốn native iOS/TestFlight cần project Xcode, macOS và ký bằng Apple Developer account.

## Giới hạn/chi phí

- Render Blueprint dùng Free web service và Free Postgres cho preview. Render cho biết Free Postgres sẽ hết hạn sau 30 ngày; không lưu dữ liệu duy nhất/quan trọng trong database thử nghiệm Free. Xác nhận bảng giá hiện hành trước khi duyệt deploy.
- API hiện là read-only và có một mật khẩu truy cập chung (chưa có tài khoản riêng/phân quyền từng người); không nhập thông tin tài khoản giao dịch, không đưa API token vào frontend, và không coi URL không công khai là biện pháp bảo mật.
- Không tự động đặt lệnh; không dùng giá demo làm cơ sở đầu tư.
