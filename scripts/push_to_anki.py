#!/usr/bin/env python3
"""
push_to_anki.py - Push TV vocabulary cards directly into a running Anki
via AnkiConnect (http://127.0.0.1:8765).

Workflow:
  1. Generate TTS audio locally (unique per-episode filenames).
  2. addNote each card (audio is attached via the `audio` entry, which makes
     AnkiConnect BOTH import the file and write the [sound:] tag -- so we must
     NOT pre-set the tag ourselves, or we get a duplicate tag + wrong file).
  3. AnkiConnect ignores `deckName` in this Anki version (notes land in the
     current deck), so we move them with `changeDeck` afterwards.

Usage:
  python push_to_anki.py --cards output/cards.json [--deck-name "..."] [--skip-dict] [--voice en-US-JennyNeural]
"""

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anki_tv_vocab import CARD_MODEL, generate_tts_batch  # noqa: E402

ANKICONNECT_URL = "http://127.0.0.1:8765"


def _ac_request(action, params=None, timeout=30):
    payload = json.dumps({"action": action, "version": 6, "params": params or {}}).encode("utf-8")
    req = urllib.request.Request(
        ANKICONNECT_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("error") is not None:
        raise RuntimeError(f"AnkiConnect error on '{action}': {result['error']}")
    return result.get("result")


def anki_connect_available():
    try:
        _ac_request("version")
        return True
    except Exception:
        return False


def ensure_model():
    """Ensure the 'TV Vocabulary' model in Anki matches CARD_MODEL exactly.

    If missing, create it. If present, sync templates + CSS so any change in
    CARD_MODEL (e.g. removing Source display from the back template) propagates
    to existing installations.
    """
    names = _ac_request("modelNames") or []
    fields = [f["name"] for f in CARD_MODEL.fields]
    templates = [{"Name": t["name"], "Front": t["qfmt"], "Back": t["afmt"]} for t in CARD_MODEL.templates]

    if CARD_MODEL.name not in names:
        _ac_request("createModel", {
            "modelName": CARD_MODEL.name,
            "inOrderFields": fields,
            "cardTemplates": templates,
            "css": CARD_MODEL.css,
        })
        print(f"  Created model '{CARD_MODEL.name}' in Anki.")
        return

    # Model already exists - sync templates + CSS to CARD_MODEL definition
    template_updates = {t["Name"]: {"Front": t["Front"], "Back": t["Back"]} for t in templates}
    _ac_request("updateModelTemplates", {
        "model": {"name": CARD_MODEL.name},
        "templates": template_updates,
    })
    _ac_request("updateModelStyling", {
        "model": {"name": CARD_MODEL.name},
        "css": CARD_MODEL.css,
    })
    print(f"  Synced model '{CARD_MODEL.name}' templates + CSS.")


def ensure_deck(deck_name):
    _ac_request("createDeck", {"deck": deck_name})


def add_note(deck_name, fields, audio_entries):
    """Add a single note. Returns note id on success, None if it was a duplicate."""
    try:
        return _ac_request("addNote", {
            "note": {
                "deckName": deck_name,
                "modelName": CARD_MODEL.name,
                "fields": fields,
                "options": {"allowDuplicate": False, "duplicateScope": "deck"},
                "audio": audio_entries,
            }
        })
    except RuntimeError as e:
        if "duplicate" in str(e).lower():
            return None
        raise


def change_deck_of_notes(note_ids, deck_name):
    if not note_ids:
        return
    card_ids = []
    for nid in note_ids:
        info = _ac_request("notesInfo", {"notes": [nid]})
        if info:
            card_ids.extend(info[0].get("cards", []))
    if card_ids:
        _ac_request("changeDeck", {"cards": card_ids, "deck": deck_name})


def deck_slug(deck_name):
    # ASCII, unique per deck name -> avoids filename collisions across episodes
    import hashlib
    return hashlib.md5(deck_name.encode("utf-8")).hexdigest()[:10]


def push_cards(cards, deck_name, skip_dict=False, voice="en-US-JennyNeural"):
    slug = deck_slug(deck_name)
    media_dir = tempfile.mkdtemp(prefix="anki_push_")
    tts_tasks = []
    plan = []  # (card, word_path, sent_path, word_fn, sent_fn)

    for i, card in enumerate(cards):
        word = card.get("word", "").strip()
        if not word:
            continue
        example = card.get("example", "")
        wfn = f"tv_{slug}_{i:03d}.mp3"
        sfn = f"tvs_{slug}_{i:03d}.mp3"
        wpath = os.path.join(media_dir, wfn)
        spath = os.path.join(media_dir, sfn) if example else ""
        tts_tasks.append((word, wpath))
        if example:
            clean = re.sub(r"^[A-Z][a-z]+:\s*", "", example)
            tts_tasks.append((clean, spath))
        plan.append((card, wpath, spath, wfn, sfn))

    if tts_tasks:
        print(f"  Generating {len(tts_tasks)} TTS audio files...")
        generate_tts_batch(tts_tasks, voice)

    ensure_model()
    ensure_deck(deck_name)

    added_ids = []
    added = 0
    for card, wpath, spath, wfn, sfn in plan:
        word = card.get("word", "").strip()
        audio_entries = []
        if os.path.exists(wpath) and os.path.getsize(wpath) > 0:
            audio_entries.append({"path": wpath, "filename": wfn, "fields": ["WordAudio"]})
        if spath and os.path.exists(spath) and os.path.getsize(spath) > 0:
            audio_entries.append({"path": spath, "filename": sfn, "fields": ["SentenceAudio"]})

        # Leave WordAudio/SentenceAudio EMPTY; AnkiConnect fills the [sound:] tag.
        # Source field intentionally left empty (user opted out of episode synopsis).
        fields = {
            "Word": word,
            "Phonetic": card.get("phonetic", ""),
            "POS": card.get("pos", ""),
            "Meaning": card.get("meaning", ""),
            "Example": card.get("example", ""),
            "ExampleTranslation": card.get("example_translation", ""),
            "Source": "",
            "WordAudio": "",
            "SentenceAudio": "",
        }
        nid = add_note(deck_name, fields, audio_entries)
        if nid:
            added_ids.append(nid)
            added += 1
            print(f"  Added: {word}", flush=True)
        else:
            print(f"  Skipped (duplicate): {word}", flush=True)

    # AnkiConnect ignores deckName -> notes are in the current deck; move them.
    change_deck_of_notes(added_ids, deck_name)
    return added


def main():
    parser = argparse.ArgumentParser(description="Push TV vocab cards into running Anki via AnkiConnect")
    parser.add_argument("--cards", "-c", required=True, help="Cards JSON file")
    parser.add_argument("--deck-name", "-d", default="", help="Override deck name")
    parser.add_argument("--skip-dict", action="store_true", help="Skip dictionary API (TTS for all word audio)")
    parser.add_argument("--voice", "-v", default="en-US-JennyNeural", help="TTS voice")
    parser.add_argument("--replace", action="store_true",
                        help="Delete existing notes in the target deck before pushing (loses study progress)")
    args = parser.parse_args()

    if not anki_connect_available():
        print("ERROR: AnkiConnect 未连接。请确认 Anki 已运行、已装 AnkiConnect 插件并重启过。")
        sys.exit(2)

    with open(args.cards, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        cards = data.get("cards", [])
        deck_name = args.deck_name or data.get("deck_name", "TV Vocabulary")
    else:
        cards = data
        deck_name = args.deck_name or "TV Vocabulary"

    if args.replace:
        existing = _ac_request("findNotes", {"query": f'deck:"{deck_name}"'})
        if existing:
            _ac_request("deleteNotes", {"notes": existing})
            print(f"  已删除目标牌组中 {len(existing)} 张旧卡片。")

    print(f"Pushing {len(cards)} cards to deck '{deck_name}' via AnkiConnect...")
    try:
        added = push_cards(cards, deck_name, skip_dict=args.skip_dict, voice=args.voice)
        print(f"\nDone. Pushed {added} cards into Anki deck '{deck_name}'.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
