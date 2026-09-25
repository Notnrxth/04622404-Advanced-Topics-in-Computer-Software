# 07 Football Data

FastAPI service สำหรับข้อมูลพรีเมียร์ลีกตาม `docs/CONTRACT.md` §6–7 อยู่ใน branch ของโมดูล 07 โดยเฉพาะ

## สิ่งที่มีแล้ว

- `GET /health`, `/ready`, `/football/status`, `/football/teams`, `/football/standings`, `/football/fixtures`, `/football/matches/{match_id}`
- `POST /ingest/run` รับ `scope=fixtures|details|all`: ดึง teams, matches, standings, scorers จาก football-data.org v4 และรายละเอียดนัดที่จบแล้วจาก API-Football; `details`/`all` ต้องตั้ง `API_FOOTBALL_KEY` ไม่เช่นนั้นตอบข้อผิดพลาดก่อนสร้าง job
- เก็บ API-Football quota ในฐานข้อมูล (จำกัด 90 คำขอต่อวัน UTC รวม retry), จับคู่ fixture จากวันเวลาและทีม, และเก็บ events/lineups/statistics ใน payload ของแมตช์
- บันทึกงานส่ง index ในฐานข้อมูลและส่งซ้ำด้วย `POST /index/reconcile` หรือเมื่อแอปเริ่มใหม่; `/football/status` แสดงจำนวนงานค้างและ quota แยกจากสถานะข้อมูลใน DB
- `GET /jobs`, `/jobs/{job_id}` สำหรับติดตาม job; ป้องกันการสั่ง job ชนิดเดียวกันซ้ำในระดับแอป
- `POST /reports/weekly/run` เรียกโมดูล 06 เพื่อสร้าง draft เมื่อแมตช์วีคจบครบ โดยสร้าง snapshot ตารางคะแนนย้อนหลังจากผลแข่งได้เมื่อ `currentMatchday` ขยับไปแล้ว; รายการ/อ่าน/แก้ไข/publish/unpublish รายงาน โดยมีงานชดเชยกรณีอัปเดต index สำเร็จแต่ DB commit ล้ม
- เก็บ Markdown ภาษาไทยไว้แสดงผล แต่สร้างข้อความค้นหาภาษาอังกฤษจากผลแข่งและตารางคะแนนที่ตรวจสอบได้สำหรับ index; มีชื่อเล่นไทยครบ 20 ทีมของฤดูกาล 2026/27
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

ดูสถานะด้วย `GET /jobs/{job_id}` และอ่าน API ที่ `/docs` ได้ เทสด้วย `pytest -q` และตรวจโค้ดด้วย `ruff check .` กับ `ruff format --check .` การทดสอบ integration ในเครื่องใช้บริการจำลอง ไม่เรียก API จริง

## งานที่ต้องทำต่อ

- เพิ่ม Alembic migration และทดสอบกับ PostgreSQL schema `football` จริง
- เพิ่ม lock/job queue ระดับฐานข้อมูลสำหรับหลาย worker และการกู้ job ที่ค้างเมื่อ process หยุด
- ทดสอบร่วมกับบริการ 05/06 และ API ภายนอกจริงหลังพร้อมใช้งาน รวมถึงตรวจความตรงของ alias และ fixture mapping กับข้อมูลจริง

ไม่ต้องใส่ API key ใน repository ให้ตั้งผ่าน environment หรือไฟล์ `.env` ที่ถูก ignore เท่านั้น
