#!/usr/bin/env python3
"""
Anki TV Vocabulary - Create Anki cards from TV show subtitles.

Subcommands:
  parse   - Parse .srt/.ass subtitle file, output sentences as JSON
  lookup  - Look up a word in Free Dictionary API
  tts     - Generate TTS audio via edge-tts
  build   - Build .apkg from cards JSON (auto-generates audio)
"""

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import urllib.request
import urllib.parse
from pathlib import Path


# ============================================================
#  Subtitle Parsing
# ============================================================

def _is_chinese_line(text):
    """Check if a line is predominantly Chinese."""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))
    alpha_chars = len(re.findall(r'[a-zA-Z]', text))
    return chinese_chars > alpha_chars


def parse_srt(filepath):
    """Parse .srt subtitle file. Returns list of {start, end, english, chinese}."""
    encodings = ['utf-8-sig', 'utf-8', 'gbk', 'gb18030', 'latin-1']
    content = None
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                content = f.read()
            break
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    if content is None:
        raise ValueError(f"Cannot read file: {filepath}")

    entries = []
    # Normalize line endings and split into blocks
    blocks = re.split(r'\n\s*\n', content.strip())

    for block in blocks:
        lines = [l.rstrip() for l in block.strip().split('\n') if l.strip()]
        if len(lines) < 2:
            continue

        # Find the timestamp line
        ts_idx = None
        for i, line in enumerate(lines):
            if re.search(r'\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->', line):
                ts_idx = i
                break
        if ts_idx is None:
            continue

        ts_match = re.match(
            r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})',
            lines[ts_idx]
        )
        if not ts_match:
            continue
        start, end = ts_match.groups()

        # Text lines are everything after the timestamp line
        text_lines = lines[ts_idx + 1:]
        english_lines = []
        chinese_lines = []
        for line in text_lines:
            # Strip HTML tags
            clean = re.sub(r'<[^>]+>', '', line).strip()
            if not clean:
                continue
            if _is_chinese_line(clean):
                chinese_lines.append(clean)
            else:
                english_lines.append(clean)

        english_text = ' '.join(english_lines).strip()
        chinese_text = ' '.join(chinese_lines).strip()

        if english_text:
            entries.append({
                'index': len(entries) + 1,
                'start': start,
                'end': end,
                'english': english_text,
                'chinese': chinese_text
            })

    return entries


def parse_ass(filepath):
    """Parse .ass subtitle file (simplified). Returns list of {start, end, english, chinese}."""
    encodings = ['utf-8-sig', 'utf-8', 'gbk', 'gb18030', 'latin-1']
    content = None
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                content = f.read()
            break
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    if content is None:
        raise ValueError(f"Cannot read file: {filepath}")

    entries = []
    for line in content.split('\n'):
        line = line.strip()
        if not line.startswith('Dialogue:'):
            continue
        parts = line.split(',', 9)
        if len(parts) < 10:
            continue

        start = parts[1].strip()
        end = parts[2].strip()
        text = parts[9]

        # Remove ASS formatting tags
        text = re.sub(r'\{[^}]*\}', '', text)
        text = text.replace('\\N', ' ').replace('\\n', ' ').strip()
        # Remove leading dash for dialogue
        text = re.sub(r'^[-\u2010-\u2015]\s*', '', text)

        if not text:
            continue

        if _is_chinese_line(text):
            # Chinese-only line, skip (or could be translation)
            continue

        entries.append({
            'index': len(entries) + 1,
            'start': start,
            'end': end,
            'english': text,
            'chinese': ''
        })

    return entries


def parse_subtitle(filepath):
    """Auto-detect format and parse subtitle file."""
    ext = Path(filepath).suffix.lower()
    if ext == '.srt':
        return parse_srt(filepath)
    elif ext in ('.ass', '.ssa'):
        return parse_ass(filepath)
    else:
        # Try SRT first, then ASS
        try:
            result = parse_srt(filepath)
            if result:
                return result
        except Exception:
            pass
        return parse_ass(filepath)


