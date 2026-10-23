STOCKVISION HOSE — BẢN EXE WINDOWS

TẠO FILE EXE (chỉ làm một lần trên máy Windows)
1. Cài Python 3.12 x64 từ https://www.python.org/downloads/windows/ nếu máy chưa có. Chọn Add Python to PATH.
2. Giải nén toàn bộ gói nguồn vào thư mục có quyền ghi.
3. Nhấp đúp BUILD_WINDOWS_EXE.bat và chờ đóng gói xong.
4. File chạy được tạo tại dist\StockVisionHOSE.exe. Sau khi tạo, người dùng cuối không cần cài Python.

CHẠY ỨNG DỤNG
- Nhấp đúp dist\StockVisionHOSE.exe.
- Cửa sổ app hiển thị bằng Microsoft Edge WebView2 Runtime; nếu thiếu, cài tại https://developer.microsoft.com/microsoft-edge/webview2/ rồi mở lại.
- Cấu hình, log và SQLite được lưu trong %LOCALAPPDATA%\StockVisionHOSE.
- Lần đầu ứng dụng chạy mặc định DEMO_MODE. Dữ liệu demo không dùng để mua/bán.

FIREANT
- Chỉ cấu hình sau khi FireAnt cấp quyền DataFeed/API và thông số endpoint/field chính thức.
- Chạy CONFIG_FIREANT.bat trong thư mục dist để mở tệp %LOCALAPPDATA%\StockVisionHOSE\.env.
- Không đưa token vào chat, screenshot hay commit source.
- Tính năng mặc định lấy nến ngày; không xem là realtime nếu hợp đồng FireAnt không bảo đảm.

LƯU Ý
- Gói source không chứa file EXE đã build. BUILD_WINDOWS_EXE.bat tạo EXE thực trên Windows vì PyInstaller không hỗ trợ cross-compile Windows từ Linux/macOS.
- Nếu Windows SmartScreen hiện cảnh báo, đó có thể là do EXE chưa được ký chứng thư phát hành. Chỉ chạy file bro tự build từ mã nguồn này.
- Ứng dụng hiện là bản MVP; chưa phải bộ cài ký số hoặc kiểm thử trên mọi máy Windows.
