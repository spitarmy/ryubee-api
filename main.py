import os
import uuid
from datetime import datetime
from typing import Optional, Any, List

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ==========================================================
# ① ここに Supabase API を差し込む（.env から読む）
# ==========================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")  # https://cquygugcndkkvxxpsgwi.supabase.co
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNxdXlndWdjbmRra3Z4eHBzZ3dpIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2NDc1NjY0NSwiZXhwIjoyMDgwMzMyNjQ1fQ.t5UNLecCHF6Q_GdB81s2tRLyyI4BufgLSNGF31el6ko

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY が設定されていません (.env を確認してください)")

def supabase_headers():
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def supabase_table_url(table: str):
    return f"{SUPABASE_URL}/rest/v1/{table}"


# ==========================================================
# ② Pydantic モデル（jobs の構造）
# ==========================================================

class JobBase(BaseModel):
    job_name: str
    customer_name: Optional[str] = None
    address: Optional[str] = None
    work_date: Optional[str] = None
    work_time: Optional[str] = None
    price_total: Optional[float] = None
    truck_type: Optional[str] = None
    workers: Optional[int] = None
    notes: Optional[str] = None
    total_volume_m3: Optional[float] = None
    ai_result: Optional[Any] = None


class Job(JobBase):
    job_id: str
    created_at: datetime
    updated_at: datetime


class JobUpdate(BaseModel):
    job_name: Optional[str] = None
    customer_name: Optional[str] = None
    address: Optional[str] = None
    work_date: Optional[str] = None
    work_time: Optional[str] = None
    price_total: Optional[float] = None
    truck_type: Optional[str] = None
    workers: Optional[int] = None
    notes: Optional[str] = None
    total_volume_m3: Optional[float] = None
    ai_result: Optional[Any] = None


class VolumeEstimateRequest(JobBase):
    pass


class VolumeEstimateResponse(BaseModel):
    job: Job
    message: str = "ok"


# ==========================================================
# ③ FastAPI 初期化
# ==========================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================================
# ④ Supabase 操作（SELECT / INSERT / UPDATE）
# ==========================================================

TABLE = "jobs"

def supabase_insert_job(data: dict) -> Job:
    url = supabase_table_url(TABLE)
    now = datetime.utcnow().isoformat()

    payload = [{
        "job_id": data.get("job_id", str(uuid.uuid4())),
        "created_at": now,
        "updated_at": now,
        **data
    }]

    res = requests.post(url, headers=supabase_headers(), json=payload)
    if not res.ok:
        raise HTTPException(500, f"Supabase insert error: {res.text}")

    return Job(**res.json()[0])


def supabase_select_job(job_id: str) -> Job:
    url = supabase_table_url(TABLE)
    params = {"job_id": f"eq.{job_id}", "select": "*"}
    res = requests.get(url, headers=supabase_headers(), params=params)

    if not res.ok:
        raise HTTPException(500, f"Supabase select error: {res.text}")

    data = res.json()
    if not data:
        raise HTTPException(404, "job not found")

    return Job(**data[0])


def supabase_select_jobs() -> List[Job]:
    url = supabase_table_url(TABLE)
    params = {"select": "*", "order": "created_at.desc"}
    res = requests.get(url, headers=supabase_headers(), params=params)

    if not res.ok:
        raise HTTPException(500, f"Supabase select error: {res.text}")

    return [Job(**item) for item in res.json()]


def supabase_update_job(job_id: str, data: dict) -> Job:
    url = supabase_table_url(TABLE)
    data["updated_at"] = datetime.utcnow().isoformat()

    params = {"job_id": f"eq.{job_id}", "select": "*"}
    res = requests.patch(url, headers=supabase_headers(), params=params, json=data)

    if not res.ok:
        raise HTTPException(500, f"Supabase update error: {res.text}")

    return Job(**res.json()[0])


# ==========================================================
# ⑤ API エンドポイント
# ==========================================================

@app.post("/v1/volume-estimate", response_model=VolumeEstimateResponse)
def create_and_estimate(payload: VolumeEstimateRequest):
    """
    ここに現在の AI 立米計算ロジックを移植してください。
    ↓ この3つを埋めて Supabase 保存
    - total_volume_m3
    - price_total
    - ai_result
    """
    job = supabase_insert_job(payload.dict())
    return VolumeEstimateResponse(job=job)


@app.get("/v1/jobs", response_model=List[Job])
def list_jobs():
    return supabase_select_jobs()


@app.get("/v1/jobs/{job_id}", response_model=Job)
def get_job(job_id: str):
    return supabase_select_job(job_id)


@app.post("/v1/jobs/{job_id}", response_model=Job)
def update_job(job_id: str, payload: JobUpdate):
    return supabase_update_job(job_id, payload.dict(exclude_unset=True))


@app.get("/v1/jobs/{job_id}/worksheet")
def job_pdf(job_id: str):
    job = supabase_select_job(job_id)
    raise HTTPException(501, "PDF ロジック未実装（既存PDF生成をここに貼り付け）")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