# ============================================================
#  Dictionary Lookup (Free Dictionary API)
# ============================================================

def lookup_word(word, timeout=3):
    """Look up word in Free Dictionary API. Returns dict with phonetic, audio_url, meanings."""
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word.lower())}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'AnkiTVVocab/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        if not data or not isinstance(data, list):
            return {'word': word, 'phonetic': '', 'audio_url': '', 'meanings': [], 'error': 'No results'}

        entry = data[0]

        # Extract phonetic
        phonetic = entry.get('phonetic', '')
        for ph in entry.get('phonetics', []):
            if ph.get('text'):
                phonetic = ph['text']
                break

        # Extract audio URL (prefer US English)
        audio_url = ''
        for ph in entry.get('phonetics', []):
            if ph.get('audio') and 'us' in ph['audio'].lower():
                audio_url = ph['audio']
                break
        if not audio_url:
            for ph in entry.get('phonetics', []):
                if ph.get('audio'):
                    audio_url = ph['audio']
                    break

        # Extract meanings
        meanings = []
        for meaning in entry.get('meanings', []):
            pos = meaning.get('partOfSpeech', '')
            for defn in meaning.get('definitions', []):
                meanings.append({
                    'pos': pos,
                    'definition': defn.get('definition', ''),
                    'example': defn.get('example', '')
                })

        return {
            'word': word,
            'phonetic': phonetic,
            'audio_url': audio_url,
            'meanings': meanings
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {'word': word, 'phonetic': '', 'audio_url': '', 'meanings': [], 'error': 'Word not found'}
        return {'word': word, 'phonetic': '', 'audio_url': '', 'meanings': [], 'error': f'HTTP {e.code}'}
    except Exception as e:
        return {'word': word, 'phonetic': '', 'audio_url': '', 'meanings': [], 'error': str(e)}


# ============================================================
#  TTS Generation (edge-tts)
# ============================================================

# Fix asyncio on Windows: use SelectorEventLoop for compatibility
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _tts_async(text, output_path, voice='en-US-JennyNeural'):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


async def _tts_batch_async(tasks, voice='en-US-JennyNeural'):
    """Generate multiple TTS files concurrently."""
    import edge_tts
    sem = asyncio.Semaphore(3)  # Limit concurrency

    async def generate_one(text, output_path):
        async with sem:
            try:
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(output_path)
                return True
            except Exception as e:
                print(f"  TTS error for '{text[:30]}...': {e}", file=sys.stderr)
                return False

    coros = [generate_one(text, path) for text, path in tasks]
    return await asyncio.gather(*coros)


def generate_tts(text, output_path, voice='en-US-JennyNeural'):
    """Generate TTS audio file. Returns True on success."""
    try:
        asyncio.run(_tts_async(text, output_path, voice))
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"  TTS error for '{text[:30]}...': {e}", file=sys.stderr)
        return False


def generate_tts_batch(tasks, voice='en-US-JennyNeural'):
    """Generate multiple TTS files in one event loop. tasks = [(text, path), ...]"""
    try:
        results = asyncio.run(_tts_batch_async(tasks, voice))
        return results
    except Exception as e:
        print(f"  Batch TTS error: {e}", file=sys.stderr)
        return [False] * len(tasks)


# ============================================================
#  Anki Package Creation (genanki)
# ============================================================

import genanki

# Model ID (fixed, deterministic)
MODEL_ID = 1732845620

