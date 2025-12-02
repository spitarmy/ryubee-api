from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import uuid
from datetime import datetime
import json
import os

from pydantic import BaseModel
from PIL import Image
import imagehash
from io import BytesIO

app = FastAPI()

# CORS（フロントのRyu兵衛から叩けるようにする）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 慣れてきたら Vercel のドメインだけに絞ってOK
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 「どれくらい似てたら同じ画像とみなすか」のしきい値（0〜64くらい）
# 値が小さいほど厳しめ（5〜8あたりが現実的）
DUP_HASH_THRESHOLD = 5

# 案件データを保存するファイル名（超シンプルにJSONで）
JOBS_FILE = "jobs.json"

# メモリ上の案件データ（起動中ずっと保持）
jobs = {}  # job_id -> dict


def load_jobs_from_file():
    global jobs
    if os.path.exists(JOBS_FILE):
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                jobs = json.load(f)
        except Exception:
            jobs = {}
    else:
        jobs = {}


def save_jobs_to_file():
    try:
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
    except Exception:
        # 本番ではログに出したりしてもよいが、今は軽く無視
        pass


# 起動時に一度だけ読み込む
load_jobs_from_file()


class JobUpdate(BaseModel):
    """ユーザーが後から編集できる項目だけを定義"""

    job_name: Optional[str] = None        # 現場名（例：伏見区○○様 不用品回収）
    customer_name: Optional[str] = None   # お客様名
    address: Optional[str] = None         # 住所
    work_date: Optional[str] = None       # 作業日（文字列でOK：2025-12-10 など）
    work_time: Optional[str] = None       # 作業時間帯（10:00-12:00 など）
    price_total: Optional[float] = None   # 見積金額（税込）
    truck_type: Optional[str] = None      # 使用トラック種別（2t / 3t など）
    workers: Optional[int] = None         # 作業員人数
    notes: Optional[str] = None           # 備考（階段・EVなし・要養生など）


async def deduplicate_images(files: List[UploadFile]):
    """
    角度違い・ほぼ同じ構図の画像をまとめて1枚扱いにする。
    - imagehash の pHash（知覚ハッシュ）で類似度を見て、
      しきい値以下なら「重複」と判断して弾く。
    """
    unique_files: List[UploadFile] = []
    hashes = []
    kept_names = []
    all_names = [f.filename for f in files]

    for f in files:
        # UploadFile からバイト列を取り出す
        content = await f.read()

        try:
            img = Image.open(BytesIO(content))
        except Exception:
            # 画像として読めなければスキップ
            continue

        # pHash を計算
        h = imagehash.phash(img)

        # すでにあるハッシュとの距離を見て「似ているかどうか」判定
        is_dup = False
        for existing in hashes:
            if h - existing <= DUP_HASH_THRESHOLD:
                # 似すぎている＝重複と判断
                is_dup = True
                break

        if not is_dup:
            hashes.append(h)
            unique_files.append(f)
            kept_names.append(f.filename)

        # このあとまた read() できるようにポインタを先頭に戻す
        f.file.seek(0)

    return unique_files, kept_names, all_names


@app.post("/v1/volume-estimate")
async def volume_estimate(images: List[UploadFile] = File(...)):
    """
    立米AIエンドポイント（ダミー版）
    - 画像を受け取る
    - 重複画像をまとめて1枚扱いにする
    - 仮の立米＆品目リストを返す
    - 同時に「案件レコード」を作成して保存する
    """

    # ★ まず重複画像を除外
    deduped_images, kept_names, all_names = await deduplicate_images(images)

    # ★ 案件ID = request_id = 一意なID
    request_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    job_id = request_id
    now_iso = datetime.utcnow().isoformat()

    # ★ ダミーの立米結果（ここは後で本物ロジックに置き換える）
    dummy_response = {
        "request_id": request_id,
        "job_id": job_id,  # フロントからもこのIDで案件をひけるように
        "total_volume_m3": 5.0,
        "volume_detail": {
            "base_volume_m3": 4.5,
            "scene_volume_m3": 2.0,
            "safety_factor": 1.10,
            "rounded_rule": "0.5m3切り上げ",
        },
        "items": [
            {
                "category": "冷蔵庫",
                "subtype": "2ドア",
                "size_class": "中",
                "quantity": 1,
                "volume_per_item_m3": 0.6,
                "volume_total_m3": 0.6,
                "flags": ["家電リサイクル"],
            },
            {
                "category": "マットレス",
                "subtype": "シングル",
                "size_class": "中",
                "quantity": 1,
                "volume_per_item_m3": 0.48,
                "volume_total_m3": 0.48,
                "flags": ["特処分"],
            },
        ],
        "special_disposal": {
            "recycle_items": ["冷蔵庫（2ドア）"],
            "hard_disposal_items": ["マットレス（シングル）"],
            "dangerous_items": [],
        },
        "warnings": [
            "2階以上の大型家具が含まれる可能性があります。",
            "マットレスは特処分品です。",
        ],
        "debug": {
            "received_count": len(all_names),         # フロントから送られてきた枚数
            "after_dedup_count": len(deduped_images), # 重複除外後に残った枚数
            "all_images": all_names,                  # 全ファイル名
            "kept_images": kept_names,                # 解析に使うファイル名
        },
    }

    # ★ 案件レコードを作成して保存
    job_record = {
        "job_id": job_id,
        "job_name": "",          # ここはフロントからあとで編集してもらう
        "created_at": now_iso,
        "updated_at": now_iso,
        "customer_name": "",
        "address": "",
        "work_date": "",
        "work_time": "",
        "price_total": None,
        "truck_type": "",
        "workers": None,
        "notes": "",
        "total_volume_m3": dummy_response["total_volume_m3"],
        "ai_result": dummy_response,  # 立米AIの結果をまるごと保持
    }

    jobs[job_id] = job_record
    save_jobs_to_file()

    return dummy_response


@app.get("/v1/jobs")
def list_jobs():
    """
    案件一覧を返す（営業用の履歴画面イメージ）
    - 新しい順にソート
    """
    job_list = list(jobs.values())
    job_list.sort(key=lambda j: j.get("created_at", ""), reverse=True)

    # 一覧では必要そうな項目だけ返す
    summarized = []
    for j in job_list:
        summarized.append(
            {
                "job_id": j["job_id"],
                "job_name": j.get("job_name", ""),
                "created_at": j.get("created_at", ""),
                "customer_name": j.get("customer_name", ""),
                "address": j.get("address", ""),
                "total_volume_m3": j.get("total_volume_m3", None),
                "price_total": j.get("price_total", None),
            }
        )
    return summarized


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str):
    """
    1件分の案件詳細を返す
    - 立米AIの結果（ai_result）も含む
    """
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/v1/jobs/{job_id}")
def update_job(job_id: str, payload: JobUpdate):
    """
    案件情報を更新する（営業が後から編集）
    - 現場名
    - お客様情報
    - 金額 etc.
    """
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    data = payload.dict(exclude_unset=True)
    for k, v in data.items():
        job[k] = v

    job["updated_at"] = datetime.utcnow().isoformat()

    jobs[job_id] = job
    save_jobs_to_file()

    return job
