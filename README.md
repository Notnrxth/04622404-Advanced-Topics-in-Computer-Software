# 07 Football Data

FastAPI service สำหรับข้อมูลพรีเมียร์ลีกตาม `docs/CONTRACT.md` §6–7 อยู่ใน branch ของโมดูล 07 โดยเฉพาะ

## สิ่งที่มีแล้ว

- `GET /health`, `/ready`, `/football/status`, `/football/teams`, `/football/standings`, `/football/fixtures`, `/football/matches/{match_id}`
- `POST /ingest/run` รับ `scope=fixtures|details|all`: ดึง teams, matches, standings, scorers จาก football-data.org v4 และรายละเอียดนัดที่จบแล้วจาก API-Football; `details`/`all` ต้องตั้ง `API_FOOTBALL_KEY` ไม่เช่นนั้นตอบข้อผิดพลาดก่อนสร้าง job
- เก็บ API-Football quota ในฐานข้อมูล (จำกัด 90 คำขอต่อวัน UTC รวม retry), จับคู่ fixture จากวันเวลาและทีม, และเก็บ events/lineups/statistics ใน payload ของแมตช์
- บันทึกงานส่ง index ในฐานข้อมูล มี background worker ส่งซ้ำอัตโนมัติระหว่าง process ทำงาน (เริ่มรอ 2 วินาที, backoff สูงสุด 60 วินาที) หรือสั่ง `POST /index/reconcile`; `/football/status` แสดงงานค้าง, `last_error` และ quota แยกจากข้อมูลใน DB
- Upsert แบ่ง batch 1–100 เอกสารและ body ไม่เกิน 5,000,000 UTF-8 bytes; ล้างเฉพาะงานที่ส่งสำเร็จ ส่วนเอกสารเดี่ยวที่ใหญ่เกินกำหนดคงไว้พร้อม error ให้แก้
- `/football/standings` และ status เลือก snapshot สัปดาห์ที่จบแล้วล่าสุดถ้ามี; snapshot ระหว่างสัปดาห์ติดป้าย `live` ชัดเจน ส่วนดาวซัลโวปัจจุบันอยู่ในเอกสาร `category=standings` พร้อมเวลาข้อมูล
- `GET /jobs`, `/jobs/{job_id}` สำหรับติดตาม job; ป้องกันการสั่ง job ชนิดเดียวกันซ้ำในระดับแอป
- `POST /reports/weekly/run` เรียกโมดูล 06 เพื่อสร้าง draft เมื่อแมตช์วีคจบครบ โดยสร้าง snapshot ตารางคะแนนย้อนหลังจากผลแข่งได้เมื่อ `currentMatchday` ขยับไปแล้ว; รายการ/อ่าน/แก้ไข/publish/unpublish รายงาน โดยมีงานชดเชยกรณีอัปเดต index สำเร็จแต่ DB commit ล้ม
- เก็บ Markdown ภาษาไทยไว้แสดงผล แต่ใช้ `search_text_policy=source_facts`: ข้อความค้นภาษาอังกฤษมาจากผลแข่งและตารางคะแนนใน DB การแก้ Markdown จึงไม่เปลี่ยนข้อเท็จจริงที่ค้นได้; รายงานเก่าที่ไม่มีข้อความค้นจะ backfill ก่อน publish/reconcile หรือปฏิเสธเมื่อข้อมูลต้นทางไม่ครบ ไม่สร้างข้อความทั่วไปแทน; มีชื่อเล่นไทยครบ 20 ทีมของฤดูกาล 2026/27
- `X-Request-ID` และ Problem-JSON, เวลา Asia/Bangkok, `team_id` จาก football-data.org

ฐานข้อมูลใช้ schema `football` ใน PostgreSQL และสร้างตารางเมื่อแอปเริ่ม (`create_all`) ส่วน SQLite ใช้สำหรับพัฒนาในเครื่อง ยังต้องเพิ่ม Alembic ก่อน deploy จริง

## การรันในเครื่อง

