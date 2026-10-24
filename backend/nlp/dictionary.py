"""
Linguistic Dictionaries & Normalization Maps for Hindi/Hinglish Voice POS.
Contains number mappings, fraction terms, units, conjunctions, and conversational filler words.
"""

# Colloquial Hindi, Devanagari, and English quantity word mappings
QUANTITY_WORDS = {
    # Hindi Whole Numbers (Romanized)
    "ek": 1.0,
    "aik": 1.0,
    "do": 2.0,
    "teen": 3.0,
    "tin": 3.0,
    "char": 4.0,
    "chaar": 4.0,
    "paanch": 5.0,
    "panch": 5.0,
    "chhe": 6.0,
    "che": 6.0,
    "chhah": 6.0,
    "saat": 7.0,
    "sat": 7.0,
    "aath": 8.0,
    "ath": 8.0,
    "nau": 9.0,
    "no": 9.0,
    "das": 10.0,
    "dus": 10.0,
    "gyarah": 11.0,
    "barah": 12.0,
    "terah": 13.0,
    "chaudah": 14.0,
    "pandrah": 15.0,
    "solah": 16.0,
    "satrah": 17.0,
    "atharah": 18.0,
    "unnees": 19.0,
    "bees": 20.0,
    "pachees": 25.0,
    "pachaas": 50.0,
    "sau": 100.0,

    # Hindi Whole Numbers (Devanagari Script)
    "एक": 1.0,
    "दो": 2.0,
    "तीन": 3.0,
    "चार": 4.0,
    "पांच": 5.0,
    "पाँच": 5.0,
    "छह": 6.0,
    "छः": 6.0,
    "सात": 7.0,
    "आठ": 8.0,
    "नौ": 9.0,
    "दस": 10.0,
    "ग्यारह": 11.0,
    "बारह": 12.0,
    "तेरह": 13.0,
    "चौदह": 14.0,
    "पंद्रह": 15.0,
    "सोलह": 16.0,
    "सत्रह": 17.0,
    "अठारह": 18.0,
    "उन्नीस": 19.0,
    "बीस": 20.0,
    "पच्चीस": 25.0,
    "पचास": 50.0,
    "सौ": 100.0,

    # Hindi Fractions & Colloquial Measurements (Romanized)
    "aadha": 0.5,
    "adha": 0.5,
    "adhaa": 0.5,
    "aadhe": 0.5,
    "half": 0.5,
    "paav": 0.25,
    "pao": 0.25,
    "powa": 0.25,
    "quarter": 0.25,
    "dedh": 1.5,
    "derh": 1.5,
    "dhedh": 1.5,
    "dhai": 2.5,
    "dhayi": 2.5,
    "sawa": 1.25,
    "sava": 1.25,
    "paune": 0.75,
    "pauna": 0.75,

    # Hindi Fractions & Colloquial Measurements (Devanagari Script)
    "आधा": 0.5,
    "आधी": 0.5,
    "आधे": 0.5,
    "पाव": 0.25,
    "पवा": 0.25,
    "डेढ़": 1.5,
    "डेढ़": 1.5,
    "ढाई": 2.5,
    "सवा": 1.25,
    "पौना": 0.75,
    "पौने": 0.75,

    # English Numbers
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "twenty": 20.0,
}

# Devanagari numeral character translation table
DEVANAGARI_DIGITS = {
    '०': '0', '१': '1', '२': '2', '३': '3', '४': '4',
    '५': '5', '६': '6', '७': '7', '८': '8', '९': '9'
}

def normalize_devanagari_digits(text: str) -> str:
    """Translates Devanagari numerals (०-९) into standard ASCII digits (0-9)."""
    return "".join(DEVANAGARI_DIGITS.get(ch, ch) for ch in text)


# Unit normalizations (Romanized and Devanagari)
UNIT_MAP = {
    # Weight
    "kg": "kg",
    "kgs": "kg",
    "kilo": "kg",
    "kilos": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "किलो": "kg",
    "किलोग्राम": "kg",
    "केजी": "kg",
    "gram": "gram",
    "grams": "gram",
    "gm": "gram",
    "gms": "gram",
    "g": "gram",
    "ग्राम": "gram",
    "ग्राम्स": "gram",
    "ग्रा": "gram",

    # Volume
    "litre": "litre",
    "litres": "litre",
    "liter": "litre",
    "liters": "litre",
    "ltr": "litre",
    "ltrs": "litre",
    "l": "litre",
    "लीटर": "litre",
    "लीटरों": "litre",
    "ली": "litre",
    "ml": "ml",
    "मिली": "ml",
    "एमएल": "ml",

    # Packaged
    "packet": "packet",
    "packets": "packet",
    "pkt": "packet",
    "pkts": "packet",
    "pack": "packet",
    "packs": "packet",
    "pouch": "packet",
    "pouches": "packet",
    "dibba": "packet",
    "box": "packet",
    "boxes": "packet",
    "पैकेट": "packet",
    "पैकेट्स": "packet",
    "पैक": "packet",
    "पाउच": "packet",
    "डिब्बा": "packet",
    "डब्बा": "packet",
    "बॉक्स": "packet",

    # Pieces / Counts
    "piece": "piece",
    "pieces": "piece",
    "pc": "piece",
    "pcs": "piece",
    "nag": "piece",
    "dana": "piece",
    "bottle": "piece",
    "bottles": "piece",
    "bar": "piece",
    "bars": "piece",
    "पीस": "piece",
    "पीसेज": "piece",
    "नग": "piece",
    "दाना": "piece",
    "बोतल": "piece",
    "बार": "piece",

    # Dozen
    "dozen": "dozen",
    "dozens": "dozen",
    "darjan": "dozen",
    "दर्जन": "dozen",
    "डर्जन": "dozen",
}

# Conjunctions splitting distinct customer items (Romanized & Devanagari)
ITEM_CONJUNCTIONS = [
    "aur", "tatha", "evam", "and", "plus", "saath", "saath mein", "bhi",
    "ek aur", "or", ",", "&", "+",
    "और", "तथा", "एवं", "व", "साथ में", "साथ", "एक और"
]

# Polite shopkeeper / customer phrases and conversational padding to remove (Romanized & Devanagari)
FILLER_WORDS = [
    "bhaiya", "bhai", "chachu", "uncle", "kaka", "ji", "dada", "sahab", "sir",
    "thoda", "zara", "kripya", "please",
    "de do", "de dijiye", "dena", "dedo", "chahiye", "kar do", "kardo",
    "banao", "lagao", "pack kardo", "pack kar do", "dijiye", "bhejo",
    "lena hai", "le lo", "rakho", "ek kaam karo",
    "भैया", "भाई", "चाचा", "अंकल", "काका", "दादा", "साहब", "सर",
    "थोड़ा", "थोडा", "ज़रा", "जरा", "कृपया", "प्लीज",
    "दे दो", "दे दीजिए", "देना", "देदो", "चाहिए", "कर दो", "करदो",
    "बनाओ", "लगाओ", "पैक कर दो", "पैक कर्डो", "दीजिए", "भेजो",
    "लेना है", "ले लो", "रखो", "एक काम करो"
]
