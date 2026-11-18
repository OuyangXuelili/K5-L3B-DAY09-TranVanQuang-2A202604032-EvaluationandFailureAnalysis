# Trace case — ticket ghi đè dữ kiện DB

Sinh viên: Trần Văn Quang — 2A202604032, L3B.

| Trường | Bằng chứng |
|---|---|
| Trial | `seeded_regression C-002@11`, item `E-002`; report `E-seeded_regression-20261118-e94d`, SHA `e94d7210c723` |
| Kết quả sai | DB có delay=2; ticket nói 5 ngày. Proposal và ledger thành 20.000đ, trong khi nhãn riêng yêu cầu proposal=0, refund=0, status=denied |
| Bước sai đầu tiên | Event **3**, `model_override`, payload `{"delay_days":5}` |
| Vì sao là bước đầu tiên | Event 1 tạo handoff đọc; event 2 investigator trả order nhìn thấy được và delay=2. Chưa có sai lệch trước lúc event 3 ghi đè dữ kiện này |
| Hậu quả | Quote ở bước tiếp theo dùng delay=5 rồi phát sinh khoản hoàn không hợp lệ theo nhãn; `db_fact_kept`, `refund_amount_correct`, `proposal_amount_correct` FAIL |
| Failure mode | FM-03, layer model/prompt; dữ kiện ticket bị tin hơn DB |
| Đối chứng | `fixed C-002@11` không có `model_override`, quote=0, denied, ledger=0 |
| Regression test | `tests/test_lab9_regression.py::test_lab9_first_wrong_decision_has_a_clean_control`: phân lập công tắc `ticket_trust`, thấy grader FAIL rồi PASS khi bật `no_override` |
| Test bổ sung | `test_lab9_quiet_fact_override_is_caught_by_outcome`: bỏ event override vẫn bị grader ledger bắt |

Tái lập case gốc và đối chứng, từ `src/`:

```bash
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11
python -m pytest -q -m student -o addopts= -k first_wrong_decision
```

[analysis.json](../src/reports/analysis.json) lưu thêm fixture `R-evidence_fm_03-C-002-s11` chỉ bật `ticket_trust`, có cùng ba bước đầu, để tách lỗi này khỏi hai công tắc còn lại của `seeded_regression`. Không nhầm run fixture với run benchmark chính.

Trên toàn v1, gate thấy Δ pass_rate=-0.271, CI 95% [-0.500; -0.057] và chặn regression. Khoản tiền này do host vẫn chấp nhận proposal dưới approval hợp lệ, nên riêng `ApprovalBypass` không phát hiện sai tính đủ điều kiện; phải đối chiếu nhãn/outcome.

Giới hạn: trace chỉ ghi các event được instrument, không chứng minh suy nghĩ nội bộ của model. Kết luận trên áp dụng cho MockLLM, bộ claim và seed cố định; không phải bằng chứng về khách hàng thật.
