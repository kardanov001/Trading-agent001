"""
news_filter.py — Анализ новостей через RSS-ленты
==================================================
Загружает новости из RSS-источников и ищет упоминания компаний из списка.
Если по бумаге выходит негативная новость — она исключается из торговли.

Это упрощённый анализ без ИИ — просто поиск ключевых слов в заголовках.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Set
import feedparser

from config import NEWS_FEEDS, NEGATIVE_KEYWORDS, POSITIVE_KEYWORDS, WATCHLIST


def fetch_news_from_feed(url: str, max_hours_ago: int = 24) -> List[dict]:
    """
    Загружает свежие новости из RSS-ленты.

    :param url: адрес RSS-ленты
    :param max_hours_ago: брать только новости за последние N часов
    :return: список словарей с новостями
    """
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        print(f"Ошибка загрузки {url}: {e}")
        return []

    threshold = datetime.now() - timedelta(hours=max_hours_ago)
    news_items = []

    for entry in feed.entries:
        # Парсим дату публикации
        published = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published = datetime(*entry.published_parsed[:6])
            except (TypeError, ValueError):
                published = None

        # Если нет даты или дата старая — пропускаем
        if published and published < threshold:
            continue

        news_items.append({
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),
            "published": published,
            "link": entry.get("link", ""),
        })

    return news_items


def fetch_all_news(max_hours_ago: int = 24) -> List[dict]:
    """
    Загружает новости из всех настроенных RSS-источников.

    :return: общий список новостей
    """
    all_news = []
    for source_name, url in NEWS_FEEDS.items():
        print(f"  Загружаю новости из {source_name}...")
        news = fetch_news_from_feed(url, max_hours_ago)
        for item in news:
            item["source"] = source_name
        all_news.extend(news)

    print(f"  Всего получено {len(all_news)} новостей")
    return all_news


def find_ticker_mentions(text: str) -> Set[str]:
    """
    Ищет упоминания тикеров и названий компаний в тексте.

    :param text: текст для поиска
    :return: множество найденных тикеров
    """
    mentions = set()
    text_lower = text.lower()

    for ticker, info in WATCHLIST.items():
        # Ищем по тикеру (например "SBER")
        if ticker.lower() in text_lower:
            mentions.add(ticker)
            continue

        # Ищем по названию компании (например "Сбербанк")
        name_lower = info["name"].lower()
        if name_lower in text_lower:
            mentions.add(ticker)

    return mentions


def classify_news(title: str, summary: str) -> str:
    """
    Классифицирует новость как 'negative', 'positive' или 'neutral'.

    :return: тип новости
    """
    text = (title + " " + summary).lower()

    # Сначала проверяем негативные слова — они приоритетнее
    for word in NEGATIVE_KEYWORDS:
        if word.lower() in text:
            return "negative"

    for word in POSITIVE_KEYWORDS:
        if word.lower() in text:
            return "positive"

    return "neutral"


def analyze_news_for_tickers(max_hours_ago: int = 24) -> Dict[str, dict]:
    """
    Анализирует все новости и группирует их по тикерам.

    :return: словарь {тикер: {"negative": [...], "positive": [...]}}
    """
    print("\n📰 Анализ новостей...")
    all_news = fetch_all_news(max_hours_ago)

    ticker_news = {ticker: {"negative": [], "positive": [], "neutral": []}
                   for ticker in WATCHLIST.keys()}

    for news_item in all_news:
        full_text = news_item["title"] + " " + news_item["summary"]
        mentions = find_ticker_mentions(full_text)

        if not mentions:
            continue

        classification = classify_news(news_item["title"], news_item["summary"])

        for ticker in mentions:
            ticker_news[ticker][classification].append({
                "title": news_item["title"],
                "source": news_item.get("source", "unknown"),
                "published": news_item.get("published"),
            })

    return ticker_news


def get_blocked_tickers(ticker_news: Dict[str, dict]) -> Set[str]:
    """
    Возвращает список тикеров, торговля которыми запрещена из-за негативных новостей.

    :return: множество тикеров для исключения
    """
    blocked = set()
    for ticker, news in ticker_news.items():
        if news["negative"]:
            blocked.add(ticker)
    return blocked


def get_news_summary_for_report(ticker_news: Dict[str, dict]) -> str:
    """
    Формирует краткую сводку новостей для отчёта.

    :return: текст сводки
    """
    lines = []
    has_news = False

    for ticker, news in ticker_news.items():
        if news["negative"] or news["positive"]:
            has_news = True
            company = WATCHLIST[ticker]["name"]
            if news["negative"]:
                titles = [n["title"][:80] for n in news["negative"][:2]]
                lines.append(f"  ⚠️  {ticker} ({company}): негатив — {'; '.join(titles)}")
            if news["positive"]:
                titles = [n["title"][:80] for n in news["positive"][:2]]
                lines.append(f"  ✅ {ticker} ({company}): позитив — {'; '.join(titles)}")

    if not has_news:
        return "  Существенных новостей по бумагам из списка не обнаружено"

    return "\n".join(lines)
