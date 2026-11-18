# Judge audit

Chạy trong `src/`:

```bash
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 10
```

FAIL là lớp dương: precision đo độ tin cậy của cảnh báo lỗi, recall đo khả năng tìm ra lỗi. Các nhãn người và verdict judge được replay từ CSV công khai; bảng dưới là đối chiếu với ghi chú sẵn có, không phải một đợt gán nhãn người độc lập. Giữ nguyên CSV khi tính calibration.

| Tiêu chí | n | TP / FP / FN / TN | κ | Precision | Recall | Đạt κ≥0,6; P≥0,8; R≥0,7? | Quyết định |
|---|---:|---|---:|---:|---:|---|---|
| tone_ok | 100 | 24 / 4 / 6 / 66 | 0,757 | 0,857 | 0,800 | Có, exit 0 | Có thể dùng cho giọng điệu trong phạm vi replay |
| helpful | 100 | 9 / 0 / 21 / 70 | 0,375 | 1,000 | 0,300 | Không, exit 1 | Loại khỏi gate |

Tone quan sát 28% lỗi, Rogan–Gladen hiệu chỉnh thành 30%; helpful quan sát 9%, hiệu chỉnh thành 30%. Hiệu chỉnh tỉ lệ không cứu được classifier có recall thấp: helpful bỏ sót 21/30 lỗi. Không dùng judge này để duyệt tiền hoặc phê duyệt; các tiêu chí đó dùng code đọc ledger và nhãn riêng.

## Các bất đồng và hành động sửa rubric

| Case | Judge | Nhãn người công khai | Đối chiếu từ dữ liệu | Hành động đề xuất |
|---|---|---|---|---|
| H-008 | PASS | FAIL | “Em … nha” bị ghi chú là quá suồng sã; nhãn người phù hợp rubric hiện tại | Thêm ví dụ xưng hô và từ kết câu bị cấm; thân thiện chưa đủ để PASS |
| H-017 | PASS | FAIL | Gọi “bạn”, dùng “nha”; ghi chú nói không phù hợp với khách lớn tuổi | Quy định cách xưng hô khi không rõ tuổi; cần ngữ cảnh khách để kiểm tra ngoài replay |
| H-029 | PASS | FAIL | “không cần nhắn thêm” mang giọng ra lệnh dù có “Dạ, vui lòng” | Chấm toàn câu và dấu hiệu ngăn khách phản hồi |
| H-042 | FAIL | PASS | Câu ngắn, có số tiền và thời gian; thiếu xin lỗi không đồng nghĩa thiếu lịch sự | Bỏ yêu cầu xin lỗi bắt buộc khi câu đã đủ ý và lịch sự |
| H-051 | FAIL | PASS | Ghi chú cho phép từ “refund”; judge phạt vì có tiếng Anh | Thêm danh sách thuật ngữ được phép và ví dụ PASS |
| H-063 | PASS | FAIL | Hứa “sẽ hoàn thêm” ngoài kết quả hệ thống | Cấm lời hứa không có căn cứ; tách kiểm tra giọng điệu và tính đúng sự thật |
| HL-015 | PASS | FAIL | Reply 55.000đ; ghi chú CSV nêu ledger 40.000đ | Thêm đối chiếu số tiền bằng code, không dùng mức lịch sự làm bằng chứng đúng tiền |
| HL-016 | PASS | FAIL | Lời xin lỗi dài che số tiền sai: 55.000đ so với 35.000đ trong ghi chú | Đặt tiêu chí đúng nghiệp vụ trước giọng điệu; câu dài không bù được lỗi tiền |

H-081 có ghi chú rằng nhãn người sai, nhưng dữ liệu không kèm hồ sơ gán nhãn mới độc lập. Ghi nhận để tái thẩm định; không tự đổi nhãn rồi công bố lại điểm calibration tốt hơn. Bảng trên cũng không khẳng định đã kiểm tra lại ledger thật của các ví dụ judge: nguồn là ghi chú CSV do đề cung cấp.

## Giới hạn và bước tiếp theo

Calibration hiện dùng toàn bộ 100 dòng công khai cho từng tiêu chí. Các sửa rubric ở trên là đề xuất cho lần đánh giá mới, chưa được chứng minh cải thiện trên held-out. Trước khi dùng judge với model thật, cần rubric cố định, nhãn người mới, tập held-out riêng và đo lại κ/P/R; κ không xác định phải FAIL. Tone đạt floors không đồng nghĩa agent đã qua kiểm thử giọng điệu ngoài hai CSV.

Nguồn: `src/data/eval/judge_tone_public.csv`, `judge_helpful_public.csv`, `lab9/judge.py` và floors của đề.
