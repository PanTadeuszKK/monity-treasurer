"""Wspólne wyszukiwanie nazw, niezależne od wielkości liter i kolejności słów."""
import unicodedata

def normalize_name(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold().replace('ł','l'))
    return ''.join(c for c in value if not unicodedata.combining(c))

def name_matches(name, query):
    normalized = normalize_name(name)
    return all(word in normalized for word in normalize_name(query).split())