# Card CSS - spacious, clean design
CARD_CSS = """
.card {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    text-align: center;
    color: #2c2c2c;
    background: #fafafa;
    padding: 48px 32px;
    line-height: 1.8;
}
.word {
    font-size: 40px;
    font-weight: 700;
    color: #1a1a1a;
    margin-bottom: 12px;
    letter-spacing: 0.5px;
}
.phonetic {
    font-size: 19px;
    color: #888;
    margin-bottom: 18px;
    font-family: 'Consolas', 'Monaco', monospace;
}
.audio-btn { margin: 14px 0; }
.pos-meaning {
    font-size: 18px;
    color: #444;
    margin: 24px 0;
    line-height: 1.9;
}
.pos {
    display: inline-block;
    color: #999;
    font-style: italic;
    margin-right: 10px;
    font-size: 16px;
}
.meaning { color: #333; }
.example-section { margin: 28px 0; }
.example {
    font-size: 19px;
    color: #1e4e8c;
    font-style: italic;
    line-height: 1.7;
    padding: 18px 24px;
    background: #ebf4ff;
    border-radius: 12px;
    margin-bottom: 12px;
}
.example-translation {
    font-size: 16px;
    color: #666;
    margin-top: 10px;
    line-height: 1.7;
}
.source {
    font-size: 13px;
    color: #b8b8b8;
    margin-top: 32px;
    padding-top: 18px;
    border-top: 1px solid #eee;
    line-height: 1.7;
}
.source-label {
    display: inline-block;
    font-size: 12px;
    font-weight: 600;
    color: #9a9a9a;
    margin-right: 6px;
}
hr {
    border: none;
    border-top: 1px solid #e8e8e8;
    margin: 28px 0;
}
"""

CARD_MODEL = genanki.Model(
    MODEL_ID,
    'TV Vocabulary',
    fields=[
        {'name': 'Word'},
        {'name': 'Phonetic'},
        {'name': 'POS'},
        {'name': 'Meaning'},
        {'name': 'Example'},
        {'name': 'ExampleTranslation'},
        {'name': 'Source'},
        {'name': 'WordAudio'},
        {'name': 'SentenceAudio'},
    ],
    templates=[
        {
            'name': 'Card 1',
            'qfmt': '''<div class="word">{{Word}}</div>
{{#Phonetic}}<div class="phonetic">{{Phonetic}}</div>{{/Phonetic}}
{{#WordAudio}}<div class="audio-btn">{{WordAudio}}</div>{{/WordAudio}}''',
            'afmt': '''<div class="word">{{Word}}</div>
{{#Phonetic}}<div class="phonetic">{{Phonetic}}</div>{{/Phonetic}}
{{#WordAudio}}<div class="audio-btn">{{WordAudio}}</div>{{/WordAudio}}

<hr>

<div class="pos-meaning">
{{#POS}}<span class="pos">{{POS}}</span>{{/POS}}
<span class="meaning">{{Meaning}}</span>
</div>

<hr>

<div class="example-section">
<div class="example">{{Example}}</div>
{{#SentenceAudio}}<div class="audio-btn">{{SentenceAudio}}</div>{{/SentenceAudio}}
{{#ExampleTranslation}}<div class="example-translation">{{ExampleTranslation}}</div>{{/ExampleTranslation}}
</div>''',
        },
    ],
    css=CARD_CSS,
)


def _deck_id_from_name(name):
    """Generate a deterministic deck ID from name."""
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0x7FFFFFFF
    return h % 1000000000


