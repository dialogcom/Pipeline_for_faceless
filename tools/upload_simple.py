#!/usr/bin/env python3
"""Simple YouTube upload using resumable with small chunks."""
import json
import os
import sys
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(ROOT, "tools", "youtube_token.json")

def get_token():
    with open(TOKEN_FILE) as f:
        token_data = json.load(f)
    return token_data.get('token')

def upload_video(file_path, title, description, tags, token):
    """Upload video using resumable with small file."""
    file_size = os.path.getsize(file_path)

    # Step 1: Initiate resumable upload
    url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"

    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "27"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(file_size)
    }

    req = urllib.request.Request(url, data=json.dumps(metadata).encode('utf-8'), headers=headers, method='POST')

    try:
        print(f"Инициализация загрузки {os.path.basename(file_path)} ({file_size} bytes)...")
        with urllib.request.urlopen(req, timeout=60) as response:
            upload_url = response.headers.get('Location')
            if not upload_url:
                print("Error: No upload URL in response")
                return None

        print(f"Загружаю файл...")
        # Step 2: Upload the file
        with open(file_path, 'rb') as f:
            video_data = f.read()

        headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(file_size)
        }

        req = urllib.request.Request(upload_url, data=video_data, headers=headers, method='PUT')

        with urllib.request.urlopen(req, timeout=600) as response:
            result = json.loads(response.read().decode('utf-8'))
            video_id = result.get('id')
            print(f"✓ Видео загружено: {video_id}")
            return video_id

    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
        print(e.read().decode('utf-8'))
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: upload_simple.py <file> <title> <description> <tags>")
        sys.exit(1)

    file_path = sys.argv[1]
    title = sys.argv[2]
    description = sys.argv[3]
    tags = sys.argv[4].split(',')

    token = get_token()
    upload_video(file_path, title, description, tags, token)
