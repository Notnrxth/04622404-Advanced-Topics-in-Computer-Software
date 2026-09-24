# 07 Football Data

FastAPI service สำหรับข้อมูลพรีเมียร์ลีกตาม `docs/CONTRACT.md` §6–7 อยู่ใน branch ของโมดูล 07 โดยเฉพาะ

## สิ่งที่มีแล้ว

- `GET /health`, `/ready`, `/football/status`, `/football/teams`, `/football/standings`, `/football/fixtures`, `/football/matches/{match_id}`
- `POST /ingest/run` รับ `scope=fixtures` แล้วสร้าง job เพื่อดึง teams, matches, standings, scorers จาก football-data.org v4 บันทึกในฐานข้อมูล และ upsert เอกสาร match/standings/fixtures ไปโมดูล 05
- `GET /jobs`, `/jobs/{job_id}` สำหรับติดตาม job; ป้องกันการสั่ง job ชนิดเดียวกันซ้ำในระดับแอป
- `POST /reports/weekly/run` เรียกโมดูล 06 เพื่อสร้าง draft เมื่อแมตช์วีคจบครบ, รายการ/อ่าน/แก้ไข/publish/unpublish รายงาน; publish และ unpublish อัปเดต index ของโมดูล 05 ก่อนเปลี่ยนสถานะ
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
$env:RETRIEVAL_URL = "http://localhost:8005"
$env:GENERATION_URL = "http://localhost:8006"
.venv/Scripts/uvicorn app.main:app --reload --port 8007
```

เริ่มดึงข้อมูล:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8007/ingest/run -ContentType application/json -Body '{"scope":"fixtures","triggered_by":"beat"}'
```

ดูสถานะด้วย `GET /jobs/{job_id}` และอ่าน API ที่ `/docs` ได้ เทสด้วย `pytest -q` และตรวจโค้ดด้วย `ruff check .`

## งานที่ต้องทำต่อ

- Adapter API-Football: map fixture ID ระหว่างสองแหล่ง, ดึง events/lineups/statistics เฉพาะนัดจบแล้ว, เก็บและบังคับ quota 90 ครั้ง/วัน; ตอนนี้ `scope=details` และ `scope=all` จบเป็น job `failed` พร้อม `NOT_IMPLEMENTED` ใน detail
- ระหว่างที่ยังไม่มี adapter ดังกล่าว ค่า `api_football_used_today` ใน `/football/status` เป็น `0` เสมอ
- เพิ่มชื่อเล่นไทยของทีมที่เหลือให้ครบทั้ง 20 ทีมของฤดูกาลจริงใน `app/team_aliases.json` (ตอนนี้มี 8 ทีมหลัก; ชื่อทางการของทุกทีมจะถูกเติมอัตโนมัติจาก API)
- เพิ่ม migration, ล็อก job ระดับฐานข้อมูลสำหรับหลาย worker, ทดสอบ integration กับ 05/06 และตรวจข้อมูลกับเว็บทางการ

ไม่ต้องใส่ API key ใน repository ให้ตั้งผ่าน environment หรือไฟล์ `.env` ที่ถูก ignore เท่านั้น
