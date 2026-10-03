"""Canonical metadata is derived from configured origin, never request Host."""

LABELS = {
    "uk": {
        "home": (
            "Тривалість життя: статистика та ваш час",
            "Дізнайтеся, скільки часу ви вже прожили, та порівняйте зі статистикою тривалості життя у 217 країнах і територіях. Джерело — World Bank.",
        ),
        "countries": (
            "Тривалість життя за країнами та регіонами",
            "Порівняйте очікувану тривалість життя при народженні за даними World Bank: загалом, для жінок і чоловіків. Показники за {year} рік.",
        ),
        "methodology": (
            "Методика та джерела даних",
            "Як LifeTime використовує показники World Bank, чим статистичний орієнтир відрізняється від персонального прогнозу та які обмеження мають дані.",
        ),
        "privacy": (
            "Приватність і статистика запитів",
            "Які технічні дані LifeTime зберігає для статистики запитів, як розпізнає ботів і чому дата народження не потрапляє до журналу.",
        ),
        "result": (
            "Ваш час у контексті статистики",
            "Ваш прожитий час і статистичний орієнтир обраної країни. Це порівняння зі статистикою населення, а не прогноз тривалості вашого життя.",
        ),
        "location": "Тривалість життя: {name}",
        "location_description": "{name}: очікувана тривалість життя при народженні за {year} рік. Показники загалом, для жінок і чоловіків; джерело World Bank WDI.",
    },
    "en": {
        "home": (
            "Life expectancy statistics and your time",
            "See how much time you have lived and compare it with life expectancy statistics for 217 countries and territories. Data from the World Bank.",
        ),
        "countries": (
            "Life expectancy by country and region",
            "Explore World Bank life expectancy at birth statistics for all people, women and men. Comparable indicators for {year}.",
        ),
        "methodology": (
            "Methodology and data sources",
            "How LifeTime uses World Bank indicators, why a statistical reference is different from a personal prediction, and what the data can tell you.",
        ),
        "privacy": (
            "Privacy and request statistics",
            "Learn which technical information LifeTime stores for request analytics, how it classifies bots, and why birth dates are excluded from logs.",
        ),
        "result": (
            "Your time in a statistical context",
            "Your lived time alongside a statistical reference for your selected country. A population comparison, not a personal life expectancy prediction.",
        ),
        "location": "Life expectancy: {name}",
        "location_description": "{name}: life expectancy at birth in {year}, for all people, women and men. Source: World Bank World Development Indicators.",
    },
}


def metadata(origin, locale, kind, suffix="", location=None, version="", noindex=False, dataset=None):
    text = LABELS[locale]
    if kind == "location":
        title = text[kind].format(name=location["name"])
        description = text["location_description"].format(
            name=location["name"], year=location.get("year") or (dataset or {}).get("common_year", "—")
        )
    else:
        title, description = text[kind]
    if dataset:
        description = description.format(year=dataset["common_year"])
    canonical = f"{origin}/{locale}{suffix}" if not noindex else None
    alternates = [
        {"locale": code, "name": name, "url": f"{origin}/{code}{suffix}"}
        for code, name in (("uk", "Українська"), ("en", "English"))
    ]
    schema = []
    if canonical:
        schema.append(
            {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": title,
                "description": description,
                "url": canonical,
                "inLanguage": locale,
                "isPartOf": {"@type": "WebSite", "name": "LifeTime", "url": f"{origin}/{locale}"},
            }
        )
        if kind == "home":
            schema.extend(
                [
                    {
                        "@context": "https://schema.org",
                        "@type": "WebSite",
                        "name": "LifeTime",
                        "url": canonical,
                        "inLanguage": ["uk", "en"],
                    },
                    {
                        "@context": "https://schema.org",
                        "@type": "WebApplication",
                        "name": "LifeTime",
                        "url": canonical,
                        "applicationCategory": "UtilitiesApplication",
                        "operatingSystem": "Any",
                        "softwareVersion": version,
                        "description": description,
                        "isAccessibleForFree": True,
                    },
                ]
            )
        if kind == "location":
            schema.append(
                {
                    "@context": "https://schema.org",
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": 1,
                            "name": "LifeTime",
                            "item": f"{origin}/{locale}",
                        },
                        {
                            "@type": "ListItem",
                            "position": 2,
                            "name": text["countries"][0],
                            "item": f"{origin}/{locale}/countries",
                        },
                        {"@type": "ListItem", "position": 3, "name": location["name"], "item": canonical},
                    ],
                }
            )
    if canonical and kind == "methodology" and dataset:
        schema.append(
            {
                "@context": "https://schema.org",
                "@type": "Dataset",
                "name": "LifeTime — World Bank life expectancy at birth",
                "description": description,
                "url": canonical,
                "version": str(dataset["id"]),
                "temporalCoverage": str(dataset["common_year"]),
                "creator": {
                    "@type": "Organization",
                    "name": "World Bank",
                    "url": "https://data.worldbank.org/",
                },
                "isBasedOn": "https://data.worldbank.org/indicator/SP.DYN.LE00.IN",
            }
        )
    return {
        "page_title": f"{title} — LifeTime",
        "description": description,
        "default_url": f"{origin}/uk{suffix}",
        "canonical": canonical,
        "alternates": alternates,
        "schema": schema,
        "noindex": noindex,
    }
