import menubar_notes_to_notion as appmod
import app_contract as ac


def test_app_version_matches_app_contract():
    assert appmod.APP_VERSION == ac.APP_VERSION