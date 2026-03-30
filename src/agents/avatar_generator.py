"""Deterministic avatar generator for agents.

Generates a simple identicon-style SVG from the agent's UUID hash.
The output is a data URI string that can be used directly in ``<img>`` tags
or stored in the ``avatar_url`` column.

Example::

    from src.agents.avatar_generator import generate_avatar
    avatar_data_uri = generate_avatar(agent_id)
"""

from __future__ import annotations

import hashlib
from uuid import UUID


def _hash_to_bytes(agent_id: UUID) -> bytes:
    """Return a stable 16-byte hash from an agent UUID."""
    return hashlib.md5(str(agent_id).encode()).digest()  # noqa: S324


def _byte_to_hex_color(b1: int, b2: int, b3: int) -> str:
    """Convert three bytes to a hex color string."""
    return f"#{b1:02x}{b2:02x}{b3:02x}"


def generate_avatar(agent_id: UUID, size: int = 80) -> str:
    """Generate a deterministic SVG identicon as a data URI.

    Produces a 5x5 grid identicon using the agent UUID as the seed.
    The left half is mirrored to the right for symmetry.

    Args:
        agent_id: The agent's UUID used as the hash seed.
        size: SVG width/height in pixels (default 80).

    Returns:
        A ``data:image/svg+xml,...`` URI string.
    """
    h = _hash_to_bytes(agent_id)

    # Primary color from first 3 bytes
    fg_color = _byte_to_hex_color(h[0], h[1], h[2])
    bg_color = "#f0f0f0"

    cell_size = size // 5
    rects: list[str] = []

    # Generate a 5x5 symmetric grid
    for row in range(5):
        for col in range(3):  # Only need left half + center
            byte_idx = (row * 3 + col) % len(h)
            is_filled = h[byte_idx] % 2 == 0

            if is_filled:
                # Draw on left side
                x = col * cell_size
                y = row * cell_size
                rects.append(f'<rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" fill="{fg_color}"/>')
                # Mirror to right side (except center column)
                if col < 2:
                    mirror_x = (4 - col) * cell_size
                    rects.append(
                        f'<rect x="{mirror_x}" y="{y}" width="{cell_size}" height="{cell_size}" fill="{fg_color}"/>'
                    )

    rects_str = "".join(rects)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}">'
        f'<rect width="{size}" height="{size}" fill="{bg_color}"/>'
        f"{rects_str}</svg>"
    )

    return f"data:image/svg+xml,{svg}"


def generate_color(agent_id: UUID) -> str:
    """Generate a deterministic hex color for an agent.

    Args:
        agent_id: The agent's UUID.

    Returns:
        A hex color string like ``"#a3b2c1"``.
    """
    h = _hash_to_bytes(agent_id)
    return _byte_to_hex_color(h[3], h[4], h[5])
