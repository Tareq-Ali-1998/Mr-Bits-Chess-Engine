"""Frozen board782_v1 feature and compact-record contract.

Compact position: 64 piece codes + 14 flags, all uint8.
Neural input: 12 * 64 binary piece features + the same flags = 782 floats.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import chess
import numpy as np

if TYPE_CHECKING:
    import torch

FEATURE_VERSION = "board782_v1"
INPUT_SIZE = 782
PACKED_SIZE = 78
PLANE_ORDER = ["P", "N", "B", "R", "Q", "K", "p", "n", "b", "r", "q", "k"]


def board_from_fen(fen: str, *, validate: bool = True) -> chess.Board:
    fields = fen.strip().split()
    if len(fields) == 4:
        fields.extend(["0", "1"])
    elif len(fields) != 6:
        raise ValueError("Expected four- or six-field standard-chess FEN")
    board = chess.Board(" ".join(fields), chess960=False)
    if validate and not board.is_valid():
        raise ValueError(f"Unsupported/invalid orthodox position: status={int(board.status())}")
    return board


def encode_board(board: chess.Board) -> np.ndarray:
    """Preserve board.ep_square, including a target without a legal EP capture."""
    if board.chess960 or not board.is_valid():
        raise ValueError("board782_v1 supports structurally valid orthodox chess only")
    result = np.zeros(PACKED_SIZE, dtype=np.uint8)
    for square, piece in board.piece_map().items():
        result[square ^ 56] = piece.piece_type + (0 if piece.color else 6)
    result[64] = int(board.turn == chess.WHITE)
    result[65:69] = [
        board.has_kingside_castling_rights(chess.WHITE),
        board.has_queenside_castling_rights(chess.WHITE),
        board.has_kingside_castling_rights(chess.BLACK),
        board.has_queenside_castling_rights(chess.BLACK),
    ]
    result[69 + (0 if board.ep_square is None else chess.square_file(board.ep_square) + 1)] = 1
    return result


def encode_fen(fen: str) -> np.ndarray:
    return encode_board(board_from_fen(fen))


def validate_packed(packed: np.ndarray) -> np.ndarray:
    result = np.asarray(packed)
    if result.shape != (PACKED_SIZE,) or result.dtype.kind not in "ui":
        raise ValueError("Expected 78 integer compact features")
    if np.any(result < 0) or np.any(result[:64] > 12) or np.any(result[64:] > 1):
        raise ValueError("Invalid piece code or binary flag")
    if int(result[69:].sum()) != 1:
        raise ValueError("Exactly one en-passant option must be active")
    return result


def decode_position(packed: np.ndarray) -> chess.Board:
    """Recover visible state only; original clocks/history are unavailable."""
    values = validate_packed(packed)
    board = chess.Board(None)
    for index, code in enumerate(values[:64]):
        code = int(code)
        if code:
            board.set_piece_at(index ^ 56, chess.Piece((code - 1) % 6 + 1, code <= 6))
    board.turn = bool(values[64])
    for flag, square in zip(values[65:69], [chess.H1, chess.A1, chess.H8, chess.A8]):
        if flag:
            board.castling_rights |= chess.BB_SQUARES[square]
    ep = int(np.argmax(values[69:]))
    board.ep_square = None if ep == 0 else chess.square(ep - 1, 5 if board.turn else 2)
    board.halfmove_clock = 0
    board.fullmove_number = 1
    if not board.is_valid():
        raise ValueError("Compact record decodes to an invalid orthodox position")
    return board


def position_key(packed: np.ndarray) -> bytes:
    """Clocks are deliberately absent; same visible input means same key."""
    raw = validate_packed(packed).astype(np.uint8, copy=False).tobytes()
    return hashlib.blake2b(raw, digest_size=16, person=b"mrbits-board782").digest()


def expand_numpy(packed: np.ndarray) -> np.ndarray:
    """Reference encoder for hand checks and cross-language parity."""
    values = validate_packed(packed)
    result = np.zeros(INPUT_SIZE, dtype=np.float32)
    for square, code in enumerate(values[:64]):
        if code:
            result[(int(code) - 1) * 64 + square] = 1
    result[768:] = values[64:]
    return result


def expand_batch(packed: "torch.Tensor") -> "torch.Tensor":
    """Expand compact CPU/CUDA batches on their existing device.

    Empty squares scatter a zero into an unused thirteenth plane. This avoids
    a large int64 one-hot intermediate for high-throughput GPU batches.
    """
    import torch

    if packed.ndim != 2 or packed.shape[1] != PACKED_SIZE:
        raise ValueError("Expected compact batch with shape [B,78]")
    codes = packed[:, :64].long()
    planes = torch.where(codes > 0, codes - 1, 12)
    squares = torch.arange(64, device=packed.device).unsqueeze(0)
    indexes = planes * 64 + squares
    pieces = torch.zeros((packed.shape[0], 13 * 64), device=packed.device, dtype=torch.float32)
    pieces.scatter_(1, indexes, (codes > 0).float())
    return torch.cat((pieces[:, :768], packed[:, 64:].float()), dim=1)


def feature_contract() -> dict:
    return {
        "version": FEATURE_VERSION,
        "input_size": INPUT_SIZE,
        "packed_size": PACKED_SIZE,
        "packed_piece_codes": ["empty"] + PLANE_ORDER,
        "plane_order": PLANE_ORDER,
        "square_order": "a8,b8,...,h8,a7,...,h1",
        "turn": "feature 768: 1 White, 0 Black",
        "castling": "features 769..772: White K,Q; Black k,q; retained rights",
        "en_passant": "773 none; 774..781 file a..h; preserve recorded FEN target",
        "history": "halfmove clock and repetition history unavailable; engine handles draws",
    }
