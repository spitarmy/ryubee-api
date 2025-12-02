from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import uuid
from datetime import datetime

app = FastAPI()

# 一旦どこからでも叩けるように（あとで制限してOK）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 後で Vercel のドメインだけに絞ってもいい
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/v1/volume-estimate")
async def volume_estimate(images: List[UploadFile] = File(...)):
    """
    今はダミー実装：
    - 画像は受け取るだけ
    - 仮の立米と品目リストを返す
    """

    request_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # 受け取ったファイル名だけ一覧にしておく（デバッグ用）
    image_names = [img.filename for img in images]

    dummy_response = {
        "request_id": request_id,
        "total_volume_m3": 5.0,
        "volume_detail": {
            "base_volume_m3": 4.5,
            "scene_volume_m3": 2.0,
            "safety_factor": 1.10,
            "rounded_rule": "0.5m3切り上げ"
        },
        "items": [
            {
                "category": "冷蔵庫",
                "subtype": "2ドア",
                "size_class": "中",
                "quantity": 1,
                "volume_per_item_m3": 0.6,
                "volume_total_m3": 0.6,
                "flags": ["家電リサイクル"]
            },
            {
                "category": "マットレス",
                "subtype": "シングル",
                "size_class": "中",
                "quantity": 1,
                "volume_per_item_m3": 0.48,
                "volume_total_m3": 0.48,
                "flags": ["特処分"]
            }
        ],
        "special_disposal": {
            "recycle_items": ["冷蔵庫（2ドア）"],
            "hard_disposal_items": ["マットレス（シングル）"],
            "dangerous_items": []
        },
        "warnings": [
            "2階以上の大型家具が含まれる可能性があります。",
            "マットレスは特処分品です。"
        ],
        "debug": {
            "received_images": image_names
        }
    }

    return dummy_response
