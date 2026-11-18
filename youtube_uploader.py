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
import random
import socket
import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

CLIENT_SECRET = "auth/client_secret.json"
TOKEN_CACHE = "auth/token.json"
SCOPE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
SCOPE_READ = "https://www.googleapis.com/auth/youtube.readonly"
SCOPES = [SCOPE_UPLOAD]

# Transient failures worth retrying a chunk for (Google's recommended set)
RETRY_STATUS = {500, 502, 503, 504}
MAX_RETRIES = 6


class UploadCancelled(Exception):
    pass


def _get_authenticated_service(log=print, need=(SCOPE_UPLOAD,)):
    """Return an authorized YouTube API service object.

    need: scopes this call requires. If the cached token lacks one (e.g. the
    read-only scope for looking up scheduled videos), the browser consent
    opens once for the combined set; uploads never trigger that.
    """
    creds = None
    if os.path.exists(TOKEN_CACHE):
        creds = Credentials.from_authorized_user_file(TOKEN_CACHE)
    have = set(creds.scopes or []) if creds else set()

    if creds and not set(need) <= have:
        log("  YouTube: asking for read access (to see your scheduled videos) — "
            "approve it in the browser window")
        creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # Revoked, or expired — apps left in Google's "Testing" mode
                # get refresh tokens that die after 7 days. Re-consent.
                log("  YouTube login expired — opening browser to sign in again")
                creds = None
        if not creds or not creds.valid:
            if not os.path.exists(CLIENT_SECRET):
                raise FileNotFoundError(
                    f"Missing {CLIENT_SECRET}. Download OAuth client JSON from "
                    "Google Cloud Console and place it in auth/."
                )
            scopes = sorted(have | set(need) | {SCOPE_UPLOAD})
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, scopes)
            creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
        with open(TOKEN_CACHE, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def last_scheduled_publish(log=print, recent=50):
    """Latest future publishAt among your most recent uploads (scheduled
    videos are private with a publish time), as an RFC 3339 string, or None."""
    from datetime import datetime, timezone
    yt = _get_authenticated_service(log=log, need=(SCOPE_UPLOAD, SCOPE_READ))
    chan = yt.channels().list(part="contentDetails", mine=True).execute()
    if not chan.get("items"):
        return None
    uploads = chan["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                    maxResults=min(recent, 50)).execute().get("items", [])
    ids = [it["contentDetails"]["videoId"] for it in items]
    if not ids:
        return None
    now = datetime.now(timezone.utc)
    best = None
    for v in yt.videos().list(part="status", id=",".join(ids)).execute().get("items", []):
        at = v.get("status", {}).get("publishAt")
        if not at:
            continue
        when = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if when > now and (best is None or when > best):
            best = when
    return best.strftime("%Y-%m-%dT%H:%M:%SZ") if best else None


def upload_video(
    file_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "10",      # Music
    privacy: str = "unlisted",
    publish_at: str | None = None,
    log=print,
    progress=None,
    should_stop=None,
) -> str:
    """Upload a video to YouTube and return its URL.

    Args:
        file_path:    Path to the .mp4 file.
        title:        Video title.
        description:  Video description.
        tags:         List of keyword tags.
        category_id:  YouTube category (10 = Music).
        privacy:      unlisted | public | private.
        publish_at:   RFC 3339 UTC time ("2026-11-20T20:00:00Z"). When set,
                      the video uploads as private and YouTube publishes it
                      at that time (privacy is ignored).
        progress:     optional callable(frac in [0, 1]).
        should_stop:  optional callable; returning True aborts between chunks.

    Returns:
        Full YouTube video URL (https://youtu.be/<id>).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Video not found: {file_path}")

    youtube = _get_authenticated_service(log=log)

    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:
        status["privacyStatus"] = "private"   # required by the API for publishAt
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": status,
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
    retries = 0
    while response is None:
        if should_stop and should_stop():
            raise UploadCancelled("upload cancelled")
        try:
            chunk_status, response = request.next_chunk()
            retries = 0
        except (HttpError, ConnectionError, socket.timeout, TimeoutError) as e:
            transient = (not isinstance(e, HttpError)
                         or e.resp.status in RETRY_STATUS)
            if not transient or retries >= MAX_RETRIES:
                raise
            retries += 1
            wait = min(60, 2 ** retries) + random.random()
            log(f"  Upload hiccup ({e.__class__.__name__}), retry {retries}/{MAX_RETRIES} in {wait:.0f}s")
            time.sleep(wait)
            continue
        if chunk_status:
            frac = chunk_status.progress()
            log(f"  Upload progress: {int(frac * 100)}%")
            if progress:
                progress(frac)

    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"
    log(f"  Upload complete: {url}")
    if publish_at:
        log(f"  Scheduled to go public at {publish_at}")
    return url
