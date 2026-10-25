"""Tested board-value mapping for the existing Kernel.cpp representation.

This module is an offline adapter. It does not change or call the C++ engine.
Castling rights and EP state must be supplied from the engine's actual state.
"""

from __future__ import annotations

import numpy as np

from .features import decode_position

TYPE_MAP = {1: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}


def encode_kernel_board(board, *, white_to_move: bool, castling_flags, ep_file: int | None = None):
    cells = np.asarray(board)
    if cells.shape != (8, 8) or cells.dtype.kind not in "ui":
        raise ValueError("Expected Kernel's 8x8 integer board in a8..h1 order")
    if len(castling_flags) != 4 or any(x not in (0, 1, False, True) for x in castling_flags):
        raise ValueError("Supply four retained castling rights: White K,Q, Black k,q")
    if ep_file is not None and (isinstance(ep_file, bool) or not isinstance(ep_file, int) or not 0 <= ep_file <= 7):
        raise ValueError("ep_file must be None or a=0 through h=7")
    result = np.zeros(78, dtype=np.uint8)
    for index, raw in enumerate(cells.flat):
        # Kernel uses low three bits for type, bit 3 for White; upper bits may
        # carry move-related flags. Never confuse these type codes with ours.
        code = int(raw) & 15
        piece_type = code & 7
        if piece_type == 0:
            if code & 8:
                raise ValueError("Color bit set on an empty square")
            continue
        if piece_type not in TYPE_MAP:
            raise ValueError(f"Unsupported Kernel piece type {piece_type}")
        result[index] = TYPE_MAP[piece_type] + (0 if code & 8 else 6)
    result[64] = int(bool(white_to_move))
    result[65:69] = castling_flags
    result[69 + (0 if ep_file is None else ep_file + 1)] = 1
    decode_position(result)  # Reject invalid board/rights/EP combinations.
    return result
