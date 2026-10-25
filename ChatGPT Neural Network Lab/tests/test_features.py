import unittest

import chess
import numpy as np
import torch

from chesslab.features import (
    board_from_fen, decode_position, encode_board, encode_fen,
    expand_batch, expand_numpy, position_key, validate_packed,
)
from chesslab.kernel_adapter import encode_kernel_board


class FeatureTests(unittest.TestCase):
    def test_archive_example_and_reference_indexes(self):
        packed = encode_fen("7r/1p3k2/p1bPR3/5p2/2B2P1p/8/PP4P1/3K4 b - -")
        features = expand_numpy(packed)
        self.assertEqual(features.shape, (782,))
        self.assertEqual(int(features[:768].sum()), 15)
        self.assertEqual(features[212], 1)
        self.assertEqual(features[583], 1)
        np.testing.assert_array_equal(features[768:], [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0])

    def test_numpy_torch_parity(self):
        boards = [chess.Board(), board_from_fen("7r/1p3k2/p1bPR3/5p2/2B2P1p/8/PP4P1/3K4 b - -")]
        boards[0].push_uci("e2e4")
        packed = np.stack([encode_board(b) for b in boards])
        actual = expand_batch(torch.from_numpy(packed)).numpy()
        np.testing.assert_array_equal(actual, np.stack([expand_numpy(x) for x in packed]))

    def test_ep_without_legal_capture_preserved(self):
        board = chess.Board()
        board.push_uci("e2e4")
        self.assertFalse(board.has_legal_en_passant())
        packed = encode_board(board)
        self.assertEqual(packed[69 + 5], 1)  # file e, not EP-none
        recovered = decode_position(packed)
        self.assertEqual(recovered.fen(en_passant="fen"), board.fen(en_passant="fen").rsplit(" ", 2)[0] + " 0 1")

    def test_state_roundtrips(self):
        boards = [chess.Board()]
        ep = chess.Board()
        for move in ["e2e4", "a7a6", "e4e5", "d7d5"]:
            ep.push_uci(move)
        boards.append(ep)
        boards.append(board_from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq -"))
        for board in boards:
            packed = encode_board(board)
            np.testing.assert_array_equal(encode_board(decode_position(packed)), packed)

    def test_clocks_ignored_but_side_and_rights_not(self):
        a = encode_fen(chess.STARTING_FEN)
        b = encode_fen(chess.STARTING_FEN.rsplit(" ", 2)[0] + " 83 50")
        self.assertEqual(position_key(a), position_key(b))
        c = a.copy(); c[64] = 0
        self.assertNotEqual(position_key(a), position_key(c))
        c = a.copy(); c[65] = 0
        self.assertNotEqual(position_key(a), position_key(c))

    def test_rejects_invalid_state_and_compact_flags(self):
        with self.assertRaises(ValueError):
            encode_fen("8/8/8/8/8/8/8/8 w - -")
        a = encode_fen(chess.STARTING_FEN)
        a[69:] = 0
        with self.assertRaises(ValueError):
            validate_packed(a)
        with self.assertRaises(ValueError):
            validate_packed(np.full(78, -1, dtype=np.int16))

    def test_original_kernel_starting_board_mapping(self):
        board = np.zeros((8, 8), dtype=np.int8)
        board[0] = [5, 3, 4, 6, 7, 4, 3, 5]
        board[1] = 1
        board[6] = 9
        board[7] = [13, 11, 12, 14, 15, 12, 11, 13]
        packed = encode_kernel_board(board, white_to_move=True, castling_flags=[1, 1, 1, 1])
        np.testing.assert_array_equal(packed, encode_fen(chess.STARTING_FEN))


if __name__ == "__main__":
    unittest.main()
