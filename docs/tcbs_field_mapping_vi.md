# TCBS payload mapping và quy tắc chuẩn hóa

Nguồn tham chiếu chính: TCBS Open API Developer Portal, các trang `5.2. Bảng giá cơ sở (WebSocket)` và `5.13. OHLCV dài hạn`. Payload thực tế của tài khoản/phiên bản API cần được kiểm chứng khi cấp quyền.

## Bảng giá WebSocket — channel 6 (`Ticker Match`)

| Trường TCBS | Trường nội bộ | Quy tắc |
|---|---|---|
| `symbol` | `instrument.symbol` | trim + uppercase, kiểm tra pattern |
| `matchPrice` | `quote_snapshot.last_price` | Decimal, giữ nguyên đơn vị nguồn; không tự nhân/chia 1.000 |
| `change` | `change_value` | Decimal, so với tham chiếu của nguồn |
| `changePercent` | `change_pct` | Decimal theo phần trăm do nguồn gửi, ví dụ 0.82 có nghĩa 0,82% |
| `totalVolume` | `matched_volume` | số nguyên không âm |
| `totalValue` | `matched_value` | Decimal VND, giá trị tích lũy phiên theo nguồn |
| timestamp từ frame | `quote_time` | channel 6 ví dụ không có timestamp tuyệt đối; dùng thời điểm nhận và gắn cờ `provider_timestamp_missing` |

Channel 6 không có tham chiếu/trần/sàn trong ví dụ payload chính thức. Các trường đó không được suy đoán; nếu cần, mở rộng ingest channel 4 (`bp`).

## Chỉ số — channel 8 (`Stock Index`)

| Trường TCBS | Trường nội bộ |
|---|---|
| `indexNumber` | `index_code` (1 → VNINDEX, 2 → VN30, 3 → HNXINDEX, 5 → UPCOMINDEX) |
| `index` | `index_bar.close_value` |
| `change` | `index_bar.change_value` |
| `changePercent` | `index_bar.change_pct` |
| `volume` | `index_bar.volume` |
| `increase` / `decrease` / `notChange` | `advancers` / `decliners` / `unchanged_count` |
| timestamp | dữ liệu ví dụ không có event timestamp; backend đóng bucket một phút theo UTC và lưu `received_at` riêng |

Dữ liệu breadth từ channel 8 được ưu tiên để ước lượng độ rộng toàn thị trường; nếu chưa có frame channel 8, backend chỉ báo độ rộng của tập mã đã thu thập, không giả định tập đó đại diện toàn HOSE.

## OHLCV REST dài hạn (`GET /nyx/v2/stock/bars-long-term`)

| Trường TCBS | Trường nội bộ | Quy tắc |
|---|---|---|
| `ticker` | `instrument.symbol` | uppercase |
| `tradingDate` | `bar_start` | ISO timestamp, chuẩn hóa UTC; date-only lưu tại 00:00 UTC theo ngày nguồn |
| `open` / `high` / `low` / `close` | `open_price` / `high_price` / `low_price` / `close_price` | Decimal, tất cả phải > 0; kiểm tra quan hệ OHLC |
| `volume` | `volume` | số nguyên không âm |
| `resolution=D` | `timeframe=1d` | bar end mặc định start + 1 ngày; thời gian không dùng để khẳng định phiên giao dịch thực |

## Chất lượng và giới hạn

- Timestamp nội bộ lưu dạng UTC; giao diện đổi sang `Asia/Ho_Chi_Minh` để hiển thị.
- Giá được giữ nguyên số nguồn. Trước khi production cần so sánh vài mã với bảng giá TCBS, xác nhận đơn vị price/volume/value và quyền lưu trữ.
- Bar sai OHLC, giá không dương, volume âm, timestamp không hợp lệ hoặc số NaN/infinity bị từ chối.
- Thiếu tham chiếu hoặc timestamp được ghi qua `quality_flags`; không lấp bằng giá đoán.
- Raw provider payload chưa được persist trong adapter hiện tại; nếu bật bảng `raw_event`, cần xác nhận điều khoản lưu/retention của TCBS trước.
