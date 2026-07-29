# Архитектура

```mermaid
sequenceDiagram
    participant Main as main.py
    participant Data as market_data.py
    participant Indicators as indicators.py
    participant News as news_filter.py
    participant Strategy as strategy.py
    participant Trader as trader.py
    participant Reporter as reporter.py
    Main->>Data: Инструменты и свечи
    Data-->>Main: Рыночные данные
    Main->>Indicators: Расчёт индикаторов
    Main->>News: Оценка RSS
    Main->>Strategy: Данные, индикаторы, новости
    Strategy-->>Main: Торговое решение
    Main->>Trader: Операция в песочнице
    Main->>Reporter: Отчёт и журнал
```

`main.py` оркестрирует запуск; `market_data.py` работает с API; `indicators.py` содержит расчёты; `strategy.py` формирует решения; `trader.py` отвечает за заявки; `reporter.py` сохраняет результаты.
