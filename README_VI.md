# StockVision HOSE Web 0.5 — Public Data Edition

Đây là nhánh phát triển dựa trên mã nguồn **StockVision_HOSE_Windows_EXE_0.4**. Nhánh Web 0.5 giữ lại FastAPI, PostgreSQL/SQLite, bộ chuẩn hóa, phân tích ma trận rủi ro Hermitian, PWA, đăng nhập và các adapter TCBS/FireAnt trước đó; đồng thời thêm adapter chuỗi dữ liệu công khai đa nguồn.

## Bản này làm được gì?

- Web Market Overview và PWA để dùng trên Windows, iPhone hoặc trình duyệt khác.
- Backend tự đồng bộ nến ngày (OHLCV) từ chuỗi nguồn công khai theo lịch; mặc định 60 phút một lần, 730 ngày lookback, 8 mã theo dõi và các chỉ số `VNINDEX`, `VN30`.
- Bộ lấy dữ liệu dùng `vn-market-data` được ghim ở tag `v0.3.0`. Theo tài liệu upstream, thư viện dùng cache-first SQLite và chuỗi nguồn gồm DNSE/Vietcap (OHLCV), VNDirect (giá trị giao dịch), CafeF (lịch sử khối ngoại); khả năng API cụ thể phụ thuộc từng hàm/nguồn. Bản tích hợp hiện tại sử dụng `get_ohlcv` cho nến ngày và thử lấy nến chỉ số; chưa tích hợp bảng giá intraday đầy đủ, lệnh chờ, tick tape hay toàn bộ báo cáo tài chính.
- Nguồn FireAnt và TCBS vẫn được giữ làm adapter tùy chọn, nhưng không tự gọi khi chưa cấu hình đúng.
- Phân tích phổ ma trận hiệp phương sai và Toán tử Hermitian vẫn ở phần quản trị rủi ro; không có Schrödinger/Born trong nhánh vận hành.
- Có endpoint trạng thái và đồng bộ thủ công; trạng thái nguồn, lỗi và số nến được lưu không bao gồm token hay payload thô.

## Quan trọng về dữ liệu và quyền sử dụng

“Có thể truy cập qua Internet” không đồng nghĩa dữ liệu được miễn phí vô điều kiện hoặc được phép tái phân phối. Giấy phép MIT của mã thư viện không cấp quyền sở hữu/redistribution đối với dữ liệu do nhà cung cấp trả về. Hãy xem điều khoản, giới hạn tốc độ, nguồn gốc và quyền lưu trữ của từng upstream trước khi dùng công khai hoặc thương mại.

Nguồn công khai trong bản này chủ yếu phục vụ **dữ liệu lịch sử/cuối ngày (EOD)** và cache. Không được coi là dữ liệu realtime. Dashboard phải thể hiện timestamp/độ mới và chế độ demo/dữ liệu thật. Không dùng giá mô phỏng để ra quyết định giao dịch.

## Chạy cục bộ để phát triển

Yêu cầu Python 3.11+ và Git nếu cài dependency VCS trực tiếp.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
python -m pip install -r requirements.txt
```

Tạo `.env` từ `.env.example`, sau đó cấu hình tối thiểu:

```dotenv
DEMO_MODE=false
MARKET_DATA_PROVIDER=public
PUBLIC_DATA_AUTO_SYNC_ON_STARTUP=true
APP_ACCESS_PASSWORD=  # để trống chỉ khi chạy local; phải đặt mật khẩu mạnh khi chia sẻ/triển khai
```

Chạy API (từ thư mục gốc, dùng được trên Windows PowerShell/macOS/Linux):

```bash
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000`. Nếu có mật khẩu ứng dụng, đăng nhập trước khi gọi API. Để kiểm tra trạng thái dữ liệu: `/api/v1/providers/status`; trạng thái đồng bộ: `/api/v1/providers/public/sync-status`; đồng bộ thủ công: `POST /api/v1/providers/public/sync`.

Ứng dụng **không gọi nguồn mạng khi đang ở `DEMO_MODE=true`**. Đây là chủ ý an toàn để tránh nhầm dữ liệu demo với dữ liệu thật. Đặt `DEMO_MODE=false` khi đã hiểu cấu hình và sẵn sàng lấy dữ liệu thực. Nếu package `vn-market-data` chưa cài hoặc nguồn không trả dữ liệu hợp lệ, trạng thái sẽ báo lỗi; ứng dụng không tự giả danh dữ liệu live.

## Triển khai web HTTPS

1. Đưa mã nguồn vào repository private của bro.
2. Tạo dịch vụ từ `render.yaml` (Render Blueprint) hoặc một máy chủ Docker tương đương.
3. Trên dashboard hosting, đặt `APP_ACCESS_PASSWORD` thành mật khẩu riêng có ít nhất 12 ký tự và tạo secret session. Không commit secrets vào Git.
4. Kiểm tra `/api/v1/health`, đăng nhập, `/api/v1/providers/status` và `/api/v1/providers/public/sync-status`.
5. Khi sync có dữ liệu hợp lệ, mở Safari trên iPhone → Chia sẻ → Thêm vào Màn hình chính để dùng dưới dạng PWA.

`render.yaml` là blueprint mẫu, không có nghĩa dịch vụ đã được triển khai tự động. Gói Free/preview có thể ngủ, giới hạn tài nguyên và/hoặc dùng ổ đĩa cache tạm; cần chọn cấu hình lưu trữ lâu dài trước khi vận hành thường xuyên.

## API nội bộ chính

- `GET /api/v1/health`
- `GET /api/v1/market/overview`
- `GET /api/v1/instruments`
- `GET /api/v1/providers/status`
- `GET /api/v1/providers/public/sync-status`
- `POST /api/v1/providers/public/sync`
- `GET /docs`

Các API dữ liệu cần phiên đăng nhập nếu đã cấu hình `APP_ACCESS_PASSWORD`.

## Kiểm thử

```bash
PYTHONPATH=backend pytest -q
python -m compileall -q backend scripts desktop_launcher.py
```

Bộ test hiện mô phỏng nguồn bằng fixture và kiểm tra parser, chuẩn hóa, lưu DB SQLite, API, chế độ demo và cấu hình triển khai. Đây **chưa phải** xác nhận endpoint nguồn online hoạt động tại thời điểm chạy, cũng chưa phải kiểm thử PostgreSQL/HTTPS trên máy chủ thật. Trường `network_tested` chỉ thành `true` khi một lượt sync success/partial ghi nhận được ít nhất một lời gọi nguồn upstream; cache hit đơn thuần không được coi là kiểm chứng kết nối mạng.

## Cấu trúc quan trọng

- `backend/app/providers/public_market_data_client.py`: adapter chuỗi nguồn công khai.
- `backend/app/public_market_data_sync.py`: lịch đồng bộ, upsert và trạng thái.
- `backend/app/normalizers.py`: chuẩn hóa dữ liệu dùng chung.
- `backend/app/risk.py`: phân tích ma trận/Hermitian.
- `backend/app/static/`: Market Overview và PWA.
- `backend/sql/`: schema/migrations.
- `render.yaml`, `Dockerfile`: triển khai web.
- `StockVisionHOSE.spec`, `BUILD_WINDOWS_EXE.bat`: giữ lại khả năng dựng nhánh desktop Windows.