def build_apkg(cards, output_path, deck_name='TV Vocabulary', media_dir=None,
               generate_audio=True, tts_voice='en-US-JennyNeural', skip_dict=False):
    """
    Build Anki .apkg from cards list.

    Each card dict:
      word, phonetic, pos, meaning, example, example_translation, source,
      word_audio (optional filename), sentence_audio (optional filename)
    """
    deck = genanki.Deck(_deck_id_from_name(deck_name), deck_name)
    media_files = []

    if media_dir is None:
        media_dir = tempfile.mkdtemp(prefix='anki_media_')
    os.makedirs(media_dir, exist_ok=True)

    total = len(cards)

    # --- Phase 1: Collect TTS tasks and try dictionary audio ---
    tts_tasks = []  # [(text, output_path), ...]
    card_audio_info = []  # Track audio paths for each card

    for i, card in enumerate(cards):
        word = card.get('word', '').strip()
        if not word:
            card_audio_info.append(None)
            continue

        example = card.get('example', '')
        word_audio_file = card.get('word_audio', f'word_{i:04d}.mp3')
        sentence_audio_file = card.get('sentence_audio', f'sentence_{i:04d}.mp3')
        word_audio_path = os.path.join(media_dir, word_audio_file)
        sentence_audio_path = os.path.join(media_dir, sentence_audio_file)

        info = {
            'word_audio_path': word_audio_path,
            'word_audio_file': word_audio_file,
            'sentence_audio_path': sentence_audio_path if example else '',
            'sentence_audio_file': sentence_audio_file if example else '',
        }

        if generate_audio:
            # Word audio: try existing file, then dictionary API (if not skipped), then TTS
            if not os.path.exists(word_audio_path):
                if skip_dict:
                    tts_tasks.append((word, word_audio_path))
                else:
                    word_info = lookup_word(word)
                    if word_info.get('audio_url'):
                        try:
                            urllib.request.urlretrieve(word_info['audio_url'], word_audio_path)
                            print(f"  [{i+1}/{total}] Word audio (dict): {word}", flush=True)
                        except Exception:
                            tts_tasks.append((word, word_audio_path))
                    else:
                        tts_tasks.append((word, word_audio_path))
            else:
                print(f"  [{i+1}/{total}] Word audio (exists): {word}", flush=True)

            # Sentence audio: always TTS
            if example and not os.path.exists(sentence_audio_path):
                clean_example = re.sub(r'^[A-Z][a-z]+:\s*', '', example)
                tts_tasks.append((clean_example, sentence_audio_path))

        card_audio_info.append(info)

    # --- Phase 2: Generate all TTS in one batch ---
    if tts_tasks:
        print(f"\n  Generating {len(tts_tasks)} TTS audio files...", flush=True)
        results = generate_tts_batch(tts_tasks, tts_voice)
        success_count = sum(1 for r in results if r)
        print(f"  TTS done: {success_count}/{len(tts_tasks)} succeeded\n", flush=True)

    # --- Phase 3: Create notes ---
    for i, card in enumerate(cards):
        word = card.get('word', '').strip()
        if not word:
            continue

        info = card_audio_info[i]
        if info is None:
            continue

        phonetic = card.get('phonetic', '')
        pos = card.get('pos', '')
        meaning = card.get('meaning', '')
        example = card.get('example', '')
        example_translation = card.get('example_translation', '')
        # `synopsis` 优先（每集剧情简介，渲染在卡片底部）；`source` 为旧字段名兜底
        source = card.get('synopsis') or card.get('source', '')

        word_audio_tag = ''
        sentence_audio_tag = ''

        wap = info['word_audio_path']
        if os.path.exists(wap) and os.path.getsize(wap) > 0:
            word_audio_tag = f'[sound:{info["word_audio_file"]}]'
            media_files.append(wap)

        if info['sentence_audio_path']:
            sap = info['sentence_audio_path']
            if os.path.exists(sap) and os.path.getsize(sap) > 0:
                sentence_audio_tag = f'[sound:{info["sentence_audio_file"]}]'
                media_files.append(sap)

        note = genanki.Note(
            model=CARD_MODEL,
            fields=[
                word, phonetic, pos, meaning,
                example, example_translation, source,
                word_audio_tag, sentence_audio_tag,
            ]
        )
        deck.add_note(note)

    # NOTE: genanki 0.13.1 takes media via the constructor's `media_files`
    # kwarg. Setting `package.media = ...` (the old API) is silently ignored,
    # which would produce an .apkg with [sound:] tags but ZERO bundled audio.
    package = genanki.Package(deck, media_files=media_files if media_files else None)
    package.write_to_file(output_path)

    return len(deck.notes)


# ============================================================
#  CLI
# ============================================================