ต้องมี Python 3.12+ จากนั้นรันในโฟลเดอร์นี้:

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
```

PowerShell:

```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///./football_data.db"
$env:FOOTBALL_DATA_API_KEY = "<key ของตัวเอง>"
$env:API_FOOTBALL_KEY = "<key ของตัวเอง>" # ต้องมีเมื่อใช้ details/all
$env:RETRIEVAL_URL = "http://localhost:8005"
$env:GENERATION_URL = "http://localhost:8006"
.venv/Scripts/uvicorn app.main:app --reload --port 8007
```

เริ่มดึงข้อมูล:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8007/ingest/run -ContentType application/json -Body '{"scope":"fixtures","triggered_by":"beat"}'
```

ดูสถานะด้วย `GET /jobs/{job_id}` และอ่าน API ที่ `/docs` ได้ เทสด้วย `pytest -q` และตรวจโค้ดด้วย `ruff check .` กับ `ruff format --check .` เทสปกติใช้บริการจำลอง ไม่เรียก API จริง

ตั้ง `RETRIEVAL_TEST_ROOT` เป็น absolute path ของ `services/05_retrieval_knowledge` เพื่อเปิดเทส HTTP ร่วมกับบริการ 05 จริง โดยต้องติดตั้ง `numpy faiss-cpu rank-bm25 pythainlp structlog` เพิ่มใน venv นี้ เทสนี้ใช้ FakeEmbedder และจำลอง API ฟุตบอล/Generation ไม่ใช่ end-to-end ของโมเดลจริง ดูหลักฐานและข้อจำกัดใน [LOCAL_REVIEW_VALIDATION.md](LOCAL_REVIEW_VALIDATION.md)

Worker จะกู้งาน publish/unpublish ที่ค้างหลัง grace period 120 วินาทีโดยยึดสถานะรายงานใน DB และยกเลิก task เมื่อ shutdown ตั้งเวลาได้ด้วย `INDEX_RETRY_SECONDS`, `INDEX_RETRY_MAX_SECONDS`, `INDEX_TRANSITION_TIMEOUT_SECONDS`

## ข้อมูลย้อนหลังและผลทดสอบ API จริง

เพิ่ม pipeline สำหรับ 34 ฤดูกาล, mapping 51 สโมสร และเอกสารย้อนหลัง 1,661 เอกสารแล้ว ดูคำสั่งใช้งาน ผลตรวจ API และข้อจำกัดใน [HISTORICAL_DATA.md](HISTORICAL_DATA.md) โดยยังปิด historical indexing จนกว่าทีมจะตกลง CONTRACT และ 05 รองรับ

ข้อมูลสดแพ็กเกจฟรีที่ทดสอบใช้ `scope=fixtures` จาก football-data.org เท่านั้น ส่วน API-Football ใช้ปี 2024/25 สาธิต เพราะ key ฟรีนี้ไม่รองรับ 2025/26–2026/27

เครดิตข้อมูลย้อนหลัง: © 2024 **Joshua C. Fjelstul, Ph.D.**, [Fjelstul English Football Database](https://github.com/jfjelstul/englishfootball), [CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/legalcode); ดัดแปลงโดย normalize ชื่อทีมและแปลงตารางเป็นสรุปข้อความ ร่วมกับ [openfootball/england](https://github.com/openfootball/england) (CC0 1.0) เอกสาร/ข้อมูลย้อนหลังที่สร้างเผยแพร่ภายใต้ CC-BY-SA 4.0

## งานที่ต้องทำต่อ (integration/deploy)

- เพิ่ม Alembic migration และทดสอบกับ PostgreSQL schema `football` จริง
- เพิ่ม lock/job queue ระดับฐานข้อมูลสำหรับหลาย worker และการกู้ job ที่ค้างเมื่อ process หยุด
- ทดสอบร่วมกับบริการ 05/06 และ API ภายนอกจริงหลังพร้อมใช้งาน รวมถึงตรวจความตรงของ alias และ fixture mapping กับข้อมูลจริง

ไม่ต้องใส่ API key ใน repository ให้ตั้งผ่าน environment หรือไฟล์ `.env` ที่ถูก ignore เท่านั้น
