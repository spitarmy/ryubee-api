from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import uuid
from datetime import datetime

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

        # ここでファイルポインタを先頭に戻しておくと、
        # このあと再度 read() しても読み込めるようになる
        f.file.seek(0)

    return unique_files, kept_names, all_names


@app.post("/v1/volume-estimate")
async def volume_estimate(images: List[UploadFile] = File(...)):
    """
    立米AIダミー版エンドポイント
    - 画像を受け取る
    - 重複画像をまとめて1枚扱いにする
    - 仮の立米＆品目リストを返す
    """

    # ★ まず重複画像を除外
    deduped_images, kept_names, all_names = await deduplicate_images(images)

    request_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    dummy_response = {
        "request_id": request_id,
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

    return dummy_response