def cmd_parse(args):
    """Parse subtitle file and output JSON."""
    entries = parse_subtitle(args.input)
    output = {
        'file': args.input,
        'total_entries': len(entries),
        'entries': entries
    }
    json_str = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(json_str)
        print(f"Parsed {len(entries)} entries -> {args.output}")
    else:
        print(json_str)


def cmd_lookup(args):
    """Look up a word in the dictionary."""
    result = lookup_word(args.word)
    json_str = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(json_str)
        print(f"Lookup '{args.word}' -> {args.output}")
    else:
        print(json_str)


def cmd_tts(args):
    """Generate TTS audio."""
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    success = generate_tts(args.text, args.output, args.voice)
    if success:
        print(f"TTS -> {args.output} ({os.path.getsize(args.output)} bytes)")
    else:
        print("TTS failed", file=sys.stderr)
        sys.exit(1)


def cmd_build(args):
    """Build .apkg from cards JSON."""
    with open(args.cards, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, dict):
        cards = data.get('cards', [])
        deck_name = data.get('deck_name', args.deck_name)
        top_synopsis = data.get('synopsis', '')
    else:
        cards = data
        deck_name = args.deck_name
        top_synopsis = ''

    # 顶层 synopsis（整集剧情简介）注入到每张卡，避免逐卡重复
    if top_synopsis:
        for c in cards:
            if not c.get('synopsis'):
                c['synopsis'] = top_synopsis

    # Use media_dir from JSON or CLI
    if isinstance(data, dict) and 'media_dir' in data:
        media_dir = data['media_dir']
    else:
        media_dir = args.media_dir if args.media_dir else None

    try:
        count = build_apkg(
            cards=cards,
            output_path=args.output,
            deck_name=deck_name,
            media_dir=media_dir,
            generate_audio=not args.no_audio,
            tts_voice=args.voice,
            skip_dict=args.skip_dict,
        )
        print(f"\nBuilt {count} cards -> {args.output}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Anki TV Vocabulary - Create Anki cards from TV show subtitles'
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # parse
    p_parse = subparsers.add_parser('parse', help='Parse subtitle file (.srt/.ass)')
    p_parse.add_argument('--input', '-i', required=True, help='Subtitle file path')
    p_parse.add_argument('--output', '-o', default='', help='Output JSON file (default: stdout)')

    # lookup
    p_lookup = subparsers.add_parser('lookup', help='Look up word in dictionary')
    p_lookup.add_argument('--word', '-w', required=True, help='Word to look up')
    p_lookup.add_argument('--output', '-o', default='', help='Output JSON file (default: stdout)')

    # tts
    p_tts = subparsers.add_parser('tts', help='Generate TTS audio')
    p_tts.add_argument('--text', '-t', required=True, help='Text to speak')
    p_tts.add_argument('--output', '-o', required=True, help='Output audio file path')
    p_tts.add_argument('--voice', '-v', default='en-US-JennyNeural',
                        help='TTS voice (default: en-US-JennyNeural)')

    # build
    p_build = subparsers.add_parser('build', help='Build .apkg from cards JSON')
    p_build.add_argument('--cards', '-c', required=True, help='Cards JSON file path')
    p_build.add_argument('--output', '-o', required=True, help='Output .apkg file path')
    p_build.add_argument('--deck-name', '-d', default='TV Vocabulary', help='Anki deck name')
    p_build.add_argument('--media-dir', '-m', default='', help='Media directory for audio files')
    p_build.add_argument('--no-audio', action='store_true', help='Skip audio generation')
    p_build.add_argument('--skip-dict', action='store_true', help='Skip dictionary API, use TTS for all word audio')
    p_build.add_argument('--voice', '-v', default='en-US-JennyNeural', help='TTS voice')

    args = parser.parse_args()

    if args.command == 'parse':
        cmd_parse(args)
    elif args.command == 'lookup':
        cmd_lookup(args)
    elif args.command == 'tts':
        cmd_tts(args)
    elif args.command == 'build':
        cmd_build(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
