"""Functions for the user to implement when the config file is not adequate to express bot requirements."""
from lib import model
from lib.types import OPTIONS_TYPE


def game_specific_options(game: model.Game) -> OPTIONS_TYPE:
    """
    Return a dictionary of engine options based on game aspects.

    By default, an empty dict is returned so that the options in the configuration file are used.
    """
    # Mr. Bits' Engine UCI declares the GameId option, and stores every move of the game under it in the
    # database (database/mrbits.sqlite), so the lichess sync can join the engine's side with the game's result.
    # (Spelled exactly "GameId": an engine without this option would make every game fail at its start.)
    return {"GameId": game.id}


def is_supported_extra(challenge: model.Challenge) -> bool:
    """
    Determine whether to accept a challenge.

    By default, True is always returned so that there are no extra restrictions beyond those in the config file.
    """
    return True
