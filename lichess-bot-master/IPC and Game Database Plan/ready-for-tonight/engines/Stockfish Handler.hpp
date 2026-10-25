#ifndef STOCKFISH_HANDLER_H_INCLUDED
#define STOCKFISH_HANDLER_H_INCLUDED

// Drop-in replacement for the old popen-based "Stockfish Handler.hpp" (plan 02 Phase 1b).
// Engine UCI.cpp keeps compiling unchanged: it still sees bits/stdc++.h, "using namespace std"
// and a copyable class named StockfishHandler, but every copy talks to ONE persistent Stockfish.

#include <bits/stdc++.h>
#include "StockfishProcess.hpp"

using namespace std;

using StockfishHandler = PersistentStockfishHandler;

#endif // STOCKFISH_HANDLER_H_INCLUDED
