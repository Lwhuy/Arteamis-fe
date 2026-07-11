# Arteamis Control Plane — Mockup (2026-07-12)

Mockup tương tác cho việc **dời workflow "sau khi add source"** từ `arteamis-system`
sang `Arteamis-fe`, thể hiện tầm nhìn PRD v6 nhưng với UI **một control plane, cực clear**.

## Xem
- **File:** [`index.html`](./index.html) — mở trực tiếp trong trình duyệt (self-contained, không cần server).
- **Artifact (live, để track):** https://claude.ai/code/artifact/ac18c914-abc0-4afb-81e2-38031b287890

## Cách thử
1. Bấm **`+ Add source`** → source hiện ở sidebar phải (Đang xử lý → Ready), agent tự tóm tắt insight trong chat.
2. Bấm citation (`¹` / `tr.4 ›`) → mở **panel artifact bên trái** (rail · artifact · chat · sidebar), highlight đúng đoạn trích.
3. Bấm **`Đề xuất lên Company`** → tạo proposal Pending.
4. Gạt **scope → Company** (top) → review → **`Duyệt → Company Brain`** → thành Belief.
5. Duyệt xong hiện card **Work package** → `Giao cho AI agent` / `Giao cho người` → Trace.
6. Bấm **`Ghi nhận kết quả & học lại`** → tạo **đề xuất học lại** quay về "Cần review" (propose-only) → duyệt lại để belief cập nhật.
7. Bấm belief ở **Company Brain** → panel **lineage** (nguồn · provenance · việc sinh ra · cảnh báo mâu thuẫn D4).
8. `↺ Chạy lại` để xem lại từ đầu. Có light/dark theme.

## Quyết định thiết kế đã CHỐT (qua brainstorm)
- **1 control plane** = chat giữa + **sidebar ngữ cảnh phải** (Sources · Vòng loop · Cần review · Brain). Navigation ~0.
- **Công tắc scope Personal / Company** ở top — 2 mặt PRD gộp thành một control plane.
- **Chat là nhà; trang cũ Open Notebook** (Sources/Notebook, Podcast, Connections) ẩn sau **rail trái** (đường kẻ "trang cũ").
- **Trọn vòng governed loop 8 bước** hiện dưới dạng *card-trong-chat* + *mục-ở-sidebar*, có **ranh giới Personal · Company** giữa Propose và Review.
- **Bấm citation → artifact reader** bên trái (4 cột) — "inspect exact evidence" (PRD §4.5A).
- **Vòng học lại khép kín**: trace → bài học → **propose-only** về review → duyệt → belief cập nhật (PRD §1.6A, §4.5B).
- **Belief có lineage**: nguồn, provenance, việc sinh ra, mâu thuẫn (PRD §1.6, §4.5B, D4).
- Ngôn ngữ thiết kế Arteamis: giấy ấm, coral, heading serif.

## Vòng loop 8 bước (nhãn)
`Capture → Draft insight → Propose ‖ Review → Decision → Rule/Belief → Handoff → Trace + Learning`
(‖ = ranh giới Personal/Company)

## Đã chốt (xem spec đầy đủ)
Spec: [`../../specs/2026-07-12-control-plane-governed-loop-design.md`](../../specs/2026-07-12-control-plane-governed-loop-design.md)
- **Nền tảng:** Hướng B — xây trên P1, single-tenant, "workspace-ready" (chỉ P0/P1 đã vào code).
- **Trust/DLP:** "Vừa" — private-by-default + visibility + audit; hoãn PII/secret scan.
- **Phase 1:** "cây cầu" = P8.0 + P8.1 + P8.2.
- **Lineage:** mở trong panel artifact trái (gộp).

## Trạng thái
Mockup này là **nguồn tham chiếu UI** cho spec P8. Bước tiếp theo: user review spec → writing-plans
lập các plan P8.0–P8.5.
