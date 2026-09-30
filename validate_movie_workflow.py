import asyncio
import os
import tempfile
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("BOT_TOKEN", "123456:TEST")

import bot


class FakeTelegram:
    def __init__(self):
        self.calls = []

    async def send_file(self, target, path, caption=None, supports_streaming=False):
        self.calls.append((target, Path(path).name, caption, supports_streaming))


async def main():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as media:
        media.write(b"test video")
        media_path = media.name
    try:
        fake = FakeTelegram()
        draft = {"media_path": media_path, "media_kind": "video", "caption": "Movie #movie", "channel_name": "Test Channel", "video_link": "https://example.com/video"}
        data = {
            "channels": {"channel_a": "@a", "channel_b": "@b", "channel_c": "@c"},
            "forwarding": {"next_target_index": 0},
        }
        for count, expected in enumerate(("@a", "@b", "@c"), start=1):
            results = await bot.publish_movie_draft(fake, draft, data)
            assert len(fake.calls) == count, fake.calls
            assert fake.calls[-1][0] == expected, fake.calls
            assert fake.calls[-1][3] is True, fake.calls
            assert "Test Channel" in fake.calls[-1][2], fake.calls
            assert results[0].startswith("✅"), results
        assert data["forwarding"]["next_target_index"] == 0, data
        print("round-robin movie workflow validation passed")
    finally:
        os.unlink(media_path)


asyncio.run(main())
