import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

HELPER_DIR = Path(__file__).parents[2] / "blob_helper"


@dataclass
class BlobResult:
    url: str
    pathname: str


def download(url: str) -> bytes:
    token = os.environ["BLOB_READ_WRITE_TOKEN"]
    resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    resp.raise_for_status()
    return resp.content


def upload(pathname: str, local_path: str, content_type: str) -> BlobResult:
    result = subprocess.run(
        ["node", "put.mjs", pathname, local_path, content_type],
        cwd=HELPER_DIR,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ},
    )
    data = json.loads(result.stdout)
    return BlobResult(url=data["url"], pathname=data["pathname"])
