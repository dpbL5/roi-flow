# Flow Veo Studio Bridge

Tiện ích trình duyệt dạng unpacked để chạy tự động hoá Flow trong profile trình duyệt thường của người dùng. Thiết lập hiện đang hoạt động là Yandex Browser.

Phiên bản hiện tại: `0.2.2`.

## Cài đặt hoặc cập nhật trong Yandex Browser

1. Mở `browser://extensions`.
2. Bật chế độ nhà phát triển.
3. Bấm tải tiện ích chưa đóng gói.
4. Chọn thư mục `browser_extension` này.
5. Cấp quyền truy cập trang web nếu trình duyệt hỏi.
6. Sau khi cập nhật, tải lại card tiện ích này và refresh tab Flow bằng `Ctrl+R`.

## Khi chạy

- Giữ `http://127.0.0.1:8765` đang chạy.
- Mở tab dự án Flow cần xử lý trong trình duyệt đã cài tiện ích.
- Bắt đầu và dừng chế độ này từ UI local của Flow Veo Studio.
- Dùng popup tiện ích để chuyển từ gửi prompt sang tải xuống, rồi từ tải xuống sang tạo lại hoặc hoàn tất.
- Không chạm vào tab Flow khi tiện ích đang gửi prompt hoặc tải xuống.

## Ghi chú triển khai

- Gửi prompt dùng `Control+A`, `Input.insertText`, và `Enter` qua debugger.
- Tiện ích không bấm các nút submit/generate toàn cục.
- Tải xuống lấy media bytes có uỷ quyền trong ngữ cảnh tiện ích trình duyệt và gửi về server local, server sẽ ghi `<frames>\clip_####.mp4`.
- Downloader phiên bản `0.1.4+` khớp media bên trong card Flow gần nhất có đúng một marker `#NNN`; không dùng cách khớp theo thứ tự giữa nút tải xuống và media URL.
- Phiên bản `0.1.5` chỉ tải các chỉ mục đang là submitted và đồng bộ trạng thái server từ các tệp local `clip_####.mp4` đã có.
- Phiên bản `0.1.6` dừng gửi lại prompt quá thời gian trong hàng đợi chính; các mục submitted cũ vẫn ở hàng đợi tìm/tải trong Flow, và content script quét rộng dự án khoảng 3 phút một lần.
- Phiên bản `0.1.11` giữ phiên tiện ích tiếp tục chạy khi Flow hiện cảnh báo như `We noticed some unusual activity`: tiện ích báo server, tải lại trang Flow, chờ 10 giây sau reload, rồi tự tiếp tục thay vì dừng job.
- Phiên bản `0.1.14` dùng thao tác Archive hiện tại của Flow. Archive thay cho Delete/Trash đã bị bỏ và không cần hộp thoại xác nhận.
- Phiên bản `0.1.15` archive card khi chúng vẫn đang hiển thị trong lượt cuộn và thêm fallback theo vị trí cho nút Archive chỉ có icon gần các nút tải xuống/dùng lại.
- Phiên bản `0.1.16` chỉ archive sau khi có lượt tải mới lưu thành công. Nó không archive card `skipped_existing` hoặc các `downloaded_indexes` local cũ, và xử lý tải từng card một để tránh lag DOM của Flow.
- Phiên bản `0.2.0` đổi hình dạng vòng chạy chính: gửi toàn bộ prompt sẵn sàng theo lô 25 với khoảng nghỉ 1-2 giây giữa các lần gửi và 20-30 giây giữa các lô, sau đó tải từ dưới lên, rồi chỉ archive các card đã tải trong lượt đó. Prompt chưa tải được sẽ thử lại tối đa 3 chu kỳ đầy đủ, sau đó prompt chưa xử lý sẽ bị đánh dấu `failed`.
- Phiên bản `0.2.1` tắt archive hoàn toàn. Nó không còn đánh dấu các card submitted chưa tải được là failed chỉ vì một lượt scan bỏ sót.
- Phiên bản `0.2.2` tách phiên chạy thành các pha thủ công: gửi toàn bộ prompt sẵn sàng trước, chờ nút popup để bắt đầu tải xuống, chạy tối đa 5 lượt tải, rồi chờ thao tác tạo lại hoặc hoàn tất. Tạo lại bị giới hạn bởi `FLOW_EXTENSION_REGEN_MAX` (mặc định `2`) thông qua `regen_count` trên từng prompt.
- Khi bắt đầu, server local đưa các prompt bị failed nhầm bởi logic auto-fail đã retired (`not_downloaded_after_cycle_*`, `final_not_generated`, `final_retry_exhausted`) về lại `prompt_ready`.
- Server local từ chối hash SHA256 MP4 trùng chính xác và chuyển tệp trùng vào `_flow_veo_studio\duplicate_downloads`.
