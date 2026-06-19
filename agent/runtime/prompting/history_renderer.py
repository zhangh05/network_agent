# agent/runtime/prompting/history_renderer.py
"""History renderer — build user content with image support.

Moved from message_builder.py::_build_user_content_with_images.
"""

from __future__ import annotations

import re
import base64


def build_user_content_with_images(context, user_input: str) -> str | list:
    """Detect [文件引用: filepath=uploads/xxx.png] patterns and build multimodal content."""
    pattern = re.compile(r'\[文件引用:\s*([^\]]*)\]')
    match = pattern.search(user_input)
    if not match:
        return user_input

    refs_text = match.group(1)
    image_paths = []
    for part in refs_text.split(';'):
        part = part.strip()
        fp_match = re.search(r'filepath=(\S+)', part)
        ws_match = re.search(r'workspace_id=(\S+)', part)
        if fp_match:
            fpath = fp_match.group(1)
            ws = ws_match.group(1) if ws_match else 'default'
            if fpath.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                image_paths.append((ws, fpath))

    if not image_paths:
        return user_input

    text = pattern.sub('', user_input).strip()
    if not text:
        text = '请分析以下图片内容'

    content_parts = [{"type": "text", "text": text}]

    for ws, fpath in image_paths:
        try:
            from agent.modules.knowledge.ingestion import _ws_root
            img_path = _ws_root() / ws / fpath
            if img_path.exists():
                img_data = img_path.read_bytes()
                b64 = base64.b64encode(img_data).decode()
                ext = fpath.rsplit('.', 1)[-1].lower()
                mime = f'image/{ext}' if ext != 'jpg' else 'image/jpeg'
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"}
                })
                import sys
                print(f"[vision] embedded image: {img_path} ({len(img_data)} bytes)", file=sys.stderr)
            else:
                import sys
                print(f"[vision] image not found: {img_path}", file=sys.stderr)
        except Exception as e:
            import sys
            print(f"[vision] error reading {fpath}: {e}", file=sys.stderr)

    return content_parts if len(content_parts) > 1 else user_input
