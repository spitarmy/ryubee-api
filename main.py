import os
import uuid
from datetime import datetime
from typing import Optional, Any, List

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv  # ← .env を読むために追加

# .env を読み込む
load_dotenv()

# ==========================================================
# ① Supabase API 設定（.env から読み込み）
# ==========================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY が設定されていません (.env を確認してください)"
    )


def supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def supabase_table_url(table: str) -> str:
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
    """立米AI用のリクエスト。今は JobBase と同じ構造。"""
    pass


class VolumeEstimateResponse(BaseModel):
    job: Job
    message: str = "ok"


# ==========================================================
# ③ FastAPI 初期化
# ==========================================================

app = FastAPI(title="Ryubee API (Supabase version)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番で必要ならドメインを絞る
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
        **data,
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

@app.get("/v1/health")
def health_check():
    return {"status": "ok"}


@app.post("/v1/volume-estimate", response_model=VolumeEstimateResponse)
def create_and_estimate(payload: VolumeEstimateRequest):
    """
    ここに現在の AI 立米計算ロジックを移植してください。
    ↓ この3つを埋めて Supabase 保存
    - total_volume_m3
    - price_total
    - ai_result
    """
    # TODO: OpenAI を呼び出して total_volume_m3 / price_total / ai_result を計算する処理をここに入れる

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
    # ここで job を取得して PDF を生成する
    job = supabase_select_job(job_id)
    # TODO: 既存の PDF 生成ロジックをここに移植
    raise HTTPException(501, "PDF ロジック未実装（既存PDF生成をここに貼り付け）")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
