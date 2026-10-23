# Thiết lập nguồn dữ liệu công khai

## Mặc định an toàn
- `MARKET_DATA_PROVIDER=public`
- `DEMO_MODE=true` chỉ cho chế độ demo; trong chế độ này bộ sync không tự chạy và thao tác sync thủ công trả HTTP 409.
- Để dùng nguồn công khai, xem kỹ điều khoản của từng nguồn, sau đó đặt `DEMO_MODE=false` và khởi động lại backend.
- Gói `vn-market-data` được pin ở tag `v0.3.0` trong `requirements.txt`; Dockerfile cài Git trước khi pip cài dependency VCS.

## Các biến cấu hình
- `PUBLIC_DATA_AUTO_SYNC_ON_STARTUP=true`: đồng bộ lúc backend khởi chạy.
- `PUBLIC_DATA_SYNC_INTERVAL_MINUTES=60`: khoảng giữa các vòng đồng bộ nền, tối thiểu 5 phút.
- `PUBLIC_DATA_LOOKBACK_DAYS=730`: khoảng lịch sử đề nghị.
- `PUBLIC_DATA_CACHE_TTL_SECONDS=900`: TTL theo API upstream.
- `PUBLIC_DATA_SYMBOLS=FPT,VCB,HPG,SSI,MWG,TCB,VIC,VHM`: watch universe ban đầu.
- `PUBLIC_DATA_INDEX_SYMBOLS=VNINDEX,VN30`: yêu cầu nến chỉ số; hỗ trợ phụ thuộc upstream.
- `VN_MARKET_DATA_DB`: nơi lưu cache SQLite của thư viện upstream. Trên Render preview đặt `/tmp/vn_market_data.db`; cache này có thể mất khi instance được thay thế.

## Xác minh
1. Đọc `/api/v1/providers/status` để kiểm tra package readiness. `network_tested=false` có nghĩa chưa có network probe, kể cả khi package đã cài.
2. Đọc `/api/v1/providers/public/sync-status` sau startup.
3. Nếu cần chủ động chạy, gọi `POST /api/v1/providers/public/sync` khi đã tắt demo mode.
4. Kiểm tra `bars_received`, `bars_saved`, `bars_rejected`, `indexes_saved`, `upstream_sources`, `errors` và `completed_at`.
5. Đối chiếu ít nhất một mã và ngày với nguồn hiển thị công khai. Nếu cache hit khiến upstream không được gọi trong lượt đó, trường nguồn có thể là `PUBLIC_MULTI` và phải kiểm tra provenance riêng.

Không đẩy `.env`, token hoặc log có dữ liệu nhạy cảm vào repository. Không dùng payload nguồn vượt quyền được cấp; không suy luận quyền tái phân phối chỉ từ giấy phép MIT của mã thư viện.
