import os
import httpx
import asyncio
from typing import List
from urllib.parse import quote

# 动画资源列表 (GitHub Raw URLs)
BASE_URL = "https://raw.githubusercontent.com/tk256ailab/vrm-viewer/main/VRMA/"
VRMA_FILES = [
    "Angry.vrma",
    "Blush.vrma",
    "Clapping.vrma",
    "Goodbye.vrma",
    "Jump.vrma",
    "LookAround.vrma",
    "Relax.vrma",
    "Sad.vrma",
    "Sleepy.vrma",
    "Surprised.vrma",
    "Thinking.vrma",
    "愤怒的.vrma",
    "腮红.vrma",
    "鼓掌.vrma",
    "再见。.vrma",
    "环顾四周.vrma",
    "放松.vrma",
    "悲伤的.vrma",
    "瞌睡.vrma",
    "惊讶.vrma",
    "思考.vrma"
]

TARGET_DIR = "static/vrm/animation"

async def download_file(client: httpx.AsyncClient, filename: str):
    url = BASE_URL + quote(filename)
    path = os.path.join(TARGET_DIR, filename)
    
    # Skip if already exists
    if os.path.exists(path):
        print(f"Skipping {filename}, already exists.")
        return

    try:
        response = await client.get(url, follow_redirects=True, timeout=30.0)
        if response.status_code == 200:
            with open(path, "wb") as f:
                f.write(response.content)
            print(f"Successfully downloaded: {filename}")
        else:
            # Some might be duplicates (English vs Chinese names in different commit versions)
            # We'll just ignore 404s for the variations
            if response.status_code != 404:
                print(f"Failed to download {filename}: HTTP {response.status_code}")
    except Exception as e:
        print(f"Error downloading {filename}: {e}")

async def main():
    os.makedirs(TARGET_DIR, exist_ok=True)
    async with httpx.AsyncClient() as client:
        tasks = [download_file(client, f) for f in VRMA_FILES]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
