"""Static content: moods, icebreakers, topics, daily questions."""
import datetime

MOODS = [
    ("chill", "Chill"),
    ("curious", "Curious"),
    ("playful", "Playful"),
    ("thoughtful", "Thoughtful"),
    ("lonely", "Could use company"),
]
MOOD_KEYS = {key for key, _ in MOODS}

ICEBREAKERS = [
    "What's your dream destination?",
    "What's something that makes you happy?",
    "What's the best thing you've eaten this week?",
    "If you could learn any skill instantly, what would it be?",
    "What's a song you never skip?",
    "What was the last thing that made you laugh?",
    "Mountains or beach?",
    "What's a small thing that improves your day?",
]

TOPICS = [
    "If you could have dinner with anyone, living or not, who would it be?",
    "What's a hobby you'd pick up if time weren't an issue?",
    "What's the best advice you've ever been given?",
    "Describe your perfect lazy Sunday.",
    "What's a movie or show you could rewatch forever?",
    "What would you do with a free month and no obligations?",
    "What's something you changed your mind about recently?",
    "What's your most useless talent?",
    "Which fictional world would you live in?",
    "What's a place you'd like to revisit?",
]

DAILY_QUESTIONS = [
    "What's one thing you're looking forward to this week?",
    "What's a tiny win you had recently?",
    "Which book, game or show has stuck with you lately?",
    "What would your ideal morning look like?",
    "What's a skill you admire in other people?",
    "What's the kindest thing a stranger has done for you?",
    "If today had a theme song, what would it be?",
]


def daily_question(today=None):
    today = today or datetime.date.today()
    return DAILY_QUESTIONS[today.toordinal() % len(DAILY_QUESTIONS)]


ADJECTIVES = ["Quiet", "Brave", "Sunny", "Mellow", "Swift", "Gentle", "Clever", "Cosmic"]
ANIMALS = ["Otter", "Heron", "Fox", "Panda", "Lynx", "Finch", "Gecko", "Moth"]
