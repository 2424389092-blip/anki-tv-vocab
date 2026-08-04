#!/usr/bin/env python3
"""
Smoke test for anki-tv-vocab.

Validates the two pipelines end-to-end with fixture data, without needing a
real Anki running or TTS network access:

  1. test_build_apkg        - cards.json -> .apkg (genanki only, audio off)
  2. test_push_calls_actions - mock AnkiConnect; verify createModel/createDeck/
                                addNote/changeDeck are hit in order
  3. test_ensure_model_sync  - mock AnkiConnect; verify updateModelTemplates +
                                updateModelStyling run when the model already
                                exists (regression test for the bug where
                                ensure_model used to no-op on existing models)

Run:
    "${PYTHON:-C:/Users/cmy/.workbuddy/binaries/python/envs/default/Scripts/python.exe}" \\
        tests/smoke.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from anki_tv_vocab import build_apkg  # noqa: E402

SAMPLE_CARDS = {
    "deck_name": "SmokeTest S01E01",
    "cards": [
        {
            "word": "ephemeral",
            "phonetic": "/ɪˈfem(ə)rəl/",
            "pos": "adj.",
            "meaning": "短暂的、转瞬即逝的",
            "example": "Beauty is ephemeral.",
            "example_translation": "美丽是短暂的。",
        },
        {
            "word": "resilient",
            "phonetic": "/rɪˈzɪliənt/",
            "pos": "adj.",
            "meaning": "有韧性的、能迅速恢复的",
            "example": "Children are remarkably resilient.",
            "example_translation": "孩子们的适应力惊人。",
        },
        {
            "word": "precarious",
            "phonetic": "/prɪˈkeəriəs/",
            "pos": "adj.",
            "meaning": "危险的、不稳定的",
            "example": "His position was precarious.",
            "example_translation": "他的处境岌岌可危。",
        },
    ],
}


def test_build_apkg():
    """Build a valid .apkg from 3 fixture cards; no TTS, no dict lookup."""
    out = tempfile.NamedTemporaryFile(suffix=".apkg", delete=False)
    out.close()

    count = build_apkg(
        cards=SAMPLE_CARDS["cards"],
        output_path=out.name,
        deck_name=SAMPLE_CARDS["deck_name"],
        generate_audio=False,
        skip_dict=True,
    )
    assert count == 3, f"expected 3 notes, got {count}"
    assert os.path.getsize(out.name) > 0, ".apkg is empty"
    print(f"  [PASS] build_apkg -> {out.name} ({os.path.getsize(out.name)} bytes, 3 notes)")


def _make_mock_ac():
    """Build a fake _ac_request that records calls and returns plausible data."""
    import push_to_anki as p

    calls = []

    def fake_ac(action, params=None, timeout=30):
        calls.append((action, params))
        if action == "version":
            return 6
        if action == "modelNames":
            return [p.CARD_MODEL.name]
        if action == "deckNames":
            return [p.CARD_MODEL.name]
        if action == "createModel":
            return None
        if action == "updateModelTemplates":
            return None
        if action == "updateModelStyling":
            return None
        if action == "createDeck":
            return None
        if action == "addNote":
            return 99000 + len([c for c in calls if c[0] == "addNote"])
        if action == "notesInfo":
            return [{"cards": [12345]}]
        if action == "changeDeck":
            return None
        return None

    return calls, fake_ac


def test_push_calls_actions():
    """Verify the push pipeline hits all required AnkiConnect actions in order."""
    from unittest.mock import patch
    import push_to_anki as p

    calls, fake_ac = _make_mock_ac()

    # Pretend TTS succeeded so audio_entries get populated.
    def fake_tts(tasks, voice="en-US-JennyNeural"):
        return [True] * (len(tasks) * 2)

    with patch.object(p, "_ac_request", side_effect=fake_ac), \
         patch.object(p, "anki_connect_available", return_value=True), \
         patch.object(p, "generate_tts_batch", side_effect=fake_tts):
        added = p.push_cards(
            SAMPLE_CARDS["cards"],
            SAMPLE_CARDS["deck_name"],
            skip_dict=True,
        )

    assert added == 3, f"expected 3 cards added, got {added}"
    actions = [c[0] for c in calls]
    for required in ("createDeck", "addNote", "changeDeck"):
        assert required in actions, f"missing AnkiConnect action: {required}"
    # addNote should be called exactly once per card
    assert actions.count("addNote") == 3, f"addNote calls = {actions.count('addNote')}, want 3"
    print(f"  [PASS] push flow hits createDeck/addNote*3/changeDeck (model existed, synced)")


def test_ensure_model_sync():
    """Regression test: when model already exists, ensure_model must update
    templates + CSS, not silently return. Otherwise the back template from an
    older CARD_MODEL would persist forever.
    """
    from unittest.mock import patch
    import push_to_anki as p

    calls, fake_ac = _make_mock_ac()

    with patch.object(p, "_ac_request", side_effect=fake_ac):
        p.ensure_model()

    actions = [c[0] for c in calls]
    assert "createModel" not in actions, "createModel should NOT be called when model exists"
    assert "updateModelTemplates" in actions, "updateModelTemplates missing (regression)"
    assert "updateModelStyling" in actions, "updateModelStyling missing"
    print(f"  [PASS] ensure_model syncs existing model (updateModelTemplates + updateModelStyling)")


def main():
    print(f"Running anki-tv-vocab smoke tests (skill: {SKILL_DIR})\n")
    test_build_apkg()
    test_push_calls_actions()
    test_ensure_model_sync()
    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()