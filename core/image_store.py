"""
Image asset storage helpers.

The chat model may need a base64 data URL for the current turn, but conversation
history should only keep stable image references plus a short summary.
"""

import base64
import copy
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple


DATA_URL_RE = re.compile(r"^data:(image/[-+.\w]+);base64,(.+)$", re.DOTALL)


class ImageStore:
    """Stores image payloads once and rewrites chat history to image refs."""

    @staticmethod
    def is_data_image_url(url: str) -> bool:
        return bool(isinstance(url, str) and DATA_URL_RE.match(url))

    @staticmethod
    def parse_data_url(data_url: str) -> Tuple[str, str, int, str]:
        match = DATA_URL_RE.match(data_url)
        if not match:
            raise ValueError("Unsupported image data URL")

        mime_type = match.group(1)
        base64_data = match.group(2)
        raw = base64.b64decode(base64_data, validate=True)
        sha256 = hashlib.sha256(raw).hexdigest()
        return mime_type, base64_data, len(raw), sha256

    @staticmethod
    def build_summary(image_id: str, mime_type: str, size_bytes: int, source_url: Optional[str] = None) -> str:
        size_kb = round(size_bytes / 1024, 1)
        source_text = f", source={source_url}" if source_url else ""
        return f"Image {image_id}: {mime_type}, {size_kb} KB{source_text}. Use the original image only when visual details are required."

    @classmethod
    def store_processed_messages(
        cls,
        db: Any,
        session_id: str,
        original_messages: List[Dict[str, Any]],
        processed_messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Persist data URLs as assets and return history-safe messages."""
        storage_messages = copy.deepcopy(processed_messages)

        for msg_index, msg in enumerate(storage_messages):
            if msg.get("role") != "user":
                continue

            content = msg.get("content")
            if not isinstance(content, list):
                continue

            original_content = None
            if msg_index < len(original_messages):
                original_content = original_messages[msg_index].get("content")

            for item_index, item in enumerate(content):
                if item.get("type") != "image_url":
                    continue

                image_url_obj = item.get("image_url", {})
                if not isinstance(image_url_obj, dict):
                    continue

                data_url = image_url_obj.get("url", "")
                if not cls.is_data_image_url(data_url):
                    continue

                source_url = cls._get_original_url(original_content, item_index)
                mime_type, base64_data, size_bytes, sha256 = cls.parse_data_url(data_url)
                image_id = db.upsert_image_asset(
                    session_id=session_id,
                    mime_type=mime_type,
                    data_base64=base64_data,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    source_url=source_url,
                    summary=cls.build_summary(sha256[:16], mime_type, size_bytes, source_url),
                )
                image = db.get_image_asset(image_id)
                summary = image.get("summary") if image else cls.build_summary(image_id, mime_type, size_bytes, source_url)

                item.clear()
                item.update({
                    "type": "image_ref",
                    "image_id": image_id,
                    "summary": summary,
                })

        return storage_messages

    @staticmethod
    def _get_original_url(original_content: Any, item_index: int) -> Optional[str]:
        if not isinstance(original_content, list) or item_index >= len(original_content):
            return None

        original_item = original_content[item_index]
        if not isinstance(original_item, dict) or original_item.get("type") != "image_url":
            return None

        image_url_obj = original_item.get("image_url", {})
        if isinstance(image_url_obj, dict):
            url = image_url_obj.get("url")
            if isinstance(url, str) and url.startswith("data:image/"):
                return None
            return url
        return None

    @staticmethod
    def refs_to_summary_content(content: Any) -> Any:
        """Convert saved image refs into text-only context snippets."""
        if not isinstance(content, list):
            return content

        converted = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "image_ref":
                image_id = item.get("image_id", "unknown")
                summary = item.get("summary") or f"Image reference {image_id}."
                converted.append({
                    "type": "text",
                    "text": f"[Historical image {image_id}] {summary}",
                })
            else:
                converted.append(item)
        return converted
