# youtube_uploader.py
"""YouTube Data API v3 — OAuth 2.0 authentication and video upload.

First-run setup:
  1. Go to https://console.cloud.google.com
  2. Create a project → Enable "YouTube Data API v3"
  3. Create OAuth 2.0 credentials (Desktop app)
  4. Download the JSON → save as  auth/client_secret.json
  5. Run once — a browser window opens for consent.
     The refresh token is cached to  auth/token.json  for future runs.
"""

import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

CLIENT_SECRET = "auth/client_secret.json"
TOKEN_CACHE = "auth/token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _get_authenticated_service():
    """Return an authorized YouTube API service object."""
    creds = None

    if os.path.exists(TOKEN_CACHE):
        creds = Credentials.from_authorized_user_file(TOKEN_CACHE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRET):
                raise FileNotFoundError(
                    f"Missing {CLIENT_SECRET}. Download OAuth client JSON from "
                    "Google Cloud Console and place it in auth/."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
        with open(TOKEN_CACHE, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def upload_video(
    file_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "10",      # Music
    privacy: str = "unlisted",
    log=print,
) -> str:
    """Upload a video to YouTube and return its URL.

    Args:
        file_path:    Path to the .mp4 file.
        title:        Video title.
        description:  Video description.
        tags:         List of keyword tags.
        category_id:  YouTube category (10 = Music).
        privacy:      unlisted | public | private.

    Returns:
        Full YouTube video URL (https://youtu.be/<id>).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Video not found: {file_path}")

    youtube = _get_authenticated_service()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    # 32 MB chunks: fewer request round-trips than the default while still
    # giving progress updates and resumability.
    media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True,
                            chunksize=32 * 1024 * 1024)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    log("  Uploading to YouTube...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            log(f"  Upload progress: {pct}%")

    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"
    log(f"  Upload complete: {url}")
    return url