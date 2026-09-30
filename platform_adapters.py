"""Official social-platform publishing adapters.

The adapters intentionally support only documented API calls and never accept
account passwords, browser cookies, or scraped endpoints. Missing credentials,
missing account identifiers, and unsupported media requirements return explicit
errors instead of silently pretending to publish.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests


class PlatformPublishError(RuntimeError):
    """A platform rejected or cannot currently support a publish request."""


@dataclass
class PublishResult:
    platform: str
    account_slot: str
    status: str
    post_id: str | None = None
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "account_slot": self.account_slot,
            "status": self.status,
            "post_id": self.post_id,
            "message": self.message,
        }


def env_value(prefix: str, slot: str, suffix: str) -> str:
    return os.getenv(f"{prefix}_ACCOUNT_{slot}_{suffix}", "").strip()


def request_error(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)
            return str(payload.get("message") or payload)
    except ValueError:
        pass
    return response.text[:300] or f"HTTP {response.status_code}"


def post_json_or_form(
    method: str,
    url: str,
    *,
    data: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    response = requests.request(
        method,
        url,
        data=data,
        json=json_data,
        headers=headers,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise PlatformPublishError(request_error(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise PlatformPublishError("Platform returned a non-JSON response") from exc
    if not isinstance(payload, dict):
        raise PlatformPublishError("Platform returned an unexpected response")
    return payload


class FacebookPagesAdapter:
    platform = "facebook"

    def publish(self, draft: dict[str, Any], slot: str) -> PublishResult:
        page_id = env_value("FACEBOOK", slot, "PAGE_ID")
        token = env_value("FACEBOOK", slot, "TOKEN")
        if not page_id or not token:
            raise PlatformPublishError(
                f"Facebook account slot {slot} needs PAGE_ID and TOKEN"
            )
        version = os.getenv("META_GRAPH_API_VERSION", "v26.0")
        base_url = f"https://graph.facebook.com/{version}/{page_id}"
        caption = str(draft.get("caption", "")).strip()
        links = [str(x) for x in draft.get("video_links", [])[:2] if x]
        message = (caption + "\n\n" if caption and links else caption) + "\n".join(links)
        data: dict[str, Any] = {"message": message, "access_token": token}
        if links:
            # Facebook Page feed accepts one dedicated link preview; the
            # second link remains in the message text instead of being lost.
            data["link"] = links[0]

        # A Page feed link/text post does not require downloading a video.
        payload = post_json_or_form("POST", f"{base_url}/feed", data=data)
        return PublishResult(
            platform=self.platform,
            account_slot=slot,
            status="published",
            post_id=str(payload.get("id")) if payload.get("id") else None,
            message="Facebook Page feed post published",
        )


class InstagramAdapter:
    platform = "instagram"

    def publish(self, draft: dict[str, Any], slot: str) -> PublishResult:
        account_id = env_value("INSTAGRAM", slot, "IG_ID")
        token = env_value("INSTAGRAM", slot, "TOKEN")
        image_url = str(draft.get("external_image_url") or "").strip()
        if not account_id or not token:
            raise PlatformPublishError(
                f"Instagram account slot {slot} needs IG_ID and TOKEN"
            )
        if not image_url:
            raise PlatformPublishError(
                "Instagram image publishing needs a public external_image_url; Telegram file IDs are not public media URLs"
            )
        version = os.getenv("META_GRAPH_API_VERSION", "v26.0")
        host = os.getenv("INSTAGRAM_GRAPH_HOST", "https://graph.instagram.com").rstrip("/")
        base_url = f"{host}/{version}/{account_id}"
        caption = str(draft.get("caption", "")).strip()
        links = [str(x) for x in draft.get("video_links", [])[:2] if x]
        if links:
            caption = (caption + "\n\n" if caption else "") + "\n".join(links)
        container = post_json_or_form(
            "POST",
            f"{base_url}/media",
            data={"image_url": image_url, "caption": caption, "access_token": token},
        )
        creation_id = container.get("id")
        if not creation_id:
            raise PlatformPublishError("Instagram did not return a media container ID")
        published = post_json_or_form(
            "POST",
            f"{base_url}/media_publish",
            data={"creation_id": creation_id, "access_token": token},
        )
        return PublishResult(
            platform=self.platform,
            account_slot=slot,
            status="published",
            post_id=str(published.get("id")) if published.get("id") else None,
            message="Instagram image post published",
        )


class ThreadsAdapter:
    platform = "threads"

    def publish(self, draft: dict[str, Any], slot: str) -> PublishResult:
        user_id = env_value("THREADS", slot, "USER_ID")
        token = env_value("THREADS", slot, "TOKEN")
        if not user_id or not token:
            raise PlatformPublishError(
                f"Threads account slot {slot} needs USER_ID and TOKEN"
            )
        version = os.getenv("THREADS_API_VERSION", "v1.0")
        base_url = f"https://graph.threads.com/{version}/{user_id}"
        caption = str(draft.get("caption", "")).strip()
        links = [str(x) for x in draft.get("video_links", [])[:2] if x]
        if links:
            caption = (caption + "\n\n" if caption else "") + "\n".join(links)
        image_url = str(draft.get("external_image_url") or "").strip()
        data: dict[str, Any] = {"access_token": token}
        if image_url:
            data.update({"media_type": "IMAGE", "image_url": image_url, "text": caption})
        else:
            data.update({"media_type": "TEXT", "text": caption})
        container = post_json_or_form("POST", f"{base_url}/threads", data=data)
        creation_id = container.get("id")
        if not creation_id:
            raise PlatformPublishError("Threads did not return a media container ID")

        wait_seconds = int(os.getenv("THREADS_PUBLISH_WAIT_SECONDS", "30"))
        if wait_seconds > 0:
            time.sleep(min(wait_seconds, 60))
        published = post_json_or_form(
            "POST",
            f"{base_url}/threads_publish",
            data={"creation_id": creation_id, "access_token": token},
        )
        return PublishResult(
            platform=self.platform,
            account_slot=slot,
            status="published",
            post_id=str(published.get("id")) if published.get("id") else None,
            message="Threads post published",
        )


class XAdapter:
    platform = "x"

    def publish(self, draft: dict[str, Any], slot: str) -> PublishResult:
        token = env_value("X", slot, "USER_ACCESS_TOKEN")
        if not token:
            raise PlatformPublishError(f"X account slot {slot} needs USER_ACCESS_TOKEN")
        caption = str(draft.get("caption", "")).strip()
        links = [str(x) for x in draft.get("video_links", [])[:2] if x]
        text = (caption + "\n\n" if caption and links else caption) + "\n".join(links)
        if not text:
            raise PlatformPublishError("X needs text or links")
        # Text/link publishing does not upload the large Telegram video files.
        # Image upload is intentionally not guessed because X media upload uses
        # a separate authenticated upload flow and media IDs.
        if draft.get("external_image_url"):
            raise PlatformPublishError(
                "X image publishing needs the separate media-upload credential flow; text/link publishing is enabled first"
            )
        payload = post_json_or_form(
            "POST",
            "https://api.x.com/2/tweets",
            json_data={"text": text},
            headers={"Authorization": f"Bearer {token}"},
        )
        post_id = ((payload.get("data") or {}).get("id") if isinstance(payload.get("data"), dict) else None)
        return PublishResult(
            platform=self.platform,
            account_slot=slot,
            status="published",
            post_id=str(post_id) if post_id else None,
            message="X text/link post published",
        )


ADAPTERS = {
    "facebook": FacebookPagesAdapter(),
    "instagram": InstagramAdapter(),
    "threads": ThreadsAdapter(),
    "x": XAdapter(),
}


def publish_to_platform(platform: str, draft: dict[str, Any], slot: str) -> PublishResult:
    adapter = ADAPTERS.get(platform)
    if adapter is None:
        raise PlatformPublishError(f"Unsupported platform: {platform}")
    return adapter.publish(draft, slot)