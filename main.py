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

from starlette.responses import StreamingResponse

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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

# 案件データを保存するファイル名（シンプルにJSONで）
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

# 日本語フォントの登録（文字化け防止）
FONT_NAME = "JP"
FONT_PATH = "fonts/ipaexg.ttf"

try:
    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
except Exception:
    # フォントが見つからない/読み込めない場合は英字フォントにフォールバック
    FONT_NAME = "Helvetica"


class JobUpdate(BaseModel):
    """ユーザーが後から編集できる項目だけを定義"""

    job_name: Optional[str] = None        # 現場名
    customer_name: Optional[str] = None   # お客様名
    address: Optional[str] = None         # 住所
    work_date: Optional[str] = None       # 作業日
    work_time: Optional[str] = None       # 作業時間帯
    price_total: Optional[float] = None   # 見積金額（税込）
    truck_type: Optional[str] = None      # 使用トラック種別
    workers: Optional[int] = None         # 作業員人数
    notes: Optional[str] = None           # 備考


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

    # 1. 重複画像を除外
    deduped_images, kept_names, all_names = await deduplicate_images(images)

    # 2. 案件ID = request_id
    request_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    job_id = request_id
    now_iso = datetime.utcnow().isoformat()

    # 3. ダミーの立米結果（あとで本物ロジックに差し替え）
    dummy_response = {
        "request_id": request_id,
        "job_id": job_id,
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
            "received_count": len(all_names),
            "after_dedup_count": len(deduped_images),
            "all_images": all_names,
            "kept_images": kept_names,
        },
    }

    # 4. 案件レコードを作成して保存
    job_record = {
        "job_id": job_id,
        "job_name": "",
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
        "ai_result": dummy_response,
    }

    jobs[job_id] = job_record
    save_jobs_to_file()

    return dummy_response


@app.get("/v1/jobs")
def list_jobs():
    """
    案件一覧を返す（営業用の履歴画面イメージ）
    """
    job_list = list(jobs.values())
    job_list.sort(key=lambda j: j.get("created_at", ""), reverse=True)

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
    """
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/v1/jobs/{job_id}")
def update_job(job_id: str, payload: JobUpdate):
    """
    案件情報を更新する（営業が後から編集）
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


def generate_worksheet_pdf(job: dict) -> BytesIO:
    """
    作業書PDFを1枚生成して BytesIO として返す。
    A4縦 / シンプルなレイアウト。
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    margin_x = 40
    y = height - 40

    def draw_text(line, text, size=10):
        nonlocal y
        c.setFont(FONT_NAME, size)
        c.drawString(margin_x, y, text)
        y -= line

    # タイトル
    c.setFont(FONT_NAME, 16)
    c.drawString(margin_x, y, "作業指示書")
    y -= 30

    # 案件基本情報
    draw_text(16, f"案件ID：{job.get('job_id', '')}", 10)
    draw_text(16, f"現場名：{job.get('job_name', '')}", 10)
    draw_text(16, f"お客様名：{job.get('customer_name', '')}", 10)
    draw_text(16, f"住所：{job.get('address', '')}", 10)
    draw_text(16, f"作業日：{job.get('work_date', '')}", 10)
    draw_text(16, f"作業時間帯：{job.get('work_time', '')}", 10)

    price = job.get("price_total")
    price_str = f"{int(price):,} 円（税込）" if price is not None else "-"
    draw_text(16, f"見積金額：{price_str}", 10)

    draw_text(16, f"トラック種別：{job.get('truck_type', '')}", 10)
    workers = job.get("workers")
    workers_str = f"{workers} 名" if workers is not None else "-"
    draw_text(16, f"作業員人数：{workers_str}", 10)

    y -= 10
    c.line(margin_x, y, width - margin_x, y)
    y -= 20

    # 立米と品目（AI結果から）
    ai = job.get("ai_result", {})
    total_volume = ai.get("total_volume_m3")
    total_volume_str = f"{total_volume} ㎥" if total_volume is not None else "-"

    draw_text(16, f"想定立米：{total_volume_str}", 10)

    y -= 10
    c.setFont(FONT_NAME, 11)
    c.drawString(margin_x, y, "品目一覧：")
    y -= 18

    items = ai.get("items") or []
    if not items:
        draw_text(14, "（品目情報なし）", 10)
    else:
        c.setFont(FONT_NAME, 9)
        # 簡易テーブルヘッダ
        headers = ["品目", "サブタイプ", "数量", "立米小計"]
        col_x = [margin_x, margin_x + 160, margin_x + 300, margin_x + 360]
        for i, h_txt in enumerate(headers):
            c.drawString(col_x[i], y, h_txt)
        y -= 14
        c.line(margin_x, y + 4, width - margin_x, y + 4)
        y -= 8

        for it in items:
            if y < 80:
                c.showPage()
                c.setFont(FONT_NAME, 9)
                y = height - 60
            c.drawString(col_x[0], y, str(it.get("category", "")))
            c.drawString(col_x[1], y, str(it.get("subtype", "")))
            c.drawString(col_x[2], y, str(it.get("quantity", "")))
            c.drawString(col_x[3], y, str(it.get("volume_total_m3", "")))
            y -= 14

    y -= 10
    c.line(margin_x, y, width - margin_x, y)
    y -= 20

    # 備考
    notes = job.get("notes") or ""
    draw_text(16, "備考：", 10)
    if notes:
        # 行ごとにざっくり折り返し
        c.setFont(FONT_NAME, 10)
        max_width = width - margin_x * 2
        for line in notes.splitlines():
            # 単純に長さでカット（ざっくりでOK）
            while line:
                part = line[:40]
                c.drawString(margin_x, y, part)
                y -= 14
                line = line[40:]
                if y < 60:
                    c.showPage()
                    c.setFont(FONT_NAME, 10)
                    y = height - 60
    else:
        draw_text(14, "（特記事項なし）", 10)

    y -= 20
    c.line(margin_x, y, width - margin_x, y)
    y -= 20

    # 確認サイン欄
    draw_text(16, "お客様確認サイン：", 10)
    c.rect(margin_x + 110, y + 4, 200, 40)  # サイン枠

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


@app.get("/v1/jobs/{job_id}/worksheet")
def get_job_worksheet(job_id: str):
    """
    案件の作業書PDFを生成して返す
    """
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    pdf_bytes = generate_worksheet_pdf(job)
    filename = f"worksheet_{job_id}.pdf"

    return StreamingResponse(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
