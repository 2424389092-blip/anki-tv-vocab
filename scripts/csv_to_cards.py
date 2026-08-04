#!/usr/bin/env python3
"""
Convert Doubao/AI-exported CSV to anki-tv-vocab cards JSON.

Expected CSV format (3 columns, tab or comma separated):
  word | html_back | source

Example html_back:
  🔊 英 /ˌhaɪpəˈθetɪkli/  美 /ˌhaɪpəˈθetɪkli/<br>📝 adv. 假设地；假定地<br>💡 例句：Could the daughter stay here if, hypothetically, someone reported the mother to Immigration?
"""

import argparse
import csv
import json
import os
import re
import sys


def clean_html(html_text):
    """Strip HTML tags and normalize whitespace."""
    text = re.sub(r'<[^>]+>', '\n', html_text)
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    return text


def extract_phonetic(line):
    """
    Extract phonetic from a line.
    Supports formats like:
      英 /xxx/ 美 /yyy/
      /xxx/
    Returns (phonetic_str, remaining_line) or (None, line).
    """
    line = line.strip()

    # Pattern: 英 /uk/ 美 /us/
    m = re.search(r'英\s*(/[^/]+/)\s*美\s*(/[^/]+/)', line)
    if m:
        uk, us = m.group(1), m.group(2)
        return f"英 {uk} 美 {us}", re.sub(r'英\s*/[^/]+/\s*美\s*/[^/]+/', '', line).strip()

    # Pattern: /phonetic/ anywhere
    m = re.search(r'(/[^/]+/)', line)
    if m:
        return m.group(1), re.sub(r'/[^/]+/', '', line, count=1).strip()

    return None, line


def parse_back_field(text):
    """
    Parse the back-field HTML/text into structured fields.
    Returns dict with: phonetic, pos, meaning, example
    """
    # Normalize <br> variants to newline
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = clean_html(text)

    lines = [l.strip() for l in text.split('\n') if l.strip()]

    result = {
        'phonetic': '',
        'pos': '',
        'meaning': '',
        'example': '',
    }

    # Remove leading emojis / markers like 🔊 📝 💡
    def strip_markers(s):
        s = re.sub(r'^[🔊📝💡📎🎧✅❌⭐🔹•\-\*\s]+', '', s).strip()
        return s

    example_lines = []
    meaning_parts = []

    for raw_line in lines:
        line = strip_markers(raw_line)
        if not line:
            continue

        # 1. Phonetic line (only process first one)
        ph, _ = extract_phonetic(line)
        if ph and not result['phonetic']:
            result['phonetic'] = ph
            continue

        # 2. Example line: starts with "例句" or "例："
        m = re.match(r'(?:例句|例)[:：]\s*(.+)', line, re.DOTALL)
        if m:
            example_lines.append(m.group(1).strip())
            continue

        # 3. POS + meaning: pattern like "n. 托管；由第三方保管的契约"
        m = re.match(r'^([a-zA-Z]+)\s*\.\s*(.+)', line)
        if m:
            pos, meaning = m.group(1).strip(), m.group(2).strip()
            pos = pos.lower() + '.'
            result['pos'] = pos
            meaning_parts.append(meaning)
            continue

        # 4. Fallback: treat as example if we already have pos/meaning
        if result['pos'] or result['meaning']:
            example_lines.append(line)
        # Otherwise ignore unrecognized lines

    if meaning_parts:
        result['meaning'] = '；'.join(meaning_parts)

    if example_lines:
        result['example'] = ' '.join(example_lines)

    # Clean remaining emojis in meaning/example
    result['meaning'] = _remove_emojis(result['meaning'])
    result['example'] = _remove_emojis(result['example'])

    return result


def _remove_emojis(text):
    """Remove common emoji and bullet markers while preserving Chinese text."""
    if not text:
        return ''
    # Remove common emoji / symbol characters explicitly (conservative list)
    text = re.sub(r'[🔊📝💡📎🎧✅❌⭐🔹•✦◆◇▪▸\-\*]+', '', text)
    # Remove any remaining codepoints in common emoji blocks (emoticons, pictographs, transport)
    # Use separate ranges to avoid accidentally matching CJK characters
    text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]+', '', text)
    return text.strip()


def detect_delimiter(sample):
    """Detect whether CSV uses tab or comma delimiter."""
    tab_count = sample.count('\t')
    comma_count = sample.count(',')
    return '\t' if tab_count > comma_count else ','


def convert_csv_to_cards(csv_path, deck_name=None, source_override=None):
    """Convert CSV file to cards JSON structure."""
    # Read with BOM support
    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        sample = f.read(4096)
        f.seek(0)
        delimiter = detect_delimiter(sample)
        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)

    if not rows:
        return {'deck_name': deck_name or 'TV Vocabulary', 'cards': []}

    cards = []
    seen_words = set()

    for idx, row in enumerate(rows):
        if not row or not row[0].strip():
            continue

        word = row[0].strip()

        # Skip header row if it looks like one
        if idx == 0 and word.lower() in ('word', '单词', 'front', '正面'):
            continue

        # Deduplicate by word
        key = word.lower()
        if key in seen_words:
            continue
        seen_words.add(key)

        back_text = row[1].strip() if len(row) > 1 else ''
        source = source_override or (row[2].strip() if len(row) > 2 else '')

        parsed = parse_back_field(back_text)

        cards.append({
            'word': word,
            'phonetic': parsed['phonetic'],
            'pos': parsed['pos'],
            'meaning': parsed['meaning'],
            'example': parsed['example'],
            'example_translation': '',  # User can fill manually or AI can add later
            'source': source,
        })

    return {
        'deck_name': deck_name or 'TV Vocabulary',
        'cards': cards,
    }


def main():
    parser = argparse.ArgumentParser(description='Convert AI-exported CSV to cards.json')
    parser.add_argument('--input', '-i', required=True, help='Input CSV file path')
    parser.add_argument('--output', '-o', required=True, help='Output cards.json path')
    parser.add_argument('--deck-name', '-d', default=None, help='Anki deck name')
    parser.add_argument('--source', '-s', default=None, help='Override source column value')
    args = parser.parse_args()

    data = convert_csv_to_cards(args.input, args.deck_name, args.source)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Converted {len(data['cards'])} cards -> {args.output}")


if __name__ == '__main__':
    main()
